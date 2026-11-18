//! The seam to the model (T144 fills it). T141 owns the HTTP side only; whatever answers a chat or an embed
//! request implements [`Backend`].

use crate::error::ApiError;
use futures_util::future::BoxFuture;
use futures_util::stream::BoxStream;
use laris_protocol::p1::{
    ChatRequest, ChatResponseChunk, EmbedRequest, EmbedResponse, ToolList, ToolRequest,
    ToolResponse,
};

/// A failure after the answer stream started. It is sent as an `error` event followed by `[DONE]`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StreamFailure {
    /// Message for the client; it must not carry request or answer content.
    pub message: String,
    /// Error class name or code.
    pub kind: String,
}

/// The chunks of one answer.
pub type ChunkStream = BoxStream<'static, Result<ChatResponseChunk, StreamFailure>>;

/// What answers requests.
pub trait Backend: Send + Sync + 'static {
    /// Starts an answer. An `Err` here is an HTTP status; failures after this returns go in the stream.
    fn chat(&self, request: ChatRequest) -> BoxFuture<'static, Result<ChunkStream, ApiError>>;
    /// Starts an answer for the key `caller` (its id), when the request came from one. A backend that does not need
    /// to know who asked leaves this as it is.
    fn chat_for(
        &self,
        request: ChatRequest,
        _caller: Option<&str>,
    ) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        self.chat(request)
    }
    /// Embeds texts.
    fn embed(&self, request: EmbedRequest) -> BoxFuture<'static, Result<EmbedResponse, ApiError>>;
    /// The remote tools on offer (the model service's scientific tools, SR-M2). A backend with none answers 502.
    fn tools(&self) -> BoxFuture<'static, Result<ToolList, ApiError>> {
        Box::pin(async {
            Err(ApiError::BadGateway(
                "the model service is not connected".into(),
            ))
        })
    }
    /// Runs the remote tool `name`. A refusal by the tool is `Ok` with an `error` in the response; an `Err` is the
    /// transport or the service failing (or [`ApiError::NotFound`] for a name nobody serves).
    fn tool(
        &self,
        _name: String,
        _request: ToolRequest,
    ) -> BoxFuture<'static, Result<ToolResponse, ApiError>> {
        Box::pin(async {
            Err(ApiError::BadGateway(
                "the model service is not connected".into(),
            ))
        })
    }
}

/// The backend of a server with no model connected: every call is a 502.
#[derive(Debug, Default, Clone, Copy)]
pub struct NoBackend;

impl Backend for NoBackend {
    fn chat(&self, _request: ChatRequest) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        Box::pin(async {
            Err(ApiError::BadGateway(
                "the model service is not connected".into(),
            ))
        })
    }

    fn embed(&self, _request: EmbedRequest) -> BoxFuture<'static, Result<EmbedResponse, ApiError>> {
        Box::pin(async {
            Err(ApiError::BadGateway(
                "the model service is not connected".into(),
            ))
        })
    }
}
