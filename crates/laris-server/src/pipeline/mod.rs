//! The request pipeline of the server (ADR-025, T239): what happens to a chat turn between the policy and the model.
//!
//! [`Pipeline`] is a [`Backend`] that stands in front of another one (the policy gateway). For a turn it runs, in
//! order:
//!
//! 1. the **Prefilter** on the latest user message: a hit is the answer and the model is never called;
//! 2. **retrieval** over the server's vault: lexical passages with the note path as their source;
//! 3. when passages exist, the **harness** ([`laris_policy::HarnessModel`]): the prompt with the passages as marked,
//!    untrusted data, one or more drafts from the model behind this backend, the evidence gate on each, a bounded
//!    retry, then the checked draft or an abstention. The draft is buffered (D53), so text that fails the gate is
//!    never sent;
//! 4. without passages the turn is *free*: the inner answer is streamed unbuffered and claims no evidence
//!    (`grounding = optional`), or the turn abstains (`grounding = required`).
//!
//! Every stage ends in a step event (stage, outcome, milliseconds, rule or reason code) sent as it ends and kept in
//! the audit row; no step carries message text. With every stage off the route is the policy gateway alone, as before
//! (D56). Tool-call proposals and continuations after a tool result are never gated: they go on to the client
//! (ADR-025 section 2.2).
//!
//! This is a text rule over a model's draft (see [`laris_evidence`]): a cited passage that does not support the
//! sentence passes. It does not qualify any model.

mod adapter;
mod decider;

pub use decider::{DeciderConfig, DeciderTexts, Decision, TurnCounters, Verdict, decide};

use crate::backend::{Backend, Caller, ChunkStream, StreamFailure};
use crate::config::ConfigError;
use crate::error::ApiError;
use crate::mainbrain::MainBrain;
use futures_util::future::BoxFuture;
use futures_util::{StreamExt, stream};
use laris_core::{Model, ModelRequest};
use laris_policy::{
    Ending, HarnessConfig, HarnessModel, NoTurnSink, Outcome, Passage, PassageSource, Prefilter,
    Redactor, Shield, latest_user_message,
};
use laris_protocol::chat::{FinishReason, Usage};
use laris_protocol::p1::{ChatRequest, ChatResponseChunk, Kind, LarisMeta};
use laris_protocol::p2::{ChunkChoice, ChunkDelta, ChunkObject};
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

/// Keys of the `laris` block that only the server may set. A request that carries them has them dropped (TM-31).
pub const SERVER_ONLY_KEYS: [&str; 3] = ["steps", "decision", "evidence"];

/// What happens to a turn that retrieval found no passages for.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Grounding {
    /// No retrieval and no harness: the route is the policy gateway alone.
    Off,
    /// A turn with passages is answered through the harness; a turn without passages is a free answer.
    Optional,
    /// Every turn must be grounded: without passages it abstains and the model is not called.
    Required,
}

/// Settings of the pipeline, from `LARIS_SERVER__PIPELINE_*` variables (SR-L1). Every stage is off by default.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PipelineConfig {
    /// Run the Prefilter (`LARIS_SERVER__PIPELINE_PREFILTER`, `true` or `false`).
    pub prefilter: bool,
    /// Retrieval and harness (`LARIS_SERVER__PIPELINE_GROUNDING`: `off`, `optional` or `required`).
    pub grounding: Grounding,
    /// Most characters of main-brain passages one answer may carry (`LARIS_SERVER__PIPELINE_MAX_EVIDENCE_CHARS`):
    /// the budget that keeps a prompt from reading the brain out one answer at a time (TM-33).
    pub max_evidence_chars: usize,
    /// Longest draft the server buffers, in characters (`LARIS_SERVER__PIPELINE_MAX_DRAFT_CHARS`).
    pub max_draft_chars: usize,
    /// Longest one call to the model may take inside the pipeline (`LARIS_SERVER__PIPELINE_STAGE_TIMEOUT_MS`).
    pub stage_timeout: Duration,
}

