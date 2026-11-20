//! The Prefilter: deterministic answers before the model (T229, SR-M11, D48).
//!
//! A message that a fixed rule can answer — a greeting, a request for help or the version, a request to enable
//! training, an attempt to override the instructions — gets its canned text and never reaches the model. The rules
//! and the texts are the owner's policy (`.laris/prefilter.toml`, covered by the integrity lock); nothing is
//! hardcoded here. The first rule that matches wins, so a refusal is listed before a greeting.
//!
//! * [`Prefilter::check`] decides one message: [`Outcome::Answer`] or [`Outcome::Pass`].
//! * [`PrefilterModel`] is a [`Model`] that checks the latest user message before it asks the wrapped model, and
//!   sits outside [`crate::RedactingModel`]: a hit is answered from the rule's text and the conversation is not
//!   handed on, redacted or not.
//! * Each hit is reported to a [`HitSink`] as a [`Hit`]: the rule, its kind, the length and the SHA-256 of the
//!   message. The message text is not kept, since it may hold a secret. [`StoreSink`] writes the hit to the event
//!   log of a session as a `prefilter_hit` event.
//!
//! This is a text rule, not a judge of intent: a hostile message that matches no rule passes, and the shield, the
//! permission rules and the sandbox stay the limits that matter. The message is normalised (whitespace folded,
//! zero-width characters dropped) before it is matched, and a rule never sees more than `max_chars` of it.

use laris_core::{Model, ModelAnswer, ModelError, ModelRequest};
use laris_protocol::{ChatMessage, Content, Role};
use laris_store::Store;
use regex::Regex;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::Arc;

/// The kind of event a hit is stored as.
pub const HIT_EVENT: &str = "prefilter_hit";

/// A prefilter that cannot be built. The message names a rule, never a message.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum PrefilterError {
    /// The file is not valid TOML of the expected shape.
    #[error("prefilter: {0}")]
    Syntax(String),
    /// A rule is incomplete or its pattern does not compile.
    #[error("prefilter rule `{id}`: {reason}")]
    Rule {
        /// The rule's id.
        id: String,
        /// What is wrong.
        reason: String,
    },
    /// Two rules share an id.
    #[error("prefilter rule `{0}` is declared twice")]
    Duplicate(String),
    /// A text uses a `{{variable}}` the caller did not supply.
    #[error("prefilter rule `{id}` uses the undefined variable `{name}`")]
    Variable {
        /// The rule's id.
        id: String,
        /// The variable's name.
        name: String,
    },
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct File {
    version: String,
    /// Longest message, in characters, that a rule sees unless it says otherwise.
    #[serde(default = "default_max")]
    max_chars: usize,
    #[serde(default, rename = "rule")]
    rules: Vec<RuleDef>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RuleDef {
    id: String,
    kind: String,
    pattern: String,
    answer: String,
    max_chars: Option<usize>,
}

fn default_max() -> usize {
    200
}

struct Compiled {
    id: String,
    kind: String,
    regex: Regex,
    answer: String,
    max_chars: usize,
}

/// What the Prefilter decides for one message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Outcome {
    /// A rule answers; the model is not asked.
    Answer(Hit),
    /// No rule matches; the message goes on.
    Pass,
}

/// One rule that fired.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Hit {
    /// The rule's id.
    pub rule: String,
    /// The rule's kind (`greeting`, `help`, `refusal`, `injection`, ...).
    pub kind: String,
    /// The canned answer, with the policy variables filled in.
    pub text: String,
    /// Length of the message in characters.
    pub message_chars: usize,
    /// SHA-256 (hex) of the normalised message. The message itself is not kept.
    pub message_sha256: String,
}

impl Hit {
    /// The hit as the JSON an event carries.
    pub fn to_json(&self) -> serde_json::Value {
        serde_json::json!({
            "rule": self.rule,
            "kind": self.kind,
            "message_chars": self.message_chars,
            "message_sha256": self.message_sha256,
        })
    }
}

/// Where hits are recorded.
pub trait HitSink: Send + Sync {
    /// Keeps one hit.
    fn record(&self, hit: &Hit);
}

/// A sink that drops hits.
pub struct NoSink;

impl HitSink for NoSink {
    fn record(&self, _hit: &Hit) {}
}

/// A sink that writes each hit to the event log of one session.
pub struct StoreSink {
    store: Store,
    session: String,
}

impl StoreSink {
    /// Records into `session` of `store`.
    pub fn new(store: Store, session: impl Into<String>) -> Self {
        Self {
            store,
            session: session.into(),
        }
    }
}

impl HitSink for StoreSink {
    fn record(&self, hit: &Hit) {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0.0, |d| d.as_secs_f64());
        // a failed write must not turn a canned answer into an error; the answer is still correct
        let _ = self
            .store
            .append_event(&self.session, HIT_EVENT, now, &hit.to_json().to_string());
    }
}

/// The rules, compiled.
pub struct Prefilter {
    version: String,
    rules: Vec<Compiled>,
}

