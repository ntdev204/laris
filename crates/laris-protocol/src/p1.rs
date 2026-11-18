//! P1: the client's API to the server. Chat is a server-sent event stream; the other routes answer JSON.
//!
//! Routes: `POST /v1/laris/chat` (SSE), `POST /v1/laris/embed`, `GET /v1/laris/{workflows,help,account}`,
//! `POST /v1/laris/tools/{name}`, `GET /v1/models`, `GET /v1/admin/{usage,reasoning}`.

use crate::chat::{ChatMessage, ToolSchema, Usage};
use crate::p2::{ChunkChoice, ChunkObject};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// Kind of a chat request.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    /// A normal turn.
    #[default]
    Turn,
    /// Summarise the conversation (compaction).
    Summarize,
}

/// A workflow the client asks to run.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct WorkflowRequest {
    /// Workflow name from `GET /v1/laris/workflows`.
    pub name: String,
    /// The user's request for it.
    #[serde(default)]
    pub request: String,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One of the client's own instruction files.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct InstructionLayer {
    /// Where it came from.
    #[serde(default = "default_label")]
    pub label: String,
    /// Its text.
    #[serde(default)]
    pub text: String,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

fn default_label() -> String {
    "client".to_owned()
}

/// What belongs to the user and travels with a request.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct Layers {
    /// The client's instruction files.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub instructions: Vec<InstructionLayer>,
    /// Index of the user's skills.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub skills_index: String,
    /// The user's memory.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub memory: String,
    /// Extra text.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub extra: String,
}

/// The `laris` block of a chat request.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct LarisRequest {
    /// Turn or summary.
    #[serde(default)]
    pub kind: Kind,
    /// Session id (4-64 of `A-Za-z0-9_-`); the server makes one when absent.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    /// The task in a few words, used for routing.
    #[serde(default)]
    pub task: String,
    /// What a summary should keep.
    #[serde(default)]
    pub focus: String,
    /// A workflow to run.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub workflow: Option<WorkflowRequest>,
    /// The user's own layers.
    #[serde(default, skip_serializing_if = "layers_empty")]
    pub layers: Layers,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

fn layers_empty(layers: &Layers) -> bool {
    *layers == Layers::default()
}

/// `POST /v1/laris/chat` request.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ChatRequest {
    /// The conversation; the system prompt is never accepted from a client.
    pub messages: Vec<ChatMessage>,
    /// The client's tools.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tools: Vec<ToolSchema>,
    /// Stream the answer; defaults to true.
    #[serde(default = "default_true")]
    pub stream: bool,
    /// The `laris` block.
    #[serde(default, skip_serializing_if = "laris_empty")]
    pub laris: LarisRequest,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

fn default_true() -> bool {
    true
}

fn laris_empty(laris: &LarisRequest) -> bool {
    *laris == LarisRequest::default()
}

/// The `laris` block of a response chunk: the evidence list of the system brain (note titles, never content).
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct LarisMeta {
    /// Titles of the guidance notes consulted for this turn, in the order they were opened.
    #[serde(default)]
    pub brain: Vec<String>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One server-sent event of a chat answer: an OpenAI-style chunk, optionally with [`LarisMeta`] and usage.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ChatResponseChunk {
    /// Answer id.
    pub id: String,
    /// Constant.
    #[serde(default)]
    pub object: ChunkObject,
    /// Model name.
    #[serde(default)]
    pub model: String,
    /// The brain evidence list, sent once before the text.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub laris: Option<LarisMeta>,
    /// Choices; empty on the evidence and usage events.
    #[serde(default)]
    pub choices: Vec<ChunkChoice>,
    /// Tokens used, on the last event before `[DONE]`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub usage: Option<Usage>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// A string or a list of strings.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(untagged)]
pub enum OneOrMany {
    /// One text.
    One(String),
    /// Several texts.
    Many(Vec<String>),
}

impl OneOrMany {
    /// The texts as a list.
    pub fn into_vec(self) -> Vec<String> {
        match self {
            Self::One(s) => vec![s],
            Self::Many(v) => v,
        }
    }
}

/// `POST /v1/laris/embed` (P1) and `POST /v1/embeddings` (P2) request.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct EmbedRequest {
    /// Texts to embed.
    pub input: OneOrMany,
    /// Model name; may be empty.
    #[serde(default)]
    pub model: String,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// Constant `embedding`.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum EmbeddingObject {
    /// One vector.
    #[default]
    #[serde(rename = "embedding")]
    Embedding,
}

/// Constant `list`.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum ListObject {
    /// A list.
    #[default]
    #[serde(rename = "list")]
    List,
}

