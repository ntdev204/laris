//! The vault index: notes, resolved links, backlinks and orphans. Deterministic and rebuildable.
//!
//! Link resolution follows Obsidian's shortest-path rule: a bare name matches a note title (case-insensitively); a
//! name with a folder part matches the path suffix. Ambiguous names are reported, never guessed. The same folder gives
//! the same index and the same bytes from [`VaultIndex::export_string`], whatever the order the files are read in.
//! A rebuild reuses every note whose size and modification time are unchanged ([`VaultIndex::build`] with a previous
//! index or a [`VaultIndex::dumps`] cache); deleting the cache loses nothing.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value as Json, json};

use crate::note::{Link, Note, link_name, parse_note};

/// Folders that are never scanned (spec section 2, plus `.laris` and `_templates`).
pub const IGNORED_DIRS: [&str; 6] = [
    ".obsidian",
    ".git",
    ".trash",
    "__pycache__",
    ".laris",
    "_templates",
];
/// Version of the cache format; a cache of another version is ignored.
pub const CACHE_VERSION: u64 = 1;

/// Size and modification time (nanoseconds) of a file when it was read.
pub type Fingerprint = (i64, u64);

/// The vault folder could not be scanned.
#[derive(Debug)]
pub struct VaultError {
    /// The folder or file.
    pub path: PathBuf,
    /// The operating system error.
    pub source: std::io::Error,
}

impl fmt::Display for VaultError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "cannot read {}: {}", self.path.display(), self.source)
    }
}

impl std::error::Error for VaultError {}

/// What a build did, for tests and logs. Not part of the index content.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BuildStats {
    /// Notes read and parsed.
    pub parsed: Vec<String>,
    /// Notes taken unchanged from the previous index.
    pub reused: Vec<String>,
    /// Files that could not be read, with the reason; they are not in the index.
    pub unreadable: Vec<(String, String)>,
}

/// How a link resolved.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Resolution {
    /// Exactly one note.
    Ok,
    /// No note.
    Missing,
    /// More than one note.
    Ambiguous,
    /// An empty target (`[[#Heading]]`): the note itself.
    SelfLink,
}

/// The index of a vault folder.
#[derive(Debug, Clone, Default)]
pub struct VaultIndex {
    /// The folder.
    pub root: PathBuf,
    /// Notes by vault-relative path.
    pub notes: BTreeMap<String, Note>,
    /// `(note path, target as written)` for links to nothing, in path order.
    pub unresolved: Vec<(String, String)>,
    /// `(note path, target as written)` for links to several notes, in path order.
    pub ambiguous: Vec<(String, String)>,
    /// What the last build did.
    pub stats: BuildStats,
    stems: BTreeMap<String, Vec<String>>,
    fingerprints: BTreeMap<String, Fingerprint>,
    out: BTreeMap<String, Vec<(String, String)>>,
    incoming: BTreeMap<String, BTreeSet<String>>,
}

/// `(target path, how it resolved, target as written, edge kind)`.
type ResolvedLink = (Option<String>, Resolution, String, String);

fn ignored(name: &str) -> bool {
    IGNORED_DIRS.contains(&name)
}

/// Text as read from disk: lossy UTF-8 and universal newlines.
fn read_text(path: &Path) -> std::io::Result<String> {
    let bytes = fs::read(path)?;
    let text = String::from_utf8_lossy(&bytes);
    Ok(text.replace("\r\n", "\n").replace('\r', "\n"))
}

fn fingerprint(meta: &fs::Metadata) -> Fingerprint {
    let nanos = meta
        .modified()
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map_or(0, |d| d.as_nanos() as u64);
    (meta.len() as i64, nanos)
}