impl Prefilter {
    /// Builds the rules from the text of `prefilter.toml`. `variables` fill the `{{name}}` placeholders of the
    /// canned texts (`help`, `version`, ...); a placeholder with no value is an error, not an empty string.
    pub fn from_toml(
        text: &str,
        variables: &HashMap<String, String>,
    ) -> Result<Self, PrefilterError> {
        let file: File = toml::from_str(text).map_err(|e| PrefilterError::Syntax(e.to_string()))?;
        let mut rules: Vec<Compiled> = Vec::with_capacity(file.rules.len());
        for def in file.rules {
            let fail = |reason: &str| PrefilterError::Rule {
                id: def.id.clone(),
                reason: reason.to_owned(),
            };
            if def.id.trim().is_empty() || def.kind.trim().is_empty() {
                return Err(fail("id and kind are required"));
            }
            if rules.iter().any(|r| r.id == def.id) {
                return Err(PrefilterError::Duplicate(def.id));
            }
            if def.answer.trim().is_empty() {
                return Err(fail("answer must not be empty"));
            }
            let regex = Regex::new(&def.pattern).map_err(|_| fail("pattern does not compile"))?;
            let answer = fill(&def.answer, variables).map_err(|name| PrefilterError::Variable {
                id: def.id.clone(),
                name,
            })?;
            rules.push(Compiled {
                id: def.id,
                kind: def.kind,
                regex,
                answer,
                max_chars: def.max_chars.unwrap_or(file.max_chars),
            });
        }
        Ok(Self {
            version: file.version,
            rules,
        })
    }

    /// The version of the rule file.
    pub fn version(&self) -> &str {
        &self.version
    }

    /// How many rules there are.
    pub fn len(&self) -> usize {
        self.rules.len()
    }

    /// Whether there are no rules (every message passes).
    pub fn is_empty(&self) -> bool {
        self.rules.is_empty()
    }

    /// Decides `message`: the first rule that matches answers, otherwise it passes.
    pub fn check(&self, message: &str) -> Outcome {
        let normal = normalise(message);
        let chars = normal.chars().count();
        for rule in &self.rules {
            // a long message is never a greeting or a command word; only a rule that allows it sees it
            if chars <= rule.max_chars && rule.regex.is_match(&normal) {
                return Outcome::Answer(Hit {
                    rule: rule.id.clone(),
                    kind: rule.kind.clone(),
                    text: rule.answer.clone(),
                    message_chars: chars,
                    message_sha256: Sha256::digest(normal.as_bytes())
                        .iter()
                        .map(|b| format!("{b:02x}"))
                        .collect(),
                });
            }
        }
        Outcome::Pass
    }
}

/// Whitespace folded to single spaces, zero-width and control characters dropped, ends trimmed.
fn normalise(message: &str) -> String {
    let mut out = String::with_capacity(message.len());
    let mut space = false;
    for c in message.chars() {
        if matches!(c, '\u{200b}'..='\u{200f}' | '\u{2060}' | '\u{feff}') {
            continue;
        }
        if c.is_whitespace() || c.is_control() {
            space = true;
            continue;
        }
        if space && !out.is_empty() {
            out.push(' ');
        }
        space = false;
        out.push(c);
    }
    out
}

/// `text` with every `{{name}}` replaced from `variables`; the name of the first one missing is the error.
fn fill(text: &str, variables: &HashMap<String, String>) -> Result<String, String> {
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(open) = rest.find("{{") {
        out.push_str(&rest[..open]);
        let after = &rest[open + 2..];
        let Some(close) = after.find("}}") else {
            out.push_str(&rest[open..]);
            return Ok(out);
        };
        let name = after[..close].trim();
        out.push_str(variables.get(name).ok_or_else(|| name.to_owned())?);
        rest = &after[close + 2..];
    }
    out.push_str(rest);
    Ok(out)
}

/// The text of a message.
fn text_of(message: &ChatMessage) -> String {
    match &message.content {
        Some(Content::Text(t)) => t.clone(),
        Some(Content::Parts(parts)) => parts
            .iter()
            .filter_map(|p| p.get("text").and_then(|t| t.as_str()))
            .collect::<Vec<_>>()
            .join("\n"),
        None => String::new(),
    }
}

/// The message the user just sent: the last one of the conversation, when it is the user's. A conversation that
/// ends in a tool result is the loop continuing a turn the model already took, and is not checked again.
pub fn latest_user_message(messages: &[ChatMessage]) -> Option<String> {
    messages
        .last()
        .filter(|m| m.role == Role::User)
        .map(text_of)
}

/// A [`Model`] that lets the [`Prefilter`] answer first. Put it outside [`crate::RedactingModel`].
pub struct PrefilterModel<M> {
    inner: M,
    prefilter: Arc<Prefilter>,
    sink: Arc<dyn HitSink>,
}

impl<M: Model> PrefilterModel<M> {
    /// Wraps `inner`; hits go to `sink`.
    pub fn new(inner: M, prefilter: Arc<Prefilter>, sink: Arc<dyn HitSink>) -> Self {
        Self {
            inner,
            prefilter,
            sink,
        }
    }

    /// The wrapped model.
    pub fn inner(&self) -> &M {
        &self.inner
    }

    /// The wrapped model.
    pub fn inner_mut(&mut self) -> &mut M {
        &mut self.inner
    }
}

impl<M: Model> Model for PrefilterModel<M> {
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        if let Some(message) = latest_user_message(request.messages)
            && let Outcome::Answer(hit) = self.prefilter.check(&message)
        {
            self.sink.record(&hit);
            return Ok(ModelAnswer {
                text: hit.text,
                ..ModelAnswer::default()
            });
        }
        self.inner.answer(request)
    }
}
