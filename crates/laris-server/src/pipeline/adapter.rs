//! The seam between the harness and the server's backend: a [`Model`] whose every call is one chat request to the
//! backend behind the pipeline (the policy gateway, then the model service), read to its end and bounded.
//!
//! The harness is synchronous and runs on a blocking thread; each call here blocks on the backend's stream on the
//! runtime handle of the request. A draft longer than `max_draft_chars` is an error, never truncated (ADR-025
//! section 7), and a call that takes longer than the stage timeout is an error.

use crate::backend::Backend;
use futures_util::StreamExt;
use laris_core::{Model, ModelAnswer, ModelError, ModelRequest};
use laris_protocol::chat::{ToolCall, Usage};
use laris_protocol::p1::ChatRequest;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::{Duration, Instant};

/// What the pipeline learns about the calls, shared with the code that reports the stages.
#[derive(Default)]
pub struct Seen {
    state: Mutex<State>,
}

#[derive(Default)]
struct State {
    model_ms: u64,
    model: String,
    brain: Vec<String>,
    failure: Option<String>,
}

impl Seen {
    fn with<T>(&self, f: impl FnOnce(&mut State) -> T) -> T {
        f(&mut self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner))
    }

    /// Milliseconds spent inside the model calls, summed.
    pub fn model_ms(&self) -> u64 {
        self.with(|s| s.model_ms)
    }

    /// The model name the answer reported.
    pub fn model(&self) -> String {
        self.with(|s| s.model.clone())
    }

    /// The system brain notes the answer consulted (titles), latest list.
    pub fn brain(&self) -> Vec<String> {
        self.with(|s| s.brain.clone())
    }

    /// The reason code of the failure, when a call failed.
    pub fn failure(&self) -> Option<String> {
        self.with(|s| s.failure.clone())
    }
}

/// A [`Model`] over the backend of the pipeline.
pub struct BackendModel {
    backend: Arc<dyn Backend>,
    base: ChatRequest,
    caller: Option<String>,
    handle: tokio::runtime::Handle,
    max_chars: usize,
    timeout: Duration,
    seen: Arc<Seen>,
}

impl BackendModel {
    /// Calls `backend` with `base` (its tools and settings) and the messages the harness builds.
    pub fn new(
        backend: Arc<dyn Backend>,
        base: ChatRequest,
        caller: Option<String>,
        handle: tokio::runtime::Handle,
        max_chars: usize,
        timeout: Duration,
        seen: Arc<Seen>,
    ) -> Self {
        Self {
            backend,
            base,
            caller,
            handle,
            max_chars,
            timeout,
            seen,
        }
    }
}

fn fail(seen: &Seen, code: &str) -> ModelError {
    seen.with(|s| s.failure = Some(code.to_owned()));
    ModelError::Failed(code.to_owned())
}

impl Model for BackendModel {
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        let mut chat = self.base.clone();
        chat.messages = request.messages.to_vec();
        let started = Instant::now();
        let seen = self.seen.clone();
        let (backend, caller, max_chars, timeout) = (
            self.backend.clone(),
            self.caller.clone(),
            self.max_chars,
            self.timeout,
        );
        let result = self.handle.block_on(async move {
            let call = async {
                let mut stream = backend
                    .chat_for(chat, caller.as_deref())
                    .await
                    .map_err(|_| "model_unavailable")?;
                let mut text = String::new();
                let mut chars = 0usize;
                let mut calls: Vec<ToolCall> = Vec::new();
                let mut usage: Option<Usage> = None;
                while let Some(item) = stream.next().await {
                    let chunk = item.map_err(|_| "model_unavailable")?;
                    if !chunk.model.is_empty() {
                        seen.with(|s| s.model.clone_from(&chunk.model));
                    }
                    if let Some(meta) = &chunk.laris
                        && !meta.brain.is_empty()
                    {
                        seen.with(|s| s.brain.clone_from(&meta.brain));
                    }
                    if chunk.usage.is_some() {
                        usage = chunk.usage;
                    }
                    for choice in chunk.choices {
                        if let Some(piece) = choice.delta.content {
                            chars += piece.chars().count();
                            if chars > max_chars {
                                return Err("draft_too_large");
                            }
                            text.push_str(&piece);
                        }
                        for part in choice.delta.tool_calls {
                            merge(&mut calls, part);
                        }
                    }
                }
                Ok(ModelAnswer {
                    text,
                    tool_calls: calls,
                    usage,
                })
            };
            tokio::time::timeout(timeout, call)
                .await
                .unwrap_or(Err("model_timeout"))
        });
        let elapsed = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
        self.seen.with(|s| s.model_ms += elapsed);
        result.map_err(|code| fail(&self.seen, code))
    }
}

/// Folds one streamed tool-call fragment into the calls so far: fragments with the same index are one call.
fn merge(calls: &mut Vec<ToolCall>, part: ToolCall) {
    let slot = part
        .index
        .and_then(|i| calls.iter().position(|c: &ToolCall| c.index == Some(i)));
    match slot {
        Some(at) => {
            let call = &mut calls[at];
            if call.id.is_none() {
                call.id = part.id;
            }
            if call.function.name.is_empty() {
                call.function.name = part.function.name;
            }
            call.function.arguments.push_str(&part.function.arguments);
        }
        None => calls.push(part),
    }
}