fn collect(base: &Path, dir: &Path, found: &mut Vec<PathBuf>, stats: &mut BuildStats) {
    let rel = dir
        .strip_prefix(base)
        .unwrap_or(dir)
        .to_string_lossy()
        .into_owned();
    let entries = match fs::read_dir(dir) {
        Ok(e) => e,
        Err(e) => {
            stats.unreadable.push((rel, e.to_string()));
            return;
        }
    };
    let mut names: Vec<(String, PathBuf, fs::FileType)> = Vec::new();
    for entry in entries.flatten() {
        let (Ok(ft), Some(name)) = (
            entry.file_type(),
            entry.file_name().to_str().map(str::to_string),
        ) else {
            continue;
        };
        names.push((name, entry.path(), ft));
    }
    names.sort_by(|a, b| a.0.cmp(&b.0));
    for (name, path, ft) in names {
        if ignored(&name) {
            continue;
        }
        if ft.is_dir() {
            collect(base, &path, found, stats); // a symlink to a folder is not followed
        } else if name.ends_with(".md") {
            found.push(path);
        }
    }
}

impl VaultIndex {
    /// Scan the folder. A note whose size and modification time equal those in `previous` is reused instead of read.
    pub fn build(root: &Path, previous: Option<&VaultIndex>) -> Result<VaultIndex, VaultError> {
        let root_meta = fs::metadata(root).map_err(|source| VaultError {
            path: root.to_path_buf(),
            source,
        })?;
        if !root_meta.is_dir() {
            return Err(VaultError {
                path: root.to_path_buf(),
                source: std::io::Error::new(std::io::ErrorKind::NotADirectory, "not a folder"),
            });
        }
        let mut index = VaultIndex {
            root: root.to_path_buf(),
            ..VaultIndex::default()
        };
        let canonical_root = fs::canonicalize(root).ok();
        let mut files = Vec::new();
        collect(root, root, &mut files, &mut index.stats);
        for path in files {
            let rel = path.strip_prefix(root).unwrap_or(&path);
            let key = rel
                .components()
                .map(|c| c.as_os_str().to_string_lossy().into_owned())
                .collect::<Vec<_>>()
                .join("/");
            let Ok(meta) = fs::metadata(&path) else {
                continue; // a broken link
            };
            if !meta.is_file() {
                continue;
            }
            if fs::symlink_metadata(&path).is_ok_and(|m| m.file_type().is_symlink()) {
                let inside = match (fs::canonicalize(&path), &canonical_root) {
                    (Ok(real), Some(base)) => real.starts_with(base),
                    _ => false,
                };
                if !inside {
                    continue; // a link to a file outside the vault is never read
                }
            }
            let fp = fingerprint(&meta);
            let reused = previous.and_then(|p| {
                (p.fingerprints.get(&key) == Some(&fp))
                    .then(|| p.notes.get(&key))
                    .flatten()
            });
            let note = if let Some(note) = reused {
                index.stats.reused.push(key.clone());
                note.clone()
            } else {
                match read_text(&path) {
                    Ok(text) => {
                        index.stats.parsed.push(key.clone());
                        parse_note(&text, &key)
                    }
                    Err(e) => {
                        index.stats.unreadable.push((key, e.to_string()));
                        continue;
                    }
                }
            };
            index.fingerprints.insert(key.clone(), fp);
            index.notes.insert(key, note);
        }
        index.link();
        Ok(index)
    }

