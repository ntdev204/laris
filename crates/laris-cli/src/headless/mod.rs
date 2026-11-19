//! `laris -p`: one request, no interface (SR-C5).
//!
//! The request comes from the arguments and standard input; the answer goes to standard output as `text`, as one
//! `json` object, or as `stream-json` (the core events of [`laris_protocol`] as JSON lines, written the moment they
//! happen). Nobody can be asked for approval, so a call that needs one is refused with the typed error the model is
//! told (`approval_denied`); `--allowedTools`, `--disallowedTools` and `--permission-mode` say beforehand what may
//! run. Every run is a session in the project's store, so `--continue` and `--resume ID` pick it up again.
//!
//! The run itself ([`execute`]) takes its model and tools as parts, so tests drive it with a scripted model;
//! [`real`] builds the parts that talk to the server.
//!
//! Exit codes ([`exit`]): 0 the turn completed, 1 it failed, 2 usage, 3 not signed in, 4 the turn limit was
//! reached, 5 no such session. Interrupting the process is left to the operating system (the signal ends it and the
//! session resumes from its log).

pub mod args;
pub mod real;
mod run;
mod server;

pub use args::{Format, Options, Resume, USAGE, parse};
pub use run::{
    Console, INPUT_LIMIT, MAX_TURNS, Opened, Setup, engine, execute, open_session, read_request,
};
pub use server::{HttpRemote, ServerModel};

/// The exit codes of a headless run.
pub mod exit {
    /// The turn completed.
    pub const OK: u8 = 0;
    /// The turn failed: a model or tool failure, a timeout, a loop that repeats itself.
    pub const FAILED: u8 = 1;
    /// The command line or the input is wrong.
    pub const USAGE: u8 = 2;
    /// There is no server or key to ask.
    pub const NOT_SIGNED_IN: u8 = 3;
    /// The model calls allowed in the turn ran out before an answer.
    pub const TURN_LIMIT: u8 = 4;
    /// The session to continue or resume does not exist.
    pub const NO_SESSION: u8 = 5;
}

/// The exit code of a turn that ended with `status` (the `done` event).
pub fn exit_code_of(status: &str) -> u8 {
    match status {
        "completed" => exit::OK,
        "max_steps" => exit::TURN_LIMIT,
        _ => exit::FAILED,
    }
}
