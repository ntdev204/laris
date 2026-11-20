//! The router and its handlers: body validation before any work, then the backend.

use crate::access::{Access, Principal, Reservation, Used, perm};
use crate::backend::{Backend, Caller, ChunkStream, StreamFailure};
use crate::config::ServerConfig;
use crate::error::ApiError;
use crate::log::RequestScope;
use axum::Extension;
use axum::Router;
use axum::body::{Body, Bytes};
use axum::extract::{Path, Request, State};
use axum::http::{HeaderMap, HeaderValue, StatusCode, header};
use axum::response::Response;
use axum::routing::{get, post};
use futures_util::StreamExt;
use laris_protocol::chat::Role;
use laris_protocol::p1::{ChatRequest, EmbedRequest, ToolRequest};
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
    /// Keys, roles and quotas. `None` serves every request without a key: only [`AppState::open`] makes that, for
    /// tests of the HTTP layer; `main` always builds the access layer.
    pub access: Option<Arc<Access>>,
    /// The policy (workflows and help routes). `None` serves neither.
    pub policy: Option<Arc<crate::policy::Policy>>,
    /// Where the operator reads the model's reasoning. `None` serves no such route.
    pub reasoning: Option<Arc<dyn crate::policy::ReasoningStore>>,
    /// Where the operator reads the traces, and where each request's trace goes. `None` keeps none.
    pub traces: Option<Arc<dyn crate::trace::TraceStore>>,
    /// The main brain and its write gate (T240). `None` serves no brain routes.
    pub main_brain: Option<Arc<crate::mainbrain::MainBrain>>,
}

impl AppState {
    /// State with keys, roles and quotas.
    pub fn new(config: ServerConfig, backend: Arc<dyn Backend>, access: Arc<Access>) -> Self {
        Self {
            config,
            backend,
            access: Some(access),
            policy: None,
            reasoning: None,
            traces: None,
            main_brain: None,
        }
    }

    /// The same state serving the policy's workflows and help, and the operator's reasoning route.
    pub fn with_policy(
        mut self,
        policy: Arc<crate::policy::Policy>,
        reasoning: Arc<dyn crate::policy::ReasoningStore>,
    ) -> Self {
        self.policy = Some(policy);
        self.reasoning = Some(reasoning);
        self
    }

    /// The same state keeping a content-free trace of each request and serving them to the operator.
    pub fn with_traces(mut self, traces: Arc<dyn crate::trace::TraceStore>) -> Self {
        self.traces = Some(traces);
        self
    }

    /// The same state serving the main brain's admin routes.
    pub fn with_main_brain(mut self, brain: Arc<crate::mainbrain::MainBrain>) -> Self {
        self.main_brain = Some(brain);
        self
    }

