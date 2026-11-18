//! `laris-sandbox-helper`: applies the restrictions named on its command line and then becomes the command.
#![allow(missing_docs)]

#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::process::{Command, ExitCode};

fn main() -> ExitCode {
    let (restrictions, command) =
        match laris_sandbox::helper::parse_args(std::env::args_os().skip(1)) {
            Ok(parsed) => parsed,
            Err(e) => {
                eprintln!("laris-sandbox-helper: {e}");
                return ExitCode::from(125);
            }
        };
    if let Err(e) = laris_sandbox::helper::apply(&restrictions) {
        eprintln!("laris-sandbox-helper: {e}");
        return ExitCode::from(125);
    }
    #[cfg(unix)]
    let error = Command::new(&command[0]).args(&command[1..]).exec();
    #[cfg(not(unix))]
    let error = std::io::Error::other("the helper runs on Unix only");
    eprintln!("laris-sandbox-helper: cannot run {:?}: {error}", command[0]);
    ExitCode::from(127)
}
