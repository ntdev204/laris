//! The main brain (SR-K3, SR-K4, ADR-024): the single write gate, the verification tools that feed it and the
//! assembly of answers from accepted Claims.
//!
//! * [`gate`]: the only writer of the main-brain vault. A proposal is checked (shape, span, metadata, support,
//!   contradiction search), then written with an audit record, refused with a reason or written with a Conflict.
//!   Retracting or replacing a Source downgrades its dependants ([`gate::Gate::retract_source`]).
//! * [`text`]: the rule check on statements that the gate and the answer check share.
//!
//! Everything is deterministic: the same vault and proposal give the same decision. Nothing here is tuned by a
//! hidden default: thresholds come from [`gate::GateSettings`], which the owner of the configuration fills.

pub mod audit;
pub mod gate;
pub mod text;

pub use gate::{
    ClaimProposal, ConsolidationReport, Decision, Evidence, Gate, GateError, GateSettings,
    MetadataCheck, Proposer, Refusal, SourceProposal, TheoryProposal,
};
