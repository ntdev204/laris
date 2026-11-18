//! The permission policy a command runs under: what it may read, what it may write, whether it has a network.
//!
//! This is LARIS's own small type. It replaces the `codex-protocol` permission model the codex sandbox was written
//! against (T134 decision 1, `docs/architecture/SANDBOX_MEASUREMENT.md`). Nothing here touches the operating system;
//! the backends turn a `Policy` into bubblewrap arguments, a Landlock ruleset or a Seatbelt profile.

use std::path::{Path, PathBuf};

/// Names that stay read-only inside a writable root (project metadata and LARIS policy).
pub const PROTECTED_NAMES: [&str; 2] = [".git", ".laris"];

/// What a command may read.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Readable {
    /// The whole disk (the usual case).
    Everything,
    /// Only the platform's system folders and these roots.
    Only(Vec<PathBuf>),
}

/// The permissions of one sandboxed command.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Policy {
    /// What may be read.
    pub readable: Readable,
    /// Folders that may be written (their contents too). Everything else is read-only.
    pub writable: Vec<PathBuf>,
    /// Paths hidden from reads even when they lie inside a readable root.
    pub deny_read: Vec<PathBuf>,
    /// File or folder names that stay read-only inside every writable root.
    pub protected_names: Vec<String>,
    /// Whether the command has a network.
    pub network: bool,
}

impl Policy {
    /// Read everything, write only `roots`, no network, `.git` and `.laris` protected.
    #[must_use]
    pub fn workspace(roots: impl IntoIterator<Item = PathBuf>) -> Self {
        Self {
            readable: Readable::Everything,
            writable: roots.into_iter().collect(),
            deny_read: Vec::new(),
            protected_names: PROTECTED_NAMES.iter().map(|s| (*s).to_owned()).collect(),
            network: false,
        }
    }

    /// Read everything, write nothing, no network.
    #[must_use]
    pub fn read_only() -> Self {
        Self::workspace(Vec::new())
    }

    /// Allows or forbids the network.
    #[must_use]
    pub fn with_network(mut self, on: bool) -> Self {
        self.network = on;
        self
    }

    /// Hides `paths` from reads.
    #[must_use]
    pub fn with_deny_read(mut self, paths: impl IntoIterator<Item = PathBuf>) -> Self {
        self.deny_read.extend(paths);
        self
    }

    /// Limits reads to the system folders and `roots`.
    #[must_use]
    pub fn with_readable_only(mut self, roots: impl IntoIterator<Item = PathBuf>) -> Self {
        self.readable = Readable::Only(roots.into_iter().collect());
        self
    }

    /// The protected paths that exist inside the writable roots: they are mounted read-only.
    #[must_use]
    pub fn protected_paths(&self) -> Vec<PathBuf> {
        let mut found = Vec::new();
        for root in &self.writable {
            for name in &self.protected_names {
                let path = root.join(name);
                if path.symlink_metadata().is_ok() && !found.contains(&path) {
                    found.push(path);
                }
            }
        }
        found
    }

    /// Whether `path` is inside a writable root and not under a protected name.
    #[must_use]
    pub fn allows_write(&self, path: &Path) -> bool {
        self.writable.iter().any(|root| {
            path.starts_with(root)
                && !self
                    .protected_names
                    .iter()
                    .any(|name| path.starts_with(root.join(name)))
        })
    }
}

/// Why a command could not be confined or started.
#[derive(Debug, thiserror::Error)]
pub enum SandboxError {
    /// No backend can enforce the policy on this machine. The command must not run unconfined.
    #[error("sandbox unavailable: {0}")]
    Unavailable(String),
    /// The policy asks for something this backend cannot enforce.
    #[error("sandbox cannot enforce this policy: {0}")]
    Unsupported(String),
    /// The Python environment could not be built or repaired.
    #[error("python environment: {0}")]
    Python(String),
    /// A file or process failed.
    #[error("{context}: {source}")]
    Io {
        /// What was being done.
        context: String,
        /// The cause.
        source: std::io::Error,
    },
}

impl SandboxError {
    pub(crate) fn io(context: &str, source: std::io::Error) -> Self {
        Self::Io {
            context: context.to_owned(),
            source,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn write_is_limited_to_roots_and_protected_names_are_excluded() {
        let policy = Policy::workspace([PathBuf::from("/work")]);
        assert!(policy.allows_write(Path::new("/work/a.txt")));
        assert!(!policy.allows_write(Path::new("/elsewhere/a.txt")));
        assert!(!policy.allows_write(Path::new("/work/.git/config")));
        assert!(!policy.allows_write(Path::new("/work/.laris/rules")));
        assert!(!policy.network);
    }
}
