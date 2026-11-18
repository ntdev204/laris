//! Safe writing into a vault: path confinement, atomic writes, managed blocks and conflict detection (SR-L2).
//!
//! LARIS writes only inside blocks it owns, marked by comments:
//!
//! ```text
//! <!-- laris:begin NAME sha=0123456789abcdef -->
//! generated text
//! <!-- laris:end NAME -->
//! ```
//!
//! `sha` is the first 16 hexadecimal digits of the SHA-256 of the text LARIS last wrote there. When the text no longer
//! matches, a person edited the block, so LARIS leaves the note alone and reports a conflict. Text outside blocks is
//! never touched. A file is replaced atomically: the new text goes to a temporary file in the same folder, is flushed
//! to disk and renamed over the old one, so a crash leaves the old file or the new one, never a mixture.
//!
//! Differences from generation 1, all refusals: a block name must match `[\w.-]+`, a block text must not hold a LARIS
//! marker, and property names must be plain lines of text (the properties are written by [`crate::emit`]).

use std::collections::BTreeSet;
use std::fmt;
use std::fs;
use std::io::{self, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::LazyLock;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use regex::Regex;

use crate::emit::dump_properties;
use crate::note::{FORBIDDEN_NAME_CHARS, sha256_hex};
use crate::yaml::Value;

/// Longest note name `safe_title` returns, in characters.
pub const MAX_TITLE_CHARS: usize = 100;
/// Where the text of a replaced block goes, relative to the vault root (never indexed).
pub const BACKUP_DIR: &str = ".laris/backups";
/// Prefix and suffix of the temporary files `atomic_write` makes.
pub const TEMP_PREFIX: &str = ".laris-";
/// Suffix of the temporary files `atomic_write` makes.
pub const TEMP_SUFFIX: &str = ".tmp";

static BEGIN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"<!-- laris:begin ([\w.-]+) sha=([0-9a-f]{8,64}) -->\n").expect("static pattern")
});
static BLOCK_NAME: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[\w.-]+$").expect("static pattern"));

/// A write was refused (path escape, unsafe content, size, rate) or failed.
#[derive(Debug)]
pub struct VaultWriteError {
    /// What happened.
    pub message: String,
}

impl VaultWriteError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl fmt::Display for VaultWriteError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for VaultWriteError {}

impl From<io::Error> for VaultWriteError {
    fn from(e: io::Error) -> Self {
        Self::new(format!("cannot write: {e}"))
    }
}

/// A note name that cannot break a wikilink or a file name.
pub fn safe_title(text: &str, fallback: &str) -> String {
    let cleaned: String = text
        .chars()
        .map(|c| {
            if FORBIDDEN_NAME_CHARS.contains(c) || (c as u32) < 32 {
                ' '
            } else {
                c
            }
        })
        .collect();
    let cleaned = cleaned.split_whitespace().collect::<Vec<_>>().join(" ");
    let cut = |s: &str| s.trim_matches(|c| c == ' ' || c == '.').to_string();
    let cleaned = cut(&cleaned);
    let capped: String = cleaned.chars().take(MAX_TITLE_CHARS).collect();
    let capped = cut(&capped);
    if capped.is_empty() {
        fallback.to_string()
    } else {
        capped
    }
}