impl Default for PipelineConfig {
    fn default() -> Self {
        Self {
            prefilter: false,
            grounding: Grounding::Off,
            max_evidence_chars: 6 * 1024,
            max_draft_chars: 64 * 1024,
            stage_timeout: Duration::from_secs(120),
        }
    }
}

impl PipelineConfig {
    /// Whether any stage is on.
    pub fn enabled(&self) -> bool {
        self.prefilter || self.grounding != Grounding::Off
    }

    /// Reads the settings from `env`.
    pub fn from_env(env: &HashMap<String, String>) -> Result<Self, ConfigError> {
        let get = |name: &str| env.get(name).map(|v| v.trim()).filter(|v| !v.is_empty());
        let invalid =
            |name: &'static str, reason: &'static str| ConfigError::Invalid { name, reason };
        let mut cfg = Self::default();
        if let Some(v) = get("LARIS_SERVER__PIPELINE_PREFILTER") {
            cfg.prefilter = match v {
                "true" => true,
                "false" => false,
                _ => {
                    return Err(invalid(
                        "LARIS_SERVER__PIPELINE_PREFILTER",
                        "expected true or false",
                    ));
                }
            };
        }
        if let Some(v) = get("LARIS_SERVER__PIPELINE_GROUNDING") {
            cfg.grounding = match v {
                "off" => Grounding::Off,
                "optional" => Grounding::Optional,
                "required" => Grounding::Required,
                _ => {
                    return Err(invalid(
                        "LARIS_SERVER__PIPELINE_GROUNDING",
                        "expected off, optional or required",
                    ));
                }
            };
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
        if let Some(n) = number("LARIS_SERVER__PIPELINE_MAX_DRAFT_CHARS")? {
            cfg.max_draft_chars = usize::try_from(n).unwrap_or(usize::MAX);
        }
        if let Some(n) = number("LARIS_SERVER__PIPELINE_MAX_EVIDENCE_CHARS")? {
            cfg.max_evidence_chars = usize::try_from(n).unwrap_or(usize::MAX);
        }
        if let Some(n) = number("LARIS_SERVER__PIPELINE_STAGE_TIMEOUT_MS")? {
            cfg.stage_timeout = Duration::from_millis(n);
        }
        Ok(cfg)
    }
}

/// A pipeline that cannot start. The message names a setting or a file, never content.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum PipelineError {
    /// The Prefilter is on but `.laris/prefilter.toml` is not there (fail closed).
    #[error("the Prefilter is on but .laris/prefilter.toml is missing")]
    NoPrefilter,
    /// Grounding is on but `.laris/harness.toml` is not there (fail closed).
    #[error("grounding is on but .laris/harness.toml is missing")]
    NoHarness,
    /// Grounding is on but there is no main brain to read (`LARIS_SERVER__MAIN_BRAIN_DIR`).
    #[error("grounding is on but no main brain is configured")]
    NoBrain,
}

/// The passages of one turn, found before the harness runs; the harness takes them as its source.
struct Prefetched(Vec<Passage>);

impl PassageSource for Prefetched {
    fn passages(&self, _query: &str, limit: usize) -> Vec<Passage> {
        self.0.iter().take(limit).cloned().collect()
    }
}

/// One stage as it ended.
#[derive(Debug, Clone)]
struct Step {
    stage: &'static str,
    outcome: &'static str,
    ms: u64,
    code: String,
    /// The decider's choice (action and rule), sent once with its step.
    decision: Option<Value>,
}

impl Step {
    fn new(stage: &'static str, outcome: &'static str, started: Instant, code: &str) -> Self {
        Self {
            stage,
            outcome,
            ms: u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX),
            code: code.to_owned(),
            decision: None,
        }
    }
}

struct Inner {
    backend: Arc<dyn Backend>,
    prefilter: Option<Arc<Prefilter>>,
    harness: Option<HarnessConfig>,
    brain: Option<Arc<MainBrain>>,
    decider: Option<DeciderConfig>,
    shield: Arc<Shield>,
    config: PipelineConfig,
}

/// A [`Backend`] that runs the Prefilter, retrieval and the harness around another one.
pub struct Pipeline {
    inner: Arc<Inner>,
}

