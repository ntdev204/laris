//! State machine, event log, decider seam and context.
//!
//! T130 builds the event log (SR-H2, ADR-021 D38): every step of a session is an append-only [`Record`] in the
//! client store, and the session state is a pure fold of the *input* records ([`Session::apply`]):
//!
//! * inputs: interface commands, model answers (with a digest of the request they answered) and tool outcomes, the
//!   only sources of change from outside;
//! * outputs: the core events sent to the interface, derived from the inputs and recorded after them.
//!
//! [`replay`] folds a log again with a [`ScriptedModel`] in place of the real model and checks that the regenerated
//! outputs equal the recorded ones byte for byte. [`Recorder::open`] resumes a session after a killed process: it
//! rebuilds the state from the log and writes any outputs that were lost between the last input and the kill.
//!
//! The loop of T131 (plan, tools, reflection, budgets) and its decider seam are built on this: the loop chooses the
//! next input, the fold stays the same.

mod error;
mod model;
mod record;
mod recorder;
mod replay;
mod session;

pub use error::CoreError;
pub use model::{Model, ModelError, ScriptedModel, digest_of};
pub use record::{ModelAnswer, Record, decode_record, encode_record};
pub use recorder::{Recorder, Resumed};
pub use replay::{Replayed, replay};
pub use session::{Pending, Session};
