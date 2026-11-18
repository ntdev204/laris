//! Evidence gate (SR-H7, ADR-004, D39): what an answer cites must exist, and what it asserts must be cited.
//!
//! One check, once, before an answer is displayed:
//!
//! * [`Evidence`] is what the turn actually received: the hits of retrieval tools (`[source #rank] text`, as text or
//!   as JSON objects with `source`, `rank` and `text`) and the titles of the brain notes the server listed in
//!   [`laris_protocol::LarisMeta`].
//! * [`citation::parse`] finds the citations of an answer: `[source #rank]` for workspace evidence (rule E-2),
//!   `[brain: Title]` for brain evidence, and the verbatim quote that stands right before a citation, if any.
//! * [`Gate::check`] reports and marks four things in a [`Verdict`]: a citation that names no evidence
//!   ([`FindingKind::FabricatedCitation`]); a quote that is not in the evidence it cites
//!   ([`FindingKind::SpanMissing`]); a statement that cites nothing and is not marked as assumed
//!   ([`FindingKind::UnsupportedStatement`]); and a conclusion of absence that does not say what was searched
//!   ([`FindingKind::AbsenceClaim`], rule E-5). An answer without findings comes back byte for byte unchanged.
//!
//! This is a text rule, not a judge of meaning: a citation to a real hit that does not support the sentence passes,
//! a quote is compared after case and whitespace are folded, and "statement" means a sentence of some length. It
//! proves that the cited places exist, not that they entail the claim (that is the model block's NLI, reached as a
//! remote tool, D41). Nothing wires the gate into a running session yet (the client tasks).

pub mod citation;
mod evidence;
mod gate;
mod text;

pub use citation::{Citation, Target};
pub use evidence::{Evidence, Hit};
pub use gate::{Config, Finding, FindingKind, Gate, Marks, Verdict};