impl Pipeline {
    /// Puts the pipeline in front of `backend`. `prefilter` and `harness` come from the verified policy. A stage that
    /// is on without its policy file is an error, so the server does not start half checked. A vault that cannot be
    /// read is not: the retrieval stage reports `skipped` and, when grounding is required, the turn abstains.
    pub fn new(
        backend: Arc<dyn Backend>,
        config: PipelineConfig,
        prefilter: Option<Arc<Prefilter>>,
        harness: Option<HarnessConfig>,
        brain: Option<Arc<MainBrain>>,
    ) -> Result<Self, PipelineError> {
        if config.prefilter && prefilter.is_none() {
            return Err(PipelineError::NoPrefilter);
        }
        if config.grounding != Grounding::Off && harness.is_none() {
            return Err(PipelineError::NoHarness);
        }
        if config.grounding != Grounding::Off && brain.is_none() {
            return Err(PipelineError::NoBrain);
        }
        Ok(Self {
            inner: Arc::new(Inner {
                backend,
                prefilter: config.prefilter.then_some(prefilter).flatten(),
                harness,
                brain,
                decider: None,
                shield: Arc::new(Shield::new(Arc::new(Redactor::standard()))),
                config,
            }),
        })
    }
}

impl Pipeline {
    /// Puts the rule decider (stage 5) behind the decision seam. It needs the main brain and grounding.
    pub fn with_decider(mut self, config: DeciderConfig) -> Result<Self, PipelineError> {
        let inner = Arc::get_mut(&mut self.inner).expect("the pipeline is not shared yet");
        if inner.brain.is_none() || inner.config.grounding == Grounding::Off {
            return Err(PipelineError::NoBrain);
        }
        inner.decider = Some(config);
        Ok(self)
    }
}

impl Backend for Pipeline {
    fn chat(&self, request: ChatRequest) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        self.chat_for(request, None)
    }

    fn chat_for(
        &self,
        request: ChatRequest,
        caller: Option<&str>,
    ) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        // a caller the HTTP layer did not describe is a server without keys: it may read the brain
        self.chat_as(
            request,
            &Caller {
                key_id: caller.map(str::to_owned),
                brain_read: true,
            },
        )
    }

    fn chat_as(
        &self,
        mut request: ChatRequest,
        caller: &Caller,
    ) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        for key in SERVER_ONLY_KEYS {
            request.laris.extra.remove(key);
        }
        let this = self.inner.clone();
        let caller = caller.clone();
        Box::pin(async move { run(this, request, caller).await })
    }

    fn embed(
        &self,
        request: laris_protocol::p1::EmbedRequest,
    ) -> BoxFuture<'static, Result<laris_protocol::p1::EmbedResponse, ApiError>> {
        self.inner.backend.embed(request)
    }

    fn tools(&self) -> BoxFuture<'static, Result<laris_protocol::p1::ToolList, ApiError>> {
        self.inner.backend.tools()
    }

    fn tool(
        &self,
        name: String,
        request: laris_protocol::p1::ToolRequest,
    ) -> BoxFuture<'static, Result<laris_protocol::p1::ToolResponse, ApiError>> {
        self.inner.backend.tool(name, request)
    }
}

const FAILED: &str = "the model service failed";

fn chunk(
    delta: ChunkDelta,
    finish: Option<FinishReason>,
    laris: Option<LarisMeta>,
    usage: Option<Usage>,
    model: &str,
) -> ChatResponseChunk {
    ChatResponseChunk {
        id: "laris-pipeline".to_owned(),
        object: ChunkObject::default(),
        model: model.to_owned(),
        laris,
        choices: if delta == ChunkDelta::default() && finish.is_none() {
            Vec::new()
        } else {
            vec![ChunkChoice {
                index: 0,
                delta,
                finish_reason: finish,
                extra: Map::new(),
            }]
        },
        usage,
        extra: Map::new(),
    }
}

