//! Research gaps from the papers that were read (the `research-gap` workflow, steps 2–5, and its evaluation).
//!
//! * [`sections`]: the sections of a paper, so every item says where it was written.
//! * [`extract`]: what the model is shown of a paper and how its JSON record is read back.
//! * [`analyze`]: knowledge links, the gap rules G1–G4 with their filters, the conflict rule `r ⊥ r′` with its
//!   explanation conditions, and the ranking `s(g)`; deterministic, every step kept.
//! * [`report`]: the report with the workflow's fixed sections.
//! * [`baseline`]: the closed-book, full-context and plain-RAG (BM25 fused by RRF) baselines.
//! * [`audit`]: nonexistent citations, fabricated quotations, uncited claims and claims from absence.
//! * [`evaluate`]: extraction precision and recall, concept-tag precision, expert ratings, the time split.
//!
//! The policy (weights, rule parameters, cue words, prompts) is read from `.laris/gap.toml` and the vocabulary from
//! a topic file ([`config`]); nothing is a constant of the code. This is a text and rule engine over a model's
//! extraction: it does not qualify the model, which stays NOT QUALIFIED.

pub mod analyze;
pub mod audit;
pub mod baseline;
pub mod config;
pub mod evaluate;
pub mod extract;
pub mod report;
pub mod sections;
pub mod text;

pub use analyze::{Analysis, analyze};
pub use config::{Settings, Topic};
pub use extract::{Paper, Record};
