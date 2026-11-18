//! P2: OpenAI-compatible chat completions and embeddings between the server and the model service.

use crate::chat::{ChatMessage, FinishReason, ToolCall, ToolSchema, Usage};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// `POST /v1/chat/completions` request.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ModelChatRequest {
    /// Model name; may be empty.
    #[serde(default)]
    pub model: String,
    /// The conversation.
    pub messages: Vec<ChatMessage>,
    /// Tools the model may call.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tools: Vec<ToolSchema>,
    /// Sampling temperature.
    #[serde(default)]
    pub temperature: f64,
    /// Whether to answer as an event stream.
    #[serde(default)]
    pub stream: bool,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// Constant `chat.completion`.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum CompletionObject {
    /// A full answer.
    #[default]
    #[serde(rename = "chat.completion")]
    Completion,
}

/// Constant `chat.completion.chunk`.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum ChunkObject {
    /// One streamed event.
    #[default]
    #[serde(rename = "chat.completion.chunk")]
    Chunk,
}

/// The assistant message of a full answer.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct CompletionMessage {
    /// Always `assistant`.
    pub role: String,
    /// Text of the answer.
    #[serde(default)]
    pub content: Option<String>,
    /// Calls the model made.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tool_calls: Vec<ToolCall>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One choice of a full answer.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct CompletionChoice {
    /// Position.
    pub index: u32,
    /// The message.
    pub message: CompletionMessage,
    /// Why it ended.
    pub finish_reason: FinishReason,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// Non-streaming answer.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ChatCompletion {
    /// Answer id.
    pub id: String,
    /// Constant.
    #[serde(default)]
    pub object: CompletionObject,
    /// Unix time.
    pub created: u64,
    /// Model name.
    pub model: String,
    /// Choices.
    pub choices: Vec<CompletionChoice>,
    /// Token counts when the model reports them.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub usage: Option<Usage>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// Increment of a streamed choice.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ChunkDelta {
    /// Visible text.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
    /// The model's private reasoning; P2 only, never forwarded to a client.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reasoning_content: Option<String>,
    /// Tool calls.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tool_calls: Vec<ToolCall>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One choice of a streamed event.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ChunkChoice {
    /// Position.
    pub index: u32,
    /// The increment.
    pub delta: ChunkDelta,
    /// Set on the last event of a choice.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub finish_reason: Option<FinishReason>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One P2 streaming event.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ChatCompletionChunk {
    /// Answer id, equal on every event of a stream.
    pub id: String,
    /// Constant.
    #[serde(default)]
    pub object: ChunkObject,
    /// Model name.
    #[serde(default)]
    pub model: String,
    /// Choices; empty on the usage event.
    #[serde(default)]
    pub choices: Vec<ChunkChoice>,
    /// Token counts, on the last event when reported.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub usage: Option<Usage>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}