/// Path of `relative` below `root`; refuses absolute paths, `..` and symlinks that lead out of the vault.
pub fn resolve_inside(root: &Path, relative: &str) -> Result<PathBuf, VaultWriteError> {
    let refused = || VaultWriteError::new("path must be relative and stay inside the vault");
    let rel = Path::new(relative);
    if relative.trim().is_empty()
        || rel.is_absolute()
        || rel.components().any(|c| {
            matches!(
                c,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
    {
        return Err(refused());
    }
    let base = root
        .canonicalize()
        .map_err(|e| VaultWriteError::new(format!("vault folder is not readable: {e}")))?;
    let mut target = base.clone();
    let parts = rel.components().filter_map(|c| match c {
        Component::Normal(p) => Some(p.to_os_string()),
        _ => None,
    });
    // follow every existing part (symlinks included); what does not exist yet is appended as written
    let mut exists = true;
    for part in parts {
        target.push(&part);
        if exists {
            match fs::symlink_metadata(&target) {
                Ok(_) => {
                    target = target
                        .canonicalize()
                        .map_err(|e| VaultWriteError::new(format!("cannot resolve path: {e}")))?;
                }
                Err(_) => exists = false,
            }
        }
        if !target.starts_with(&base) {
            return Err(VaultWriteError::new("path escapes the vault"));
        }
    }
    if target == base {
        return Err(refused());
    }
    Ok(target)
}

/// The points of an atomic write, for tests that stop it half way.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    /// The new text is in the temporary file (not flushed yet).
    TempWritten,
    /// The temporary file is on disk, the old file is still in place.
    TempSynced,
    /// The new file is in place.
    Renamed,
}

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

/// Replace `path` with `text` atomically. The folder is created when missing.
pub fn atomic_write(path: &Path, text: &str) -> io::Result<()> {
    atomic_write_with(path, text, &mut |_| Ok(()))
}

/// [`atomic_write`] that tells `hook` where it is. A hook that returns an error stops the write there: the temporary
/// file is removed and the old file is untouched. A hook that aborts the process leaves a stale temporary file
/// (see [`sweep_stale_temp`]) and the old file untouched.
pub fn atomic_write_with(
    path: &Path,
    text: &str,
    hook: &mut dyn FnMut(Stage) -> io::Result<()>,
) -> io::Result<()> {
    let dir = path.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(dir)?;
    let tmp = dir.join(format!(
        "{TEMP_PREFIX}{}-{}{TEMP_SUFFIX}",
        std::process::id(),
        TEMP_COUNTER.fetch_add(1, Ordering::SeqCst)
    ));
    let result = (|| {
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&tmp)?;
        file.write_all(text.as_bytes())?;
        hook(Stage::TempWritten)?;
        file.sync_all()?;
        if let Ok(meta) = fs::metadata(path) {
            fs::set_permissions(&tmp, meta.permissions())?;
        }
        drop(file);
        hook(Stage::TempSynced)?;
        fs::rename(&tmp, path)?;
        hook(Stage::Renamed)?;
        Ok(())
    })();
    if let Err(e) = result {
        if tmp.exists() {
            let _ = fs::remove_file(&tmp);
        }
        return Err(e);
    }
    #[cfg(unix)]
    if let Ok(d) = fs::File::open(dir) {
        let _ = d.sync_all();
    }
    Ok(())
}

/// Remove the temporary files a killed write left in `dir` and its sub-folders; returns how many.
pub fn sweep_stale_temp(dir: &Path) -> usize {
    let mut removed = 0;
    let Ok(entries) = fs::read_dir(dir) else {
        return 0;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().into_owned();
        match entry.file_type() {
            Ok(t) if t.is_dir() => removed += sweep_stale_temp(&path),
            Ok(t)
                if t.is_file() && name.starts_with(TEMP_PREFIX) && name.ends_with(TEMP_SUFFIX) =>
            {
                removed += usize::from(fs::remove_file(&path).is_ok());
            }
            _ => {}
        }
    }
    removed
}

fn digest(text: &str) -> String {
    sha256_hex(text.trim_matches('\n'))[..16].to_string()
}

/// One managed block as text.
pub fn block(name: &str, content: &str) -> String {
    let content = content.trim_matches('\n');
    format!(
        "<!-- laris:begin {name} sha={} -->\n{content}\n<!-- laris:end {name} -->",
        digest(content)
    )
}

/// What `upsert_block` did.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BlockStatus {
    /// The block was not there and has been added.
    Created,
    /// The block text changed.
    Updated,
    /// The block already held this text.
    Unchanged,
    /// A person edited the block; nothing was changed.
    Conflict,
}

/// One block found in a text.
struct Found {
    name: String,
    sha: String,
    body: String,
    start: usize,
    end: usize,
}

/// The blocks of a text, left to right, as generation 1's pattern finds them: a begin marker with its first end marker.
fn find_blocks(text: &str) -> Vec<Found> {
    let mut found = Vec::new();
    let mut from = 0;
    while let Some(m) = BEGIN.captures_at(text, from) {
        let whole = m.get(0).expect("whole match");
        let name = m[1].to_string();
        let end_marker = format!("<!-- laris:end {name} -->");
        let body_start = whole.end();
        match text[body_start..].find(&end_marker) {
            Some(at) => {
                let body_end = body_start + at;
                let body = &text[body_start..body_end];
                let body = body.strip_suffix('\n').unwrap_or(body);
                found.push(Found {
                    name,
                    sha: m[2].to_string(),
                    body: body.to_string(),
                    start: whole.start(),
                    end: body_end + end_marker.len(),
                });
                from = body_end + end_marker.len();
            }
            None => from = whole.start() + 1,
        }
        if from > text.len() {
            break;
        }
    }
    found
}

