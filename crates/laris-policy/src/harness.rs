//! The harness loop over the brain (T232, SR-M11, D48): prompt, draft, evidence check, retry or abstain.
//!
//! [`HarnessModel`] is a [`Model`] that answers a question from retrieved passages and from nothing else:
//!
//! 1. The user's latest message is the question. (A conversation that ends in a tool result is the loop going on with
//!    a turn already taken; it passes to the wrapped model unchanged.) Put [`crate::PrefilterModel`] outside it: a
//!    message the Prefilter answers never gets here, and a message it passes is what this loop receives.
//! 2. A [`PassageSource`] returns the best passages. Each is redacted, folded to one line (so it cannot forge a
//!    citation line) and read by the [`Shield`]: a passage that gives orders to the model is dropped and counted,
//!    never shown to it. The rest are numbered `[note path #rank]`.
//! 3. With no passage left the loop **abstains without calling the model**: there is nothing to cite.
//! 4. Otherwise the prompt is built from the owner's template (question and passages) and the model drafts an
//!    answer. The [`Gate`] checks the draft against exactly these passages: a citation that names none of them, a
//!    quote that is not in its passage, an uncited statement and an unscoped conclusion of absence are findings, and
//!    so is an answer with no citation at all. A model that answers with the configured abstain marker abstains.
//! 5. A draft with findings is sent back once per remaining attempt with the findings listed. After
//!    `max_attempts` drafts the loop abstains; the unverified draft is never returned.
//!
//! The texts of the prompt and of the abstentions, the number of passages and the number of attempts come from a
//! configuration ([`HarnessConfig::from_toml`]); nothing is hardcoded here. A turn is reported to a [`TurnSink`]
//! without the question (its length and SHA-256 only), the way the Prefilter reports a hit.
//!
//! This is a text rule over a model's draft, not a judge of meaning (see [`laris_evidence`]): a cited passage that
//! does not support the sentence passes. It does not make any model qualified.

use crate::prefilter::latest_user_message;
use crate::shield::Shield;
use laris_core::{Model, ModelAnswer, ModelError, ModelRequest};
use laris_evidence::{Evidence, Finding, Gate, Hit as EvidenceHit, citation};
use laris_protocol::{ChatMessage, Content, Role, Usage};
use laris_retrieval::{Scorer, VaultPassages};
use laris_store::Store;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::sync::Arc;

/// The kind of event a turn is stored as.
pub const TURN_EVENT: &str = "harness_turn";

/// A configuration that cannot be used.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum HarnessError {
    /// The text is not valid TOML of the expected shape.
    #[error("harness: {0}")]
    Syntax(String),
    /// A value is out of range or a template lacks its placeholder.
    #[error("harness: {0}")]
    Invalid(String),
}

/// The owner's settings of the loop. Every field is required: there are no defaults to drift from the policy.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HarnessConfig {
    /// Version of the settings file.
    pub version: String,
    /// Most passages put in a prompt.
    pub passages: usize,
    /// Most drafts per question, the first included.
    pub max_attempts: usize,
    /// A draft that starts with this text means "the passages do not answer this"; the loop abstains.
    pub abstain_marker: String,
    /// The prompt. `{{question}}` and `{{passages}}` are replaced.
    pub prompt_template: String,
    /// The message that sends a draft back. `{{findings}}` is replaced by the list of findings.
    pub retry_template: String,
    /// The answer when nothing was retrieved.
    pub abstain_no_source: String,
    /// The answer when the model says the passages do not answer.
    pub abstain_model: String,
    /// The answer when no draft passed the gate.
    pub abstain_unverified: String,
    /// What the server says when its decider stops the turn (steps, time or a cycle spent).
    pub decider_stop: String,
    /// What the server says when its decider asks the user to say more.
    pub decider_ask_user: String,
}

