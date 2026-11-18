//! The model proxy (SR-S6): a [`Backend`] that speaks P2 to the model service over the internal network.
//!
//! * Bounded concurrency: at most `max_concurrent` calls to the model are open at once; a call waits up to
//!   `queue_wait` for a place and is then refused with 503. A place is held for the whole answer stream and given
//!   back when the stream ends or the client goes away (dropping the stream closes the request to the model).
//! * Unbuffered streaming: each P2 chunk is decoded as it arrives and handed on at once.
//! * The first event is read before the answer is returned, so a model that fails at the start is a 502, not an
//!   empty stream; a failure after that is an `error` event (SR-P1).
//! * Nothing of the model's own error text reaches a client: messages are fixed, and the address of the model
//!   service is never printed. Reasoning stays in the chunk for the policy gateway to divert.
//!
//! The address and every limit come from `LARIS_SERVER__MODEL_*` variables; without `LARIS_SERVER__MODEL_URL` the
//! server has no model and answers 502 ([`crate::NoBackend`]).

use crate::backend::{Backend, ChunkStream, StreamFailure};
use crate::config::ConfigError;
use crate::error::ApiError;
use bytes::Bytes;
use futures_util::StreamExt;
use futures_util::future::BoxFuture;
use futures_util::stream::BoxStream;
use laris_protocol::p1::{
    ChatRequest, ChatResponseChunk, EmbedRequest, EmbedResponse, ToolList, ToolRequest,
    ToolResponse,
};
use laris_protocol::p2::{ChatCompletionChunk, ModelChatRequest};
use laris_protocol::sse::{P2Event, SseDecoder};
use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

const FAILED: &str = "the model service failed";

/// Settings of the connection to the model service.
#[derive(Clone, PartialEq, Eq)]
pub struct ModelConfig {
    /// Base address of P2, e.g. `http://model:8000` (`LARIS_SERVER__MODEL_URL`); `/v1/...` is added.
    pub base_url: String,
    /// Model name sent on a request that names none (`LARIS_SERVER__MODEL_NAME`; empty by default).
    pub model_name: String,
    /// Calls open at once (`LARIS_SERVER__MODEL_MAX_CONCURRENT`).
    pub max_concurrent: usize,
    /// Longest a call waits for a place (`LARIS_SERVER__MODEL_QUEUE_WAIT_MS`).
    pub queue_wait: Duration,
    /// Longest wait for the connection (`LARIS_SERVER__MODEL_CONNECT_TIMEOUT_MS`).
    pub connect_timeout: Duration,
    /// Longest wait for the answer headers, which the model sends after its queue (`LARIS_SERVER__MODEL_HEADER_TIMEOUT_MS`).
    pub header_timeout: Duration,
    /// Longest silence inside a stream or an embed body (`LARIS_SERVER__MODEL_IDLE_MS`).
    pub idle: Duration,
    /// Largest stream event or embed answer, in bytes (`LARIS_SERVER__MODEL_MAX_EVENT_BYTES`).
    pub max_event_bytes: usize,
}

impl std::fmt::Debug for ModelConfig {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ModelConfig")
            .field("max_concurrent", &self.max_concurrent)
            .field("queue_wait", &self.queue_wait)
            .finish_non_exhaustive()
    }
}

impl ModelConfig {
    /// A configuration for `base_url` with every other setting at its default.
    pub fn new(base_url: impl Into<String>) -> Self {
        Self {
            base_url: base_url.into(),
            model_name: String::new(),
            max_concurrent: 4,
            queue_wait: Duration::from_secs(30),
            connect_timeout: Duration::from_secs(5),
            header_timeout: Duration::from_secs(120),
            idle: Duration::from_secs(120),
            max_event_bytes: 16 * 1024 * 1024,
        }
    }