/// A block's stored hash is a prefix of the hash of its text (the format allows 8 to 64 digits).
fn matches_sha(body: &str, sha: &str) -> bool {
    !sha.is_empty() && sha256_hex(body.trim_matches('\n')).starts_with(sha)
}

/// Names of the blocks a person edited (their hash no longer matches), in order.
pub fn conflicts(text: &str) -> Vec<String> {
    find_blocks(text)
        .into_iter()
        .filter(|b| !matches_sha(&b.body, &b.sha))
        .map(|b| b.name)
        .collect()
}

/// Sign every edited block again as it stands: the person's text becomes the block's text.
pub fn accept_edits(text: &str) -> String {
    let mut out = String::new();
    let mut at = 0;
    for b in find_blocks(text) {
        out.push_str(&text[at..b.start]);
        if matches_sha(&b.body, &b.sha) {
            out.push_str(&text[b.start..b.end]);
        } else {
            out.push_str(&block(&b.name, &b.body));
        }
        at = b.end;
    }
    out.push_str(&text[at..]);
    out
}

/// Insert or replace one managed block. Returns the new text and what happened; on a conflict the text is returned
/// unchanged.
pub fn upsert_block(
    text: &str,
    name: &str,
    content: &str,
) -> Result<(String, BlockStatus), VaultWriteError> {
    if !BLOCK_NAME.is_match(name) {
        return Err(VaultWriteError::new("block name must match [\\w.-]+"));
    }
    if content.contains("<!-- laris:begin") || content.contains("<!-- laris:end") {
        return Err(VaultWriteError::new(
            "block text must not hold a LARIS marker",
        ));
    }
    let new = block(name, content);
    for b in find_blocks(text) {
        if b.name != name {
            continue;
        }
        if !matches_sha(&b.body, &b.sha) {
            return Ok((text.to_string(), BlockStatus::Conflict));
        }
        if text[b.start..b.end] == new {
            return Ok((text.to_string(), BlockStatus::Unchanged));
        }
        let mut out = String::with_capacity(text.len() + new.len());
        out.push_str(&text[..b.start]);
        out.push_str(&new);
        out.push_str(&text[b.end..]);
        return Ok((out, BlockStatus::Updated));
    }
    let head = text.trim_end_matches('\n');
    let sep = if text.trim().is_empty() { "" } else { "\n\n" };
    Ok((format!("{head}{sep}{new}\n"), BlockStatus::Created))
}

/// A note as text: properties between `---` lines, then the body.
pub fn render_note(props: &[(String, Value)], body: &str) -> Result<String, VaultWriteError> {
    let front = dump_properties(props).map_err(|e| VaultWriteError::new(e.to_string()))?;
    Ok(format!("---\n{front}\n---\n\n{}\n", body.trim()))
}

/// What `write_note` did.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WriteStatus {
    /// The note did not exist.
    Created,
    /// A block changed.
    Updated,
    /// Nothing to change.
    Unchanged,
    /// A person edited a block; the note was left alone.
    Conflict,
}

/// A scanner: true for text that must not be stored.
pub type Scanner = Box<dyn Fn(&str) -> bool + Send + Sync>;
/// Replaces secrets in text before it is stored.
pub type Redactor = Box<dyn Fn(&str) -> String + Send + Sync>;
/// Seconds on a monotonic clock.
pub type Clock = Box<dyn Fn() -> f64 + Send + Sync>;

/// What a writer is told by its owner; nothing here has a default of its own.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WriterLimits {
    /// Longest block text, in characters.
    pub max_chars: usize,
    /// Keep the text being replaced under [`BACKUP_DIR`].
    pub backup: bool,
    /// Writes allowed in a minute; 0 for no limit.
    pub max_writes_per_minute: usize,
}

/// Writes notes below a root.
pub struct VaultWriter {
    root: PathBuf,
    limits: WriterLimits,
    scan: Option<Scanner>,
    redact: Option<Redactor>,
    clock: Clock,
    stamps: Vec<f64>,
}

impl VaultWriter {
    /// A writer for the vault at `root`.
    pub fn new(root: &Path, limits: WriterLimits) -> Self {
        let start = Instant::now();
        Self {
            root: root.to_path_buf(),
            limits,
            scan: None,
            redact: None,
            clock: Box::new(move || start.elapsed().as_secs_f64()),
            stamps: Vec::new(),
        }
    }

    /// Refuse text for which `scan` returns true (an injection scan).
    pub fn with_scan(mut self, scan: Scanner) -> Self {
        self.scan = Some(scan);
        self
    }