impl HarnessConfig {
    /// Reads the settings from the text of a TOML file.
    pub fn from_toml(text: &str) -> Result<Self, HarnessError> {
        let config: Self = toml::from_str(text).map_err(|e| HarnessError::Syntax(e.to_string()))?;
        config.validate()?;
        Ok(config)
    }

    fn validate(&self) -> Result<(), HarnessError> {
        let bad = |why: &str| Err(HarnessError::Invalid(why.to_owned()));
        if self.passages == 0 {
            return bad("passages must be at least 1");
        }
        if self.max_attempts == 0 {
            return bad("max_attempts must be at least 1");
        }
        if self.abstain_marker.trim().is_empty() {
            return bad("abstain_marker must not be empty");
        }
        if !self.prompt_template.contains("{{question}}")
            || !self.prompt_template.contains("{{passages}}")
        {
            return bad("prompt_template needs {{question}} and {{passages}}");
        }
        if !self.retry_template.contains("{{findings}}") {
            return bad("retry_template needs {{findings}}");
        }
        for (name, text) in [
            ("abstain_no_source", &self.abstain_no_source),
            ("abstain_model", &self.abstain_model),
            ("abstain_unverified", &self.abstain_unverified),
            ("decider_stop", &self.decider_stop),
            ("decider_ask_user", &self.decider_ask_user),
        ] {
            if text.trim().is_empty() {
                return Err(HarnessError::Invalid(format!("{name} must not be empty")));
            }
        }
        Ok(())
    }
}

/// One passage handed to the loop.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Passage {
    /// The source named in the citation (a note path).
    pub source: String,
    /// The text.
    pub text: String,
    /// Character offset of the text in the note body (0 when the source does not know).
    pub start: usize,
    /// Character offset after the text in the note body.
    pub end: usize,
    /// The level of the note (`sourced`, ...), or empty when the source does not know.
    pub level: String,
}

/// Where passages come from.
pub trait PassageSource {
    /// The best `limit` passages for `query`, best first.
    fn passages(&self, query: &str, limit: usize) -> Vec<Passage>;
}

/// The lexical index of a vault (T230) as a source.
pub struct VaultSource {
    index: VaultPassages,
    scorer: Scorer,
}

impl VaultSource {
    /// Searches `index` with `scorer`.
    pub fn new(index: VaultPassages, scorer: Scorer) -> Self {
        Self { index, scorer }
    }
}

impl PassageSource for VaultSource {
    fn passages(&self, query: &str, limit: usize) -> Vec<Passage> {
        self.index
            .search(query, self.scorer, limit)
            .into_iter()
            .map(|hit| Passage {
                source: hit.passage.path,
                text: hit.passage.text,
                start: hit.passage.start,
                end: hit.passage.end,
                level: String::new(),
            })
            .collect()
    }
}

/// How a turn ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Ending {
    /// A draft passed the gate and is the answer.
    Answered,
    /// No passage was retrieved; the model was not called.
    NoSource,
    /// The model said the passages do not answer.
    ModelAbstained,
    /// Every draft had findings.
    Unverified,
    /// The conversation did not end in a user message, or the model asked for a tool; passed on unchanged.
    PassedOn,
}

impl Ending {
    /// A stable code for logs.
    pub fn code(self) -> &'static str {
        match self {
            Self::Answered => "answered",
            Self::NoSource => "no_source",
            Self::ModelAbstained => "model_abstained",
            Self::Unverified => "unverified",
            Self::PassedOn => "passed_on",
        }
    }
}

/// What the loop reports about one question. The question itself is not in it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Turn {
    /// How it ended.
    pub ending: Ending,
    /// Drafts asked of the model.
    pub attempts: usize,
    /// Passages shown to the model.
    pub passages_used: usize,
    /// Passages dropped because they give orders to the model.
    pub passages_dropped: usize,
    /// The codes of the findings of each draft, in order.
    pub findings: Vec<Vec<&'static str>>,
    /// Length of the question in characters.
    pub question_chars: usize,
    /// SHA-256 (hex) of the question.
    pub question_sha256: String,
}

