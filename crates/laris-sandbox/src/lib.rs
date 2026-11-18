//! OS confinement for the commands the model runs, and the Python environment they run in (T135, SR-H6).
//!
//! The mechanisms are forked in part from codex (Apache-2.0; `THIRD_PARTY.md`) and cut down as `T134` decided:
//! an own `Policy` type, no managed network proxy, no bundled bubblewrap.
//!
//! | Platform | Backend | State |
//! | --- | --- | --- |
//! | Linux | bubblewrap + seccomp, Landlock fallback | built and tested |
//! | macOS | Seatbelt profile | profile generated and tested as text, **never run** |
//! | Windows | write-restricted token + ACLs + job object (no read hiding, no network block) | written, `cargo check` only, **never run** |

pub mod bwrap;
pub mod helper;
pub mod macos;
pub mod policy;
pub mod pyenv;
pub mod sandbox;
pub mod winargs;
#[cfg(windows)]
pub mod windows;

pub use policy::{PROTECTED_NAMES, Policy, Readable, SandboxError};
pub use pyenv::PythonEnv;
pub use sandbox::{Backend, Sandbox};
