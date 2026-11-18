//! The P1 client: version check, key, bounded retries before a stream starts, timeouts, interrupt, and a pull-based
//! decoder for the chat stream.

use crate::config::{ApiKey, ClientConfig};
use crate::error::ClientError;
use crate::interrupt::Interrupt;
use crate::transport::{BodyStream, HttpRequest, Method, ResponseHead, Transport, TransportError};
use laris_protocol::p1::{ChatRequest, HttpError};
use laris_protocol::sse::{P1Event, SseDecoder};
use laris_protocol::version::{PROTOCOL_HEADER, PROTOCOL_VERSION, check_version};
use serde::Serialize;
use serde::de::DeserializeOwned;
use std::collections::VecDeque;
use std::time::Duration;

const USER_AGENT: &str = concat!("laris-model-client/", env!("CARGO_PKG_VERSION"));

/// Talks P1 to a Laris server through a [`Transport`].
#[derive(Debug)]
pub struct ModelClient<T: Transport> {
    transport: T,
    base: String,
    key: Option<ApiKey>,
    config: ClientConfig,
}

impl<T: Transport> ModelClient<T> {
    /// Makes a client; fails when the configuration is not usable.
    pub fn new(transport: T, config: ClientConfig) -> Result<Self, ClientError> {
        let base = config.validated_base()?;
        Ok(Self {
            transport,
            base,
            key: config.api_key.clone(),
            config,
        })
    }

    /// `POST /v1/laris/chat`: the stream of the answer. The request is always sent with `stream: true`. Errors that
    /// come before the first byte of the stream (refusals, version and key problems, timeouts) are returned here;
    /// an error after the stream started arrives as an `error` event, then `[DONE]`.
    pub async fn chat(
        &self,
        request: &ChatRequest,
        interrupt: &Interrupt,
    ) -> Result<ChatStream<T::Body>, ClientError> {
        let mut request = request.clone();
        request.stream = true;
        let body = encode(&request)?;
        let http = self.request(Method::Post, "/laris/chat", Some(body), "text/event-stream");
        let (_, stream_body) = self.send_checked(&http, interrupt).await?;
        Ok(ChatStream {
            body: stream_body,
            decoder: SseDecoder::new(),
            queue: VecDeque::new(),
            finished: false,
            fed_since_event: 0,
            idle_timeout: self.config.idle_timeout,
            max_event_bytes: self.config.max_body_bytes,
            interrupt: interrupt.clone(),
        })
    }

    /// `GET` of a JSON route below the address, e.g. `/laris/help`.
    pub async fn get_json<R: DeserializeOwned>(
        &self,
        path: &str,
        interrupt: &Interrupt,
    ) -> Result<R, ClientError> {
        let http = self.request(Method::Get, path, None, "application/json");
        self.json_answer(&http, interrupt).await
    }

    /// `POST` of a JSON body to a JSON route, e.g. `/laris/embed`.
    pub async fn post_json<B: Serialize, R: DeserializeOwned>(
        &self,
        path: &str,
        body: &B,
        interrupt: &Interrupt,
    ) -> Result<R, ClientError> {
        let http = self.request(Method::Post, path, Some(encode(body)?), "application/json");
        self.json_answer(&http, interrupt).await
    }

    async fn json_answer<R: DeserializeOwned>(
        &self,
        http: &HttpRequest,
        interrupt: &Interrupt,
    ) -> Result<R, ClientError> {
        let (_, mut body) = self.send_checked(http, interrupt).await?;
        let bytes = self.read_limited(&mut body, interrupt).await?;
        serde_json::from_slice(&bytes).map_err(|e| ClientError::Decode(e.to_string()))
    }

    fn request(
        &self,
        method: Method,
        path: &str,
        body: Option<Vec<u8>>,
        accept: &str,
    ) -> HttpRequest {
        let mut headers = vec![
            (PROTOCOL_HEADER.to_owned(), PROTOCOL_VERSION.to_owned()),
            ("Accept".to_owned(), accept.to_owned()),
            ("User-Agent".to_owned(), USER_AGENT.to_owned()),
        ];
        if body.is_some() {
            headers.push(("Content-Type".to_owned(), "application/json".to_owned()));
        }
        if let Some(key) = &self.key {
            headers.push(("Authorization".to_owned(), key.bearer()));
        }
        HttpRequest {
            method,
            url: format!("{}{}", self.base, path),
            headers,
            body,
        }
    }

    /// Sends with bounded retries and returns the head and body of a successful answer.
    async fn send_checked(
        &self,
        http: &HttpRequest,
        interrupt: &Interrupt,
    ) -> Result<(ResponseHead, T::Body), ClientError> {
        let mut attempt: u32 = 0;
        loop {
            let (error, retry_after) = match self.attempt(http, interrupt).await {
                Ok(done) => return Ok(done),
                Err(failed) => failed,
            };
            if !error.is_retryable() || attempt >= self.config.max_retries {
                return Err(error);
            }
            let wait = self.backoff(attempt, retry_after);
            attempt += 1;
            tokio::select! {
                biased;
                () = interrupt.triggered() => return Err(ClientError::Interrupted),
                () = tokio::time::sleep(wait) => {}
            }
        }
    }

