//! The integrity lock of the protected policy files (SR-S4; rule G-3).
//!
//! `.laris/integrity.lock` holds a SHA-256 per file of `LARIS.md`, the help text and everything under `.laris/prompts`,
//! `rules`, `workflows`, `brain` and `vault`. The format and the set of files are those of generation 1, so the lock
//! the Python harness wrote verifies here and the other way round.
//!
//! The server reads every protected file once into a [`Snapshot`], hashes those bytes, compares them with the lock,
//! and builds everything it serves from the same bytes: a file that changes on disk after the check cannot slip into
//! the prompt. A problem is reported by name and kind only, never by content.

use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

/// The lock file, relative to the project root.
pub const LOCK_FILE: &str = ".laris/integrity.lock";
/// The root instruction file.
pub const ROOT_FILE: &str = "LARIS.md";
/// The prepared user guide.
pub const HELP_FILE: &str = ".laris/help/how-to-use.md";
/// Folders whose files are protected.
pub const PROTECTED_DIRS: [&str; 5] = [
    ".laris/prompts",
    ".laris/rules",
    ".laris/workflows",
    ".laris/brain",
    ".laris/vault",
];

/// Largest protected file, and the most bytes in all: a bigger tree is refused rather than half read.
const MAX_FILE: u64 = 8 << 20;
const MAX_TOTAL: u64 = 64 << 20;

/// The policy cannot be read or does not match its lock.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum IntegrityError {
    /// A protected file or folder could not be read.
    #[error("cannot read {0}")]
    Unreadable(String),
    /// A symbolic link or special file sits inside a protected folder.
    #[error("{0} is not a regular file")]
    NotRegular(String),
    /// The protected tree is larger than the server reads.
    #[error("the protected policy files are too large")]
    TooLarge,
    /// The lock disagrees with the files; each entry names one file.
    #[error("the policy does not match integrity.lock: {}", .0.join("; "))]
    Mismatch(Vec<String>),
}

/// Every protected file, read once.
#[derive(Debug, Clone, Default)]
pub struct Snapshot {
    files: BTreeMap<String, Vec<u8>>,
}

fn label_of(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .components()
        .map(|c| c.as_os_str().to_string_lossy().into_owned())
        .collect::<Vec<_>>()
        .join("/")
}

impl Snapshot {
    /// Reads the protected files under `root`.
    pub fn read(root: &Path) -> Result<Self, IntegrityError> {
        let mut snapshot = Self::default();
        let mut total = 0u64;
        let mut paths = Vec::new();
        for single in [ROOT_FILE, HELP_FILE] {
            let path = root.join(single);
            if path.is_file() {
                paths.push(path);
            }
        }
        for dir in PROTECTED_DIRS {
            let path = root.join(dir);
            if path.is_dir() {
                walk(root, &path, &mut paths)?;
            }
        }
        for path in paths {
            let label = label_of(root, &path);
            let meta = fs::symlink_metadata(&path)
                .map_err(|_| IntegrityError::Unreadable(label.clone()))?;
            if !meta.is_file() {
                return Err(IntegrityError::NotRegular(label));
            }
            total += meta.len();
            if meta.len() > MAX_FILE || total > MAX_TOTAL {
                return Err(IntegrityError::TooLarge);
            }
            let bytes = fs::read(&path).map_err(|_| IntegrityError::Unreadable(label.clone()))?;
            snapshot.files.insert(label, bytes);
        }
        Ok(snapshot)
    }

    /// The bytes of one protected file by its label (`.laris/prompts/manifest.yaml`).
    pub fn get(&self, label: &str) -> Option<&[u8]> {
        self.files.get(label).map(Vec::as_slice)
    }

    /// One protected file as text; a file that is not UTF-8 is a policy fault.
    pub fn text(&self, label: &str) -> Option<Result<&str, IntegrityError>> {
        self.get(label).map(|b| {
            std::str::from_utf8(b).map_err(|_| IntegrityError::Unreadable(label.to_owned()))
        })
    }

    /// Labels of the files inside `dir`, with `suffix`, sorted.
    pub fn labels_in(&self, dir: &str, suffix: &str) -> Vec<&str> {
        let prefix = format!("{dir}/");
        self.files
            .keys()
            .filter(|k| k.starts_with(&prefix) && k.ends_with(suffix))
            .map(String::as_str)
            .collect()
    }

    /// The SHA-256 of every file, by label.
    pub fn digests(&self) -> BTreeMap<String, String> {
        self.files
            .iter()
            .map(|(k, v)| (k.clone(), hex(&Sha256::digest(v))))
            .collect()
    }

