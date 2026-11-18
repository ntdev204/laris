//! Binary laris.

use laris_cli::learn;
use std::path::PathBuf;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("learn") => {
            let env: Vec<(String, String)> = std::env::vars().collect();
            let home = env
                .iter()
                .find(|(k, _)| k == "HOME")
                .map(|(_, v)| PathBuf::from(v).join(".laris"));
            let (Some(home), Ok(project)) = (home, std::env::current_dir()) else {
                eprintln!("laris: cannot find the home or the working folder");
                return ExitCode::from(2);
            };
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_or(0.0, |d| d.as_secs_f64());
            let cx = learn::Context {
                home,
                project,
                env,
                now,
            };
            match learn::run(&args[1..], &cx) {
                Ok(out) => {
                    println!("{out}");
                    ExitCode::SUCCESS
                }
                Err(message) => {
                    eprintln!("laris learn: {message}");
                    ExitCode::from(2)
                }
            }
        }
        _ => {
            eprintln!(
                "usage: laris learn <stats | collect [--session ID] | export --kind sft|retrieval|preference --out FILE [--min-rating none|up] | rate ID up|down | purge --yes>"
            );
            ExitCode::from(2)
        }
    }
}
