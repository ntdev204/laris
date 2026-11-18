//! The decider seam (SR-H14, ADR-021 D38): the next step of the loop is chosen here, from the closed set of
//! [`Action`]s, given the state. [`FollowModel`] is the generation-1 policy and the only implementation in
//! programme 2: it follows what the model proposed, under the limits of the settings and a [`ToolGate`]. Programme 3
//! replaces it with the decision network; nothing else in the core changes.

use crate::action::{Action, AutoStep, Mark, Notice, NoticeKind, PlanChange};
use crate::model::ModelError;
use crate::plan::{PLAN_TOOL, StepStatus, open_steps, parse_plan, render};
use crate::session::{Pending, Session, arguments_of, call_key};
use laris_config::Catalogue;
use laris_config::settings::{Agent, PlanMode};
use serde_json::{Map, Value};
use std::time::Duration;

/// What the decider may know that is not in the session: the clock.
#[derive(Clone, Copy, Debug)]
pub struct Clock {
    /// Time since the turn started.
    pub elapsed: Duration,
}

/// Chooses the next step of the loop.
pub trait Decider {
    /// The next action, or `None` when the session waits for the user (or is closed).
    fn decide(&mut self, session: &Session, clock: &Clock) -> Option<Action>;

    /// What to do when the model asked for by [`Action::AskModel`] failed.
    fn model_failed(&mut self, session: &Session, error: &ModelError) -> Action;

    /// Whether the tool `name` is offered to the model.
    fn offers(&self, name: &str) -> bool {
        let _ = name;
        true
    }
}

/// A refusal of a tool call before it runs.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Refusal {
    /// Typed error code.
    pub code: String,
    /// Message for the model.
    pub message: String,
}

/// The policy a call passes before it runs: approvals, modes and rules (T133) and the leak guard (T135).
pub trait ToolGate {
    /// `Some` refuses the call.
    fn check(&self, name: &str, arguments: &Map<String, Value>) -> Option<Refusal>;
}

/// A gate that refuses nothing.
#[derive(Clone, Copy, Debug, Default)]
pub struct OpenGate;

impl ToolGate for OpenGate {
    fn check(&self, _name: &str, _arguments: &Map<String, Value>) -> Option<Refusal> {
        None
    }
}

/// The generation-1 policy: follow the model's proposal under limits.
///
/// Per model step it asks for an answer while steps and time remain; it clears, refuses or applies each proposed
/// tool call (the plan tool, too many calls, a tool outside the workflow, the gate, an identical repeat); it checks
/// progress after the results (a typed error or an empty answer allows a bounded replan; an error no change of
/// approach can fix is said once); and it accepts an answer only when the plan has no open step, sending the model
/// back a bounded number of times first.
pub struct FollowModel {
    agent: Agent,
    catalogue: Catalogue,
    allowed: Option<Vec<String>>,
    gate: Box<dyn ToolGate>,
}

impl FollowModel {
    /// A policy with the limits of `agent` and the messages of `catalogue`.
    pub fn new(agent: Agent, catalogue: Catalogue) -> Self {
        Self {
            agent,
            catalogue,
            allowed: None,
            gate: Box::new(OpenGate),
        }
    }

    /// Only these tools may run (a workflow's tool set); the plan tool stays available when planning is on.
    pub fn allow_only(mut self, tools: impl IntoIterator<Item = String>) -> Self {
        self.allowed = Some(tools.into_iter().collect());
        self
    }

    /// The gate every call passes.
    pub fn with_gate(mut self, gate: impl ToolGate + 'static) -> Self {
        self.gate = Box::new(gate);
        self
    }

    fn text(&self, key: &str, args: &[(&str, &str)]) -> String {
        self.catalogue
            .get(key, args)
            .unwrap_or_else(|_| key.to_owned())
    }

    fn planning(&self) -> bool {
        self.agent.plan.mode != PlanMode::Off
    }

    fn plan_required(&self, session: &Session) -> bool {
        match self.agent.plan.mode {
            PlanMode::Off => false,
            PlanMode::Always => true,
            PlanMode::Auto => {
                session.last_user_text().split_whitespace().count()
                    >= self.agent.plan.min_request_words as usize
            }
        }
    }

