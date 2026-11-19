//! `cargo xtask <command>`: governance helpers of the workspace.
//!
//! Commands: `dist` packages, signs and checks a release (T159); `security` runs the security suite of the threat model (T154); `bench` measures the performance budgets (T154); `eval` is the model-free evaluation runner (T140); `schema [--check]` writes or checks the P1/P2 JSON Schema; `spec` checks the ledger (port of `scripts/validate_spec.py`); `guard` is the
//! no-training guard over the Rust sources and CI files; `scan` finds hardcoded endpoints and secrets.

mod bench;
mod dist;
mod eval;
mod guard;
mod scan;
mod schema;
mod security;
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
        Some("dist") => dist::run_dist(&root, &args.collect::<Vec<_>>()),
        Some("eval") => eval::run(&root, &args.collect::<Vec<_>>()),
        Some("spec") => spec::run(&root),
        Some("security") => security::run(&root, &args.collect::<Vec<_>>()),
        Some("bench") => bench::run(&root, &args.collect::<Vec<_>>()),
        Some("schema") => schema::run(&root, args.next().as_deref() == Some("--check")),
        Some("scan") => scan::run(&args.next().map_or(root, PathBuf::from)),
        Some("guard") => guard::run(&args.next().map_or(root, PathBuf::from)),
        _ => {
            eprintln!(
                "usage: cargo xtask <spec | dist <subcommand> | eval [options] | security [options] | bench [options] | guard [root] | scan [root] | schema [--check]>"
            );
            ExitCode::from(2)
        }
    }
}