fn step_chunk(step: &Step) -> ChatResponseChunk {
    chunk(
        ChunkDelta::default(),
        None,
        Some(LarisMeta {
            steps: vec![laris_protocol::Step {
                stage: step.stage.to_owned(),
                outcome: step.outcome.to_owned(),
                ms: step.ms,
                code: step.code.clone(),
            }],
            decision: step
                .decision
                .as_ref()
                .map(|d| laris_protocol::PipelineDecision {
                    action: d["action"].as_str().unwrap_or("").to_owned(),
                    rule: d["rule"].as_str().unwrap_or("").to_owned(),
                }),
            ..LarisMeta::default()
        }),
        None,
        "",
    )
}

/// The evidence event: the server-held passages an answer cites, once, before the text.
fn evidence_chunk(items: Vec<laris_protocol::ServerEvidence>) -> Option<ChatResponseChunk> {
    (!items.is_empty()).then(|| {
        chunk(
            ChunkDelta::default(),
            None,
            Some(LarisMeta {
                evidence: items,
                ..LarisMeta::default()
            }),
            None,
            "",
        )
    })
}

/// The passages `text` cites, as evidence entries (`origin: server`).
fn evidence_of(text: &str, passages: &[Passage]) -> Vec<laris_protocol::ServerEvidence> {
    use sha2::{Digest, Sha256};
    passages
        .iter()
        .filter(|p| {
            text.contains(&format!(
                "[{} #",
                p.source.split_whitespace().collect::<Vec<_>>().join(" ")
            ))
        })
        .map(|p| laris_protocol::ServerEvidence {
            id: p.source.clone(),
            origin: "server".to_owned(),
            level: p.level.clone(),
            title: p
                .source
                .trim_end_matches(".md")
                .rsplit('/')
                .next()
                .unwrap_or("")
                .to_owned(),
            start: p.start as u64,
            end: p.end as u64,
            sha256: Sha256::digest(p.text.as_bytes())
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect(),
        })
        .collect()
}

/// The chunks of an answer the pipeline wrote itself (a Prefilter hit, an abstention): the text, the end and zero
/// usage, because no completion was produced.
fn canned(text: &str) -> Vec<ChatResponseChunk> {
    let say = (!text.is_empty()).then(|| {
        chunk(
            ChunkDelta {
                content: Some(text.to_owned()),
                ..ChunkDelta::default()
            },
            None,
            None,
            None,
            "",
        )
    });
    say.into_iter()
        .chain([
            chunk(
                ChunkDelta::default(),
                Some(FinishReason::Stop),
                None,
                None,
                "",
            ),
            chunk(
                ChunkDelta::default(),
                None,
                None,
                Some(Usage::default()),
                "",
            ),
        ])
        .collect()
}

/// Whether the last user messages follow a tool result: the client's loop speaking to the model in the middle of a
/// turn (a replan or wrap-up notice), not a new question of the person, so retrieval and the harness leave it alone.
fn continues_tool_work(messages: &[laris_protocol::ChatMessage]) -> bool {
    messages
        .iter()
        .rev()
        .find(|m| m.role != laris_protocol::Role::User)
        .is_some_and(|m| m.role == laris_protocol::Role::Tool)
}

fn ready(chunks: Vec<ChatResponseChunk>) -> ChunkStream {
    stream::iter(chunks.into_iter().map(Ok)).boxed()
}