    /// What the model sees besides the conversation, for this call only: the plan, or the request to make one.
    fn note(&self, session: &Session) -> Option<String> {
        if !self.planning() {
            return None;
        }
        let required = self.plan_required(session);
        if session.plan().is_empty() && !required {
            return None;
        }
        let mut lines = vec![self.text("plan.header", &[])];
        if session.plan().is_empty() {
            lines.push(self.text("plan.required", &[]));
        } else {
            lines.push(render(session.plan()));
            if session.turn().leftover() && !open_steps(session.plan()).is_empty() {
                lines.push(self.text("plan.resumed", &[]));
            }
        }
        Some(lines.join("\n"))
    }

    fn stop(&self, status: &str, key: &str) -> Action {
        Action::Stop {
            status: status.to_owned(),
            notice: self.text(key, &[]),
        }
    }

    fn reject(&self, id: &str, code: &str, key: &str) -> Action {
        Action::RejectTool {
            id: id.to_owned(),
            code: code.to_owned(),
            message: self.text(key, &[]),
        }
    }

    fn tools(&self, session: &Session) -> Action {
        let calls = session.open_calls();
        // A call cleared to run whose outcome never reached the log (the process died): it may or may not have
        // run, so it is answered as interrupted instead of being run again.
        if let Some((_, call)) = calls.iter().find(|(_, c)| {
            c.id.as_deref()
                .is_some_and(|id| session.turn().is_cleared(id))
        }) {
            return self.reject(
                call.id.as_deref().unwrap_or_default(),
                "interrupted",
                "loop.interrupted",
            );
        }
        if self.planning()
            && self.plan_required(session)
            && session.plan().is_empty()
            && session.turn().resolved() == 0
        {
            let steps: Vec<AutoStep> = session
                .last_calls()
                .iter()
                .filter(|c| c.function.name != PLAN_TOOL)
                .map(|c| AutoStep {
                    id: c.id.clone().unwrap_or_default(),
                    text: self.text("plan.auto_step", &[("tool", &c.function.name)]),
                })
                .collect();
            if !steps.is_empty() {
                return Action::AutoPlan { steps };
            }
        }
        let Some((index, call)) = calls.first() else {
            return self.stop("provider_error", "loop.provider_error");
        };
        let id = call.id.as_deref().unwrap_or_default();
        let name = call.function.name.as_str();
        let arguments = arguments_of(&call.function.arguments);
        if name == PLAN_TOOL && self.planning() {
            let change = match parse_plan(
                &arguments,
                self.agent.plan.max_steps as usize,
                self.agent.plan.step_chars as usize,
            ) {
                Ok(steps) => PlanChange::Accept { steps },
                Err(reason) => PlanChange::Refuse {
                    message: self.text("plan.invalid", &[("reason", &reason)]),
                },
            };
            return Action::SetPlan {
                id: id.to_owned(),
                change,
            };
        }
        if *index >= self.agent.max_tool_calls_per_step as usize {
            return self.reject(id, "too_many_calls", "loop.too_many_calls");
        }
        if self
            .allowed
            .as_ref()
            .is_some_and(|allowed| !allowed.iter().any(|a| a == name))
        {
            return self.reject(id, "tool_not_allowed", "loop.tool_not_allowed");
        }
        if let Some(refusal) = self.gate.check(name, &arguments) {
            return Action::RejectTool {
                id: id.to_owned(),
                code: refusal.code,
                message: refusal.message,
            };
        }
        if session.turn().has_seen(&call_key(call)) {
            return self.reject(id, "cyclic_call", "loop.cyclic_call");
        }
        Action::RunTool { id: id.to_owned() }
    }