    /// State that accepts every caller. For tests of the HTTP layer only.
    pub fn open(config: ServerConfig, backend: Arc<dyn Backend>) -> Self {
        Self {
            config,
            backend,
            access: None,
            policy: None,
            reasoning: None,
            traces: None,
            main_brain: None,
        }
    }
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
        .route("/v1/laris/tools", get(tool_list))
        .route("/v1/laris/tools/{name}", post(tool_call))
        .route("/v1/laris/account", get(crate::admin::account))
        .route("/v1/laris/workflows", get(crate::policy::workflows_route))
        .route("/v1/laris/help", get(crate::policy::help))
        .route("/v1/admin/reasoning", get(crate::policy::reasoning_route))
        .route("/v1/admin/traces", get(crate::admin::traces))
        .route("/v1/admin/usage", get(crate::admin::usage))
        .route(
            "/v1/admin/keys",
            get(crate::admin::keys_list).post(crate::admin::keys_create),
        )
        .route(
            "/v1/admin/brain/sources",
            post(crate::mainbrain::submit_source),
        )
        .route(
            "/v1/admin/brain/claims",
            post(crate::mainbrain::submit_claim),
        )
        .route(
            "/v1/admin/brain/retract",
            post(crate::mainbrain::retract_source),
        )
        .route("/v1/admin/keys/{id}/revoke", post(crate::admin::key_revoke))
        .route("/v1/admin/keys/{id}/limit", post(crate::admin::key_limit))
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
    let (mut body, principal, length) =
        read_json::<ChatRequest>(state, scope, request, perm::CHAT).await?;
    validate_chat(&body)?;
    // the client cannot assert steps, a decision or evidence for itself (TM-31)
    for key in crate::pipeline::SERVER_ONLY_KEYS {
        body.laris.extra.remove(key);
    }
    let session = body.laris.session_id.clone().unwrap_or_default();
    scope.trace(|t| t.set_session(&session));
    let meter = reserve_for(state, principal.as_ref(), length, "chat", session).await?;
    let caller = Caller {
        key_id: principal.as_ref().map(|p| p.key_id.clone()),
        brain_read: principal.as_ref().is_none_or(|p| p.can(perm::BRAIN_READ)),
    };
    let stream = match state.backend.chat_as(body, &caller).await {
        Ok(stream) => stream,
        Err(error) => {
            if let Some(m) = &meter {
                let _ = m.reservation.release().await;
            }
            return Err(error);
        }
    };
    Ok(sse_response(
        stream,
        state.config.stream_idle,
        scope.clone(),
        meter,
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
    let (body, principal, length) =
        read_json::<EmbedRequest>(state, scope, request, perm::EMBED).await?;
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
    let meter = reserve_for(state, principal.as_ref(), length, "embed", String::new()).await?;
    let answer = match state.backend.embed(body).await {
        Ok(answer) => answer,
        Err(error) => {
            if let Some(m) = &meter {
                let _ = m.reservation.release().await;
            }
            return Err(error);
        }
    };
    if let Some(m) = meter {
        let (prompt, completion) = match &answer.usage {
            Some(u) => (to_i64(u.prompt_tokens), to_i64(u.completion_tokens)),
            None => (m.prompt_estimate, 0),
        };
        scope.trace(|t| t.set_tokens(prompt, completion));
        m.settle_detached(prompt, completion);
    }
    let bytes = serde_json::to_vec(&answer).map_err(|_| ApiError::Internal)?;
    Ok(json_response(StatusCode::OK, bytes))
}

async fn tool_list(State(state): Shared, Extension(scope): Scope, headers: HeaderMap) -> Response {
    scope.set_route("tools");
    let result = async {
        gate(&state, &scope, &headers, perm::TOOLS).await?;
        let list = state.backend.tools().await?;
        let bytes = serde_json::to_vec(&list).map_err(|_| ApiError::Internal)?;
        Ok(json_response(StatusCode::OK, bytes))
    }
    .await;
    result.unwrap_or_else(ApiError::into_response)
}

/// A tool name as the model service spells them: lower-case letters, digits and `_`. Anything else is a name nobody
/// serves, and never reaches the model service's address.
fn valid_tool_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}

async fn tool_call(
    State(state): Shared,
    Extension(scope): Scope,
    Path(name): Path<String>,
    request: Request,
) -> Response {
    scope.set_route("tools");
    let result = async {
        let (body, _principal, _length) =
            read_json::<ToolRequest>(&state, &scope, request, perm::TOOLS).await?;
        if !valid_tool_name(&name) {
            return Err(ApiError::NotFound);
        }
        let answer = state.backend.tool(name.clone(), body).await?;
        // only a name the service served is kept; an unknown one is a 404 above and leaves no text in a row
        scope.trace(|t| t.add_tool(&name));
        let bytes = serde_json::to_vec(&answer).map_err(|_| ApiError::Internal)?;
        Ok(json_response(StatusCode::OK, bytes))
    }
    .await;
    result.unwrap_or_else(ApiError::into_response)
}

/// Checks the headers, then reads and parses the body. Nothing is read before the checks pass, so a body that is
/// refused (411, 413) is never accepted into memory.
pub(crate) async fn read_json<T: DeserializeOwned>(
    state: &AppState,
    scope: &RequestScope,
    request: Request,
    permission: &'static str,
) -> Result<(T, Option<Principal>, u64), ApiError> {
    let (parts, body) = request.into_parts();
    let principal = gate(state, scope, &parts.headers, permission).await?;
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
    let parsed = serde_json::from_slice(&bytes)
        .map_err(|e| ApiError::BadRequest(invalid(&e.to_string())))?;
    Ok((parsed, principal, bytes.len() as u64))
}

/// The checks every route starts with: protocol version (426), then who the caller is (401) and whether they may
/// (403). Nothing of the body is read before they pass.
pub(crate) async fn gate(
    state: &AppState,
    scope: &RequestScope,
    headers: &HeaderMap,
    permission: &str,
) -> Result<Option<Principal>, ApiError> {
    check_version(header_text(headers, PROTOCOL_HEADER))
        .map_err(|e| ApiError::UpgradeRequired(e.to_string()))?;
    let Some(access) = &state.access else {
        return Ok(None);
    };
    let principal = access
        .authenticate(header_text(headers, "authorization"), scope.client())
        .await?;
    scope.trace(|t| t.set_key(&principal.key_id));
    access.require(&principal, permission)?;
    Ok(Some(principal))
}

fn to_i64(n: u64) -> i64 {
    i64::try_from(n).unwrap_or(i64::MAX)
}

/// Tokens set aside for one request, and what is needed to settle them.
pub(crate) struct Meter {
    access: Arc<Access>,
    pub(crate) reservation: Arc<Reservation>,
    prompt_estimate: i64,
    kind: &'static str,
    session: String,
}

impl Meter {
    /// Settles without waiting (the answer is already on its way).
    fn settle_detached(self, prompt: i64, completion: i64) {
        let used = Used {
            prompt_tokens: prompt,
            completion_tokens: completion,
            kind: self.kind.to_string(),
            session_id: self.session,
        };
        self.reservation.settle_detached(used, crate::access::now());
    }
}

async fn reserve_for(
    state: &AppState,
    principal: Option<&Principal>,
    length: u64,
    kind: &'static str,
    session: String,
) -> Result<Option<Meter>, ApiError> {
    let (Some(access), Some(principal)) = (&state.access, principal) else {
        return Ok(None);
    };
    let estimate = access.estimate_tokens(length);
    let reservation = access.reserve(principal, estimate).await?;
    Ok(Some(Meter {
        access: access.clone(),
        reservation,
        prompt_estimate: estimate,
        kind,
        session,
    }))
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
    meter: Option<Meter>,
    answer_chars: u64,
    reported: Option<(i64, i64)>,
    model: String,
}

impl EndGuard {
    /// Counts what one chunk carried: the model's own token counts when it gives them, else visible characters.
    fn observe(&mut self, chunk: &laris_protocol::p1::ChatResponseChunk) {
        if let Some(u) = &chunk.usage {
            self.reported = Some((to_i64(u.prompt_tokens), to_i64(u.completion_tokens)));
        }
        if self.model.is_empty() && !chunk.model.is_empty() {
            self.model.clone_from(&chunk.model);
        }
        if let Some(meta) = &chunk.laris {
            if !meta.brain.is_empty() {
                self.scope.trace(|t| t.set_brain(&meta.brain));
            }
            for step in &meta.steps {
                self.scope
                    .trace(|t| t.add_stage(&step.stage, &step.outcome, step.ms, &step.code));
            }
        }
        for choice in &chunk.choices {
            for call in &choice.delta.tool_calls {
                if !call.function.name.is_empty() {
                    self.scope.trace(|t| t.add_tool(&call.function.name));
                }
            }
            if let Some(text) = &choice.delta.content {
                self.answer_chars += text.chars().count() as u64;
            }
        }
    }
}

impl Drop for EndGuard {
    fn drop(&mut self) {
        // billed whether the answer ended, failed or the client left: what was produced is what is charged
        let mut tokens = self.reported;
        if let Some(meter) = self.meter.take() {
            let (prompt, completion) = self.reported.unwrap_or((
                meter.prompt_estimate,
                meter.access.estimate_tokens(self.answer_chars),
            ));
            tokens = Some((prompt, completion));
            meter.settle_detached(prompt, completion);
        }
        self.scope.trace(|t| {
            t.set_model(&self.model);
            t.set_answer_chars(self.answer_chars);
            if let Some((prompt, completion)) = tokens {
                t.set_tokens(prompt, completion);
            }
        });
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
    meter: Option<Meter>,
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
            meter,
            answer_chars: 0,
            reported: None,
            model: String::new(),
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
            Ok(Some(Ok(chunk))) => {
                st.guard.observe(&chunk);
                Some((Ok(Bytes::from(P1Event::Chunk(chunk).encode())), st))
            }
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
