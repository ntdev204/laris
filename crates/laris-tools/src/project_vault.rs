//! The project vault (SR-H8): an Obsidian vault the person and LARIS share.
//!
//! * [`ProjectVault::init`] makes a vault where there is none and adopts one where there is: it never overwrites a
//!   file, and it refuses to put a vault inside another vault or above one (no nesting). Run twice, it changes
//!   nothing. A vault that already exists is left exactly as it is.
//! * [`ProjectVault::source_note`] writes the Source note of an ingested document, with where it came from.
//! * [`ProjectVault::write_note`] writes a note of any type of the schema with provenance (`origin`, the sources it
//!   rests on). LARIS writes only inside a managed block; whatever a person wrote around it is never touched, and a
//!   block a person edited is left alone and reported as a conflict.
//! * [`ProjectVault::remember`] keeps a memory in `Memory/`.
//! * The proposals inbox (`_inbox/`) holds what LARIS suggests and nobody accepted: [`ProjectVault::propose`], then
//!   [`ProjectVault::accept`] or [`ProjectVault::reject`]. Retrieval never reads the inbox.
//!
//! Every limit comes from the caller.

use crate::ingest::Document;
use laris_vault::schema::Schema;
use laris_vault::writer::{
    VaultWriteError, VaultWriter, WriteStatus, WriterLimits, atomic_write, render_note, safe_title,
};
use laris_vault::{Value, VaultIndex, note::parse_note};
use std::fs;
use std::path::{Path, PathBuf};

/// The proposals inbox folder.
pub const INBOX: &str = laris_retrieval::INBOX;
/// The root note of a vault LARIS made.
pub const ROOT_NOTE: &str = "Index.md";
/// The managed block LARIS writes in its notes.
pub const BLOCK: &str = "laris";

/// What `init` found and did.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum InitStatus {
    /// A new vault was made; the paths created are listed.
    Created(Vec<String>),
    /// A vault was already there and was left as it is.
    Adopted,
}

/// A vault that cannot be made or used.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum VaultProblem {
    /// A vault already exists above this folder.
    #[error("this folder is inside the vault at {0}; a vault does not nest")]
    InsideVault(String),
    /// A vault already exists below this folder.
    #[error("there is already a vault inside this folder at {0}; a vault does not nest")]
    ContainsVault(String),
    /// Reading or writing failed.
    #[error("{0}")]
    Io(String),
    /// A note type or property the schema does not allow.
    #[error("{0}")]
    Invalid(String),
    /// The note is there and a person edited LARIS's block in it.
    #[error("a person edited this note's LARIS block, so it was left alone")]
    Conflict,
    /// The target of an acceptance exists.
    #[error("{0} already exists; it was not overwritten")]
    Exists(String),
}

impl From<VaultWriteError> for VaultProblem {
    fn from(e: VaultWriteError) -> Self {
        VaultProblem::Io(e.to_string())
    }
}

impl From<std::io::Error> for VaultProblem {
    fn from(e: std::io::Error) -> Self {
        VaultProblem::Io(e.kind().to_string())
    }
}

/// A suggestion waiting in the inbox.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Proposal {
    /// Vault-relative path.
    pub path: String,
    /// The note title.
    pub title: String,
    /// `pending`, `accepted` or `rejected`.
    pub status: String,
    /// What made it.
    pub origin: String,
    /// The type it would have as a note.
    pub target_type: String,
}

/// Where a note went.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Written {
    /// Vault-relative path.
    pub path: String,
    /// What happened.
    pub status: WriteStatus,
}

type Redact = std::sync::Arc<dyn Fn(&str) -> String + Send + Sync>;

/// The shared vault of a project.
pub struct ProjectVault {
    root: PathBuf,
    schema: Schema,
    limits: WriterLimits,
    redact: Option<Redact>,
    today: Box<dyn Fn() -> String + Send + Sync>,
}

fn io<T>(r: std::io::Result<T>) -> Result<T, VaultProblem> {
    r.map_err(VaultProblem::from)
}