    fn link(&mut self) {
        for (path, note) in &self.notes {
            self.stems
                .entry(note.title.to_lowercase())
                .or_default()
                .push(path.clone());
        }
        for stems in self.stems.values_mut() {
            stems.sort();
        }
        for path in self.notes.keys() {
            self.out.insert(path.clone(), Vec::new());
            self.incoming.entry(path.clone()).or_default();
        }
        let mut resolved: Vec<(String, Vec<ResolvedLink>)> = Vec::new();
        for (path, note) in &self.notes {
            let rows = note
                .links
                .iter()
                .map(|link| {
                    let (target, status) = self.resolve(link, path);
                    let kind = if link.prop.is_empty() {
                        "body".to_string()
                    } else {
                        link.prop.clone()
                    };
                    (target, status, link.target.clone(), kind)
                })
                .collect();
            resolved.push((path.clone(), rows));
        }
        for (path, rows) in resolved {
            let mut seen: BTreeSet<String> = BTreeSet::new();
            for (target, status, written, kind) in rows {
                match status {
                    Resolution::SelfLink => {}
                    Resolution::Ambiguous => self.ambiguous.push((path.clone(), written)),
                    Resolution::Missing => {
                        if !written.is_empty() {
                            self.unresolved.push((path.clone(), written));
                        }
                    }
                    Resolution::Ok => {
                        let target = target.expect("resolved target");
                        if target != path && seen.insert(target.clone()) {
                            self.out
                                .entry(path.clone())
                                .or_default()
                                .push((target.clone(), kind));
                            self.incoming
                                .entry(target)
                                .or_default()
                                .insert(path.clone());
                        }
                    }
                }
            }
        }
    }

    /// The note a link points at and how it resolved. `source` is the path of the note that holds the link.
    pub fn resolve(&self, link: &Link, source: &str) -> (Option<String>, Resolution) {
        let mut name = link.target.trim();
        if name.is_empty() {
            return (
                (!source.is_empty()).then(|| source.to_string()),
                Resolution::SelfLink,
            );
        }
        if name.to_lowercase().ends_with(".md") {
            name = &name[..name.len() - 3];
        }
        let lowered = name.to_lowercase();
        let hits: Vec<&String> = if lowered.contains('/') {
            self.notes
                .keys()
                .filter(|p| p[..p.len() - 3].to_lowercase().ends_with(&lowered))
                .collect()
        } else {
            self.stems
                .get(&lowered)
                .map(|v| v.iter().collect())
                .unwrap_or_default()
        };
        match hits.len() {
            1 => (Some(hits[0].clone()), Resolution::Ok),
            0 => (None, Resolution::Missing),
            _ => (None, Resolution::Ambiguous),
        }
    }

    /// Adds a note that was just written, without reading the folder again: its path and title become known to
    /// [`VaultIndex::find`] and [`VaultIndex::resolve`]. Links, backlinks and fingerprints are not updated; a full
    /// [`VaultIndex::build`] gives those. For a writer that adds many notes in one run (the brain's write gate).
    pub fn insert(&mut self, note: Note) {
        let path = note.path.clone();
        let stems = self.stems.entry(note.title.to_lowercase()).or_default();
        if !stems.contains(&path) {
            stems.push(path.clone());
            stems.sort();
        }
        self.notes.insert(path, note);
    }

    /// The note a name points at, when exactly one does.
    pub fn find(&self, title: &str) -> Option<&Note> {
        let (target, status) = self.resolve(&Link::to(title), "");
        match (target, status) {
            (Some(t), Resolution::Ok) => self.notes.get(&t),
            _ => None,
        }
    }

    /// `(target path, kind)` of the notes a note links to; kind is `body` or the property name of the first link.
    pub fn outgoing(&self, path: &str) -> Vec<(String, String)> {
        self.out.get(path).cloned().unwrap_or_default()
    }

    /// Paths of the notes that link to a note, sorted.
    pub fn backlinks(&self, path: &str) -> Vec<String> {
        self.incoming
            .get(path)
            .map(|s| s.iter().cloned().collect())
            .unwrap_or_default()
    }

    /// Notes linked in either direction, sorted.
    pub fn neighbours(&self, path: &str) -> Vec<String> {
        let mut all: BTreeSet<String> = self
            .out
            .get(path)
            .into_iter()
            .flatten()
            .map(|(t, _)| t.clone())
            .collect();
        all.extend(self.incoming.get(path).into_iter().flatten().cloned());
        all.into_iter().collect()
    }

    /// Notes nothing links to and that link to nothing.
    pub fn orphans(&self) -> Vec<String> {
        self.notes
            .keys()
            .filter(|p| self.incoming[*p].is_empty() && self.out[*p].is_empty())
            .cloned()
            .collect()
    }

