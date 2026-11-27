//! The STEM evaluation profile in the server pipeline (T284, ADR-025, ADR-026).
//!
//! The router, the model-free path, the brain notes, the draft with its thinking budget and conclusion, the model's
//! solver formalisation with its repair, the solver check, self-consistency, review and the notes check of the Python
//! harness (T278-T280, T285-T287, T290) run here as one stage of the pipeline, so the system that is measured is the
//! one that is deployed, and the web client, the terminal client and the benchmark runner are answered alike:
//!
//! * the **engine** is the vLLM server of T282 ([`engine::VllmEngine`]);
//! * the **solver** is the remote tool `solve_stem`, and the profile's deterministic steps (prompt filter, model-free
//!   patterns, repair, solver answer, answer equivalence, cross-check) are the remote tool `stem_check` of the model
//!   service: the very Python code the reference harness runs ([`checks::RemoteChecks`]);
//! * **retrieval** reads the frozen snapshot through [`MainBrain`]; network tools are off (a turn of the profile never
//!   reaches the policy gateway's tools).
//!
//! A turn enters the profile when it carries an item (`laris.stem`, the benchmark runner), or, with entry `auto`,
//! when it is the first question of a conversation, has no attached documents and passes the prompt filter with a
//! STEM signal. Any other turn goes on through the pipeline as before. The profile does not qualify the model: the
//! model and the system are NOT QUALIFIED until gates B1-B6 pass on the sealed test (ADR-026).

pub mod checks;
pub mod config;
pub mod engine;
pub mod harness;
pub mod text;

pub use config::{Entry, StemConfig};
pub use harness::{Harness, Item, Trace};

use crate::backend::{ChunkStream, StreamFailure};
use crate::mainbrain::MainBrain;
use futures_util::StreamExt;
use laris_brain::certain;
use laris_policy::{PassageSource, Redactor};
use laris_protocol::chat::{FinishReason, Usage};
use laris_protocol::p1::{ChatRequest, ChatResponseChunk, LarisMeta};
use laris_protocol::p2::{ChunkChoice, ChunkDelta, ChunkObject};
use laris_vault::brain::Level;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::mpsc;

