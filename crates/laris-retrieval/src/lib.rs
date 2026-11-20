//! BM25, graph expansion and fusion over a vault (SR-L3).
//!
//! The rankings, the scores and the metrics on `tests/fixtures/retrieval/` are pinned by the recorded expectations in
//! `tests/fixtures/retrieval/expected.json`, so a change of the algorithm shows as a failing test.
//!
//! * [`NoteSearch`]: Okapi BM25 over a note's body and title (a title word counts three times).
//! * [`GraphRetriever`]: BM25 seeds plus the notes linked around them, with a decayed score.
//! * [`fuse_with_corpus`] and [`fuse_ranked`]: reciprocal-rank fusion, deterministic ties.
//! * [`cite`]: every result carries the span of the note it was found in, and [`verify_span`] fails closed.
//! * [`dense`]: the dense channel as an interface. No dense channel is qualified until stage 1 passes G12, so
//!   fused results say so.
//! * [`passages`]: BM25 over the passages of ingested documents, each with its character span.
//! * [`lexical`]: TF-IDF, BM25 and their fusion over the passages of a vault, each hit with note path and span.
//! * [`metrics`]: recall@k, MRR, nDCG@k.
//!
//! Everything is deterministic: the same index and query give byte-identical results.

pub mod dense;
pub mod fusion;
pub mod graph;
pub mod lexical;
pub mod metrics;
pub mod passages;
pub mod provenance;
pub mod search;
pub mod text;

pub use dense::{DenseChannel, DenseHit, NoDense};
pub use fusion::{Channel, Fused, fuse_ranked, fuse_with_corpus, source_title};
pub use graph::{GraphConfig, GraphRetriever, RetrievalResult, Via};
pub use lexical::{
    FUSION_DEPTH, MAX_PASSAGE_CHARS, PassageError, Scorer, VaultPassage, VaultPassageHit,
    VaultPassages, split_body, verify_passage,
};
pub use metrics::{evaluate, mrr, ndcg_at_k, recall_at_k};
pub use passages::{PassageHit, PassageIndex, PassageRecord};
pub use provenance::{Cited, Span, SpanError, cite, verify_span};
pub use search::{Hit, INBOX, NoteSearch, in_inbox};
pub use text::{round_to, tokens};
