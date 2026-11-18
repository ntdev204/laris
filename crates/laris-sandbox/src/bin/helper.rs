//! `laris-sandbox-helper`: applies the restrictions named on its command line and then becomes (Unix) or runs
//! (Windows) the command.
#![allow(missing_docs)]

use std::process::ExitCode;

#[cfg(unix)]
fn main() -> ExitCode {
    use std::os::unix::process::CommandExt;
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
    let error = std::process::Command::new(&command[0])
        .args(&command[1..])
        .exec();
    eprintln!("laris-sandbox-helper: cannot run {:?}: {error}", command[0]);
    ExitCode::from(127)
}

#[cfg(windows)]
fn main() -> ExitCode {
    match laris_sandbox::windows::run_from_args(std::env::args_os().skip(1)) {
        // the command's own code, kept to the range an `ExitCode` holds
        Ok(code) => ExitCode::from(u8::try_from(code).unwrap_or(1)),
        Err(e) => {
            eprintln!("laris-sandbox-helper: {e}");
            ExitCode::from(125)
        }
    }
}