impl Turn {
    /// The turn as the JSON an event carries.
    pub fn to_json(&self) -> serde_json::Value {
        serde_json::json!({
            "ending": self.ending.code(),
            "attempts": self.attempts,
            "passages_used": self.passages_used,
            "passages_dropped": self.passages_dropped,
            "findings": self.findings,
            "question_chars": self.question_chars,
            "question_sha256": self.question_sha256,
        })
    }
}

/// Where turns are recorded.
pub trait TurnSink: Send + Sync {
    /// Keeps one turn.
    fn record(&self, turn: &Turn);
}

/// A sink that drops turns.
pub struct NoTurnSink;

impl TurnSink for NoTurnSink {
    fn record(&self, _turn: &Turn) {}
}

/// A sink that writes each turn to the event log of one session.
pub struct StoreTurnSink {
    store: Store,
    session: String,
}

impl StoreTurnSink {
    /// Records into `session` of `store`.
    pub fn new(store: Store, session: impl Into<String>) -> Self {
        Self {
            store,
            session: session.into(),
        }
    }
}

impl TurnSink for StoreTurnSink {
    fn record(&self, turn: &Turn) {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0.0, |d| d.as_secs_f64());
        // a failed write must not turn a correct answer into an error
        let _ =
            self.store
                .append_event(&self.session, TURN_EVENT, now, &turn.to_json().to_string());
    }
}

/// A [`Model`] that answers from passages, checks the draft and retries or abstains.
pub struct HarnessModel<M, S> {
    inner: M,
    source: S,
    shield: Arc<Shield>,
    gate: Gate,
    config: HarnessConfig,
    sink: Arc<dyn TurnSink>,
    last: Option<Turn>,
}

impl<M: Model, S: PassageSource> HarnessModel<M, S> {
    /// Wraps `inner`. The gate holds every draft to the research rules, retrieved evidence or not.
    pub fn new(
        inner: M,
        source: S,
        shield: Arc<Shield>,
        config: HarnessConfig,
        sink: Arc<dyn TurnSink>,
    ) -> Self {
        Self {
            inner,
            source,
            shield,
            gate: Gate::strict(),
            config,
            sink,
            last: None,
        }
    }

    /// The wrapped model.
    pub fn inner(&self) -> &M {
        &self.inner
    }

    /// The report of the last question.
    pub fn last_turn(&self) -> Option<&Turn> {
        self.last.as_ref()
    }

    fn finish(&mut self, turn: Turn, text: String, usage: Option<Usage>) -> ModelAnswer {
        self.sink.record(&turn);
        self.last = Some(turn);
        ModelAnswer {
            text,
            tool_calls: Vec::new(),
            usage,
        }
    }
}

fn message(role: Role, text: String) -> ChatMessage {
    ChatMessage {
        role,
        content: Some(Content::Text(text)),
        tool_calls: Vec::new(),
        tool_call_id: None,
        name: None,
        extra: serde_json::Map::new(),
    }
}