    /// One attempt. The error side carries the server's `Retry-After`, if it sent one.
    async fn attempt(
        &self,
        http: &HttpRequest,
        interrupt: &Interrupt,
    ) -> Result<(ResponseHead, T::Body), (ClientError, Option<Duration>)> {
        if interrupt.is_triggered() {
            return Err((ClientError::Interrupted, None));
        }
        let sent = tokio::select! {
            biased;
            () = interrupt.triggered() => return Err((ClientError::Interrupted, None)),
            sent = tokio::time::timeout(self.config.request_timeout, self.transport.send(http)) => sent,
        };
        let (head, mut body) = match sent {
            Err(_) => return Err((ClientError::Timeout(self.config.request_timeout), None)),
            Ok(Err(e)) => return Err((transport_error(&e), None)),
            Ok(Ok(answer)) => answer,
        };
        if let Some(seen) = head.header(PROTOCOL_HEADER)
            && let Err(e) = check_version(Some(seen))
        {
            return Err((ClientError::Version(e.to_string()), None));
        }
        if (200..300).contains(&head.status) {
            return Ok((head, body));
        }
        let retry_after = head
            .header("Retry-After")
            .and_then(|v| v.trim().parse::<u64>().ok())
            .map(Duration::from_secs);
        let text = match self.read_limited(&mut body, interrupt).await {
            Ok(bytes) => error_text(&bytes),
            Err(ClientError::Interrupted) => return Err((ClientError::Interrupted, None)),
            Err(_) => String::new(),
        };
        let error = match head.status {
            426 => ClientError::Version(text),
            401 | 403 => ClientError::Unauthorized(text),
            status => ClientError::Http {
                status,
                message: text,
            },
        };
        Err((error, retry_after))
    }

    /// Doubling backoff from `backoff_base`, capped at `backoff_max`; a longer `Retry-After` is honoured up to the cap.
    fn backoff(&self, attempt: u32, retry_after: Option<Duration>) -> Duration {
        let doubled = self
            .config
            .backoff_base
            .saturating_mul(2u32.saturating_pow(attempt));
        doubled
            .max(retry_after.unwrap_or_default())
            .min(self.config.backoff_max)
    }

    async fn read_limited(
        &self,
        body: &mut T::Body,
        interrupt: &Interrupt,
    ) -> Result<Vec<u8>, ClientError> {
        let mut out = Vec::new();
        loop {
            let chunk = read_chunk(body, self.config.idle_timeout, interrupt).await?;
            match chunk {
                None => return Ok(out),
                Some(bytes) => {
                    out.extend_from_slice(&bytes);
                    if out.len() > self.config.max_body_bytes {
                        return Err(ClientError::Stream(format!(
                            "the answer is larger than {} bytes",
                            self.config.max_body_bytes
                        )));
                    }
                }
            }
        }
    }
}

fn encode<B: Serialize>(body: &B) -> Result<Vec<u8>, ClientError> {
    serde_json::to_vec(body).map_err(|e| ClientError::Decode(e.to_string()))
}

fn transport_error(error: &TransportError) -> ClientError {
    ClientError::Transport(error.message().to_owned())
}

fn error_text(bytes: &[u8]) -> String {
    match serde_json::from_slice::<HttpError>(bytes) {
        Ok(parsed) => parsed.error,
        Err(_) => String::from_utf8_lossy(bytes).chars().take(300).collect(),
    }
}

async fn read_chunk<B: BodyStream>(
    body: &mut B,
    idle: Duration,
    interrupt: &Interrupt,
) -> Result<Option<Vec<u8>>, ClientError> {
    tokio::select! {
        biased;
        () = interrupt.triggered() => Err(ClientError::Interrupted),
        read = tokio::time::timeout(idle, body.chunk()) => match read {
            Err(_) => Err(ClientError::IdleTimeout(idle)),
            Ok(Err(e)) => Err(transport_error(&e)),
            Ok(Ok(chunk)) => Ok(chunk),
        },
    }
}

/// The events of one chat answer. Bytes are read only when [`ChatStream::next`] needs them, so a slow consumer slows
/// the server down instead of filling memory. After `[DONE]` (or any error) the stream is finished and the connection
/// is released when it is dropped.
#[derive(Debug)]
pub struct ChatStream<B: BodyStream> {
    body: B,
    decoder: SseDecoder,
    queue: VecDeque<String>,
    finished: bool,
    fed_since_event: usize,
    idle_timeout: Duration,
    max_event_bytes: usize,
    interrupt: Interrupt,
}

impl<B: BodyStream> ChatStream<B> {
    /// The next event; `Ok(None)` after `[DONE]`. A stream that ends or goes silent before `[DONE]`, a malformed
    /// event and an interrupt are errors, after which the stream is finished.
    pub async fn next(&mut self) -> Result<Option<P1Event>, ClientError> {
        loop {
            if !self.finished && self.interrupt.is_triggered() {
                return Err(self.fail(ClientError::Interrupted));
            }
            if let Some(data) = self.queue.pop_front() {
                let event = P1Event::from_data(&data)
                    .map_err(|e| self.fail(ClientError::Stream(e.to_string())))?;
                if event == P1Event::Done {
                    self.finished = true;
                    self.queue.clear();
                }
                return Ok(Some(event));
            }
            if self.finished {
                return Ok(None);
            }
            let chunk = match read_chunk(&mut self.body, self.idle_timeout, &self.interrupt).await {
                Ok(chunk) => chunk,
                Err(e) => return Err(self.fail(e)),
            };
            let Some(bytes) = chunk else {
                return Err(self.fail(ClientError::Truncated));
            };
            let events = self
                .decoder
                .feed(&bytes)
                .map_err(|e| self.fail(ClientError::Stream(e.to_string())))?;
            if events.is_empty() {
                self.fed_since_event += bytes.len();
                if self.fed_since_event > self.max_event_bytes {
                    return Err(self.fail(ClientError::Stream(format!(
                        "an event is larger than {} bytes",
                        self.max_event_bytes
                    ))));
                }
            } else {
                self.fed_since_event = 0;
            }
            self.queue.extend(events);
        }
    }

    fn fail(&mut self, error: ClientError) -> ClientError {
        self.finished = true;
        self.queue.clear();
        error
    }
}