/// A failure of the profile. The message names the part that failed, never content.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum StemError {
    /// The engine failed.
    #[error("{0}")]
    Engine(&'static str),
    /// A remote tool failed.
    #[error("{0}")]
    Tool(&'static str),
}

/// The key of the request's and the answer's `laris` block that carries the profile's item and record.
pub const STEM_KEY: &str = "stem";

/// A turn the profile takes.
#[derive(Debug, Clone, PartialEq)]
pub struct Wanted {
    /// The item's id (the runner's, or the SHA-256 of a chat question).
    pub id: String,
    /// The question.
    pub question: String,
    /// The options.
    pub options: Vec<String>,
    /// The seed, when the request names one.
    pub seed: Option<u64>,
    /// Sent by the runner (a filter stop is answered as such); a chat turn falls through instead.
    pub requested: bool,
}

/// The item seed of the reference runner: generation seed, offset and the first 32 bits of the id's SHA-256 modulo
/// 100,000.
pub fn item_seed(generation_seed: u64, offset: u64, id: &str) -> u64 {
    let digest = Sha256::digest(id.as_bytes());
    let head = u64::from(u32::from_be_bytes([
        digest[0], digest[1], digest[2], digest[3],
    ]));
    generation_seed + offset + head % 100_000
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// The profile: its configuration, the loop and the brain snapshot.
pub struct StemProfile {
    cfg: Arc<StemConfig>,
    harness: Harness,
    checks: Arc<dyn checks::Checks>,
    brain: Option<Arc<MainBrain>>,
    redactor: Arc<Redactor>,
}

impl StemProfile {
    /// The profile over `engine` and `checks`; `brain` is the frozen snapshot (none: no notes).
    pub fn new(
        cfg: Arc<StemConfig>,
        engine: Arc<dyn engine::Engine>,
        checks: Arc<dyn checks::Checks>,
        brain: Option<Arc<MainBrain>>,
        redactor: Arc<Redactor>,
    ) -> Self {
        Self {
            harness: Harness::new(cfg.clone(), engine, checks.clone()),
            cfg,
            checks,
            brain,
            redactor,
        }
    }

    /// The profile of `cfg`: the vLLM engine, the tools of the model service behind `tools`, and the frozen snapshot
    /// when a class gets notes.
    pub fn build(
        cfg: Arc<StemConfig>,
        tools: Arc<dyn crate::backend::Backend>,
        redactor: Arc<Redactor>,
    ) -> Result<Self, String> {
        let engine = engine::VllmEngine::new(
            &cfg.engine_url,
            &cfg.baseline.model_id,
            cfg.harness.concurrency,
            cfg.engine_timeout,
        )
        .map_err(|e| e.to_string())?;
        let snapshot = if cfg.harness.retrieval.classes.is_empty() {
            None
        } else {
            let brain = MainBrain::open(&cfg.brain)
                .map_err(|e| format!("cannot open the STEM snapshot: {}", e.kind()))?;
            if brain.source().is_none() {
                return Err("the STEM snapshot cannot be indexed".to_owned());
            }
            Some(Arc::new(brain))
        };
        let checks = checks::RemoteChecks::new(tools, cfg.harness.solver_check.max_concurrency);
        Ok(Self::new(
            cfg,
            Arc::new(engine),
            Arc::new(checks),
            snapshot,
            redactor,
        ))
    }

    /// The configuration.
    pub fn config(&self) -> &StemConfig {
        &self.cfg
    }

    /// The record of one runner item (`laris-server stem run`): the same stage as a chat turn, without HTTP.
    pub async fn record(self: Arc<Self>, item: Map<String, Value>) -> Result<Value, StemError> {
        let mut request = ChatRequest {
            messages: Vec::new(),
            tools: Vec::new(),
            stream: true,
            laris: laris_protocol::LarisRequest::default(),
            extra: Map::new(),
        };
        request
            .laris
            .extra
            .insert(STEM_KEY.to_owned(), Value::Object(item));
        let wanted = self
            .wanted(&request, "")
            .ok_or(StemError::Tool("the item has no question"))?;
        let stream = self
            .run(wanted, Vec::new())
            .await?
            .ok_or(StemError::Tool("the item was not taken"))?;
        let chunks: Vec<_> = stream.collect().await;
        let mut record = None;
        for chunk in chunks {
            match chunk {
                Ok(c) => {
                    if let Some(r) = c.laris.and_then(|mut m| m.extra.remove(STEM_KEY)) {
                        record = Some(r);
                    }
                }
                Err(_) => return Err(StemError::Engine("the item failed")),
            }
        }
        record.ok_or(StemError::Engine("the item ended without a record"))
    }

    /// Whether the profile takes this turn (before the filter): an item in `laris.stem`, or, with entry `auto`, the
    /// first question of a conversation without attached documents. `question` is the latest user message.
    pub fn wanted(&self, request: &ChatRequest, question: &str) -> Option<Wanted> {
        if self.cfg.entry == Entry::Off {
            return None;
        }
        if let Some(Value::Object(item)) = request.laris.extra.get(STEM_KEY) {
            let question = item.get("question").and_then(Value::as_str)?.to_owned();
            let options: Vec<String> = item
                .get("options")
                .and_then(Value::as_array)
                .map(|a| {
                    a.iter()
                        .filter_map(|o| o.as_str().map(str::to_owned))
                        .collect()
                })
                .unwrap_or_default();
            let id = item
                .get("id")
                .and_then(Value::as_str)
                .map_or_else(|| hex(&Sha256::digest(question.as_bytes())), str::to_owned);
            return Some(Wanted {
                id,
                question,
                options,
                seed: item.get("seed").and_then(Value::as_u64),
                requested: true,
            });
        }
        if self.cfg.entry != Entry::Auto {
            return None;
        }
        let earlier = request
            .messages
            .iter()
            .any(|m| m.role == laris_protocol::Role::Assistant);
        if earlier || request.laris.extra.contains_key("documents") {
            return None;
        }
        let chat = &self.cfg.server.chat;
        let (question, options) =
            text::chat_item(question, &self.cfg.option_line, chat.min_options);
        Some(Wanted {
            id: hex(&Sha256::digest(question.as_bytes())),
            question,
            options,
            seed: None,
            requested: false,
        })
    }

    /// The prompt filter's outcome for `wanted`; `None` when the filter is off.
    async fn screen(&self, wanted: &Wanted) -> Result<Option<Value>, StemError> {
        if !self.cfg.harness.filter.enabled {
            return Ok(None);
        }
        self.checks
            .check(json!({"op": "screen", "question": wanted.question, "options": wanted.options}))
            .await
            .map(Some)
    }

    /// Notes and certain Claims of the frozen snapshot for `item` (question and options as the query).
    fn notes(&self, item: &Item) -> (Vec<String>, Vec<String>) {
        let Some(brain) = &self.brain else {
            return (Vec::new(), Vec::new());
        };
        let Some(source) = brain.source() else {
            return (Vec::new(), Vec::new());
        };
        let query = format!("{} {}", item.question, item.options.join(" "));
        let hits = source.passages(&query, self.cfg.harness.retrieval.k);
        let certain: Vec<String> = match (&self.cfg.admissible, brain.index()) {
            (Some(rules), Some(index)) => {
                hits.iter()
                    .filter(|p| {
                        index.notes.get(&p.source).is_some_and(|n| {
                            certain::check(&index, n, rules, Level::Sourced).is_ok()
                        })
                    })
                    .map(|p| p.text.clone())
                    .collect()
            }
            _ => Vec::new(),
        };
        (hits.into_iter().map(|p| p.text).collect(), certain)
    }

    /// Runs the turn: `None` when a chat turn does not belong to the profile (filter stop or no STEM signal), so the
    /// pipeline goes on; otherwise the answer stream. `before` are the step chunks of earlier stages.
    pub async fn run(
        self: Arc<Self>,
        wanted: Wanted,
        before: Vec<ChatResponseChunk>,
    ) -> Result<Option<ChunkStream>, StemError> {
        let started = Instant::now();
        let screened = self.screen(&wanted).await?;
        let stopped = screened
            .as_ref()
            .is_some_and(|s| s["stopped"].as_bool().unwrap_or(false));
        if !wanted.requested {
            let signal = screened
                .as_ref()
                .is_some_and(|s| s["stem_signal"].as_bool().unwrap_or(false));
            if stopped || !signal {
                return Ok(None);
            }
        }
        let mut item = Item {
            question: wanted.question.clone(),
            options: wanted.options.clone(),
        };
        if let Some(s) = &screened {
            if let Some(q) = s["question"].as_str() {
                item.question = q.to_owned();
            }
            if let Some(o) = s["options"].as_array() {
                item.options = o
                    .iter()
                    .filter_map(|v| v.as_str().map(str::to_owned))
                    .collect();
            }
        }
        let seed = wanted.seed.unwrap_or_else(|| {
            item_seed(
                self.cfg.baseline.generation_seed,
                self.cfg.harness.seed_offset,
                &wanted.id,
            )
        });
        let filter_ms = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
        let (tx, rx) = mpsc::unbounded_channel::<Result<ChatResponseChunk, StreamFailure>>();
        for c in before {
            let _ = tx.send(Ok(c));
        }
        let _ = tx.send(Ok(step_chunk(
            if stopped { "stop" } else { "ok" },
            filter_ms,
            &format!(
                "filter:{}",
                screened
                    .as_ref()
                    .and_then(|s| s["rule"].as_str().or(s["status"].as_str()))
                    .unwrap_or("off")
            ),
        )));
        let this = self.clone();
        tokio::spawn(async move {
            let work = this
                .clone()
                .answer(item, seed, wanted, screened, stopped, tx.clone());
            let beat = Duration::from_millis(this.cfg.server.heartbeat_ms.max(1));
            let mut ticker = tokio::time::interval_at(tokio::time::Instant::now() + beat, beat);
            tokio::pin!(work);
            loop {
                tokio::select! {
                    () = &mut work => break,
                    () = tx.closed() => break, // the client went away: the engine requests are dropped with `work`
                    _ = ticker.tick() => { let _ = tx.send(Ok(heartbeat())); }
                }
            }
        });
        let stream = futures_util::stream::unfold(rx, |mut rx| async move {
            rx.recv().await.map(|item| (item, rx))
        });
        Ok(Some(stream.boxed()))
    }

    async fn answer(
        self: Arc<Self>,
        item: Item,
        seed: u64,
        wanted: Wanted,
        screened: Option<Value>,
        stopped: bool,
        tx: mpsc::UnboundedSender<Result<ChatResponseChunk, StreamFailure>>,
    ) {
        let began = Instant::now();
        let mut record = Map::new();
        record.insert("id".into(), json!(wanted.id));
        record.insert("seed".into(), json!(seed));
        record.insert(
            "profile_config_sha256".into(),
            json!(self.cfg.config_sha256),
        );
        record.insert(
            "brain_snapshot_sha256".into(),
            json!(self.cfg.snapshot_sha256),
        );
        record.insert("model_id".into(), json!(self.cfg.baseline.model_id));
        if let Some(s) = &screened {
            record.insert("filter".into(), s["record"].clone());
        }
        if stopped {
            let decided = text::route(
                &item.question,
                &item.options,
                self.cfg.harness.router.numeric_option_share,
                self.cfg.harness.router.knowledge_max_question_words,
            );
            let rule = screened.as_ref().map_or(Value::Null, |s| s["rule"].clone());
            record.insert("cls".into(), json!(decided.cls));
            record.insert("rule".into(), json!(decided.rule));
            record.insert("final".into(), Value::Null);
            record.insert("final_from".into(), json!("filter_stop"));
            record.insert("steps".into(), json!([{"step": "filter", "rule": rule}]));
            let text = self.cfg.server.chat.no_answer.clone();
            finish(&tx, &text, record, 0, 0);
            return;
        }
        let decided = text::route(
            &item.question,
            &item.options,
            self.cfg.harness.router.numeric_option_share,
            self.cfg.harness.router.knowledge_max_question_words,
        );
        let (notes, certain) = if self
            .cfg
            .harness
            .retrieval
            .classes
            .iter()
            .any(|c| c == decided.cls)
        {
            let t = Instant::now();
            let found = self.notes(&item);
            let _ = tx.send(Ok(step_chunk(
                "ok",
                u64::try_from(t.elapsed().as_millis()).unwrap_or(u64::MAX),
                &format!("notes:{}", found.0.len()),
            )));
            found
        } else {
            (Vec::new(), Vec::new())
        };
        let quantities = screened.as_ref().map(|s| s["quantities"].clone());
        let steps = tx.clone();
        let last = Arc::new(std::sync::Mutex::new(Instant::now()));
        let on_step: harness::OnStep = Arc::new(move |entry: &Value| {
            let mut at = last
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let ms = u64::try_from(at.elapsed().as_millis()).unwrap_or(u64::MAX);
            *at = Instant::now();
            let _ = steps.send(Ok(step_chunk("ok", ms, &step_code(entry))));
        });
        let out = self
            .harness
            .answer(&item, seed, &notes, &certain, quantities.as_ref(), on_step)
            .await;
        let trace = match out {
            Ok(t) => t,
            Err(e) => {
                let _ = tx.send(Err(StreamFailure {
                    message: e.to_string(),
                    kind: "stem_profile".to_owned(),
                }));
                return;
            }
        };
        let chat = &self.cfg.server.chat;
        let mut said = String::new();
        if let Some(shown) = &trace.shown
            && matches!(
                trace.final_from.as_str(),
                "draft" | "vote" | "review_solver" | "review_notes"
            )
        {
            said.push_str(self.redactor.redact(text::py_strip(shown)).as_ref());
        }
        match &trace.final_answer {
            Some(answer) => {
                let from = chat
                    .from
                    .get(&trace.final_from)
                    .cloned()
                    .unwrap_or_else(|| trace.final_from.clone());
                let answer = self.redactor.redact(answer);
                let answer = if answer.chars().any(|c| chat.math_marks.contains(c)) {
                    text::fill(&chat.answer_math, &[("answer", answer.as_ref())])
                } else {
                    answer.into_owned()
                };
                said.push_str(&text::fill(
                    &chat.answer_line,
                    &[("answer", &answer), ("from", &from)],
                ));
            }
            None => said.push_str(&chat.no_answer),
        }
        let (prompt, generated) = (trace.prompt_tokens, trace.generated_tokens);
        if let Ok(Value::Object(t)) = serde_json::to_value(&trace) {
            record.extend(t);
        }
        record.insert("seconds".into(), json!(began.elapsed().as_secs_f64()));
        finish(&tx, said.trim_start(), record, prompt, generated);
    }
}

/// The step code a client shows: the step's name and its outcome, never text.
fn step_code(entry: &Value) -> String {
    let name = entry["step"].as_str().unwrap_or("step");
    let detail = match name {
        "solver" | "model_free" => entry["status"].as_str().map(str::to_owned),
        "vote" => Some(format!("{}/{}", entry["top"], entry["groups"])),
        "repair" => entry["fixes"].as_array().map(|a| {
            a.iter()
                .filter_map(Value::as_str)
                .collect::<Vec<_>>()
                .join("+")
        }),
        "notes_check" => entry["supported"].as_str().map(str::to_owned),
        "conclude" => Some(
            if entry["answered"] == true {
                "answered"
            } else {
                "none"
            }
            .to_owned(),
        ),
        "brain_only" => Some(
            if entry["answered"] == true {
                "answered"
            } else {
                "none"
            }
            .to_owned(),
        ),
        _ => {
            let mut parts = Vec::new();
            if entry["thinking"] == true {
                parts.push(format!("thinking {} tokens", entry["tokens"]));
            } else if let Some(t) = entry["tokens"].as_u64() {
                parts.push(format!("{t} tokens"));
            }
            if entry["truncated"] == true {
                parts.push("cut".to_owned());
            }
            (!parts.is_empty()).then(|| parts.join(", "))
        }
    };
    match detail {
        Some(d) if !d.is_empty() => format!("{name}:{d}"),
        _ => name.to_owned(),
    }
}

fn base_chunk() -> ChatResponseChunk {
    ChatResponseChunk {
        id: "laris-stem".to_owned(),
        object: ChunkObject::default(),
        model: String::new(),
        laris: None,
        choices: Vec::new(),
        usage: None,
        extra: Map::new(),
    }
}

/// A step event of stage `stem`.
fn step_chunk(outcome: &str, ms: u64, code: &str) -> ChatResponseChunk {
    ChatResponseChunk {
        laris: Some(LarisMeta {
            steps: vec![laris_protocol::Step {
                stage: "stem".to_owned(),
                outcome: outcome.to_owned(),
                ms,
                code: code.to_owned(),
            }],
            ..LarisMeta::default()
        }),
        ..base_chunk()
    }
}

/// An event with nothing in it, sent while a step runs so that no client or proxy takes the silence for a hang.
fn heartbeat() -> ChatResponseChunk {
    base_chunk()
}

fn finish(
    tx: &mpsc::UnboundedSender<Result<ChatResponseChunk, StreamFailure>>,
    said: &str,
    record: Map<String, Value>,
    prompt: u64,
    generated: u64,
) {
    let mut extra = Map::new();
    extra.insert(STEM_KEY.to_owned(), Value::Object(record));
    let _ = tx.send(Ok(ChatResponseChunk {
        laris: Some(LarisMeta {
            extra,
            ..LarisMeta::default()
        }),
        ..base_chunk()
    }));
    let choice = |delta: ChunkDelta, finish: Option<FinishReason>| ChunkChoice {
        index: 0,
        delta,
        finish_reason: finish,
        extra: Map::new(),
    };
    let _ = tx.send(Ok(ChatResponseChunk {
        choices: vec![choice(
            ChunkDelta {
                content: Some(said.to_owned()),
                ..ChunkDelta::default()
            },
            None,
        )],
        ..base_chunk()
    }));
    let _ = tx.send(Ok(ChatResponseChunk {
        choices: vec![choice(ChunkDelta::default(), Some(FinishReason::Stop))],
        ..base_chunk()
    }));
    let _ = tx.send(Ok(ChatResponseChunk {
        usage: Some(Usage {
            prompt_tokens: prompt,
            completion_tokens: generated,
            total_tokens: prompt + generated,
            extra: Map::new(),
        }),
        ..base_chunk()
    }));
}

#[cfg(test)]
mod tests;