/// `YYYY-MM-DD` of today (UTC).
pub fn today() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs());
    let days = (secs / 86_400) as i64;
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!("{y:04}-{m:02}-{d:02}")
}

fn is_vault(dir: &Path) -> bool {
    dir.join(".obsidian").is_dir()
}

/// A vault below `dir`, looking at most `depth` folders down and skipping hidden and build folders.
fn vault_below(dir: &Path, depth: usize) -> Option<PathBuf> {
    if depth == 0 {
        return None;
    }
    for entry in fs::read_dir(dir).ok()?.flatten() {
        let path = entry.path();
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if !path.is_dir()
            || name.starts_with('.')
            || matches!(name.as_ref(), "node_modules" | "target")
        {
            continue;
        }
        if is_vault(&path) {
            return Some(path);
        }
        if let Some(found) = vault_below(&path, depth - 1) {
            return Some(found);
        }
    }
    None
}

fn text(v: &str) -> Value {
    Value::Str(v.to_owned())
}

impl ProjectVault {
    /// A vault at `root` that is already there (made by `init` or by a person). No file is read or written.
    pub fn open(root: &Path, schema: Schema, limits: WriterLimits) -> Self {
        Self {
            root: root.to_path_buf(),
            schema,
            limits,
            redact: None,
            today: Box::new(today),
        }
    }

    /// Makes a vault at `root`, or adopts the one that is there.
    ///
    /// A new vault gets `.obsidian/app.json` and a root note `Index.md`. An existing vault gets nothing: not a file,
    /// not a folder. A vault inside or around `root` is refused.
    pub fn init(
        root: &Path,
        schema: Schema,
        limits: WriterLimits,
    ) -> Result<(Self, InitStatus), VaultProblem> {
        io(fs::create_dir_all(root))?;
        let root = io(root.canonicalize())?;
        for ancestor in root.ancestors().skip(1) {
            if is_vault(ancestor) {
                return Err(VaultProblem::InsideVault(ancestor.display().to_string()));
            }
        }
        let vault = Self::open(&root, schema, limits);
        if is_vault(&root) {
            return Ok((vault, InitStatus::Adopted));
        }
        if let Some(inner) = vault_below(&root, 4) {
            return Err(VaultProblem::ContainsVault(inner.display().to_string()));
        }
        let mut created = Vec::new();
        io(fs::create_dir_all(root.join(".obsidian")))?;
        let app = root.join(".obsidian/app.json");
        if !app.exists() {
            io(atomic_write(&app, "{}\n"))?;
            created.push(".obsidian/app.json".to_owned());
        }
        let index = root.join(ROOT_NOTE);
        if !index.exists() {
            let props = vec![
                ("type".to_owned(), text("index")),
                ("created".to_owned(), text(&(vault.today)())),
            ];
            let body = "# Index\n\nThe root of this vault. LARIS writes only inside its own blocks; \
                        everything else here is yours.";
            let rendered = render_note(&props, body)?;
            io(atomic_write(&index, &rendered))?;
            created.push(ROOT_NOTE.to_owned());
        }
        Ok((vault, InitStatus::Created(created)))
    }

    /// Hides secrets in what LARIS writes.
    #[must_use]
    pub fn with_redactor(
        mut self,
        redact: impl Fn(&str) -> String + Send + Sync + 'static,
    ) -> Self {
        self.redact = Some(std::sync::Arc::new(redact));
        self
    }

    /// Uses another date (tests).
    #[must_use]
    pub fn with_date(mut self, date: impl Fn() -> String + Send + Sync + 'static) -> Self {
        self.today = Box::new(date);
        self
    }

    /// The folder of the vault.
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// The note types.
    pub fn schema(&self) -> &Schema {
        &self.schema
    }

    /// The index of the vault as it is now.
    pub fn index(&self) -> Result<VaultIndex, VaultProblem> {
        VaultIndex::build(&self.root, None).map_err(|e| VaultProblem::Io(e.to_string()))
    }

