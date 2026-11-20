//! The closed action set, the measured signals and the rule decider v0 (SR-K5, ADR-024 sections 5 and 7).
//!
//! The decider chooses among [`Act`]s from [`Signals`]: numbers and categories the system measured, never free text and
//! never the advisor's own stated confidence. [`legal`] builds the candidate list; every decider (the rules here, the
//! network of T169) returns one of its members, so it cannot emit an action that is not allowed. The policy gate still
//! runs after the choice, so a decider cannot widen what the system may do.
//!
//! [`RuleDecider`] is deterministic and ordered. Its thresholds are [`RuleSettings`], filled by the caller (there is
//! no default). Every [`Choice`] keeps the signals it read, the candidates, the rule that fired and the reason, and
//! can be written as one JSON line, so each choice is traceable to its signals (SR-K5).

use std::collections::BTreeSet;

use laris_vault::brain::Level;
use laris_vault::index::VaultIndex;
use serde_json::{Value, json};

use crate::answer::{self, AnswerSettings, prop};
use crate::text;

/// The closed set of actions (ADR-024 5.1). It changes only by amending the ADR.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Act {
    /// Search the main brain and the project vault.
    Retrieve,
    /// Ask the advisor for a proposal (plan, claim, tool call).
    AskAdvisor,
    /// Run the advisor's proposed tool call (policy and sandbox still apply).
    RunTool,
    /// Search and fetch a source document.
    Acquire,
    /// Verify a candidate Claim against its Source.
    Verify,
    /// Assemble the answer from accepted Claims.
    Answer,
    /// Ask a clarifying question.
    AskUser,
    /// State that the question cannot be answered from accepted Claims.
    Abstain,
    /// End the turn.
    Stop,
}

impl Act {
    /// Every action, in the fixed order used for features and traces.
    pub const ALL: [Act; 9] = [
        Act::Retrieve,
        Act::AskAdvisor,
        Act::RunTool,
        Act::Acquire,
        Act::Verify,
        Act::Answer,
        Act::AskUser,
        Act::Abstain,
        Act::Stop,
    ];

    /// The name used in logs and datasets.
    pub fn as_str(self) -> &'static str {
        match self {
            Act::Retrieve => "retrieve",
            Act::AskAdvisor => "ask_advisor",
            Act::RunTool => "run_tool",
            Act::Acquire => "acquire",
            Act::Verify => "verify",
            Act::Answer => "answer",
            Act::AskUser => "ask_user",
            Act::Abstain => "abstain",
            Act::Stop => "stop",
        }
    }

    /// The action named `name`, if any.
    pub fn parse(name: &str) -> Option<Act> {
        Act::ALL.into_iter().find(|a| a.as_str() == name)
    }
}

/// What the loop knows about the advisor's proposed tool call.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CallState {
    /// No call is proposed.
    None,
    /// A call is proposed and the policy checks pass.
    Legal,
    /// A call is proposed and the policy refuses it.
    Refused,
}

impl CallState {
    fn as_str(self) -> &'static str {
        match self {
            CallState::None => "none",
            CallState::Legal => "legal",
            CallState::Refused => "refused",
        }
    }
}

/// The measured state a decision reads. Every field is computed by the system.
#[derive(Debug, Clone, PartialEq)]
pub struct Signals {
    /// Name of the missing required slot of the request, when a closed test found one.
    pub missing_slot: Option<String>,
    /// Share of the question's content words found in accepted notes at the required level (0 to 1).
    pub coverage: f64,
    /// The highest level among the accepted notes that match the question.
    pub best_level: Option<Level>,
    /// Accepted notes that match the question (any level from `sourced`).
    pub accepted: usize,
    /// Accepted notes that match the question but sit below the required level.
    pub below_required: usize,
    /// Proposals of the advisor in this turn that no check has verified yet.
    pub pending_candidates: usize,
    /// Open Conflicts that touch the matching notes.
    pub open_conflicts: usize,
    /// Sources retracted or superseded under matching notes in this turn.
    pub retracted_dependencies: usize,
    /// Whether acquisition is allowed by policy and configuration.
    pub acquisition_allowed: bool,
    /// Retrievals done in this turn.
    pub retrievals: u32,
    /// Acquisitions done in this turn.
    pub acquisitions: u32,
    /// Advisor calls made in this turn.
    pub advisor_asks: u32,
    /// Something was stored since the last retrieval.
    pub fresh_since_retrieve: bool,
    /// The advisor's proposed call.
    pub call: CallState,
    /// How many times in a row the last action was chosen.
    pub repeats: u32,
    /// Steps left in the turn.
    pub steps_left: u32,
    /// Seconds left in the turn.
    pub time_left_seconds: f64,
    /// Share of the money or token budget left (0 to 1).
    pub budget_left: f64,
}

