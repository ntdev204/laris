//! Chat types shared by P1 and P2: messages, tool schemas, tool calls, usage.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// Role of a message in a request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    /// Instructions; only the server writes the system prompt.
    System,
    /// The user's turn.
    User,
    /// The model's earlier turn.
    Assistant,
    /// A tool result.
    Tool,
}

/// Message content: a string, or a list of parts (kept as JSON).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(untagged)]
pub enum Content {
    /// Plain text.
    Text(String),
    /// Structured parts.
    Parts(Vec<Value>),
}

/// The only kind of tool call the wire knows.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "lowercase")]
pub enum FunctionKind {
    /// A function call.
    #[default]
    Function,
}

/// Name and JSON-encoded arguments of a call. Chunks may carry partial text.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ToolCallFunction {
    /// Tool name.
    #[serde(default)]
    pub name: String,
    /// Arguments as a JSON string.
    #[serde(default)]
    pub arguments: String,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// A tool call of the model.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ToolCall {
    /// Position inside a streamed delta.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub index: Option<u32>,
    /// Call id the tool result must echo.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    /// Always `function`.
    #[serde(rename = "type", default)]
    pub kind: FunctionKind,
    /// What to call.
    pub function: ToolCallFunction,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One message of a conversation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ChatMessage {
    /// Who wrote it.
    pub role: Role,
    /// Text or parts; null for a pure tool-call turn.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content: Option<Content>,
    /// Calls the assistant made in this turn.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tool_calls: Vec<ToolCall>,
    /// For `tool` messages: the call answered.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_call_id: Option<String>,
    /// Optional author or tool name.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// A tool the client offers: JSON Schema of its parameters.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ToolSchema {
    /// Always `function`.
    #[serde(rename = "type", default)]
    pub kind: FunctionKind,
    /// The function description.
    pub function: ToolFunctionSchema,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// Name, description and parameter schema of a tool.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ToolFunctionSchema {
    /// Tool name.
    pub name: String,
    /// What it does.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    /// JSON Schema of the arguments.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parameters: Option<Value>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// Why a choice ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum FinishReason {
    /// Normal end.
    Stop,
    /// The turn is tool calls.
    ToolCalls,
    /// A length limit cut the answer.
    Length,
}

/// Token counts of one request.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct Usage {
    /// Tokens of the prompt.
    #[serde(default)]
    pub prompt_tokens: u64,
    /// Tokens of the answer.
    #[serde(default)]
    pub completion_tokens: u64,
    /// Sum of both.
    #[serde(default)]
    pub total_tokens: u64,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}
