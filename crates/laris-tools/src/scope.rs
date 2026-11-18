//! Which paths a tool may touch: the project folder and the extra folders the permissions name, minus secrets.
//!
//! A path is resolved before it is judged, so `..` and symbolic links cannot leave the allowed folders. `.git` and
//! the policy folder `.laris` are never written by a tool (the policy changes only with the owner's approval).

use crate::error::ToolError;
use crate::glob::glob_to_regex;
use regex::Regex;
use std::path::{Component, Path, PathBuf};

/// Folders no tool writes.
const NEVER_WRITTEN: [&str; 2] = [".git", ".laris"];

/// The allowed folders and the file names that are never read or written.
#[derive(Clone, Debug)]
pub struct Scope {
    roots: Vec<PathBuf>,
    denied: Vec<Regex>,
}

impl Scope {
    /// A scope over `root` and `extra` folders (which must exist), with `denied_files` name patterns.
    pub fn new(root: &Path, extra: &[PathBuf], denied_files: &[String]) -> Result<Self, ToolError> {
        let mut roots = Vec::new();
        for path in std::iter::once(root).chain(extra.iter().map(PathBuf::as_path)) {
            let resolved = path.canonicalize().map_err(|e| {
                ToolError::io("invalid_root", &format!("folder {}", path.display()), &e)
            })?;
            if !roots.contains(&resolved) {
                roots.push(resolved);
            }
        }
        let denied = denied_files
            .iter()
            .map(|pattern| {
                glob_to_regex(pattern).ok_or_else(|| {
                    ToolError::new(
                        "invalid_setting",
                        format!("bad denied file pattern `{pattern}`"),
                    )
                })
            })
            .collect::<Result<_, _>>()?;
        Ok(Self { roots, denied })
    }

    /// The project folder, resolved.
    pub fn root(&self) -> &Path {
        &self.roots[0]
    }

    /// Whether `path` (already resolved) is inside an allowed folder.
    pub fn inside(&self, path: &Path) -> bool {
        self.roots.iter().any(|root| path.starts_with(root))
    }

    /// Whether the file name of `path` is a secret.
    pub fn is_secret(&self, path: &Path) -> bool {
        path.file_name()
            .and_then(|n| n.to_str())
            .is_some_and(|name| self.denied.iter().any(|re| re.is_match(name)))
    }

    /// `path` as shown to the model: relative to the folder it is in, never absolute.
    pub fn display(&self, path: &Path) -> String {
        for root in &self.roots {
            if let Ok(relative) = path.strip_prefix(root) {
                return relative
                    .components()
                    .map(|c| c.as_os_str().to_string_lossy().into_owned())
                    .collect::<Vec<_>>()
                    .join("/");
            }
        }
        path.file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default()
    }

    /// Resolves `raw` (relative to the project folder) and checks it. With `write` it also refuses `.git` and
    /// `.laris`. Errors: `outside_project`, `denied`.
    pub fn resolve(&self, raw: &str, write: bool) -> Result<PathBuf, ToolError> {
        let given = Path::new(raw);
        let joined = if given.is_absolute() {
            given.to_path_buf()
        } else {
            self.root().join(given)
        };
        let lexical = normalise(&joined);
        let path = real(&lexical)?;
        if !self.inside(&path) {
            return Err(ToolError::new(
                "outside_project",
                "the path is outside the project folders",
            ));
        }
        if self.is_secret(&path) || self.is_secret(&lexical) {
            return Err(ToolError::new("denied", "this file is internal or secret"));
        }
        if write && self.never_written(&path) {
            return Err(ToolError::new(
                "denied",
                "this folder is never written by tools",
            ));
        }
        Ok(path)
    }

    /// `raw` (relative to the project folder) as a resolved path, without judging it: for the permission rules,
    /// which must match the path a tool would touch and never its spelling. `None` when it cannot be resolved.
    pub fn locate(&self, raw: &str) -> Option<PathBuf> {
        let given = Path::new(raw);
        let joined = if given.is_absolute() {
            given.to_path_buf()
        } else {
            self.root().join(given)
        };
        real(&normalise(&joined)).ok()
    }

    /// `path` relative to the project folder, with `/` separators; `None` outside it.
    pub fn relative_to_root(&self, path: &Path) -> Option<String> {
        path.strip_prefix(self.root()).ok().map(|relative| {
            relative
                .components()
                .map(|c| c.as_os_str().to_string_lossy().into_owned())
                .collect::<Vec<_>>()
                .join("/")
        })
    }

    fn never_written(&self, path: &Path) -> bool {
        self.roots.iter().any(|root| {
            path.strip_prefix(root).is_ok_and(|relative| {
                let parts: Vec<_> = relative.components().collect();
                let first = parts.first().and_then(|c| c.as_os_str().to_str());
                first.is_some_and(|f| NEVER_WRITTEN.contains(&f))
                    || parts.iter().any(|c| c.as_os_str() == ".git")
            })
        })
    }

    /// Whether a tool could write `path` now (used by rewind, which never writes where a tool could not).
    pub fn writable(&self, path: &Path) -> bool {
        self.inside(path) && !self.is_secret(path) && !self.never_written(path)
    }
}

/// Removes `.` and resolves `..` lexically.
fn normalise(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                if !out.pop() {
                    out.push("..");
                }
            }
            other => out.push(other.as_os_str()),
        }
    }
    out
}

/// The path with every existing part resolved (symbolic links followed); a part that does not exist yet is
/// appended as written.
fn real(path: &Path) -> Result<PathBuf, ToolError> {
    let mut rest = Vec::new();
    let mut base = path.to_path_buf();
    loop {
        match base.canonicalize() {
            Ok(resolved) => {
                let mut out = resolved;
                out.extend(rest.iter().rev());
                return Ok(out);
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                // a dangling link would resolve to nothing: refuse it instead of writing through it
                if base.symlink_metadata().is_ok() {
                    return Err(ToolError::new("outside_project", "a dangling link"));
                }
                match (base.file_name().map(ToOwned::to_owned), base.parent()) {
                    (Some(name), Some(parent)) => {
                        rest.push(name);
                        base = parent.to_path_buf();
                    }
                    _ => return Err(ToolError::new("not_found", "no such path")),
                }
            }
            Err(error) => {
                return Err(ToolError::io(
                    "unreadable",
                    "cannot resolve the path",
                    &error,
                ));
            }
        }
    }
}
