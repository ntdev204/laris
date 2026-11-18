//! The model as the loop sees it, and the scripted model used for replay and tests.

use crate::record::{ModelAnswer, Record};
use laris_protocol::{ChatMessage, ToolSchema};
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

/// What the model is asked.
#[derive(Clone, Copy, Debug)]
pub struct ModelRequest<'a> {
    /// The conversation. The answer is bound to its digest.
    pub messages: &'a [ChatMessage],
    /// A note for this call only (the current plan); not part of the conversation.
    pub note: Option<&'a str>,
    /// The tools offered.
    pub tools: &'a [ToolSchema],
}

/// What a [`ScriptedModel`] was asked, kept so a test can see what the model saw.
#[derive(Clone, Debug, PartialEq)]
pub struct Seen {
    /// The conversation.
    pub messages: Vec<ChatMessage>,
    /// The note.
    pub note: Option<String>,
    /// Names of the tools offered.
    pub tools: Vec<String>,
}

/// Anything that answers a conversation. The loop reaches a model only through this, and only after a decided
/// action; the P1 client and the scripted model are its implementations.
pub trait Model {
    /// The answer to `request`.
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError>;
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
    seen: Vec<Seen>,
}

impl ScriptedModel {
    /// A script of answers that are given whatever is asked.
    pub fn new(answers: impl IntoIterator<Item = ModelAnswer>) -> Self {
        Self {
            script: answers.into_iter().map(|a| (None, a)).collect(),
            seen: Vec::new(),
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
        Self {
            script,
            seen: Vec::new(),
        }
    }

    /// Every request so far, oldest first.
    pub fn seen(&self) -> &[Seen] {
        &self.seen
    }

    /// Answers still in the script.
    pub fn remaining(&self) -> usize {
        self.script.len()
    }
}

impl Model for ScriptedModel {
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        self.seen.push(Seen {
            messages: request.messages.to_vec(),
            note: request.note.map(str::to_owned),
            tools: request
                .tools
                .iter()
                .map(|t| t.function.name.clone())
                .collect(),
        });
        let (digest, answer) = self.script.pop_front().ok_or(ModelError::Exhausted)?;
        if let Some(expected) = digest {
            let found = digest_of(request.messages);
            if expected != found {
                return Err(ModelError::RequestDiverged { expected, found });
            }
        }
        Ok(answer)
    }
}