    fn writer(&self) -> VaultWriter {
        let mut w = VaultWriter::new(&self.root, self.limits);
        if let Some(r) = &self.redact {
            let r = r.clone();
            w = w.with_redactor(Box::new(move |t| r(t)));
        }
        w
    }

    fn check_props(&self, kind: &str, props: &[(String, Value)]) -> Result<(), VaultProblem> {
        let Some(rule) = self.schema.types.get(kind) else {
            return Err(VaultProblem::Invalid(format!("no note type `{kind}`")));
        };
        let missing: Vec<&str> = rule
            .required
            .iter()
            .filter(|r| {
                !props.iter().any(|(k, v)| {
                    k == *r
                        && match v {
                            Value::Str(s) => !s.is_empty(),
                            Value::List(l) => !l.is_empty(),
                            Value::Null => false,
                            _ => true,
                        }
                })
            })
            .map(String::as_str)
            .collect();
        if missing.is_empty() {
            Ok(())
        } else {
            Err(VaultProblem::Invalid(format!(
                "a `{kind}` note needs: {}",
                missing.join(", ")
            )))
        }
    }

    fn put(
        &self,
        folder: &str,
        title: &str,
        props: &[(String, Value)],
        lead: &str,
        body: &str,
    ) -> Result<Written, VaultProblem> {
        let name = safe_title(title, "Untitled");
        let path = if folder.is_empty() {
            format!("{name}.md")
        } else {
            format!("{folder}/{name}.md")
        };
        if let Some(parent) = Path::new(&path)
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
        {
            io(fs::create_dir_all(self.root.join(parent)))?;
        }
        let status =
            self.writer()
                .write_note(&path, props, &[(BLOCK.to_owned(), body.to_owned())], lead)?;
        if status == WriteStatus::Conflict {
            return Err(VaultProblem::Conflict);
        }
        Ok(Written { path, status })
    }

    /// The vault path a note of `title` would have if it did not exist, avoiding another document's note.
    fn source_path(&self, title: &str, origin: &str, sha: &str) -> String {
        let name = safe_title(title, "Untitled");
        let folder = self.schema.folder_of("source").to_owned();
        let plain = if folder.is_empty() {
            name.clone()
        } else {
            format!("{folder}/{name}")
        };
        let taken_by_other = fs::read_to_string(self.root.join(format!("{plain}.md")))
            .ok()
            .is_some_and(|t| {
                let note = parse_note(&t, &format!("{plain}.md"));
                note.prop_list("source") != [origin.to_owned()]
            });
        if taken_by_other {
            format!("{plain} ({})", &sha[..8.min(sha.len())])
        } else {
            plain
        }
    }

    /// Writes the Source note of an ingested document. The same document again is `Unchanged`; the same title for
    /// another document gets its own note.
    pub fn source_note(
        &self,
        document: &Document,
        origin: &str,
        passages: usize,
        domain: Option<&str>,
    ) -> Result<Written, VaultProblem> {
        let plain = self.source_path(&document.title, origin, &document.sha256);
        let (folder, name) = plain
            .rsplit_once('/')
            .map_or(("", plain.as_str()), |(f, n)| (f, n));
        let mut props = vec![
            ("type".to_owned(), text("source")),
            ("trust".to_owned(), text("unverified")),
            ("source".to_owned(), text(origin)),
            ("created".to_owned(), text(&(self.today)())),
            ("kind".to_owned(), text(document.kind.as_str())),
            ("sha256".to_owned(), text(&document.sha256)),
        ];
        if let Some(d) = domain.filter(|d| !d.trim().is_empty()) {
            props.push(("domain".to_owned(), text(d.trim())));
        }
        self.check_props("source", &props)?;
        let body = format!(
            "- File: `{origin}`\n- Kind: {}\n- Characters: {}\n- Passages: {passages}\n- SHA-256: `{}`",
            document.kind.as_str(),
            document.text.chars().count(),
            document.sha256
        );
        let written = self.put(
            folder,
            name,
            &props,
            &format!("# {}", document.title),
            &body,
        )?;
        if let Some(d) = domain.filter(|d| !d.trim().is_empty()) {
            self.refresh_hub(d.trim())?;
        }
        Ok(written)
    }

