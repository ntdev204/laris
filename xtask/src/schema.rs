//! `cargo xtask schema [--check]`: writes the JSON Schema of P1 and P2, or checks the committed file.

use std::path::Path;
use std::process::ExitCode;

const FILE: &str = "crates/laris-protocol/schema/laris-protocol.schema.json";

pub fn run(root: &Path, check: bool) -> ExitCode {
    let path = root.join(FILE);
    let fresh = laris_protocol::schema::export_string();
    if check {
        if std::fs::read_to_string(&path).is_ok_and(|current| current == fresh) {
            println!("schema: {FILE} is current");
            return ExitCode::SUCCESS;
        }
        eprintln!("schema: {FILE} is stale; run `cargo xtask schema`");
        return ExitCode::FAILURE;
    }
    if let Some(dir) = path.parent()
        && let Err(e) = std::fs::create_dir_all(dir)
    {
        eprintln!("schema: {e}");
        return ExitCode::FAILURE;
    }
    match std::fs::write(&path, fresh) {
        Ok(()) => {
            println!("schema: wrote {FILE}");
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("schema: {e}");
            ExitCode::FAILURE
        }
    }
}