    /// What differs from the lock text; empty when the policy is intact.
    pub fn problems(&self, lock: Option<&str>) -> Vec<String> {
        let Some(lock) = lock else {
            return vec!["integrity lock is missing".to_owned()];
        };
        let Some(expected) = parse_lock(lock) else {
            return vec!["integrity lock is unreadable".to_owned()];
        };
        let actual = self.digests();
        let mut out = Vec::new();
        for (name, digest) in &actual {
            if expected.get(name).is_some_and(|e| e != digest) {
                out.push(format!("changed: {name}"));
            }
        }
        out.extend(
            actual
                .keys()
                .filter(|n| !expected.contains_key(*n))
                .map(|n| format!("added: {n}")),
        );
        out.extend(
            expected
                .keys()
                .filter(|n| !actual.contains_key(*n))
                .map(|n| format!("missing: {n}")),
        );
        out
    }

    /// The text of a new lock for these files, byte for byte what generation 1 wrote
    /// (`json.dumps(indent=2, sort_keys=True)` and a newline).
    pub fn render_lock(&self) -> String {
        let mut out = String::from("{\n  \"algorithm\": \"sha256\",\n  \"files\": {");
        let digests = self.digests();
        if digests.is_empty() {
            out.push('}');
        } else {
            out.push('\n');
            let last = digests.len() - 1;
            for (i, (name, digest)) in digests.iter().enumerate() {
                out.push_str(&format!(
                    "    {}: \"{digest}\"{}\n",
                    ascii_json(name),
                    if i == last { "" } else { "," }
                ));
            }
            out.push_str("  ");
            out.push('}');
        }
        out.push_str("\n}\n");
        out
    }
}

/// Reads the project's policy, checks it against its lock and returns it, or says what differs.
pub fn verified(root: &Path) -> Result<Snapshot, IntegrityError> {
    let snapshot = Snapshot::read(root)?;
    let lock = fs::read_to_string(root.join(LOCK_FILE)).ok();
    let problems = snapshot.problems(lock.as_deref());
    if problems.is_empty() {
        Ok(snapshot)
    } else {
        Err(IntegrityError::Mismatch(problems))
    }
}

/// Writes a fresh lock for the files as they are now. The owner runs this after approving a policy change.
pub fn write_lock(root: &Path) -> Result<PathBuf, IntegrityError> {
    let snapshot = Snapshot::read(root)?;
    let path = root.join(LOCK_FILE);
    let tmp = path.with_extension("lock.tmp");
    fs::write(&tmp, snapshot.render_lock())
        .and_then(|()| fs::rename(&tmp, &path))
        .map_err(|_| IntegrityError::Unreadable(LOCK_FILE.to_owned()))?;
    Ok(path)
}

fn walk(root: &Path, dir: &Path, out: &mut Vec<PathBuf>) -> Result<(), IntegrityError> {
    let unreadable = || IntegrityError::Unreadable(label_of(root, dir));
    let mut entries: Vec<_> = fs::read_dir(dir)
        .map_err(|_| unreadable())?
        .collect::<Result<_, _>>()
        .map_err(|_| unreadable())?;
    entries.sort_by_key(fs::DirEntry::file_name);
    for entry in entries {
        let path = entry.path();
        if path.components().any(|c| c.as_os_str() == "__pycache__") {
            continue;
        }
        let kind = entry.file_type().map_err(|_| unreadable())?;
        if kind.is_dir() {
            walk(root, &path, out)?;
        } else {
            out.push(path);
        }
    }
    Ok(())
}

fn parse_lock(text: &str) -> Option<BTreeMap<String, String>> {
    let value: serde_json::Value = serde_json::from_str(text).ok()?;
    let files = value.get("files")?.as_object()?;
    files
        .iter()
        .map(|(k, v)| Some((k.clone(), v.as_str()?.to_owned())))
        .collect()
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// A JSON string with every non-ASCII character escaped, as Python's `ensure_ascii` writes it.
fn ascii_json(text: &str) -> String {
    let mut out = String::from("\"");
    for c in text.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 || (c as u32) > 0x7e => {
                let mut units = [0u16; 2];
                for unit in c.encode_utf16(&mut units) {
                    out.push_str(&format!("\\u{unit:04x}"));
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keys_are_escaped_like_python() {
        assert_eq!(ascii_json("a/b \"c\""), r#""a/b \"c\"""#);
        assert_eq!(ascii_json("é😀"), r#""\u00e9\ud83d\ude00""#);
        assert_eq!(ascii_json("\u{7f}"), r#""\u007f""#);
    }
}