    /// Writes a note of type `kind` with its provenance: `origin` says what made it and `sources` lists the notes it
    /// rests on (as titles). The text goes in LARIS's managed block.
    pub fn write_note(
        &self,
        kind: &str,
        title: &str,
        body: &str,
        extra: &[(String, Value)],
        origin: &str,
        sources: &[String],
    ) -> Result<Written, VaultProblem> {
        if matches!(kind, "source" | "proposal" | "index") {
            return Err(VaultProblem::Invalid(format!(
                "a `{kind}` note is not written this way"
            )));
        }
        let mut props = vec![
            ("type".to_owned(), text(kind)),
            ("created".to_owned(), text(&(self.today)())),
            ("origin".to_owned(), text(origin)),
        ];
        for (k, v) in extra {
            if !props.iter().any(|(p, _)| p == k) {
                props.push((k.clone(), v.clone()));
            }
        }
        if let Some(first) = sources.first() {
            if matches!(kind, "claim" | "limitation") {
                props.push(("source_ref".to_owned(), text(&format!("[[{first}]]"))));
            } else {
                let links = sources.iter().map(|s| text(&format!("[[{s}]]"))).collect();
                props.push(("sources".to_owned(), Value::List(links)));
            }
        }
        self.check_props(kind, &props)?;
        let folder = self.schema.folder_of(kind).to_owned();
        self.put(&folder, title, &props, &format!("# {title}"), body)
    }

    /// Keeps a memory in `Memory/`.
    pub fn remember(&self, name: &str, body: &str, origin: &str) -> Result<Written, VaultProblem> {
        self.write_note("memory", name, body, &[], origin, &[])
    }

    /// The notes of a domain, linked from its hub note `Knowledge/<Domain>.md`.
    pub fn refresh_hub(&self, domain: &str) -> Result<Written, VaultProblem> {
        let index = self.index()?;
        let mut members: Vec<String> = index
            .notes
            .values()
            .filter(|n| {
                n.prop_list("domain") == [domain.to_owned()]
                    && n.prop_list("type") != ["knowledge-hub"]
            })
            .map(|n| n.title.clone())
            .collect();
        members.sort();
        let list = members
            .iter()
            .map(|t| format!("- [[{t}]]"))
            .collect::<Vec<_>>()
            .join("\n");
        let props = vec![
            ("type".to_owned(), text("knowledge-hub")),
            ("domain".to_owned(), text(domain)),
            ("created".to_owned(), text(&(self.today)())),
        ];
        self.check_props("knowledge-hub", &props)?;
        let folder = self.schema.folder_of("knowledge-hub").to_owned();
        self.put(&folder, domain, &props, &format!("# {domain}"), &list)
    }

    /// Puts a suggestion in the inbox. It is a note of type `proposal`, status `pending`.
    pub fn propose(
        &self,
        title: &str,
        body: &str,
        origin: &str,
        target_type: &str,
    ) -> Result<Written, VaultProblem> {
        if !self.schema.types.contains_key(target_type)
            || matches!(target_type, "proposal" | "index")
        {
            return Err(VaultProblem::Invalid(format!(
                "a proposal cannot become a `{target_type}` note"
            )));
        }
        let props = vec![
            ("type".to_owned(), text("proposal")),
            ("status".to_owned(), text("pending")),
            ("origin".to_owned(), text(origin)),
            ("created".to_owned(), text(&(self.today)())),
            ("target_type".to_owned(), text(target_type)),
        ];
        self.check_props("proposal", &props)?;
        self.put(INBOX, title, &props, &format!("# {title}"), body)
    }