    /// Reads the settings; `None` when `LARIS_SERVER__MODEL_URL` is not set.
    pub fn from_env(env: &HashMap<String, String>) -> Result<Option<Self>, ConfigError> {
        let get = |name: &str| env.get(name).map(|v| v.trim()).filter(|v| !v.is_empty());
        let Some(url) = get("LARIS_SERVER__MODEL_URL") else {
            return Ok(None);
        };
        let invalid =
            |name: &'static str, reason: &'static str| ConfigError::Invalid { name, reason };
        let base = url.trim_end_matches('/');
        if !(base.starts_with("http://") || base.starts_with("https://")) || base.len() < 9 {
            return Err(invalid(
                "LARIS_SERVER__MODEL_URL",
                "expected an http:// or https:// address",
            ));
        }
        let mut cfg = Self::new(base);
        if let Some(name) = get("LARIS_SERVER__MODEL_NAME") {
            cfg.model_name = name.to_owned();
        }
        let number = |name: &'static str| -> Result<Option<u64>, ConfigError> {
            match get(name) {
                None => Ok(None),
                Some(v) => match v.parse::<u64>() {
                    Ok(n) if n >= 1 => Ok(Some(n)),
                    _ => Err(invalid(name, "expected a whole number in range")),
                },
            }
        };
        let ms = |n: u64| Duration::from_millis(n);
        let size = |n: u64| usize::try_from(n).unwrap_or(usize::MAX);
        if let Some(n) = number("LARIS_SERVER__MODEL_MAX_CONCURRENT")? {
            cfg.max_concurrent = size(n);
        }
        if let Some(n) = number("LARIS_SERVER__MODEL_QUEUE_WAIT_MS")? {
            cfg.queue_wait = ms(n);
        }
        if let Some(n) = number("LARIS_SERVER__MODEL_CONNECT_TIMEOUT_MS")? {
            cfg.connect_timeout = ms(n);
        }
        if let Some(n) = number("LARIS_SERVER__MODEL_HEADER_TIMEOUT_MS")? {
            cfg.header_timeout = ms(n);
        }
        if let Some(n) = number("LARIS_SERVER__MODEL_IDLE_MS")? {
            cfg.idle = ms(n);
        }
        if let Some(n) = number("LARIS_SERVER__MODEL_MAX_EVENT_BYTES")? {
            cfg.max_event_bytes = size(n);
        }
        Ok(Some(cfg))
    }
}

/// The P2 client behind the server.
pub struct ModelBackend {
    http: reqwest::Client,
    config: ModelConfig,
    places: Arc<Semaphore>,
}

impl std::fmt::Debug for ModelBackend {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ModelBackend")
            .field("config", &self.config)
            .finish_non_exhaustive()
    }
}

impl ModelBackend {
    /// Makes the client. Redirects are never followed and the environment's proxy is not used: the model service
    /// is on the internal network.
    pub fn new(config: ModelConfig) -> Result<Self, ConfigError> {
        let http = reqwest::Client::builder()
            .connect_timeout(config.connect_timeout)
            .redirect(reqwest::redirect::Policy::none())
            .no_proxy()
            .build()
            .map_err(|_| ConfigError::Invalid {
                name: "LARIS_SERVER__MODEL_URL",
                reason: "the HTTP client cannot be built",
            })?;
        let places = Arc::new(Semaphore::new(config.max_concurrent.max(1)));
        Ok(Self {
            http,
            config,
            places,
        })
    }

    /// Places free right now (for tests and the operator).
    pub fn free_places(&self) -> usize {
        self.places.available_permits()
    }
}

/// What the model service's status means for a caller of this server.
fn refusal(status: reqwest::StatusCode) -> ApiError {
    if status == reqwest::StatusCode::SERVICE_UNAVAILABLE {
        ApiError::Unavailable("the model service is busy".into())
    } else {
        ApiError::BadGateway(FAILED.into())
    }
}

async fn place(places: &Arc<Semaphore>, wait: Duration) -> Result<OwnedSemaphorePermit, ApiError> {
    match tokio::time::timeout(wait, places.clone().acquire_owned()).await {
        Ok(Ok(permit)) => Ok(permit),
        _ => Err(ApiError::Unavailable("the model service is busy".into())),
    }
}