impl Signals {
    /// Signals with nothing known: no coverage, nothing pending, full budget. A starting point for callers.
    pub fn empty(steps_left: u32, time_left_seconds: f64) -> Signals {
        Signals {
            missing_slot: None,
            coverage: 0.0,
            best_level: None,
            accepted: 0,
            below_required: 0,
            pending_candidates: 0,
            open_conflicts: 0,
            retracted_dependencies: 0,
            acquisition_allowed: false,
            retrievals: 0,
            acquisitions: 0,
            advisor_asks: 0,
            fresh_since_retrieve: false,
            call: CallState::None,
            repeats: 0,
            steps_left,
            time_left_seconds,
            budget_left: 1.0,
        }
    }

    /// Fills the brain-side signals (coverage, levels, conflicts) from the vault for `question`. The loop-side
    /// signals keep the values they had.
    #[must_use]
    pub fn measure(
        mut self,
        index: &VaultIndex,
        question: &str,
        answer: &AnswerSettings,
        required: Level,
    ) -> Signals {
        let used = answer::matching(index, question, answer);
        let level_of = |n: &laris_vault::note::Note| {
            if prop(n, "type") == "theory" {
                Level::Sourced
            } else {
                Level::parse(&prop(n, "level")).unwrap_or(Level::Candidate)
            }
        };
        self.accepted = used.len();
        self.best_level = used.iter().map(|n| level_of(n)).max();
        self.below_required = used.iter().filter(|n| level_of(n) < required).count();
        let covering: Vec<&&laris_vault::note::Note> =
            used.iter().filter(|n| level_of(n) >= required).collect();
        let wanted = text::facts(question).content;
        let held: BTreeSet<String> = covering
            .iter()
            .flat_map(|n| text::facts(&n.body).content)
            .collect();
        self.coverage = if wanted.is_empty() {
            0.0
        } else {
            wanted.iter().filter(|w| held.contains(*w)).count() as f64 / wanted.len() as f64
        };
        self.open_conflicts = answer::open_conflicts(index, &used).len();
        self
    }

    /// The signals as JSON, for the decision log and the dataset.
    pub fn to_json(&self) -> Value {
        json!({
            "missing_slot": self.missing_slot,
            "coverage": self.coverage,
            "best_level": self.best_level.map(Level::as_str),
            "accepted": self.accepted,
            "below_required": self.below_required,
            "pending_candidates": self.pending_candidates,
            "open_conflicts": self.open_conflicts,
            "retracted_dependencies": self.retracted_dependencies,
            "acquisition_allowed": self.acquisition_allowed,
            "retrievals": self.retrievals,
            "acquisitions": self.acquisitions,
            "advisor_asks": self.advisor_asks,
            "fresh_since_retrieve": self.fresh_since_retrieve,
            "call": self.call.as_str(),
            "repeats": self.repeats,
            "steps_left": self.steps_left,
            "time_left_seconds": self.time_left_seconds,
            "budget_left": self.budget_left,
        })
    }
}

/// Thresholds of the rule decider. They are configuration; there is no default.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RuleSettings {
    /// The level a Claim must have for an answer.
    pub required_level: Level,
    /// The share of the question that accepted notes must cover for an answer (0 to 1).
    pub min_coverage: f64,
    /// Retrievals allowed in one turn.
    pub max_retrievals: u32,
    /// Acquisitions allowed in one turn.
    pub max_acquisitions: u32,
    /// Advisor calls allowed in one turn.
    pub max_advisor_asks: u32,
    /// The same action chosen this many times in a row is a cycle.
    pub max_repeats: u32,
}

