//! Redaction: credentials are hidden before text leaves the machine or is kept (SR-H10; threat TM-17).
//!
//! [`Redactor`] knows the shapes of common credentials (private key blocks, cloud and forge tokens, JWTs, bearer
//! headers, passwords in URLs, `secret = value` assignments) and the exact values of secrets this process holds.
//! It is applied in three places: to what `Write`, `Edit` and `save_memory` persist ([`Redactor::for_tools`]), to
//! every tool result before the loop logs it and the model reads it ([`crate::ShieldedRunner`]), and to the whole
//! conversation just before a request leaves for the model service ([`RedactingModel`]).
//!
//! Redaction is a filter, not a proof: a secret in a shape nobody listed passes. The files tools refuse by name
//! (`tools.deniedFiles`) are the first line; this is the second.

use laris_core::{Model, ModelAnswer, ModelError, ModelRequest};
use laris_protocol::ChatMessage;
use regex::{Captures, Regex};
use serde_json::Value;
use std::borrow::Cow;
use std::sync::Arc;

/// What replaces a secret.
pub const MASK: &str = "[REDACTED]";

/// Shortest literal secret that is replaced by value; shorter ones would hide ordinary words.
const MIN_LITERAL: usize = 8;

/// A name that marks an environment variable as holding a secret.
const SECRET_NAME_WORDS: [&str; 8] = [
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "PASSPHRASE",
    "CREDENTIAL",
    "AUTH",
];

enum Rule {
    /// The whole match is replaced.
    Whole(Regex),
    /// Group 1 stays, group 2 stays, group 3 (the value) is replaced.
    Value(Regex),
    /// Group 1 stays, the rest of the match is replaced.
    Prefix(Regex),
    /// A password in a URL: `scheme://user:` stays, the password goes, `@` stays.
    Url(Regex),
}

/// Hides credentials in text and in JSON.
pub struct Redactor {
    rules: Vec<Rule>,
    literals: Vec<String>,
}

impl Default for Redactor {
    fn default() -> Self {
        Self::standard()
    }
}

fn re(pattern: &str) -> Regex {
    Regex::new(pattern).expect("the built-in redaction patterns are valid")
}

