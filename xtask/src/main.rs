//! `cargo xtask <command>`: governance helpers of the workspace.
//!
//! Commands: `spec` checks the ledger (port of `scripts/validate_spec.py`); `guard` is the
//! no-training guard over the Rust sources and CI files.

mod guard;
mod spec;

use std::path::{Path, PathBuf};
use std::process::ExitCode;

/// Workspace root: the parent of this crate's manifest directory.
fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_default()
}

fn main() -> ExitCode {
    let mut args = std::env::args().skip(1);
    let root = workspace_root();
    match args.next().as_deref() {
        Some("spec") => spec::run(&root),
        Some("guard") => guard::run(&args.next().map_or(root, PathBuf::from)),
        _ => {
            eprintln!("usage: cargo xtask <spec | guard [root]>");
            ExitCode::from(2)
        }
    }
}
