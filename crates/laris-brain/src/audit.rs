//! The append-only audit record of the gate (ADR-024 section 4, step 5): who proposed, what was checked, what was decided.
//!
//! One JSON object per line in `.laris/brain-audit.jsonl` below the vault root, a folder the vault index never scans.
//! Lines are only ever appended.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};

/// Where the audit lives, relative to the vault root.
pub const AUDIT_FILE: &str = ".laris/brain-audit.jsonl";

/// The audit file of the vault at `root`.
pub fn path(root: &Path) -> PathBuf {
    root.join(AUDIT_FILE)
}

/// Appends `record` with the next sequence number. Returns that number.
pub fn append(root: &Path, mut record: Value) -> std::io::Result<u64> {
    let file = path(root);
    if let Some(dir) = file.parent() {
        fs::create_dir_all(dir)?;
    }
    let seq = fs::read_to_string(&file).map_or(0, |t| t.lines().count() as u64) + 1;
    if let Value::Object(map) = &mut record {
        map.insert("seq".to_string(), json!(seq));
    }
    let mut out = OpenOptions::new().create(true).append(true).open(&file)?;
    out.write_all(format!("{record}\n").as_bytes())?;
    out.sync_all()?;
    Ok(seq)
}

/// Every record, oldest first; lines that are not JSON are skipped.
pub fn read(root: &Path) -> Vec<Value> {
    fs::read_to_string(path(root))
        .unwrap_or_default()
        .lines()
        .filter_map(|l| serde_json::from_str(l).ok())
        .collect()
}
