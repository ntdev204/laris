//! Stage 5 of the pipeline: the rule decider behind the server's decision seam (T241, ADR-025 section 4, D54).
//!
//! The decider is the rule decider of `laris-brain` (ADR-024 section 7). The decision network is **not** here and a
//! setting cannot turn it on: it is not promoted (T171). The decider reads measured signals (coverage of the question
//! by accepted Claims, their levels, open Conflicts) and the loop counters of the turn the client reports in
//! `laris.turn`. The server is stateless between requests, so those counters are *inputs*: each is clamped to the
//! server's own hard caps, and none can skip a stage or widen the legal set (TM-35).
//!
//! Of the closed action set the server pipeline acts on `answer`, `abstain`, `ask_user`, `retrieve`, `ask_advisor` and
//! `stop`. `run_tool` is a proposal the model makes and the client decides on, and `acquire` and `verify` are remote
//! tools (T165): the server never decides them, so the signals this stage reads carry no proposed call, no
//! acquisition and no pending candidate.
//!
//! Each decision is a [`Choice`]: the action, the rule that fired, the reason and the signals read. The rule id and the
//! action go to the step event and the audit row; the signals stay out of both.

use crate::config::ConfigError;
use laris_brain::answer::{self, AnswerSettings};
use laris_brain::decide::{Act, Choice, RuleDecider, RuleSettings, Signals};
use laris_vault::VaultIndex;
use laris_vault::brain::Level;
use serde_json::{Map, Value};
use std::collections::HashMap;

/// Settings of the decider stage (`LARIS_SERVER__DECIDER_*`). Nothing has a default: set `ENABLED` and every other
/// value is required, so a threshold is never an unnoticed constant.
#[derive(Debug, Clone, PartialEq)]
pub struct DeciderConfig {
    /// Thresholds of the rule decider.
    pub rules: RuleSettings,
    /// Assembly of an answer from Claims; its source classes (`LARIS_SERVER__DECIDER_ADMISSIBLE_SOURCES`, a JSON
    /// file, required) make only certain Claims count for coverage and the answer (T285).
    pub answer: AnswerSettings,
    /// Steps one turn may take; the client's count is clamped to it.
    pub max_steps: u32,
    /// Seconds one turn may take; the client's figure is clamped to it.
    pub max_seconds: f64,
    /// Answer from accepted Claims without calling the model when the decider chooses `answer`
    /// (`LARIS_SERVER__PIPELINE_COMPOSE_WITHOUT_MODEL`, `true` or `false`, default `false`).
    pub compose_without_model: bool,
}