/// The P2 request for a P1 chat request: the conversation and tools only. The `laris` block never goes to the
/// model, and the only sampling field passed on is a numeric `temperature`.
fn p2_request(request: ChatRequest, model_name: &str) -> ModelChatRequest {
    let temperature = request
        .extra
        .get("temperature")
        .and_then(serde_json::Value::as_f64)
        .filter(|t| t.is_finite())
        .unwrap_or(0.0);
    ModelChatRequest {
        model: model_name.to_owned(),
        messages: request.messages,
        tools: request.tools,
        temperature,
        stream: true,
        extra: serde_json::Map::new(),
    }
}

fn to_p1(chunk: ChatCompletionChunk) -> ChatResponseChunk {
    ChatResponseChunk {
        id: chunk.id,
        object: chunk.object,
        model: chunk.model,
        laris: None,
        choices: chunk.choices,
        usage: chunk.usage,
        extra: chunk.extra,
    }
}

impl Backend for ModelBackend {
    fn chat(&self, request: ChatRequest) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        let http = self.http.clone();
        let config = self.config.clone();
        let places = self.places.clone();
        Box::pin(async move {
            let permit = place(&places, config.queue_wait).await?;
            let body = serde_json::to_vec(&p2_request(request, &config.model_name))
                .map_err(|_| ApiError::Internal)?;
            let sent = http
                .post(format!("{}/v1/chat/completions", config.base_url))
                .header("Content-Type", "application/json")
                .header("Accept", "text/event-stream")
                .body(body)
                .send();
            let response = match tokio::time::timeout(config.header_timeout, sent).await {
                Ok(Ok(r)) => r,
                _ => {
                    return Err(ApiError::BadGateway(
                        "the model service is not reachable".into(),
                    ));
                }
            };
            if !response.status().is_success() {
                return Err(refusal(response.status()));
            }
            let mut stream = Answer {
                body: response.bytes_stream().boxed(),
                decoder: SseDecoder::new(),
                queue: VecDeque::new(),
                fed: 0,
                finished: false,
                idle: config.idle,
                max_event_bytes: config.max_event_bytes,
                _place: permit,
            };
            // the first event decides between a refusal (HTTP) and an answer (stream)
            match stream.next_event().await {
                Some(Ok(first)) => {
                    let rest = futures_util::stream::unfold(stream, |mut s| async move {
                        s.next_event().await.map(|item| (item, s))
                    });
                    Ok(futures_util::stream::once(async { Ok(first) })
                        .chain(rest)
                        .boxed())
                }
                _ => Err(ApiError::BadGateway(FAILED.into())),
            }
        })
    }

    fn embed(&self, request: EmbedRequest) -> BoxFuture<'static, Result<EmbedResponse, ApiError>> {
        let http = self.http.clone();
        let config = self.config.clone();
        let places = self.places.clone();
        Box::pin(async move {
            let _place = place(&places, config.queue_wait).await?;
            let mut request = request;
            if request.model.is_empty() {
                request.model.clone_from(&config.model_name);
            }
            let body = serde_json::to_vec(&request).map_err(|_| ApiError::Internal)?;
            let sent = http
                .post(format!("{}/v1/embeddings", config.base_url))
                .header("Content-Type", "application/json")
                .header("Accept", "application/json")
                .body(body)
                .send();
            let response = match tokio::time::timeout(config.header_timeout, sent).await {
                Ok(Ok(r)) => r,
                _ => {
                    return Err(ApiError::BadGateway(
                        "the model service is not reachable".into(),
                    ));
                }
            };
            if !response.status().is_success() {
                return Err(refusal(response.status()));
            }
            let bytes = read_body(response, &config).await?;
            serde_json::from_slice(&bytes).map_err(|_| ApiError::BadGateway(FAILED.into()))
        })
    }

    fn tools(&self) -> BoxFuture<'static, Result<ToolList, ApiError>> {
        let http = self.http.clone();
        let config = self.config.clone();
        let places = self.places.clone();
        Box::pin(async move {
            let _place = place(&places, config.queue_wait).await?;
            let sent = http
                .get(format!("{}/v1/tools", config.base_url))
                .header("Accept", "application/json")
                .send();
            let response = match tokio::time::timeout(config.header_timeout, sent).await {
                Ok(Ok(r)) => r,
                _ => {
                    return Err(ApiError::BadGateway(
                        "the model service is not reachable".into(),
                    ));
                }
            };
            if !response.status().is_success() {
                return Err(refusal(response.status()));
            }
            let bytes = read_body(response, &config).await?;
            serde_json::from_slice(&bytes).map_err(|_| ApiError::BadGateway(FAILED.into()))
        })
    }

    fn tool(
        &self,
        name: String,
        request: ToolRequest,
    ) -> BoxFuture<'static, Result<ToolResponse, ApiError>> {
        let http = self.http.clone();
        let config = self.config.clone();
        let places = self.places.clone();
        Box::pin(async move {
            let _place = place(&places, config.queue_wait).await?;
            // only the arguments go to the tool: fields of a newer client are not passed on
            let body = serde_json::to_vec(&serde_json::json!({"arguments": request.arguments}))
                .map_err(|_| ApiError::Internal)?;
            let sent = http
                .post(format!("{}/v1/tools/{name}", config.base_url))
                .header("Content-Type", "application/json")
                .header("Accept", "application/json")
                .body(body)
                .send();
            let response = match tokio::time::timeout(config.header_timeout, sent).await {
                Ok(Ok(r)) => r,
                _ => {
                    return Err(ApiError::BadGateway(
                        "the model service is not reachable".into(),
                    ));
                }
            };
            if response.status() == reqwest::StatusCode::NOT_FOUND {
                return Err(ApiError::NotFound);
            }
            if !response.status().is_success() {
                return Err(refusal(response.status()));
            }
            let bytes = read_body(response, &config).await?;
            let answer: ToolResponse =
                serde_json::from_slice(&bytes).map_err(|_| ApiError::BadGateway(FAILED.into()))?;
            // exactly one of `result` and `error`; the service's own error text is a tool's message, passed on
            match (&answer.result, &answer.error) {
                (Some(_), None) | (None, Some(_)) => Ok(answer),
                _ => Err(ApiError::BadGateway(FAILED.into())),
            }
        })
    }
}

