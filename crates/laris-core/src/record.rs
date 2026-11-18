//! The records of the event log and their stored form.

use crate::action::Action;
use laris_protocol::{Command, Event, ToolCall, Usage};
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// What the model answered in one turn: text, tool calls, usage.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModelAnswer {
    /// The answer text; empty for a pure tool-call turn.
    #[serde(default)]
    pub text: String,
    /// Tool calls of the turn.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tool_calls: Vec<ToolCall>,
    /// Token counts, when the server reported them.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub usage: Option<Usage>,
}

/// One entry of the event log.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "record", rename_all = "snake_case", deny_unknown_fields)]
pub enum Record {
    /// Input: a command from the interface.
    Command {
        /// The command.
        command: Command,
    },
    /// Input: a step chosen by the decider. It permits what follows (a model call, a tool run) and carries
    /// everything the decider looked at, so replay needs no decider.
    Decision {
        /// The action.
        action: Action,
    },
    /// Input: the model's answer.
    ModelAnswer {
        /// SHA-256 of the conversation the model was asked about ([`crate::digest_of`]).
        request_digest: String,
        /// The answer.
        answer: ModelAnswer,
    },
    /// Input: the outcome of a tool call; the tool is not run again on replay.
    ToolOutcome {
        /// Id of the call.
        id: String,
        /// Tool name.
        name: String,
        /// Result.
        result: Value,
    },
    /// Output: an event the core sent to the interface.
    Emitted {
        /// The event.
        event: Event,
    },
}

impl Record {
    /// The `kind` column of the stored event.
    pub fn kind(&self) -> &'static str {
        match self {
            Self::Command { .. } => "command",
            Self::Decision { .. } => "decision",
            Self::ModelAnswer { .. } => "model_answer",
            Self::ToolOutcome { .. } => "tool_outcome",
            Self::Emitted { .. } => "event",
        }
    }

    /// Whether the record is an input (the rest are outputs derived from inputs).
    pub fn is_input(&self) -> bool {
        !matches!(self, Self::Emitted { .. })
    }
}

/// The stored form: one JSON object, the same bytes for the same record.
pub fn encode_record(record: &Record) -> String {
    serde_json::to_string(record).unwrap_or_default()
}

/// Reads a stored record.
pub fn decode_record(data: &str) -> Result<Record, String> {
    serde_json::from_str(data).map_err(|e| e.to_string())
}