    fn reflect(&self, session: &Session) -> Action {
        let reflect = &self.agent.reflect;
        let mut marks = Vec::new();
        let mut issues = Vec::new();
        let mut permanent = Vec::new();
        for result in session.turn().results() {
            let problem = assess(&result.result, &reflect.empty_keys);
            if let Some(index) = session.turn().auto_step(&result.id) {
                marks.push(Mark {
                    index,
                    status: if problem.is_some() {
                        StepStatus::Failed
                    } else {
                        StepStatus::Done
                    },
                });
            }
            let Some((kind, code)) = problem else {
                continue;
            };
            let text = match kind {
                Problem::Error => {
                    self.text("reflect.error", &[("tool", &result.name), ("code", &code)])
                }
                Problem::Empty => self.text("reflect.empty", &[("tool", &result.name)]),
            };
            if reflect.permanent_errors.contains(&code) {
                permanent.push(text);
            } else {
                issues.push(text);
            }
        }
        let mut notices = Vec::new();
        let turn = session.turn();
        if reflect.enabled && !permanent.is_empty() && !turn.permanent_told() {
            notices.push(Notice {
                kind: NoticeKind::Permanent,
                text: self.text("reflect.permanent", &[("issues", &permanent.join("; "))]),
                issues: permanent,
            });
        }
        if reflect.enabled && !issues.is_empty() {
            if turn.replans() < reflect.max_replans {
                let left = (reflect.max_replans - turn.replans() - 1).to_string();
                notices.push(Notice {
                    kind: NoticeKind::Replan,
                    text: self.text(
                        "reflect.step_failed",
                        &[("issues", &issues.join("; ")), ("left", &left)],
                    ),
                    issues,
                });
            } else if !turn.budget_told() {
                notices.push(Notice {
                    kind: NoticeKind::BudgetOut,
                    text: self.text("reflect.budget_out", &[]),
                    issues,
                });
            }
        }
        Action::Reflect { marks, notices }
    }

    fn check(&self, session: &Session) -> Action {
        let open = if self.planning() {
            open_steps(session.plan())
        } else {
            Vec::new()
        };
        let mut warning = String::new();
        if !open.is_empty() && self.agent.reflect.enabled {
            if session.turn().completion_retries() < self.agent.reflect.completion_retries {
                return Action::Retry {
                    text: self.text("plan.incomplete", &[("open", &open.join("; "))]),
                    open,
                };
            }
            warning = format!(
                "\n\n{}",
                self.text("plan.incomplete_warning", &[("open", &open.join("; "))])
            );
        }
        Action::Finish { warning }
    }
}

impl Decider for FollowModel {
    fn decide(&mut self, session: &Session, clock: &Clock) -> Option<Action> {
        if session.is_closed() {
            return None;
        }
        let turn = session.turn();
        match session.pending() {
            Pending::Idle => None,
            Pending::Model => {
                if turn.cyclic() {
                    return Some(self.stop("cyclic", "loop.cyclic"));
                }
                if session.asked().is_some() {
                    // The process died after the decision and before the answer: ask again.
                    return Some(Action::AskModel {
                        note: session.asked_note().map(str::to_owned),
                    });
                }
                if clock.elapsed.as_secs_f64() > self.agent.time_budget_seconds {
                    return Some(self.stop("timeout", "loop.timeout"));
                }
                if turn.steps() >= self.agent.max_steps {
                    return Some(self.stop("max_steps", "loop.max_steps"));
                }
                Some(Action::AskModel {
                    note: self.note(session),
                })
            }
            Pending::Tools(_) | Pending::Reflect if turn.cyclic() => {
                Some(self.stop("cyclic", "loop.cyclic"))
            }
            Pending::Tools(_) => Some(self.tools(session)),
            Pending::Reflect => Some(self.reflect(session)),
            Pending::Check => Some(self.check(session)),
        }
    }

    fn model_failed(&mut self, _session: &Session, _error: &ModelError) -> Action {
        self.stop("provider_error", "loop.provider_error")
    }

    fn offers(&self, name: &str) -> bool {
        if name == PLAN_TOOL {
            return self.planning();
        }
        self.allowed
            .as_ref()
            .is_none_or(|allowed| allowed.iter().any(|a| a == name))
    }
}

enum Problem {
    Error,
    Empty,
}

/// `None` when the step made progress, else the kind of problem and its code (empty for an empty answer).
///
/// A result is a problem when it is a typed error or an empty answer to a question (`hits: []`, `passages: 0`).
/// The check is deterministic; the model decides what to do about it.
fn assess(result: &Value, empty_keys: &[String]) -> Option<(Problem, String)> {
    let object = result.as_object()?;
    if let Some(Value::Object(error)) = object.get("error") {
        let code = error
            .get("code")
            .and_then(Value::as_str)
            .unwrap_or("error")
            .to_owned();
        return Some((Problem::Error, code));
    }
    for key in empty_keys {
        if let Some(value) = object.get(key) {
            let empty = match value {
                Value::Array(a) => a.is_empty(),
                Value::Object(o) => o.is_empty(),
                Value::Number(n) => n.as_f64() == Some(0.0),
                _ => false,
            };
            return empty.then(|| (Problem::Empty, String::new()));
        }
    }
    None
}
