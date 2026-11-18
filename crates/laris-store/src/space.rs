//! Where a private space lives: `<home>/projects/<slug>/<key-fingerprint>.sqlite`.

use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

/// Characters outside `[a-z0-9._-]` collapse into one `-`.
fn collapse(name: &str) -> String {
    let mut out = String::new();
    let mut pending = false;
    for ch in name.to_lowercase().chars() {
        if ch.is_ascii_lowercase() || ch.is_ascii_digit() || matches!(ch, '.' | '_' | '-') {
            if pending {
                out.push('-');
                pending = false;
            }
            out.push(ch);
        } else {
            pending = true;
        }
    }
    if pending {
        out.push('-');
    }
    out.trim_matches('-').to_owned()
}

/// The project folder name plus the first eight hex digits of the SHA-256 of its absolute path.
pub fn slug_of(project_root: &Path) -> String {
    let resolved = std::fs::canonicalize(project_root)
        .or_else(|_| std::path::absolute(project_root))
        .unwrap_or_else(|_| project_root.to_path_buf());
    let name = resolved
        .file_name()
        .map(|n| collapse(&n.to_string_lossy()))
        .filter(|n| !n.is_empty())
        .unwrap_or_else(|| "project".to_owned());
    let digest = Sha256::digest(resolved.to_string_lossy().as_bytes());
    let hex: String = digest.iter().take(4).map(|b| format!("{b:02x}")).collect();
    format!("{name}-{hex}")
}

/// A key fingerprint reduced to `[a-z0-9._-]`; `local` when none is given or nothing is left.
pub fn fingerprint_of(key_fingerprint: Option<&str>) -> String {
    let kept: String = key_fingerprint
        .unwrap_or("local")
        .to_lowercase()
        .chars()
        .filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, '.' | '_' | '-'))
        .collect();
    if kept.is_empty() {
        "local".to_owned()
    } else {
        kept
    }
}

/// The database file of a project and key.
pub fn space_path(home: &Path, project_root: &Path, key_fingerprint: Option<&str>) -> PathBuf {
    home.join("projects")
        .join(slug_of(project_root))
        .join(format!("{}.sqlite", fingerprint_of(key_fingerprint)))
}
