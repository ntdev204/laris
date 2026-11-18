//! `cargo xtask schema [--check]`: writes the JSON Schema files (P1/P2 and core events; client settings), or
//! checks that the committed files are current.

use std::path::Path;
use std::process::ExitCode;

const PROTOCOL: &str = "crates/laris-protocol/schema/laris-protocol.schema.json";
const SETTINGS: &str = "crates/laris-config/schema/settings.schema.json";

fn files() -> [(&'static str, String); 2] {
    [
        (PROTOCOL, laris_protocol::schema::export_string()),
        (SETTINGS, laris_config::settings::schema_string()),
    ]
}

pub fn run(root: &Path, check: bool) -> ExitCode {
    let mut ok = true;
    for (file, fresh) in files() {
        let path = root.join(file);
        if check {
            if std::fs::read_to_string(&path).is_ok_and(|current| current == fresh) {
                println!("schema: {file} is current");
            } else {
                eprintln!("schema: {file} is stale; run `cargo xtask schema`");
                ok = false;
            }
            continue;
        }
        if let Some(dir) = path.parent()
            && let Err(e) = std::fs::create_dir_all(dir)
        {
            eprintln!("schema: {e}");
            ok = false;
            continue;
        }
        match std::fs::write(&path, fresh) {
            Ok(()) => println!("schema: wrote {file}"),
            Err(e) => {
                eprintln!("schema: {e}");
                ok = false;
            }
        }
    }
    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}