/// The body of a successful answer, at most `max_event_bytes`, with `idle` as the longest silence.
async fn read_body(response: reqwest::Response, config: &ModelConfig) -> Result<Vec<u8>, ApiError> {
    let mut body = response.bytes_stream();
    let mut bytes: Vec<u8> = Vec::new();
    loop {
        match tokio::time::timeout(config.idle, body.next()).await {
            Ok(Some(Ok(piece))) => {
                if bytes.len() + piece.len() > config.max_event_bytes {
                    return Err(ApiError::BadGateway(FAILED.into()));
                }
                bytes.extend_from_slice(&piece);
            }
            Ok(None) => return Ok(bytes),
            _ => return Err(ApiError::BadGateway(FAILED.into())),
        }
    }
}

/// A P2 stream being read: bytes come in only when the consumer asks for the next chunk.
struct Answer {
    body: BoxStream<'static, Result<Bytes, reqwest::Error>>,
    decoder: SseDecoder,
    queue: VecDeque<String>,
    /// Bytes read since the last complete event.
    fed: usize,
    finished: bool,
    idle: Duration,
    max_event_bytes: usize,
    /// The place in the concurrency limit, given back when the stream is dropped.
    _place: OwnedSemaphorePermit,
}

impl Answer {
    fn fail(&mut self, kind: &str) -> Option<Result<ChatResponseChunk, StreamFailure>> {
        self.finished = true;
        Some(Err(StreamFailure {
            message: FAILED.into(),
            kind: kind.into(),
        }))
    }