impl DeciderConfig {
    /// Reads the settings; `None` unless `LARIS_SERVER__DECIDER_ENABLED` is `true`.
    pub fn from_env(env: &HashMap<String, String>) -> Result<Option<Self>, ConfigError> {
        let get = |name: &str| env.get(name).map(|v| v.trim()).filter(|v| !v.is_empty());
        match get("LARIS_SERVER__DECIDER_ENABLED") {
            None | Some("false") => return Ok(None),
            Some("true") => {}
            Some(_) => {
                return Err(ConfigError::Invalid {
                    name: "LARIS_SERVER__DECIDER_ENABLED",
                    reason: "expected true or false",
                });
            }
        }
        // the decision network is not promoted (T171): no setting turns it on
        if get("LARIS_SERVER__DECIDER_NETWORK").is_some() {
            return Err(ConfigError::Invalid {
                name: "LARIS_SERVER__DECIDER_NETWORK",
                reason: "the decision network is not promoted and cannot be enabled here",
            });
        }
        let text = |name: &'static str| get(name).ok_or(ConfigError::Missing(name));
        let invalid =
            |name: &'static str, reason: &'static str| ConfigError::Invalid { name, reason };
        let ratio = |name: &'static str| -> Result<f64, ConfigError> {
            match text(name)?.parse::<f64>() {
                Ok(v) if (0.0..=1.0).contains(&v) => Ok(v),
                _ => Err(invalid(name, "expected a number from 0 to 1")),
            }
        };
        let count = |name: &'static str| -> Result<u32, ConfigError> {
            match text(name)?.parse::<u32>() {
                Ok(v) if v >= 1 => Ok(v),
                _ => Err(invalid(name, "expected a whole number in range")),
            }
        };
        let level = |name: &'static str| -> Result<Level, ConfigError> {
            match Level::parse(text(name)?) {
                Some(l) if l != Level::Candidate => Ok(l),
                _ => Err(invalid(
                    name,
                    "expected sourced, corroborated, verified or reviewed",
                )),
            }
        };
        let seconds = match text("LARIS_SERVER__DECIDER_MAX_SECONDS")?.parse::<f64>() {
            Ok(v) if v > 0.0 && v.is_finite() => v,
            _ => {
                return Err(invalid(
                    "LARIS_SERVER__DECIDER_MAX_SECONDS",
                    "expected a positive number",
                ));
            }
        };
        // the source classes a brain-only answer needs (T285): a file, so the lists are configuration, not code
        let admissible = laris_brain::certain::Admissibility::load(std::path::Path::new(text(
            "LARIS_SERVER__DECIDER_ADMISSIBLE_SOURCES",
        )?))
        .map_err(|_| {
            invalid(
                "LARIS_SERVER__DECIDER_ADMISSIBLE_SOURCES",
                "expected a readable JSON file with valid source classes",
            )
        })?;
        let compose = match get("LARIS_SERVER__PIPELINE_COMPOSE_WITHOUT_MODEL") {
            None | Some("false") => false,
            Some("true") => true,
            Some(_) => {
                return Err(invalid(
                    "LARIS_SERVER__PIPELINE_COMPOSE_WITHOUT_MODEL",
                    "expected true or false",
                ));
            }
        };
        Ok(Some(Self {
            rules: RuleSettings {
                required_level: level("LARIS_SERVER__DECIDER_REQUIRED_LEVEL")?,
                min_coverage: ratio("LARIS_SERVER__DECIDER_MIN_COVERAGE")?,
                max_retrievals: count("LARIS_SERVER__DECIDER_MAX_RETRIEVALS")?,
                max_acquisitions: 0,
                max_advisor_asks: count("LARIS_SERVER__DECIDER_MAX_ADVISOR_ASKS")?,
                max_repeats: count("LARIS_SERVER__DECIDER_MAX_REPEATS")?,
            },
            answer: AnswerSettings {
                min_cover: ratio("LARIS_SERVER__DECIDER_ANSWER_MIN_COVER")?,
                min_level: level("LARIS_SERVER__DECIDER_ANSWER_MIN_LEVEL")?,
                max_notes: count("LARIS_SERVER__DECIDER_ANSWER_MAX_NOTES")? as usize,
                admissible: Some(std::sync::Arc::new(admissible)),
            },
            max_steps: count("LARIS_SERVER__DECIDER_MAX_STEPS")?,
            max_seconds: seconds,
            compose_without_model: compose,
        }))
    }
}

/// What the client says about the turn so far (`laris.turn`). Inputs only: see the module notes.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct TurnCounters {
    /// Steps the loop has taken.
    pub steps_used: u32,
    /// Seconds the turn has run.
    pub seconds_used: f64,
    /// Times in a row the loop chose the same action.
    pub repeats: u32,
    /// Advisor calls made so far in the turn.
    pub advisor_asks: u32,
    /// Share of the client's budget left (0 to 1).
    pub budget_left: f64,
}

impl Default for TurnCounters {
    fn default() -> Self {
        Self {
            steps_used: 0,
            seconds_used: 0.0,
            repeats: 0,
            advisor_asks: 0,
            budget_left: 1.0,
        }
    }
}

impl TurnCounters {
    /// Reads `turn` from the `laris` block of a request. A field of the wrong kind counts as absent.
    pub fn from_request(extra: &Map<String, Value>) -> Self {
        let mut counters = Self::default();
        let Some(turn) = extra.get("turn").and_then(Value::as_object) else {
            return counters;
        };
        let whole = |k: &str| {
            turn.get(k)
                .and_then(Value::as_u64)
                .map(|n| u32::try_from(n).unwrap_or(u32::MAX))
        };
        let number = |k: &str| {
            turn.get(k)
                .and_then(Value::as_f64)
                .filter(|v| v.is_finite())
        };
        counters.steps_used = whole("steps_used").unwrap_or(0);
        counters.repeats = whole("repeats").unwrap_or(0);
        counters.advisor_asks = whole("advisor_asks").unwrap_or(0);
        counters.seconds_used = number("seconds_used").unwrap_or(0.0).max(0.0);
        counters.budget_left = number("budget_left").unwrap_or(1.0).clamp(0.0, 1.0);
        counters
    }
}

