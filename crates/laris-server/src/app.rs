//! The router and its handlers: body validation before any work, then the backend.

use crate::backend::{Backend, ChunkStream, StreamFailure};
use crate::config::ServerConfig;
use crate::error::ApiError;
use crate::log::RequestScope;
use axum::Extension;
use axum::Router;
use axum::body::{Body, Bytes};
use axum::extract::{Request, State};
use axum::http::{HeaderMap, HeaderValue, StatusCode, header};
use axum::response::Response;
use axum::routing::{get, post};
use futures_util::StreamExt;
use laris_protocol::chat::Role;
use laris_protocol::p1::{ChatRequest, EmbedRequest};
use laris_protocol::sse::{ErrorDetail, P1Event, StreamError};
use laris_protocol::version::{PROTOCOL_HEADER, check_version};
use serde::de::DeserializeOwned;
use std::convert::Infallible;
use std::sync::Arc;

/// What every handler needs.
pub struct AppState {
    /// Settings.
    pub config: ServerConfig,
    /// Answers chat and embed requests.
    pub backend: Arc<dyn Backend>,
}

/// Marks a response whose access record the answer stream writes when it ends.
#[derive(Clone, Copy)]
pub struct Deferred;

type Shared = State<Arc<AppState>>;
type Scope = Extension<Arc<RequestScope>>;

/// The router of `laris-server`. Requests must come through [`crate::serve`] (or a service that adds the request
/// scope) so that each one is logged.
pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/v1/laris/chat", post(chat))
        .route("/v1/laris/embed", post(embed))
        .fallback(unmatched)
        .method_not_allowed_fallback(wrong_method)
        .with_state(state)
}

async fn health(Extension(scope): Scope) -> Response {
    scope.set_route("health");
    json_response(StatusCode::OK, br#"{"status":"ok"}"#.to_vec())
}

async fn unmatched() -> Response {
    ApiError::NotFound.into_response()
}

async fn wrong_method() -> Response {
    ApiError::MethodNotAllowed.into_response()
}

fn json_response(status: StatusCode, body: Vec<u8>) -> Response {
    let mut response = Response::new(Body::from(body));
    *response.status_mut() = status;
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/json"),
    );
    response
}

async fn chat(State(state): Shared, Extension(scope): Scope, request: Request) -> Response {
    scope.set_route("chat");
    match chat_inner(&state, &scope, request).await {
        Ok(response) => response,
        Err(error) => error.into_response(),
    }
}

async fn chat_inner(
    state: &Arc<AppState>,
    scope: &Arc<RequestScope>,
    request: Request,
) -> Result<Response, ApiError> {
    let body: ChatRequest = read_json(state, scope, request).await?;
    validate_chat(&body)?;
    let stream = state.backend.chat(body).await?;
    Ok(sse_response(
        stream,
        state.config.stream_idle,
        scope.clone(),
    ))
}

async fn embed(State(state): Shared, Extension(scope): Scope, request: Request) -> Response {
    scope.set_route("embed");
    match embed_inner(&state, &scope, request).await {
        Ok(response) => response,
        Err(error) => error.into_response(),
    }
}

async fn embed_inner(
    state: &Arc<AppState>,
    scope: &Arc<RequestScope>,
    request: Request,
) -> Result<Response, ApiError> {
    let body: EmbedRequest = read_json(state, scope, request).await?;
    let count = match &body.input {
        laris_protocol::p1::OneOrMany::One(_) => 1,
        laris_protocol::p1::OneOrMany::Many(v) => v.len(),
    };
    if count == 0 {
        return Err(ApiError::BadRequest(
            "invalid request: input must not be empty".into(),
        ));
    }
    if count > state.config.embed_max_inputs {
        return Err(ApiError::BadRequest(format!(
            "invalid request: input holds more than {} texts",
            state.config.embed_max_inputs
        )));
    }
    let answer = state.backend.embed(body).await?;
    let bytes = serde_json::to_vec(&answer).map_err(|_| ApiError::Internal)?;
    Ok(json_response(StatusCode::OK, bytes))
}

