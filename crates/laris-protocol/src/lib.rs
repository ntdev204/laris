//! P1 (client to server), P2 (server to model) and their server-sent events, defined once as Rust types.
//!
//! The types follow the generation-1 wire format byte for byte where it exists (fixtures recorded from the
//! generation-1 server in `tests/fixtures/`). Every wire struct keeps unknown fields in `extra`, so a newer
//! peer does not break an older one inside one protocol version, and a message survives a round trip.
//! [`schema::export`] produces the JSON Schema of every type, deterministically.

pub mod chat;
pub mod events;
pub mod jsonl;
pub mod p1;
pub mod p2;
pub mod scenario;
pub mod schema;
pub mod sse;
pub mod version;

pub use chat::{
    ChatMessage, Content, FinishReason, FunctionKind, Role, ToolCall, ToolCallFunction, ToolSchema,
    Usage,
};
pub use events::{
    CORE_VERSION, Command, CoreEnd, Event, InterfaceEnd, VersionMismatch, channel, check_ready,
};
pub use p1::{
    AccountResponse, AdminReasoning, AdminUsage, ChatRequest, ChatResponseChunk, EmbedRequest,
    EmbedResponse, EmbeddingItem, HelpResponse, HttpError, InstructionLayer, Kind, LarisMeta,
    LarisRequest, Layers, ModelInfo, ModelList, ToolRequest, ToolResponse, UsageRow, WorkflowInfo,
    WorkflowRequest, WorkflowsResponse,
};
pub use p2::{ChatCompletion, ChatCompletionChunk, ModelChatRequest};
pub use sse::{ErrorDetail, P1Event, P2Event, SseDecoder, SseError, StreamError};
pub use version::{PROTOCOL_HEADER, PROTOCOL_VERSION, VersionError, check_version};