/// Constant `model`.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum ModelObject {
    /// A model.
    #[default]
    #[serde(rename = "model")]
    Model,
}

/// One vector of an embeddings response.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct EmbeddingItem {
    /// Constant.
    #[serde(default)]
    pub object: EmbeddingObject,
    /// Position of the input text.
    pub index: u32,
    /// The vector.
    pub embedding: Vec<f64>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// Embeddings response.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct EmbedResponse {
    /// Constant.
    #[serde(default)]
    pub object: ListObject,
    /// Model name.
    #[serde(default)]
    pub model: String,
    /// One item per input text.
    pub data: Vec<EmbeddingItem>,
    /// Tokens used when reported.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub usage: Option<Usage>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// A model the server offers.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ModelInfo {
    /// Model id.
    pub id: String,
    /// Constant.
    #[serde(default)]
    pub object: ModelObject,
    /// Owner label.
    #[serde(default)]
    pub owned_by: String,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// `GET /v1/models`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ModelList {
    /// Constant.
    #[serde(default)]
    pub object: ListObject,
    /// The models.
    pub data: Vec<ModelInfo>,
}

/// What the client needs to run a workflow's limits; phases and instructions stay on the server.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct WorkflowInfo {
    /// Workflow name.
    pub name: String,
    /// One-sentence description.
    #[serde(default)]
    pub description: String,
    /// Phrases that trigger it.
    #[serde(default)]
    pub triggers: Vec<String>,
    /// Tools it may use.
    #[serde(default)]
    pub allowed_tools: Vec<String>,
    /// Step budget.
    #[serde(default)]
    pub max_steps: u32,
    /// Whether the answer must cite sources.
    #[serde(default)]
    pub require_citations: bool,
    /// Approval mode (`ask`, ...).
    #[serde(default)]
    pub approval: String,
    /// Sections the answer must contain.
    #[serde(default)]
    pub output_sections: Vec<String>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// `GET /v1/laris/workflows`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct WorkflowsResponse {
    /// The workflows.
    pub workflows: Vec<WorkflowInfo>,
}

/// `GET /v1/laris/help`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct HelpResponse {
    /// Help text, printed verbatim.
    pub text: String,
}

/// `GET /v1/laris/account`. Without metering only `role` is present.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct AccountResponse {
    /// Role of the key.
    pub role: String,
    /// Permissions of the key.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub permissions: Option<Vec<String>>,
    /// Token limit; `None` (null) means unlimited.
    #[serde(default)]
    pub token_limit: Option<u64>,
    /// Tokens used.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tokens_used: Option<u64>,
    /// Tokens left; `None` when unlimited.
    #[serde(default)]
    pub tokens_left: Option<u64>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// Usage of one key, as the admin route sums it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct UsageRow {
    /// Key id (never the key).
    pub key_id: String,
    /// Number of requests.
    #[serde(default)]
    pub requests: u64,
    /// Prompt tokens.
    #[serde(default)]
    pub prompt: Option<u64>,
    /// Completion tokens.
    #[serde(default)]
    pub completion: Option<u64>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// `GET /v1/admin/usage`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct AdminUsage {
    /// One row per key.
    pub usage: Vec<UsageRow>,
}

/// `GET /v1/admin/reasoning`: one `trace` (with `id`) or a list of `traces`. Off by default.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct AdminReasoning {
    /// One trace.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub trace: Option<Value>,
    /// Recent traces.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub traces: Option<Vec<Value>>,
}

/// `POST /v1/laris/tools/{name}`: run one of the model service's remote tools.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ToolRequest {
    /// Arguments of the tool.
    #[serde(default)]
    pub arguments: Map<String, Value>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// Answer of a remote tool: a `result` or an `error`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ToolResponse {
    /// The result, any JSON.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    /// What went wrong.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<crate::sse::ErrorDetail>,
}

/// Body of an HTTP error (400, 401, 403, 404, 411, 413, 426, 429, 502): `{"error": "message"}`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct HttpError {
    /// The message.
    pub error: String,
}
