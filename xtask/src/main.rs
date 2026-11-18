//! `cargo xtask <command>`: governance helpers of the workspace.
//!
//! Commands: `schema [--check]` writes or checks the P1/P2 JSON Schema; `spec` checks the ledger (port of `scripts/validate_spec.py`); `guard` is the
//! no-training guard over the Rust sources and CI files; `scan` finds hardcoded endpoints and secrets.

mod guard;
mod scan;
mod schema;
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
        Some("schema") => schema::run(&root, args.next().as_deref() == Some("--check")),
        Some("scan") => scan::run(&args.next().map_or(root, PathBuf::from)),
        Some("guard") => guard::run(&args.next().map_or(root, PathBuf::from)),
        _ => {
            eprintln!("usage: cargo xtask <spec | guard [root] | scan [root] | schema [--check]>");
            ExitCode::from(2)
        }
    }
}