/// Checks the headers, then reads and parses the body. Nothing is read before the checks pass, so a body that is
/// refused (411, 413) is never accepted into memory.
async fn read_json<T: DeserializeOwned>(
    state: &AppState,
    scope: &RequestScope,
    request: Request,
) -> Result<T, ApiError> {
    let (parts, body) = request.into_parts();
    let sent = header_text(&parts.headers, PROTOCOL_HEADER);
    check_version(sent).map_err(|e| ApiError::UpgradeRequired(e.to_string()))?;
    if parts.headers.contains_key(header::TRANSFER_ENCODING) {
        return Err(ApiError::LengthRequired);
    }
    let length = parts
        .headers
        .get(header::CONTENT_LENGTH)
        .ok_or(ApiError::LengthRequired)?
        .to_str()
        .ok()
        .and_then(|v| v.trim().parse::<u64>().ok())
        .ok_or_else(|| ApiError::BadRequest("Content-Length is not a number".into()))?;
    let limit = state.config.max_body_bytes;
    if length > limit {
        return Err(ApiError::PayloadTooLarge { limit });
    }
    if !is_json(&parts.headers) {
        return Err(ApiError::BadRequest(
            "Content-Type must be application/json".into(),
        ));
    }
    let max = usize::try_from(limit).unwrap_or(usize::MAX);
    let bytes = tokio::time::timeout(state.config.body_timeout, axum::body::to_bytes(body, max))
        .await
        .map_err(|_| ApiError::RequestTimeout)?
        .map_err(|_| ApiError::BadRequest("the request body could not be read".into()))?;
    scope.set_bytes_in(bytes.len() as u64);
    serde_json::from_slice(&bytes).map_err(|e| ApiError::BadRequest(invalid(&e.to_string())))
}

fn invalid(detail: &str) -> String {
    let mut text: String = detail.chars().take(200).collect();
    if text.len() < detail.len() {
        text.push('…');
    }
    format!("invalid request: {text}")
}

fn header_text<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers.get(name).and_then(|v| v.to_str().ok())
}

fn is_json(headers: &HeaderMap) -> bool {
    header_text(headers, "content-type")
        .and_then(|v| v.split(';').next())
        .is_some_and(|m| m.trim().eq_ignore_ascii_case("application/json"))
}

fn validate_chat(request: &ChatRequest) -> Result<(), ApiError> {
    let bad = |m: &str| Err(ApiError::BadRequest(format!("invalid request: {m}")));
    if request.messages.is_empty() {
        return bad("messages must not be empty");
    }
    if request.messages.iter().any(|m| m.role == Role::System) {
        return bad("messages: the system prompt is never accepted from a client");
    }
    if !request.stream {
        return bad("stream: only streamed answers are supported");
    }
    if let Some(id) = &request.laris.session_id {
        let ok = (4..=64).contains(&id.len())
            && id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-');
        if !ok {
            return bad("laris.session_id: 4 to 64 characters of A-Z, a-z, 0-9, _ and -");
        }
    }
    Ok(())
}

struct StreamState {
    inner: Option<ChunkStream>,
    pending_done: bool,
    idle: std::time::Duration,
    outcome: Option<&'static str>,
    guard: EndGuard,
}

/// Writes the access record when the stream is over or dropped.
struct EndGuard {
    scope: Arc<RequestScope>,
    finished: bool,
    outcome: Option<&'static str>,
}

impl Drop for EndGuard {
    fn drop(&mut self) {
        let outcome = if self.finished {
            self.outcome
        } else {
            Some("client_gone")
        };
        self.scope.finish(200, outcome);
    }
}

fn sse_response(
    stream: ChunkStream,
    idle: std::time::Duration,
    scope: Arc<RequestScope>,
) -> Response {
    let state = StreamState {
        inner: Some(stream),
        pending_done: false,
        idle,
        outcome: None,
        guard: EndGuard {
            scope,
            finished: false,
            outcome: None,
        },
    };
    let body = futures_util::stream::unfold(state, |mut st| async move {
        if st.pending_done {
            st.pending_done = false;
            st.guard.finished = true;
            st.guard.outcome = st.outcome;
            return Some((
                Ok::<Bytes, Infallible>(Bytes::from(P1Event::Done.encode())),
                st,
            ));
        }
        let inner = st.inner.as_mut()?;
        match tokio::time::timeout(st.idle, inner.next()).await {
            Ok(Some(Ok(chunk))) => Some((Ok(Bytes::from(P1Event::Chunk(chunk).encode())), st)),
            Ok(None) => {
                st.inner = None;
                st.guard.finished = true;
                Some((Ok(Bytes::from(P1Event::Done.encode())), st))
            }
            Ok(Some(Err(failure))) => Some(error_event(st, failure, "midstream_error")),
            Err(_) => {
                let failure = StreamFailure {
                    message: "the answer stream stalled".into(),
                    kind: "StreamIdle".into(),
                };
                Some(error_event(st, failure, "stream_idle"))
            }
        }
    });
    let mut response = Response::new(Body::from_stream(body));
    let headers = response.headers_mut();
    headers.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("text/event-stream"),
    );
    headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-cache"));
    headers.insert("x-accel-buffering", HeaderValue::from_static("no"));
    response.extensions_mut().insert(Deferred);
    response
}

fn error_event(
    mut st: StreamState,
    failure: StreamFailure,
    outcome: &'static str,
) -> (Result<Bytes, Infallible>, StreamState) {
    st.inner = None; // stops the backend
    st.pending_done = true;
    st.outcome = Some(outcome);
    let event = P1Event::Error(StreamError {
        error: ErrorDetail {
            message: failure.message,
            kind: Some(failure.kind),
            extra: Default::default(),
        },
    });
    (Ok(Bytes::from(event.encode())), st)
}