    /// Notes nothing links to.
    pub fn unlinked(&self) -> Vec<String> {
        self.notes
            .keys()
            .filter(|p| self.incoming[*p].is_empty())
            .cloned()
            .collect()
    }

    /// Notes whose property reads as `value` (text form), in path order.
    pub fn by_prop(&self, name: &str, value: &str) -> Vec<&Note> {
        self.notes
            .values()
            .filter(|n| n.prop(name).map_or("None".to_string(), |v| v.py_str()) == value)
            .collect()
    }

    /// Paths a property links to (for example `children`, `requires`).
    pub fn targets(&self, path: &str, prop: &str) -> Vec<String> {
        let Some(note) = self.notes.get(path) else {
            return Vec::new();
        };
        note.prop_list(prop)
            .iter()
            .filter_map(|raw| match self.resolve(&Link::to(&link_name(raw)), path) {
                (Some(t), Resolution::Ok) => Some(t),
                _ => None,
            })
            .collect()
    }

    /// Everything the index knows, without file times: the form compared with the recorded index.
    pub fn export(&self) -> Json {
        let mut notes = Map::new();
        let mut outgoing = Map::new();
        let mut backlinks = Map::new();
        let mut neighbours = Map::new();
        for (path, note) in &self.notes {
            notes.insert(path.clone(), note.to_json());
            outgoing.insert(
                path.clone(),
                json!(
                    self.outgoing(path)
                        .iter()
                        .map(|(t, k)| json!([t, k]))
                        .collect::<Vec<_>>()
                ),
            );
            backlinks.insert(path.clone(), json!(self.backlinks(path)));
            neighbours.insert(path.clone(), json!(self.neighbours(path)));
        }
        let pairs =
            |rows: &[(String, String)]| rows.iter().map(|(a, b)| json!([a, b])).collect::<Vec<_>>();
        json!({
            "notes": notes,
            "outgoing": outgoing,
            "backlinks": backlinks,
            "neighbours": neighbours,
            "unresolved": pairs(&self.unresolved),
            "ambiguous": pairs(&self.ambiguous),
            "orphans": self.orphans(),
            "unlinked": self.unlinked(),
        })
    }

    /// [`VaultIndex::export`] as indented JSON with sorted keys and a final newline: same notes, same bytes.
    pub fn export_string(&self) -> String {
        let mut text = serde_json::to_string_pretty(&self.export()).expect("JSON value");
        text.push('\n');
        text
    }

    /// The disposable cache: every note with its fingerprint, compact and deterministic.
    pub fn dumps(&self) -> String {
        let mut notes = Map::new();
        for (path, note) in &self.notes {
            let fp = self.fingerprints.get(path).copied().unwrap_or((0, 0));
            notes.insert(
                path.clone(),
                json!({ "fp": [fp.0, fp.1], "note": note.to_json() }),
            );
        }
        json!({ "version": CACHE_VERSION, "notes": notes }).to_string()
    }

    /// Read a cache written by [`VaultIndex::dumps`] to pass to [`VaultIndex::build`]; `None` when it is of another
    /// version or damaged (rebuild from the notes).
    pub fn loads(root: &Path, text: &str) -> Option<VaultIndex> {
        let data: Json = serde_json::from_str(text).ok()?;
        if data.get("version")?.as_u64()? != CACHE_VERSION {
            return None;
        }
        let mut index = VaultIndex {
            root: root.to_path_buf(),
            ..VaultIndex::default()
        };
        for (path, row) in data.get("notes")?.as_object()? {
            let fp = row.get("fp")?.as_array()?;
            index
                .fingerprints
                .insert(path.clone(), (fp.first()?.as_i64()?, fp.get(1)?.as_u64()?));
            index
                .notes
                .insert(path.clone(), Note::from_json(row.get("note")?)?);
        }
        Some(index)
    }
}