/// What the pipeline does after the decision.
#[derive(Debug, Clone, PartialEq)]
pub enum Verdict {
    /// Go on to the model (stages 6 and 7).
    Continue,
    /// The turn ends here with this text (the owner's sentence).
    End(String),
    /// The answer is composed from accepted Claims (the text and the Claims it rests on, `origin: server`); the model is
    /// not called.
    Compose(String, Vec<laris_protocol::ServerEvidence>),
}

/// One decision of the stage.
#[derive(Debug, Clone)]
pub struct Decision {
    /// The rule decider's choice, with its signals.
    pub choice: Choice,
    /// What the pipeline does.
    pub verdict: Verdict,
}

impl Decision {
    /// `action:rule`, the reason code of the step.
    pub fn code(&self) -> String {
        format!("{}:{}", self.choice.act.as_str(), self.choice.rule)
    }
}

/// The owner's sentences for the decisions that end a turn (`.laris/harness.toml`).
#[derive(Debug, Clone)]
pub struct DeciderTexts {
    /// The abstention.
    pub abstain: String,
    /// The sentence of a stop.
    pub stop: String,
    /// The sentence of a request for more from the user.
    pub ask_user: String,
}

/// Decides the turn for `question`.
///
/// * `index` is the main brain as of the last write.
/// * `passages_found` says whether retrieval found anything the model could be shown.
/// * `grounding_required` makes "no evidence" final: with neither accepted Claims nor passages the advisor is not an
///   option, so the rules abstain.
/// * `texts` are the owner's sentences for the decisions that end the turn.
pub fn decide(
    config: &DeciderConfig,
    index: &VaultIndex,
    question: &str,
    passages_found: bool,
    grounding_required: bool,
    turn: &TurnCounters,
    texts: &DeciderTexts,
) -> Decision {
    // the client's figures, clamped to what this server allows
    let steps_used = turn.steps_used.min(config.max_steps);
    let seconds_used = turn.seconds_used.min(config.max_seconds);
    let mut signals = Signals::empty(
        config.max_steps - steps_used,
        config.max_seconds - seconds_used,
    );
    signals.retrievals = 1; // stage 4 was the retrieval of this turn
    signals.advisor_asks = turn.advisor_asks.min(config.rules.max_advisor_asks);
    signals.repeats = turn.repeats;
    signals.budget_left = turn.budget_left;
    let mut signals = signals.measure(index, question, &config.answer, config.rules.required_level);
    // `verify` and `acquire` are not decided here, and a held-back candidate is not a reason to stop answering
    signals.below_required = 0;
    if grounding_required && !passages_found {
        signals.advisor_asks = config.rules.max_advisor_asks;
    }
    let choice = RuleDecider::new(config.rules).decide(&signals);
    let verdict = match choice.act {
        Act::Stop => Verdict::End(texts.stop.clone()),
        Act::AskUser => Verdict::End(texts.ask_user.clone()),
        Act::Abstain => Verdict::End(texts.abstain.clone()),
        Act::Answer if config.compose_without_model => {
            let composed = answer::compose(index, question, &config.answer);
            if composed.abstained() {
                Verdict::Continue
            } else {
                Verdict::Compose(composed.render(index), claims_cited(index, &composed))
            }
        }
        _ => Verdict::Continue,
    };
    Decision { choice, verdict }
}

/// The Claims a composed answer cites, as evidence entries: the note, its level and the span of its Source the Claim
/// quotes (the span properties the write gate checked).
fn claims_cited(
    index: &VaultIndex,
    answer: &answer::Answer,
) -> Vec<laris_protocol::ServerEvidence> {
    let mut seen = std::collections::BTreeSet::new();
    answer
        .sentences
        .iter()
        .filter(|s| s.kind == answer::SentenceKind::Claim)
        .filter_map(|s| s.cites.first())
        .filter_map(|c| index.find(&laris_vault::note::link_name(c)))
        .filter(|n| seen.insert(n.path.clone()))
        .map(|n| {
            let prop = |name: &str| n.prop(name).map(|v| v.py_str()).unwrap_or_default();
            laris_protocol::ServerEvidence {
                id: n.path.clone(),
                origin: "server".to_owned(),
                level: prop("level"),
                title: n.title.clone(),
                start: prop("span_start").parse().unwrap_or(0),
                end: prop("span_end").parse().unwrap_or(0),
                sha256: prop("span_sha256"),
            }
        })
        .collect()
}