async fn run(this: Arc<Inner>, request: ChatRequest, who: Caller) -> Result<ChunkStream, ApiError> {
    let brain_read = who.brain_read;
    let caller = who.key_id;
    // a summary, a workflow-free continuation after a tool result and a pipeline with every stage off are not turns
    // this pipeline checks
    let question = (this.config.enabled()
        && request.laris.kind == Kind::Turn
        && !continues_tool_work(&request.messages))
    .then(|| latest_user_message(&request.messages))
    .flatten();
    let Some(question) = question else {
        return this.backend.chat_for(request, caller.as_deref()).await;
    };
    let mut steps: Vec<Step> = Vec::new();

    // stage 3: the Prefilter
    match &this.prefilter {
        None => steps.push(Step::new("prefilter", "skipped", Instant::now(), "")),
        Some(prefilter) => {
            let started = Instant::now();
            match prefilter.check(&question) {
                Outcome::Answer(hit) => {
                    steps.push(Step::new("prefilter", "stop", started, &hit.rule));
                    let mut out: Vec<ChatResponseChunk> = steps.iter().map(step_chunk).collect();
                    out.extend(canned(&hit.text));
                    return Ok(ready(out));
                }
                Outcome::Pass => steps.push(Step::new("prefilter", "ok", started, "")),
            }
        }
    }

    // stage 4: retrieval
    let (Some(harness), true) = (
        this.harness.clone(),
        this.config.grounding != Grounding::Off,
    ) else {
        return free(this.clone(), request, caller, steps).await;
    };
    let started = Instant::now();
    let source = if brain_read {
        this.brain.as_ref().and_then(|b| b.source())
    } else {
        None
    };
    let passages = match source {
        None => {
            let code = if brain_read {
                "vault_unavailable"
            } else {
                "no_permission"
            };
            steps.push(Step::new("retrieval", "skipped", started, code));
            Vec::new()
        }
        Some(source) => {
            let (limit, text) = (harness.passages, question.clone());
            let found = tokio::task::spawn_blocking(move || source.passages(&text, limit)).await;
            match found {
                Ok(found) => {
                    steps.push(Step::new("retrieval", "ok", started, ""));
                    within_budget(found, this.config.max_evidence_chars)
                }
                Err(_) => {
                    steps.push(Step::new("retrieval", "error", started, "retrieval_failed"));
                    Vec::new()
                }
            }
        }
    };
    // stage 5: the decider
    if let Some(decider) = this.decider {
        let started = Instant::now();
        let index = if brain_read {
            this.brain.as_ref().and_then(|b| b.index())
        } else {
            None
        };
        let Some(index) = index else {
            let code = if brain_read {
                "vault_unavailable"
            } else {
                "no_permission"
            };
            steps.push(Step::new("decider", "skipped", started, code));
            return after_decider(this, request, caller, harness, passages, steps).await;
        };
        let turn = TurnCounters::from_request(&request.laris.extra);
        let (text, found, required) = (
            question.clone(),
            !passages.is_empty(),
            this.config.grounding == Grounding::Required,
        );
        let texts = DeciderTexts {
            abstain: harness.abstain_no_source.clone(),
            stop: harness.decider_stop.clone(),
            ask_user: harness.decider_ask_user.clone(),
        };
        let decided = tokio::task::spawn_blocking(move || {
            decide(&decider, &index, &text, found, required, &turn, &texts)
        })
        .await;
        match decided {
            Err(_) => steps.push(Step::new("decider", "error", started, "decider_failed")),
            Ok(decision) => {
                let ends = !matches!(decision.verdict, Verdict::Continue | Verdict::Compose(..));
                let mut step = Step::new(
                    "decider",
                    if ends { "stop" } else { "ok" },
                    started,
                    &decision.code(),
                );
                step.decision = Some(json!({
                    "action": decision.choice.act.as_str(),
                    "rule": decision.choice.rule,
                }));
                steps.push(step);
                match decision.verdict {
                    Verdict::Continue => {}
                    Verdict::End(text) => {
                        let mut out: Vec<ChatResponseChunk> =
                            steps.iter().map(step_chunk).collect();
                        out.extend(canned(&text));
                        return Ok(ready(out));
                    }
                    Verdict::Compose(text, cited) => {
                        steps.push(Step::new("assembly", "ok", Instant::now(), ""));
                        let mut out: Vec<ChatResponseChunk> =
                            steps.iter().map(step_chunk).collect();
                        out.extend(evidence_chunk(cited));
                        out.extend(canned(&text));
                        return Ok(ready(out));
                    }
                }
            }
        }
    }
    after_decider(this, request, caller, harness, passages, steps).await
}

