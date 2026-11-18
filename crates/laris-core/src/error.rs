//! Errors of the event log.

use crate::model::ModelError;
use laris_store::StoreError;

/// Errors of recording, resuming and replaying.
#[derive(Debug, thiserror::Error)]
pub enum CoreError {
    /// The store refused an operation.
    #[error(transparent)]
    Store(#[from] StoreError),
    /// A stored record cannot be read.
    #[error("event {seq} is not a valid record: {message}")]
    Decode {
        /// Position in the session.
        seq: i64,
        /// What is wrong.
        message: String,
    },
    /// An input does not fit the state (an answer nobody asked for, an unknown tool call).
    #[error("unexpected input: {0}")]
    Unexpected(String),
    /// An output record was given where an input was expected.
    #[error("an output record is not an input")]
    NotInput,
    /// The log says something the fold does not produce.
    #[error("replay differs at event {seq}: expected {expected}, recorded {found}")]
    Diverged {
        /// Position in the session.
        seq: i64,
        /// What the fold produced.
        expected: String,
        /// What the log holds.
        found: String,
    },
    /// An input follows an input whose outputs are missing in the middle of the log.
    #[error("outputs are missing before event {seq}")]
    MissingOutputs {
        /// Position in the session.
        seq: i64,
    },
    /// The scripted model did not give the recorded answer.
    #[error("event {seq}: {source}")]
    Model {
        /// Position in the session.
        seq: i64,
        /// The cause.
        source: ModelError,
    },
}