    async fn next_event(&mut self) -> Option<Result<ChatResponseChunk, StreamFailure>> {
        loop {
            if self.finished {
                return None;
            }
            if let Some(data) = self.queue.pop_front() {
                return match P2Event::from_data(&data) {
                    Ok(P2Event::Chunk(chunk)) => Some(Ok(to_p1(chunk))),
                    Ok(P2Event::Done) => {
                        self.finished = true;
                        None
                    }
                    // the model's own message is not passed on
                    Ok(P2Event::Error(_)) => self.fail("model_error"),
                    Err(_) => self.fail("model_protocol"),
                };
            }
            match tokio::time::timeout(self.idle, self.body.next()).await {
                Err(_) => return self.fail("model_idle"),
                Ok(None) => {
                    return if self.decoder.has_pending() || !self.queue.is_empty() {
                        self.fail("model_protocol")
                    } else {
                        // the model closed the stream without `[DONE]`
                        self.fail("model_truncated")
                    };
                }
                Ok(Some(Err(_))) => return self.fail("model_connection"),
                Ok(Some(Ok(piece))) => {
                    self.fed += piece.len();
                    match self.decoder.feed(&piece) {
                        Ok(events) if events.is_empty() => {
                            if self.fed > self.max_event_bytes {
                                return self.fail("model_protocol");
                            }
                        }
                        Ok(events) => {
                            self.fed = 0;
                            self.queue.extend(events);
                        }
                        Err(_) => return self.fail("model_protocol"),
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Test addresses are built, not written out: no endpoint is hardcoded in the source (SR-L1).
    fn addr(host_port: &str) -> String {
        format!("{}://{host_port}", "http")
    }

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect()
    }

    #[test]
    fn no_url_means_no_model() {
        assert_eq!(ModelConfig::from_env(&env(&[])), Ok(None));
    }

    #[test]
    fn url_and_limits_are_read() {
        let cfg = ModelConfig::from_env(&env(&[
            (
                "LARIS_SERVER__MODEL_URL",
                &format!("{}/", addr("model:8000")),
            ),
            ("LARIS_SERVER__MODEL_MAX_CONCURRENT", "2"),
            ("LARIS_SERVER__MODEL_IDLE_MS", "500"),
        ]))
        .unwrap()
        .unwrap();
        assert_eq!(cfg.base_url, addr("model:8000"));
        assert_eq!(cfg.max_concurrent, 2);
        assert_eq!(cfg.idle, Duration::from_millis(500));
    }

    #[test]
    fn bad_values_name_the_variable_not_the_value() {
        for pairs in [
            vec![("LARIS_SERVER__MODEL_URL", "ftp://secret-host")],
            vec![
                ("LARIS_SERVER__MODEL_URL", &addr("m:1")),
                ("LARIS_SERVER__MODEL_MAX_CONCURRENT", "0"),
            ],
        ] {
            let e = ModelConfig::from_env(&env(&pairs)).unwrap_err().to_string();
            assert!(e.contains("LARIS_SERVER__MODEL_"));
            assert!(!e.contains("secret-host"));
        }
    }

    #[test]
    fn debug_hides_the_address() {
        let text = format!("{:?}", ModelConfig::new(addr("internal-model:9")));
        assert!(!text.contains("internal-model"));
    }

    #[test]
    fn the_laris_block_and_unknown_fields_stay_behind() {
        let request: ChatRequest = serde_json::from_value(serde_json::json!({
            "messages": [{"role": "user", "content": "hi"}],
            "laris": {"workflow": {"name": "x"}},
            "temperature": 0.3,
            "logit_bias": {"1": 5}
        }))
        .unwrap();
        let p2 = serde_json::to_value(p2_request(request, "m")).unwrap();
        assert_eq!(p2["temperature"], 0.3);
        assert_eq!(p2["stream"], true);
        assert!(p2.get("laris").is_none() && p2.get("logit_bias").is_none());
    }
}