fn one_line(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn sha256(text: &str) -> String {
    Sha256::digest(text.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

fn add_usage(total: &mut Option<Usage>, more: Option<&Usage>) {
    let Some(more) = more else { return };
    let sum = total.get_or_insert_with(Usage::default);
    sum.prompt_tokens += more.prompt_tokens;
    sum.completion_tokens += more.completion_tokens;
    sum.total_tokens += more.total_tokens;
}

/// The findings as the lines the model reads.
fn describe(findings: &[Finding], cited: bool) -> String {
    let mut lines: Vec<String> = findings
        .iter()
        .map(|f| {
            let text: String = f.text.chars().take(200).collect();
            format!("- {}: {}", f.kind.code(), one_line(&text))
        })
        .collect();
    if !cited {
        lines.push("- no_citation: the answer cites no passage".to_owned());
    }
    lines.join("\n")
}

impl<M: Model, S: PassageSource> Model for HarnessModel<M, S> {
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        let Some(question) = latest_user_message(request.messages) else {
            let answer = self.inner.answer(request)?;
            self.last = Some(Turn {
                ending: Ending::PassedOn,
                attempts: 1,
                passages_used: 0,
                passages_dropped: 0,
                findings: Vec::new(),
                question_chars: 0,
                question_sha256: String::new(),
            });
            return Ok(answer);
        };
        let question_chars = question.chars().count();
        let question_sha256 = sha256(&question);

        // retrieval, then the passages the model may see
        let mut evidence = Evidence::new();
        let mut listing: Vec<String> = Vec::new();
        let mut dropped = 0usize;
        for passage in self.source.passages(&question, self.config.passages) {
            let text = one_line(&self.shield.redactor().redact(&passage.text));
            if text.is_empty() || !self.shield.orders_in(&text).is_empty() {
                dropped += 1;
                continue;
            }
            let rank = u32::try_from(listing.len() + 1).unwrap_or(u32::MAX);
            let source = one_line(&passage.source);
            listing.push(format!("[{source} #{rank}] {text}"));
            evidence.add(EvidenceHit {
                source,
                rank,
                title: String::new(),
                text,
            });
        }
        let turn = |ending, attempts, findings: Vec<Vec<&'static str>>| Turn {
            ending,
            attempts,
            passages_used: listing.len(),
            passages_dropped: dropped,
            findings,
            question_chars,
            question_sha256: question_sha256.clone(),
        };
        if listing.is_empty() {
            let text = self.config.abstain_no_source.clone();
            let t = turn(Ending::NoSource, 0, Vec::new());
            return Ok(self.finish(t, text, None));
        }

        // the prompt replaces the user's last message; the rest of the conversation stays
        let prompt = self
            .config
            .prompt_template
            .replace("{{question}}", &question)
            .replace("{{passages}}", &listing.join("\n"));
        let mut messages = request.messages.to_vec();
        if let Some(last) = messages.last_mut() {
            *last = message(Role::User, prompt);
        }

        let mut usage: Option<Usage> = None;
        let mut history: Vec<Vec<&'static str>> = Vec::new();
        let mut attempts = 0usize;
        while attempts < self.config.max_attempts {
            attempts += 1;
            let draft = self.inner.answer(&ModelRequest {
                messages: &messages,
                note: request.note,
                tools: request.tools,
            })?;
            add_usage(&mut usage, draft.usage.as_ref());
            if !draft.tool_calls.is_empty() {
                // the model reached for a tool: this is not an answer yet
                let mut pass = draft;
                pass.usage = usage;
                let t = turn(Ending::PassedOn, attempts, history);
                self.sink.record(&t);
                self.last = Some(t);
                return Ok(pass);
            }
            if draft
                .text
                .trim_start()
                .starts_with(&self.config.abstain_marker)
            {
                let text = self.config.abstain_model.clone();
                let t = turn(Ending::ModelAbstained, attempts, history);
                return Ok(self.finish(t, text, usage));
            }
            let verdict = self.gate.check(&draft.text, &evidence);
            let cited = !citation::parse(&draft.text).is_empty();
            if verdict.is_clean() && cited {
                let t = turn(Ending::Answered, attempts, history);
                return Ok(self.finish(t, draft.text, usage));
            }
            history.push(
                verdict
                    .findings
                    .iter()
                    .map(|f| f.kind.code())
                    .chain((!cited).then_some("no_citation"))
                    .collect(),
            );
            let retry = self
                .config
                .retry_template
                .replace("{{findings}}", &describe(&verdict.findings, cited));
            messages.push(message(Role::Assistant, draft.text));
            messages.push(message(Role::User, retry));
        }
        let text = self.config.abstain_unverified.clone();
        let t = turn(Ending::Unverified, attempts, history);
        Ok(self.finish(t, text, usage))
    }
}