/// Why the turn must end.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Limit {
    /// The budget is spent.
    Budget,
    /// The time is spent.
    Time,
    /// No steps are left.
    Steps,
    /// The same action keeps being chosen.
    Cycle,
}

impl Limit {
    /// The name used in logs and as the stop status.
    pub fn as_str(self) -> &'static str {
        match self {
            Limit::Budget => "budget",
            Limit::Time => "time",
            Limit::Steps => "max_steps",
            Limit::Cycle => "cyclic",
        }
    }
}

/// The hard limit that holds in `signals`, if any (ADR-024 rule 1).
pub fn hard_limit(signals: &Signals, settings: &RuleSettings) -> Option<Limit> {
    if signals.budget_left <= 0.0 {
        Some(Limit::Budget)
    } else if signals.time_left_seconds <= 0.0 {
        Some(Limit::Time)
    } else if signals.steps_left == 0 {
        Some(Limit::Steps)
    } else if signals.repeats >= settings.max_repeats {
        Some(Limit::Cycle)
    } else {
        None
    }
}

/// The candidates: every action that is legal in `signals` (ADR-024 5.2), in the order of [`Act::ALL`].
pub fn legal(signals: &Signals, settings: &RuleSettings) -> Vec<Act> {
    Act::ALL
        .into_iter()
        .filter(|a| match a {
            Act::Retrieve => signals.retrievals < settings.max_retrievals,
            Act::AskAdvisor => signals.advisor_asks < settings.max_advisor_asks,
            Act::RunTool => signals.call == CallState::Legal,
            Act::Acquire => {
                signals.acquisition_allowed && signals.acquisitions < settings.max_acquisitions
            }
            Act::Verify => signals.pending_candidates > 0 || signals.below_required > 0,
            Act::Answer => signals.accepted > 0,
            Act::AskUser | Act::Abstain | Act::Stop => true,
        })
        .collect()
}

/// The rules, in the order they are tried. A decision names one of them.
pub const RULES: [&str; 10] = [
    "R1-limit",
    "R2-missing-slot",
    "R3-covered",
    "R3-covered-conflict",
    "R4-verify",
    "R5-retrieve-new",
    "R5-acquire",
    "R7-run-tool",
    "R7-ask-advisor",
    "R6-abstain",
];

/// One choice, with everything that explains it.
#[derive(Debug, Clone, PartialEq)]
pub struct Choice {
    /// The chosen action; always a member of `candidates`.
    pub act: Act,
    /// The rule that fired (a member of [`RULES`]) or `network` or `fallback`.
    pub rule: String,
    /// The rule in words, with the numbers that triggered it.
    pub reason: String,
    /// The hard limit, when the rule was a stop.
    pub limit: Option<Limit>,
    /// The signals read.
    pub signals: Signals,
    /// The legal actions.
    pub candidates: Vec<Act>,
    /// The calibrated confidence, when a network chose; the rules have none.
    pub confidence: Option<f64>,
}

impl Choice {
    /// The decision as one JSON object for the decision log.
    pub fn to_json(&self) -> Value {
        json!({
            "action": self.act.as_str(),
            "rule": self.rule,
            "reason": self.reason,
            "limit": self.limit.map(Limit::as_str),
            "candidates": self.candidates.iter().map(|a| a.as_str()).collect::<Vec<_>>(),
            "confidence": self.confidence,
            "signals": self.signals.to_json(),
        })
    }
}

/// Chooses the next action from signals. The rule decider and the network (T169) both implement it.
pub trait Chooser {
    /// The choice. It must be a member of [`legal`] for the same signals.
    fn choose(&mut self, signals: &Signals) -> Choice;
}

/// The deterministic cold-start decider (ADR-024 section 7).
#[derive(Debug, Clone, Copy)]
pub struct RuleDecider {
    settings: RuleSettings,
}