    /// Replace secrets in block text before it is stored.
    pub fn with_redactor(mut self, redact: Redactor) -> Self {
        self.redact = Some(redact);
        self
    }

    /// Use another clock for the rate limit (tests).
    pub fn with_clock(mut self, clock: Clock) -> Self {
        self.clock = clock;
        self
    }

    fn rate(&mut self) -> Result<(), VaultWriteError> {
        if self.limits.max_writes_per_minute == 0 {
            return Ok(());
        }
        let now = (self.clock)();
        self.stamps.retain(|t| now - t < 60.0);
        if self.stamps.len() >= self.limits.max_writes_per_minute {
            return Err(VaultWriteError::new("too many note writes in a minute"));
        }
        self.stamps.push(now);
        Ok(())
    }

    fn backup(&self, path: &Path, text: &str) -> Result<(), VaultWriteError> {
        if !self.limits.backup {
            return Ok(());
        }
        let base = self.root.canonicalize()?;
        let rel = path
            .strip_prefix(&base)
            .unwrap_or(path)
            .to_string_lossy()
            .replace(['/', '\\'], "__");
        let folder = self.root.join(BACKUP_DIR);
        fs::create_dir_all(&folder)?;
        let mut stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |d| d.as_nanos());
        let tag = &digest(text)[..8];
        loop {
            let target = folder.join(format!("{rel}.{stamp:020}.{tag}.bak"));
            if !target.exists() {
                return Ok(atomic_write(&target, text)?);
            }
            stamp += 1;
        }
    }

    fn check(&self, text: &str) -> Result<(), VaultWriteError> {
        if text.chars().count() > self.limits.max_chars {
            return Err(VaultWriteError::new("note is too large"));
        }
        if self.scan.as_ref().is_some_and(|scan| scan(text)) {
            return Err(VaultWriteError::new(
                "note content was refused by the injection scan",
            ));
        }
        Ok(())
    }

    /// Create the note, or update only its managed blocks. Text outside managed blocks is never touched, and a note in
    /// which a person edited a block is left alone as a whole.
    pub fn write_note(
        &mut self,
        relative: &str,
        props: &[(String, Value)],
        blocks: &[(String, String)],
        lead: &str,
    ) -> Result<WriteStatus, VaultWriteError> {
        self.write_note_with(relative, props, blocks, lead, &mut |_| Ok(()))
    }

    /// [`VaultWriter::write_note`] with a hook on the stages of the file replacement (tests that stop a write half way).
    pub fn write_note_with(
        &mut self,
        relative: &str,
        props: &[(String, Value)],
        blocks: &[(String, String)],
        lead: &str,
        hook: &mut dyn FnMut(Stage) -> io::Result<()>,
    ) -> Result<WriteStatus, VaultWriteError> {
        let path = resolve_inside(&self.root, relative)?;
        if path.extension().and_then(|e| e.to_str()) != Some("md") {
            return Err(VaultWriteError::new("notes are Markdown files"));
        }
        let mut seen: BTreeSet<&str> = BTreeSet::new();
        let mut texts: Vec<(&str, String)> = Vec::new();
        for (name, content) in blocks {
            if !seen.insert(name) {
                return Err(VaultWriteError::new("a block name appears twice"));
            }
            let content = self
                .redact
                .as_ref()
                .map_or_else(|| content.clone(), |r| r(content));
            texts.push((name, content));
        }
        for (_, text) in &texts {
            self.check(text)?;
        }
        if !path.exists() {
            let mut text = render_note(props, lead.trim())?;
            for (name, content) in &texts {
                text = upsert_block(&text, name, content)?.0;
            }
            self.rate()?;
            atomic_write_with(&path, &text, hook)?;
            return Ok(WriteStatus::Created);
        }
        let bytes = fs::read(&path)?;
        let current = String::from_utf8(bytes)
            .map_err(|_| VaultWriteError::new("the note is not valid UTF-8; it was left alone"))?;
        let mut text = current.clone();
        let mut statuses = Vec::new();
        for (name, content) in &texts {
            let (next, status) = upsert_block(&text, name, content)?;
            text = next;
            statuses.push(status);
        }
        if statuses.contains(&BlockStatus::Conflict) {
            return Ok(WriteStatus::Conflict);
        }
        if statuses.iter().all(|s| *s == BlockStatus::Unchanged) {
            return Ok(WriteStatus::Unchanged);
        }
        self.rate()?;
        self.backup(&path, &current)?;
        atomic_write_with(&path, &text, hook)?;
        Ok(WriteStatus::Updated)
    }
}