/// Stages 6 and 7 for a turn the decider let through: without passages a free answer (or the abstention when grounding
/// is required), with passages the buffered, gated answer.
async fn after_decider(
    this: Arc<Inner>,
    request: ChatRequest,
    caller: Option<String>,
    harness: HarnessConfig,
    passages: Vec<Passage>,
    mut steps: Vec<Step>,
) -> Result<ChunkStream, ApiError> {
    if passages.is_empty() {
        if this.config.grounding == Grounding::Required {
            let code = match steps.last() {
                Some(last) if last.outcome == "ok" => "no_evidence".to_owned(),
                Some(last) => last.code.clone(),
                None => "no_evidence".to_owned(),
            };
            steps.push(Step::new("gate", "stop", Instant::now(), &code));
            let mut out: Vec<ChatResponseChunk> = steps.iter().map(step_chunk).collect();
            out.extend(canned(&harness.abstain_no_source));
            return Ok(ready(out));
        }
        return free(this.clone(), request, caller, steps).await;
    }

    // stages 6 and 7: the model and the evidence gate, buffered
    let (tx, rx) = tokio::sync::mpsc::channel::<Result<ChatResponseChunk, StreamFailure>>(16);
    for step in &steps {
        let _ = tx.try_send(Ok(step_chunk(step)));
    }
    tokio::spawn(grounded(
        this, request, caller, harness, passages, steps, tx,
    ));
    Ok(stream::unfold(rx, |mut rx| async move {
        rx.recv().await.map(|item| (item, rx))
    })
    .boxed())
}

/// The passages that fit the per-answer budget, best first. A passage is never cut: the quote check needs it whole, so
/// the first one that does not fit ends the list.
fn within_budget(passages: Vec<Passage>, budget: usize) -> Vec<Passage> {
    let mut used = 0usize;
    passages
        .into_iter()
        .take_while(|p| {
            used = used.saturating_add(p.text.chars().count());
            used <= budget
        })
        .collect()
}

/// A free answer: the inner stream, unbuffered, behind the step events so far.
async fn free(
    this: Arc<Inner>,
    request: ChatRequest,
    caller: Option<String>,
    steps: Vec<Step>,
) -> Result<ChunkStream, ApiError> {
    let inner = this.backend.chat_for(request, caller.as_deref()).await?;
    let prefix: Vec<Result<ChatResponseChunk, StreamFailure>> =
        steps.iter().map(|s| Ok(step_chunk(s))).collect();
    Ok(stream::iter(prefix).chain(inner).boxed())
}