impl RuleDecider {
    /// A decider with `settings`.
    pub fn new(settings: RuleSettings) -> RuleDecider {
        RuleDecider { settings }
    }

    /// The settings.
    pub fn settings(&self) -> RuleSettings {
        self.settings
    }

    /// The cautious action the network falls back to when its confidence is below threshold: the rule decider's own
    /// choice, never the advisor's proposal.
    pub fn decide(&self, s: &Signals) -> Choice {
        let candidates = legal(s, &self.settings);
        let pick = |act: Act, rule: &str, reason: String, limit: Option<Limit>| {
            debug_assert!(RULES.contains(&rule));
            debug_assert!(candidates.contains(&act), "{act:?} is not legal");
            Choice {
                act,
                rule: rule.to_owned(),
                reason,
                limit,
                signals: s.clone(),
                candidates: candidates.clone(),
                confidence: None,
            }
        };
        let cfg = &self.settings;
        // 1. a hard limit holds
        if let Some(limit) = hard_limit(s, cfg) {
            return pick(
                Act::Stop,
                "R1-limit",
                format!("hard limit: {}", limit.as_str()),
                Some(limit),
            );
        }
        // 2. the question is unclear by a closed test
        if let Some(slot) = &s.missing_slot {
            return pick(
                Act::AskUser,
                "R2-missing-slot",
                format!("required slot '{slot}' is missing"),
                None,
            );
        }
        // 3. accepted notes cover the question at the required level
        let covered = s.accepted > 0
            && s.coverage >= cfg.min_coverage
            && s.best_level.is_some_and(|l| l >= cfg.required_level);
        if covered {
            return if s.open_conflicts == 0 {
                pick(
                    Act::Answer,
                    "R3-covered",
                    format!(
                        "coverage {:.2} >= {:.2}, no open conflict",
                        s.coverage, cfg.min_coverage
                    ),
                    None,
                )
            } else {
                // the composer states each open Conflict with both sides; the answer is not hidden behind it
                pick(
                    Act::Answer,
                    "R3-covered-conflict",
                    format!(
                        "coverage {:.2} >= {:.2}; {} open conflict(s) are presented, not resolved",
                        s.coverage, cfg.min_coverage, s.open_conflicts
                    ),
                    None,
                )
            };
        }
        // 4. a candidate or a note below the required level stands in the way
        if candidates.contains(&Act::Verify) {
            return pick(
                Act::Verify,
                "R4-verify",
                format!(
                    "{} pending candidate(s), {} note(s) below the required level",
                    s.pending_candidates, s.below_required
                ),
                None,
            );
        }
        // 5. not enough coverage: read what was stored last, else acquire
        if s.fresh_since_retrieve && candidates.contains(&Act::Retrieve) {
            return pick(
                Act::Retrieve,
                "R5-retrieve-new",
                "a source was stored since the last retrieval".to_owned(),
                None,
            );
        }
        if candidates.contains(&Act::Acquire) {
            return pick(
                Act::Acquire,
                "R5-acquire",
                format!(
                    "coverage {:.2} < {:.2} and acquisition is allowed",
                    s.coverage, cfg.min_coverage
                ),
                None,
            );
        }
        // 7. the advisor proposes; its call runs only if legal
        if candidates.contains(&Act::RunTool) {
            return pick(
                Act::RunTool,
                "R7-run-tool",
                "the advisor's call passes the policy checks".to_owned(),
                None,
            );
        }
        if candidates.contains(&Act::AskAdvisor) {
            return pick(
                Act::AskAdvisor,
                "R7-ask-advisor",
                format!(
                    "{} of {} advisor calls used",
                    s.advisor_asks, cfg.max_advisor_asks
                ),
                None,
            );
        }
        // 6. nothing else is legal: say so
        pick(
            Act::Abstain,
            "R6-abstain",
            format!(
                "coverage {:.2} < {:.2} and no legal way to get more evidence",
                s.coverage, cfg.min_coverage
            ),
            None,
        )
    }
}

impl Chooser for RuleDecider {
    fn choose(&mut self, signals: &Signals) -> Choice {
        self.decide(signals)
    }
}