    /// The proposals, pending ones first.
    pub fn proposals(&self) -> Result<Vec<Proposal>, VaultProblem> {
        let index = self.index()?;
        let mut out: Vec<Proposal> = index
            .notes
            .values()
            .filter(|n| {
                n.path.starts_with(&format!("{INBOX}/")) && n.prop_list("type") == ["proposal"]
            })
            .map(|n| Proposal {
                path: n.path.clone(),
                title: n.title.clone(),
                status: n.prop_list("status").join(""),
                origin: n.prop_list("origin").join(""),
                target_type: n.prop_list("target_type").join(""),
            })
            .collect();
        out.sort_by(|a, b| (a.status != "pending", &a.path).cmp(&(b.status != "pending", &b.path)));
        Ok(out)
    }

    fn proposal(&self, title: &str) -> Result<(String, laris_vault::Note), VaultProblem> {
        let path = format!("{INBOX}/{}.md", safe_title(title, "Untitled"));
        let text = io(fs::read_to_string(self.root.join(&path)))
            .map_err(|_| VaultProblem::Invalid(format!("there is no proposal named `{title}`")))?;
        let note = parse_note(&text, &path);
        if note.prop_list("status") != ["pending"] {
            return Err(VaultProblem::Invalid(format!(
                "`{title}` was already decided"
            )));
        }
        Ok((path, note))
    }

    fn set_status(&self, path: &str, status: &str) -> Result<(), VaultProblem> {
        let full = self.root.join(path);
        let text = io(fs::read_to_string(&full))?;
        let note = parse_note(&text, path);
        let props: Vec<(String, Value)> = note
            .props
            .iter()
            .map(|(k, v)| {
                if k == "status" {
                    (k.clone(), Value::Str(status.to_owned()))
                } else {
                    (k.clone(), v.clone())
                }
            })
            .collect();
        io(atomic_write(&full, &render_note(&props, &note.body)?))
    }

    /// Turns a pending proposal into a note of its target type, where that type lives, and marks it accepted. An
    /// existing note is never overwritten.
    pub fn accept(&self, title: &str) -> Result<Written, VaultProblem> {
        let (path, note) = self.proposal(title)?;
        let kind = note.prop_list("target_type").join("");
        let folder = self.schema.folder_of(&kind).to_owned();
        let target = if folder.is_empty() {
            format!("{}.md", note.title)
        } else {
            format!("{folder}/{}.md", note.title)
        };
        if self.root.join(&target).exists() {
            return Err(VaultProblem::Exists(target));
        }
        let props = vec![
            ("type".to_owned(), text(&kind)),
            ("created".to_owned(), text(&(self.today)())),
            (
                "origin".to_owned(),
                text(&note.prop_list("origin").join("")),
            ),
            (
                "accepted_from".to_owned(),
                text(&format!("[[{}]]", note.title)),
            ),
        ];
        // a type that asks for more than a proposal can say is refused, not guessed
        if let Some(rule) = self.schema.types.get(&kind) {
            let missing: Vec<&String> = rule
                .required
                .iter()
                .filter(|r| !props.iter().any(|(k, _)| k == *r))
                .collect();
            if !missing.is_empty() {
                return Err(VaultProblem::Invalid(format!(
                    "a `{kind}` note also needs: {}; write it with write_vault_note instead",
                    missing
                        .iter()
                        .map(|s| s.as_str())
                        .collect::<Vec<_>>()
                        .join(", ")
                )));
            }
        }
        let body = laris_vault::writer::block(
            BLOCK,
            note.body
                .trim_start_matches(&format!("# {}", note.title))
                .trim(),
        );
        io(fs::create_dir_all(
            self.root.join(&target).parent().unwrap_or(&self.root),
        ))?;
        io(atomic_write(
            &self.root.join(&target),
            &render_note(&props, &format!("# {}\n\n{body}", note.title))?,
        ))?;
        self.set_status(&path, "accepted")?;
        Ok(Written {
            path: target,
            status: WriteStatus::Created,
        })
    }

    /// Marks a pending proposal rejected. The note stays in the inbox.
    pub fn reject(&self, title: &str) -> Result<(), VaultProblem> {
        let (path, _) = self.proposal(title)?;
        self.set_status(&path, "rejected")
    }
}