/// Runs the harness on a blocking thread and sends its result as chunks.
async fn grounded(
    this: Arc<Inner>,
    request: ChatRequest,
    caller: Option<String>,
    harness: HarnessConfig,
    passages: Vec<Passage>,
    mut steps: Vec<Step>,
    tx: tokio::sync::mpsc::Sender<Result<ChatResponseChunk, StreamFailure>>,
) {
    let seen = Arc::new(adapter::Seen::default());
    let model = adapter::BackendModel::new(
        this.backend.clone(),
        request.clone(),
        caller,
        tokio::runtime::Handle::current(),
        this.config.max_draft_chars,
        this.config.stage_timeout,
        seen.clone(),
    );
    let (shield, messages, tools) = (
        this.shield.clone(),
        request.messages.clone(),
        request.tools.clone(),
    );
    let shown = passages.clone();
    let started = Instant::now();
    let joined = tokio::task::spawn_blocking(move || {
        let mut harness = HarnessModel::new(
            model,
            Prefetched(passages),
            shield,
            harness,
            Arc::new(NoTurnSink),
        );
        let answer = harness.answer(&ModelRequest {
            messages: &messages,
            note: None,
            tools: &tools,
        });
        (answer, harness.last_turn().map(|t| t.ending))
    })
    .await;
    let total = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
    let model_ms = seen.model_ms();
    let step = |stage, outcome, ms, code: &str| Step {
        stage,
        outcome,
        ms,
        code: code.to_owned(),
        decision: None,
    };
    let model_name = seen.model();
    match joined {
        Ok((Ok(answer), ending)) => {
            steps.push(step("model", "ok", model_ms, ""));
            let gate = match ending {
                Some(Ending::Answered) => step("gate", "ok", total.saturating_sub(model_ms), ""),
                Some(Ending::PassedOn) | None => step("gate", "skipped", 0, "tool_call_proposal"),
                Some(Ending::NoSource) => step(
                    "gate",
                    "stop",
                    total.saturating_sub(model_ms),
                    "no_evidence",
                ),
                Some(Ending::ModelAbstained) => step(
                    "gate",
                    "stop",
                    total.saturating_sub(model_ms),
                    "model_abstained",
                ),
                Some(Ending::Unverified) => step(
                    "gate",
                    "stop",
                    total.saturating_sub(model_ms),
                    "unsupported_draft",
                ),
            };
            steps.push(gate);
            if ending == Some(Ending::NoSource) {
                // every passage was dropped before the model saw it: the model was not asked
                steps.retain(|s| s.stage != "model");
            }
            let brain = seen.brain();
            let mut out: Vec<ChatResponseChunk> =
                steps[steps.len() - 2..].iter().map(step_chunk).collect();
            if ending == Some(Ending::Answered) {
                out.extend(evidence_chunk(evidence_of(&answer.text, &shown)));
            }
            if !brain.is_empty() {
                out.push(chunk(
                    ChunkDelta::default(),
                    None,
                    Some(LarisMeta {
                        brain,
                        ..LarisMeta::default()
                    }),
                    None,
                    &model_name,
                ));
            }
            let finish = if answer.tool_calls.is_empty() {
                FinishReason::Stop
            } else {
                FinishReason::ToolCalls
            };
            out.push(chunk(
                ChunkDelta {
                    content: (!answer.text.is_empty()).then(|| answer.text.clone()),
                    tool_calls: answer.tool_calls.clone(),
                    ..ChunkDelta::default()
                },
                None,
                None,
                None,
                &model_name,
            ));
            out.push(chunk(
                ChunkDelta::default(),
                Some(finish),
                None,
                None,
                &model_name,
            ));
            out.push(chunk(
                ChunkDelta::default(),
                None,
                None,
                Some(answer.usage.unwrap_or_default()),
                &model_name,
            ));
            for c in out {
                if tx.send(Ok(c)).await.is_err() {
                    return;
                }
            }
        }
        Ok((Err(error), _)) => {
            let code = seen.failure().unwrap_or_else(|| "model_unavailable".into());
            let _ = error;
            let step = step("model", "error", model_ms, &code);
            let _ = tx.send(Ok(step_chunk(&step))).await;
            let _ = tx
                .send(Err(StreamFailure {
                    message: FAILED.to_owned(),
                    kind: "ModelUnavailable".to_owned(),
                }))
                .await;
        }
        Err(_) => {
            let step = step("model", "error", total, "stage_failed");
            let _ = tx.send(Ok(step_chunk(&step))).await;
            let _ = tx
                .send(Err(StreamFailure {
                    message: "the pipeline failed".to_owned(),
                    kind: "PipelineFailed".to_owned(),
                }))
                .await;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::continues_tool_work;
    use laris_protocol::{ChatMessage, Content, Role};

    fn said(role: Role, text: &str) -> ChatMessage {
        ChatMessage {
            role,
            content: Some(Content::Text(text.to_owned())),
            tool_calls: Vec::new(),
            tool_call_id: None,
            name: None,
            extra: serde_json::Map::new(),
        }
    }

    #[test]
    fn a_notice_after_a_tool_result_is_not_a_new_question() {
        let question = vec![said(Role::User, "what is MPC?")];
        assert!(!continues_tool_work(&question));
        let next = vec![
            said(Role::User, "what is MPC?"),
            said(Role::Assistant, "It is a control method."),
            said(Role::User, "and NMPC?"),
        ];
        assert!(!continues_tool_work(&next));
        let notice = vec![
            said(Role::User, "find papers"),
            said(Role::Assistant, ""),
            said(Role::Tool, "{\"results\":[]}"),
            said(Role::User, "Write the final answer now."),
        ];
        assert!(continues_tool_work(&notice));
    }
}
