//! The main brain (SR-K3, SR-K4, ADR-024): the single write gate, the verification tools that feed it and the
//! assembly of answers from accepted Claims.
//!
//! * [`gate`]: the only writer of the main-brain vault. A proposal is checked (shape, span, metadata, support,
//!   contradiction search), then written with an audit record, refused with a reason or written with a Conflict.
//!   Retracting or replacing a Source downgrades its dependants ([`gate::Gate::retract_source`]).
//! * [`answer`]: composes answers from accepted Claims and checks every sentence against the notes it cites.
//! * [`tools`]: search, acquisition, metadata and quote verification, corroboration and checks, all feeding the gate.
//! * [`dataset`]: decision examples from logs and scenarios, the sealed split and the text that may train ResearchLLM.
//! * [`decide`]: the closed action set, the measured signals and the rule decider that chooses among them.
//! * [`network`]: inference of the exported decision network, with the rule decider as the fallback.
//! * [`seam`]: the adapter that puts a chooser behind the loop's `Decider` seam.
//! * [`text`]: the rule check on statements that the gate and the answer check share.
//!
//! Everything is deterministic: the same vault and proposal give the same decision. Nothing here is tuned by a
//! hidden default: thresholds come from [`gate::GateSettings`], which the owner of the configuration fills.

pub mod answer;
pub mod audit;
pub mod dataset;
pub mod decide;
pub mod gate;
pub mod network;
pub mod seam;
pub mod text;
pub mod tools;

pub use gate::{
    ClaimProposal, ConsolidationReport, Decision, Evidence, Gate, GateError, GateSettings,
    MetadataCheck, Proposer, Refusal, SourceProposal, TheoryProposal,
};
