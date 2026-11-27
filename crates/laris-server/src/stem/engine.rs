//! The engine seam of the STEM profile: the vLLM server of T282 over its OpenAI-compatible API, called the way the
//! Python runner calls it (`scripts/stem_benchmarks.py`, `HttpEngine`): a chat completion for plain drafts, a raw
//! completion for a thinking budget and for the conclusion of a cut reply, and the chat template of one user turn.
//! The template is rendered by the engine itself (`/tokenize`, then `/detokenize`), so the server holds no template
//! and no tokenizer and sends the very prompt text the runner builds from the same tokenizer files.

use super::StemError;
use super::config::Mode;
use futures_util::future::BoxFuture;
use serde_json::{Value, json};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Semaphore;

/// One reply of the engine.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Reply {
    /// The text; a chat reply's reasoning, when the engine splits it, is put back inside `<think>` tags.
    pub text: String,
    /// Prompt tokens the engine counted.
    pub prompt_tokens: u64,
    /// Tokens generated.
    pub generated_tokens: u64,
    /// The reply stopped at its token cap.
    pub truncated: bool,
    /// Wall seconds of the request.
    pub seconds: f64,
}

/// What answers the profile's model calls.
pub trait Engine: Send + Sync {
    /// A chat completion of one user turn under `mode`.
    fn chat(
        &self,
        prompt: String,
        mode: Mode,
        seed: u64,
        max_tokens: u32,
    ) -> BoxFuture<'static, Result<Reply, StemError>>;
    /// A raw completion of `raw` (a templated prompt, possibly with the reply so far) under `mode`'s sampling.
    fn complete(
        &self,
        raw: String,
        mode: Mode,
        seed: u64,
        max_tokens: u32,
    ) -> BoxFuture<'static, Result<Reply, StemError>>;
    /// The chat template of one user turn, thinking on (ends inside the open reasoning) or off.
    fn template(
        &self,
        prompt: String,
        thinking: bool,
    ) -> BoxFuture<'static, Result<String, StemError>>;
}

/// The vLLM server.
pub struct VllmEngine {
    http: reqwest::Client,
    base: String,
    model: String,
    timeout: Duration,
    places: Arc<Semaphore>,
}

impl VllmEngine {
    /// A client for `base` (no `/v1`), asking for `model`, at most `concurrency` requests at once.
    pub fn new(
        base: &str,
        model: &str,
        concurrency: usize,
        timeout: Duration,
    ) -> Result<Self, StemError> {
        let http = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(10))
            .build()
            .map_err(|_| StemError::Engine("the engine client cannot be built"))?;
        Ok(Self {
            http,
            base: base.trim_end_matches('/').to_owned(),
            model: model.to_owned(),
            timeout,
            places: Arc::new(Semaphore::new(concurrency.max(1))),
        })
    }

    fn post(
        &self,
        path: &'static str,
        body: Value,
    ) -> BoxFuture<'static, Result<Value, StemError>> {
        let http = self.http.clone();
        let url = format!("{}{path}", self.base);
        let timeout = self.timeout;
        let places = self.places.clone();
        Box::pin(async move {
            let _place = places
                .acquire_owned()
                .await
                .map_err(|_| StemError::Engine("the engine queue is closed"))?;
            let sent = http.post(url).json(&body).timeout(timeout).send();
            let response = sent
                .await
                .map_err(|_| StemError::Engine("the engine is not reachable"))?;
            if !response.status().is_success() {
                return Err(StemError::Engine("the engine refused the request"));
            }
            response
                .json::<Value>()
                .await
                .map_err(|_| StemError::Engine("the engine's answer does not parse"))
        })
    }
}

fn sampling(body: &mut Value, mode: &Mode, seed: u64, max_tokens: u32) {
    body["max_tokens"] = json!(max_tokens);
    body["temperature"] = json!(mode.temperature);
    body["top_p"] = json!(mode.top_p);
    body["top_k"] = json!(mode.top_k);
    body["seed"] = json!(seed);
}

fn reply(answer: &Value, started: Instant) -> Result<Reply, StemError> {
    let choice = answer["choices"]
        .get(0)
        .ok_or(StemError::Engine("the engine sent no choice"))?;
    let text = if let Some(message) = choice.get("message") {
        let content = message["content"].as_str().unwrap_or("");
        match message["reasoning_content"].as_str() {
            Some(r) if !r.is_empty() => format!("<think>{r}</think>{content}"),
            _ => content.to_owned(),
        }
    } else {
        choice["text"].as_str().unwrap_or("").to_owned()
    };
    Ok(Reply {
        text,
        prompt_tokens: answer["usage"]["prompt_tokens"].as_u64().unwrap_or(0),
        generated_tokens: answer["usage"]["completion_tokens"].as_u64().unwrap_or(0),
        truncated: choice["finish_reason"].as_str() == Some("length"),
        seconds: started.elapsed().as_secs_f64(),
    })
}

impl Engine for VllmEngine {
    fn chat(
        &self,
        prompt: String,
        mode: Mode,
        seed: u64,
        max_tokens: u32,
    ) -> BoxFuture<'static, Result<Reply, StemError>> {
        let mut body = json!({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "chat_template_kwargs": {"enable_thinking": mode.enable_thinking},
        });
        sampling(&mut body, &mode, seed, max_tokens);
        let sent = self.post("/v1/chat/completions", body);
        Box::pin(async move {
            let started = Instant::now();
            reply(&sent.await?, started)
        })
    }

    fn complete(
        &self,
        raw: String,
        mode: Mode,
        seed: u64,
        max_tokens: u32,
    ) -> BoxFuture<'static, Result<Reply, StemError>> {
        let mut body = json!({"model": self.model, "prompt": raw, "skip_special_tokens": false});
        sampling(&mut body, &mode, seed, max_tokens);
        let sent = self.post("/v1/completions", body);
        Box::pin(async move {
            let started = Instant::now();
            reply(&sent.await?, started)
        })
    }

    fn template(
        &self,
        prompt: String,
        thinking: bool,
    ) -> BoxFuture<'static, Result<String, StemError>> {
        let tokenize = self.post(
            "/tokenize",
            json!({
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "add_generation_prompt": true,
                "chat_template_kwargs": {"enable_thinking": thinking},
            }),
        );
        let http = Self {
            http: self.http.clone(),
            base: self.base.clone(),
            model: self.model.clone(),
            timeout: self.timeout,
            places: self.places.clone(),
        };
        Box::pin(async move {
            let tokens = tokenize.await?["tokens"].clone();
            if !tokens.is_array() {
                return Err(StemError::Engine("the engine sent no tokens"));
            }
            let text = http
                .post(
                    "/detokenize",
                    json!({"model": http.model, "tokens": tokens}),
                )
                .await?;
            text["prompt"]
                .as_str()
                .map(str::to_owned)
                .ok_or(StemError::Engine("the engine sent no prompt text"))
        })
    }
}
