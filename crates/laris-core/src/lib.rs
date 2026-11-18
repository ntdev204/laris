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
//! T131 builds the loop on this. A [`Decider`] chooses each step from the closed set of [`Action`]s; the step is
//! recorded as a decision before it is applied, and a model answer or a tool outcome is accepted only after the
//! decision that permits it. [`FollowModel`] is the default policy (plan, tool gate, reflection, completion
//! check, step and time budgets); [`Driver`] runs it against a [`Model`] and a [`ToolRunner`].

mod action;
mod decider;
mod driver;
mod error;
mod model;
mod plan;
pub mod prompt;
mod record;
mod recorder;
mod replay;
mod session;

pub use action::{Action, AutoStep, Mark, Notice, NoticeKind, PlanChange};
pub use decider::{Clock, Decider, FollowModel, OpenGate, Refusal, ToolGate};
pub use driver::{Driver, ToolRunner};
pub use error::CoreError;
pub use model::{Model, ModelError, ModelRequest, ScriptedModel, Seen, digest_of};
pub use plan::{PLAN_TOOL, PlanStep, StepStatus, open_steps, parse_plan, plan_event, render};
pub use record::{ModelAnswer, Record, decode_record, encode_record};
pub use recorder::{Recorder, Resumed};
pub use replay::{Replayed, replay};
pub use session::{Pending, Session, StepResult, Turn, call_key};