impl Redactor {
    /// The built-in shapes and no literal secrets.
    pub fn standard() -> Self {
        let rules = vec![
            // a private key block, or the start of one that was cut short
            Rule::Whole(re(
                r"(?s)-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\z)",
            )),
            Rule::Whole(re(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA)[0-9A-Z]{16}\b")),
            Rule::Whole(re(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
            Rule::Whole(re(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
            Rule::Whole(re(r"\bglpat-[A-Za-z0-9_\-]{20,}")),
            Rule::Whole(re(r"\bsk-[A-Za-z0-9_\-]{16,}")),
            Rule::Whole(re(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
            Rule::Whole(re(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
            Rule::Whole(re(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
            Rule::Whole(re(
                r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b",
            )),
            Rule::Prefix(re(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=\-]{16,}")),
            Rule::Url(re(r"(?i)\b([a-z][a-z0-9+.\-]*://[^/\s:@]+:)[^/\s@]+(@)")),
            Rule::Value(re(
                r#"(?i)\b([A-Za-z0-9_.\-]*(?:api[_\-]?key|secret|token|passwd|password|passphrase|credential|private[_\-]?key|auth[_\-]?key)[A-Za-z0-9_.\-]*)(["']?\s*[:=]\s*["']?)([^\s"'`,;&}\]]{6,})"#,
            )),
        ];
        Self {
            rules,
            literals: Vec::new(),
        }
    }

    /// Also replaces each of `secrets` wherever it appears. Values shorter than eight characters are ignored.
    #[must_use]
    pub fn with_secrets(mut self, secrets: impl IntoIterator<Item = String>) -> Self {
        for secret in secrets {
            let secret = secret.trim().to_owned();
            if secret.chars().count() >= MIN_LITERAL && !self.literals.contains(&secret) {
                self.literals.push(secret);
            }
        }
        // longer first, so a secret that contains another one is replaced whole
        self.literals.sort_by_key(|s| std::cmp::Reverse(s.len()));
        self
    }

    /// Also replaces the values of the variables among `vars` whose name says they hold a secret (`*_KEY`,
    /// `*_TOKEN`, `*SECRET*`, `*PASSWORD*`, ...).
    #[must_use]
    pub fn with_env_secrets(self, vars: impl IntoIterator<Item = (String, String)>) -> Self {
        let secrets: Vec<String> = vars
            .into_iter()
            .filter(|(name, _)| is_secret_name(name))
            .map(|(_, value)| value)
            .collect();
        self.with_secrets(secrets)
    }

    /// The standard shapes plus the secrets held in this process's environment.
    pub fn from_process_env() -> Self {
        Self::standard().with_env_secrets(std::env::vars())
    }

    /// `text` with every credential replaced by [`MASK`]. Text without one is returned as it is.
    pub fn redact<'a>(&self, text: &'a str) -> Cow<'a, str> {
        let mut out = Cow::Borrowed(text);
        for secret in &self.literals {
            if out.contains(secret.as_str()) {
                out = Cow::Owned(out.replace(secret.as_str(), MASK));
            }
        }
        for rule in &self.rules {
            let next = match rule {
                Rule::Whole(r) => r.replace_all(&out, MASK),
                Rule::Value(r) => r.replace_all(&out, |c: &Captures| {
                    // do not mask twice, and keep a value that is already hidden
                    if c[3].contains(MASK) || c[3].starts_with("[REDACT") {
                        c[0].to_owned()
                    } else {
                        format!("{}{}{MASK}", &c[1], &c[2])
                    }
                }),
                Rule::Prefix(r) => r.replace_all(&out, |c: &Captures| format!("{}{MASK}", &c[1])),
                Rule::Url(r) => {
                    r.replace_all(&out, |c: &Captures| format!("{}{MASK}{}", &c[1], &c[2]))
                }
            };
            if let Cow::Owned(changed) = next {
                out = Cow::Owned(changed);
            }
        }
        out
    }

    /// Whether `text` holds anything [`Redactor::redact`] would hide.
    pub fn finds(&self, text: &str) -> bool {
        matches!(self.redact(text), Cow::Owned(_))
    }

    /// `value` with every string inside redacted (keys are kept).
    pub fn redact_value(&self, value: &Value) -> Value {
        match value {
            Value::String(s) => Value::String(self.redact(s).into_owned()),
            Value::Array(items) => {
                Value::Array(items.iter().map(|v| self.redact_value(v)).collect())
            }
            Value::Object(map) => Value::Object(
                map.iter()
                    .map(|(k, v)| (k.clone(), self.redact_value(v)))
                    .collect(),
            ),
            other => other.clone(),
        }
    }

    /// The form the file tools take (`Context::with_redactor`).
    pub fn for_tools(self: &Arc<Self>) -> laris_tools::Redactor {
        let me = Arc::clone(self);
        Box::new(move |text| me.redact(text).into_owned())
    }
}

fn is_secret_name(name: &str) -> bool {
    let upper = name.to_ascii_uppercase();
    SECRET_NAME_WORDS.iter().any(|word| upper.contains(word))
}

/// A [`Model`] that redacts the conversation before the wrapped model sees it. The loop keeps its own copy of the
/// conversation and its digest; only the request that leaves the machine is changed.
pub struct RedactingModel<M> {
    inner: M,
    redactor: Arc<Redactor>,
}

impl<M: Model> RedactingModel<M> {
    /// Wraps `inner`.
    pub fn new(inner: M, redactor: Arc<Redactor>) -> Self {
        Self { inner, redactor }
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

impl<M: Model> Model for RedactingModel<M> {
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        let messages: Vec<ChatMessage> = request
            .messages
            .iter()
            .map(|message| {
                serde_json::to_value(message)
                    .ok()
                    .map(|v| self.redactor.redact_value(&v))
                    .and_then(|v| serde_json::from_value(v).ok())
                    // a message that cannot be round-tripped is not sent: never fall back to the original
                    .ok_or_else(|| ModelError::Failed("a message could not be redacted".to_owned()))
            })
            .collect::<Result<_, _>>()?;
        let note = request.note.map(|n| self.redactor.redact(n).into_owned());
        let redacted = ModelRequest {
            messages: &messages,
            note: note.as_deref(),
            tools: request.tools,
        };
        self.inner.answer(&redacted)
    }
}
