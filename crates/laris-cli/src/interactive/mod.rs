//! The interactive `laris`: the terminal interface joined to a real session (SR-C1, SR-C2).
//!
//! The session runs on its own thread ([`worker`]) because the loop of `laris-core` is synchronous: the interface
//! sends [`Command`]s over a channel and receives [`Event`]s, the same pair of types a recorded scenario uses, and
//! an approval travels the same way (the gate's approver waits for the person's answer). [`front::Front`] is the
//! session's side of that conversation: it runs turns, answers the slash commands, `!command`, `# note` and
//! `@path`, and completes what is typed.

pub mod commands;
pub mod control;
pub mod files;
pub mod front;
pub mod meter;
pub mod terminal;
pub mod worker;

pub use terminal::run;
