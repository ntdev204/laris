//! Permission modes, rules, hooks and folder trust (SR-H5).
//!
//! * [`Engine`] decides one call: allow, ask or deny, from the mode, the rules of the settings, the approvals the
//!   user saved for the folder and those of the session. Deny wins; the plan mode is read-only; `bypass` needs the
//!   installation's policy and never beats a `deny` or an `ask` rule.
//! * [`PolicyGate`] is the loop's [`laris_core::ToolGate`]: the engine, then the `PreToolUse` hooks, then the
//!   [`Approver`]. Paths in rules are matched resolved, so `..` and symbolic links do not dodge them.
//! * [`HookRunner`] runs the hooks the user declared in the global settings, with JSON on standard input and a
//!   time limit. A project folder declares none.
//! * [`ProjectState`] keeps whether a folder is trusted and what was approved for it, in the user's home; the
//!   project's own commands and skills are used only in a trusted folder ([`skill_dirs`], [`command_dirs`]).
//!
//! * [`Redactor`] hides credentials in text and JSON: in what tools persist, in every tool result
//!   ([`ShieldedRunner`]) and in the conversation before a request leaves ([`RedactingModel`]).
//! * [`Shield`] is the injection defence: results of third-party content are marked, watched for orders to the
//!   model, and a call that repeats such an order is refused as `injected_request` ([`PolicyGate::with_shield`]).
//!
//! * [`Prompted`] assembles each request with the prompt layer of `laris-core`: the `LARIS.md` layers and memory
//!   ([`load_layers`], the project's only in a trusted folder), the pinned items ([`PinBoard`]) and the plan, inside
//!   the model budget, with autocompact (SR-H3).
//!
//! * [`Prefilter`] answers a greeting, a help or version request, a request to enable training and an attempt to
//!   override the instructions from the owner's rules (`.laris/prefilter.toml`), before the redactor and the model
//!   ([`PrefilterModel`]); each hit is recorded without the message text (T229).
//!
//! * [`HarnessModel`] answers from retrieved passages: the Prefilter's pass, the passages (those that give orders
//!   dropped), the draft, the evidence gate, a bounded retry, or an abstention (T232).
//!
//! * [`learning`] derives training examples from the event log and exports them as JSONL (SR-H11).
//!
//! Not here: the OS sandbox and the refusal of installs outside it (T135).

mod engine;
mod gate;
mod harness;
mod hooks;
pub mod learning;
mod prefilter;
mod preview;
mod prompted;
mod redact;
mod rule;
mod shield;
mod state;

pub use engine::{Decision, Engine, PolicyError, Remember, Verdict, mode_name};
pub use gate::{
    Answer, ApprovalRequest, Approver, HookedRunner, NoApprover, PolicyGate, ShieldedRunner,
    writes_of,
};
pub use harness::{
    Ending, HarnessConfig, HarnessError, HarnessModel, NoTurnSink, Passage, PassageSource,
    StoreTurnSink, TURN_EVENT, Turn, TurnSink, VaultSource,
};
pub use hooks::{HookOutcome, HookRunner, Notice, OUTPUT_CAP, clean};
pub use prefilter::{
    HIT_EVENT, Hit, HitSink, NoSink, Outcome, Prefilter, PrefilterError, PrefilterModel, StoreSink,
    latest_user_message,
};
pub use preview::{diff, preview};
pub use prompted::{PinBoard, Prompted, Report, Sources, load_layers};
pub use redact::{MASK, RedactingModel, Redactor};
pub use rule::{Rule, parse_rule, rule_matches, suggest_rule};
pub use shield::{INJECTED_REQUEST, Shield};
pub use state::{ProjectState, command_dirs, skill_dirs};
