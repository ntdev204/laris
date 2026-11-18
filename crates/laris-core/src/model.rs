//! The model as the loop sees it, and the scripted model used for replay and tests.

use crate::record::{ModelAnswer, Record};
use laris_protocol::ChatMessage;
use sha2::{Digest, Sha256};
use std::collections::VecDeque;

/// Why a model could not answer.
#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error)]
pub enum ModelError {
    /// The script has no more answers.
    #[error("the scripted model has no more answers")]
    Exhausted,
    /// The model was asked about a different conversation than the recorded one.
    #[error("the model was asked a different question: recorded digest {expected}, now {found}")]
    RequestDiverged {
        /// Digest in the script.
        expected: String,
        /// Digest of the conversation now.
        found: String,
    },
    /// The real model failed.
    #[error("model failed: {0}")]
    Failed(String),
}

/// Anything that answers a conversation. The loop reaches a model only through this; the P1 client and the scripted
/// model are its implementations.
pub trait Model {
    /// The answer to `messages`.
    fn answer(&mut self, messages: &[ChatMessage]) -> Result<ModelAnswer, ModelError>;
}

/// SHA-256 (hex) of a conversation as serialised for the wire.
pub fn digest_of(messages: &[ChatMessage]) -> String {
    let bytes = serde_json::to_vec(messages).unwrap_or_default();
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// A model that plays back a script; used for replay, tests and the evaluation runner.
#[derive(Clone, Debug, Default)]
pub struct ScriptedModel {
    script: VecDeque<(Option<String>, ModelAnswer)>,
}

impl ScriptedModel {
    /// A script of answers that are given whatever is asked.
    pub fn new(answers: impl IntoIterator<Item = ModelAnswer>) -> Self {
        Self {
            script: answers.into_iter().map(|a| (None, a)).collect(),
        }
    }

    /// The script a log recorded: its model answers, each bound to the digest of the request it answered, so replay
    /// notices when the fold asks about anything else.
    pub fn from_records<'a>(records: impl IntoIterator<Item = &'a Record>) -> Self {
        let script = records
            .into_iter()
            .filter_map(|r| match r {
                Record::ModelAnswer {
                    request_digest,
                    answer,
                } => Some((Some(request_digest.clone()), answer.clone())),
                _ => None,
            })
            .collect();
        Self { script }
    }

    /// Answers still in the script.
    pub fn remaining(&self) -> usize {
        self.script.len()
    }
}

impl Model for ScriptedModel {
    fn answer(&mut self, messages: &[ChatMessage]) -> Result<ModelAnswer, ModelError> {
        let (digest, answer) = self.script.pop_front().ok_or(ModelError::Exhausted)?;
        if let Some(expected) = digest {
            let found = digest_of(messages);
            if expected != found {
                return Err(ModelError::RequestDiverged { expected, found });
            }
        }
        Ok(answer)
    }
}
