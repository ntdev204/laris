//! Session state: a pure fold of input records.

use crate::action::{Action, AutoStep, Mark, Notice, NoticeKind, PlanChange};
use crate::error::CoreError;
use crate::model::digest_of;
use crate::plan::{PLAN_TOOL, PlanStep, StepStatus, failed_steps, open_steps, plan_event};
use crate::record::{ModelAnswer, Record};
use laris_protocol::{ChatMessage, Command, Content, Event, Role, ToolCall};
use serde_json::{Map, Value, json};

/// What the session waits for.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Pending {
    /// Nothing: the next input is a user message.
    Idle,
    /// The model has to answer the conversation (after a decision to ask it).
    Model,
    /// Tool calls (their ids, in order) have to be answered.
    Tools(Vec<String>),
    /// Every tool call of the step is answered; the loop closes the step (progress check).
    Reflect,
    /// The model answered without tool calls; the loop checks the goal and accepts or sends the model back.
    Check,
}

/// The result of one tool call of the current model step, as the progress check reads it.
#[derive(Clone, Debug, PartialEq)]
pub struct StepResult {
    /// Call id.
    pub id: String,
    /// Tool name.
    pub name: String,
    /// What the call came to.
    pub result: Value,
}

/// Counters and marks of the turn that is running. They are part of the fold, so the decider reads them from the
/// state and replay rebuilds them.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Turn {
    steps: u32,
    replans: u32,
    completion_retries: u32,
    budget_told: bool,
    permanent_told: bool,
    repeats: u32,
    leftover: bool,
    asked: Option<Option<String>>,
    cleared: Vec<String>,
    seen: Vec<String>,
    auto: Vec<(String, usize)>,
    results: Vec<StepResult>,
    resolved: u32,
}

impl Turn {
    /// Model calls decided in this turn.
    pub fn steps(&self) -> u32 {
        self.steps
    }

    /// Replans spent.
    pub fn replans(&self) -> u32 {
        self.replans
    }

    /// Times the model was sent back to finish an open goal.
    pub fn completion_retries(&self) -> u32 {
        self.completion_retries
    }

    /// Whether the model was told once that replans are used up.
    pub fn budget_told(&self) -> bool {
        self.budget_told
    }

    /// Whether the model was told once that a failure is permanent.
    pub fn permanent_told(&self) -> bool {
        self.permanent_told
    }

    /// Identical calls refused so far in this turn.
    pub fn repeats(&self) -> u32 {
        self.repeats
    }

    /// Whether the plan is one carried over from an earlier turn that this turn has not touched.
    pub fn leftover(&self) -> bool {
        self.leftover
    }

    /// Results of the tool calls of the current model step (plan changes excluded).
    pub fn results(&self) -> &[StepResult] {
        &self.results
    }

    /// Calls of the current step that were answered.
    pub fn resolved(&self) -> u32 {
        self.resolved
    }

    /// Whether the call `id` was cleared to run (and has no outcome yet when it is still open).
    pub fn is_cleared(&self, id: &str) -> bool {
        self.cleared.iter().any(|c| c == id)
    }

    /// Whether this call was already run in the turn.
    pub fn has_seen(&self, key: &str) -> bool {
        self.seen.iter().any(|s| s == key)
    }

    /// The plan position of the step the loop made for the call `id`.
    pub fn auto_step(&self, id: &str) -> Option<usize> {
        self.auto.iter().find(|(c, _)| c == id).map(|(_, i)| *i)
    }
}

/// The state of one session, rebuilt from its log.
#[derive(Clone, Debug, PartialEq)]
pub struct Session {
    messages: Vec<ChatMessage>,
    pending: Pending,
    turns: u32,
    closed: bool,
    plan: Vec<PlanStep>,
    turn: Turn,
}

impl Default for Session {
    fn default() -> Self {
        Self::new()
    }
}

/// The key two calls share when they are the same call: the name and the arguments in a canonical form.
pub fn call_key(call: &ToolCall) -> String {
    let arguments = serde_json::from_str::<Value>(&call.function.arguments)
        .map(|v| v.to_string())
        .unwrap_or_else(|_| call.function.arguments.clone());
    format!("{}\u{0}{arguments}", call.function.name)
}

impl Session {
    /// An empty session.
    pub fn new() -> Self {
        Self {
            messages: Vec::new(),
            pending: Pending::Idle,
            turns: 0,
            closed: false,
            plan: Vec::new(),
            turn: Turn::default(),
        }
    }

    /// The conversation so far.
    pub fn messages(&self) -> &[ChatMessage] {
        &self.messages
    }

    /// What the session waits for.
    pub fn pending(&self) -> &Pending {
        &self.pending
    }

    /// User messages received.
    pub fn turns(&self) -> u32 {
        self.turns
    }

    /// Whether `shutdown` was received.
    pub fn is_closed(&self) -> bool {
        self.closed
    }

    /// The plan.
    pub fn plan(&self) -> &[PlanStep] {
        &self.plan
    }

    /// Counters of the turn that is running (or ran last).
    pub fn turn(&self) -> &Turn {
        &self.turn
    }

    /// Whether the model was cleared to answer: `Some(note)` after an `ask_model` decision.
    pub fn asked(&self) -> Option<&Option<String>> {
        self.turn.asked.as_ref()
    }

    /// The note of the decision that cleared the model, if any.
    pub fn asked_note(&self) -> Option<&str> {
        self.turn.asked.as_ref().and_then(|n| n.as_deref())
    }

    /// The text of the last user message.
    pub fn last_user_text(&self) -> &str {
        self.messages
            .iter()
            .rev()
            .find(|m| m.role == Role::User)
            .and_then(|m| match &m.content {
                Some(Content::Text(t)) => Some(t.as_str()),
                _ => None,
            })
            .unwrap_or("")
    }

    /// The tool calls of the last assistant message, with their position, that are still open.
    pub fn open_calls(&self) -> Vec<(usize, &ToolCall)> {
        let Pending::Tools(open) = &self.pending else {
            return Vec::new();
        };
        self.last_calls()
            .iter()
            .enumerate()
            .filter(|(_, c)| c.id.as_ref().is_some_and(|id| open.contains(id)))
            .collect()
    }

    /// All the calls of the last assistant message.
    pub fn last_calls(&self) -> &[ToolCall] {
        self.messages
            .iter()
            .rev()
            .find(|m| m.role == Role::Assistant)
            .map_or(&[], |m| &m.tool_calls[..])
    }

    /// SHA-256 of the conversation: what a model answer is bound to.
    pub fn digest(&self) -> String {
        digest_of(&self.messages)
    }

    /// Applies one input record and returns the events it produces. On `Err` the state is unchanged.
    pub fn apply(&mut self, input: &Record) -> Result<Vec<Event>, CoreError> {
        let mut next = self.clone();
        let events = next.step(input)?;
        *self = next;
        Ok(events)
    }

    fn step(&mut self, input: &Record) -> Result<Vec<Event>, CoreError> {
        match input {
            Record::Emitted { .. } => Err(CoreError::NotInput),
            Record::Command { command } => Ok(self.command(command)),
            Record::Decision { action } => self.decision(action),
            Record::ModelAnswer { answer, .. } => self.model_answer(answer),
            Record::ToolOutcome { id, name, result } => self.tool_outcome(id, name, result),
        }
    }

    // -- commands ------------------------------------------------------------------------------

    fn command(&mut self, command: &Command) -> Vec<Event> {
        match command {
            Command::UserMessage { text, .. } => {
                if self.pending != Pending::Idle {
                    return vec![Event::Error {
                        code: "busy".to_owned(),
                        message: "a turn is already running".to_owned(),
                    }];
                }
                self.messages.push(message(Role::User, text.clone()));
                self.turns += 1;
                self.pending = Pending::Model;
                self.turn = Turn {
                    leftover: !open_steps(&self.plan).is_empty(),
                    ..Turn::default()
                };
                if self.turn.leftover {
                    return vec![plan_event("resumed", &self.plan)];
                }
                Vec::new()
            }
            Command::Interrupt {} => {
                if self.pending == Pending::Idle {
                    return Vec::new();
                }
                let mut events = self.seal("interrupted", "interrupted by the user");
                self.pending = Pending::Idle;
                self.turn.asked = None;
                events.push(Event::Done {
                    status: "interrupted".to_owned(),
                    answer: String::new(),
                });
                events
            }
            Command::Shutdown {} => {
                self.closed = true;
                Vec::new()
            }
            _ => Vec::new(),
        }
    }

    /// Answers every open tool call with an error, so the conversation stays valid whatever stopped the turn.
    fn seal(&mut self, code: &str, text: &str) -> Vec<Event> {
        let Pending::Tools(open) = self.pending.clone() else {
            return Vec::new();
        };
        let mut events = Vec::new();
        for id in open {
            let name = self.call_name(&id);
            let result = json!({"error": {"code": code, "message": text}});
            self.push_tool_message(&id, &name, &result);
            events.push(Event::ToolResult { id, name, result });
        }
        events
    }

    // -- decisions -----------------------------------------------------------------------------

    fn decision(&mut self, action: &Action) -> Result<Vec<Event>, CoreError> {
        match action {
            Action::AskModel { note } => {
                self.expect(Pending::Model, "ask the model")?;
                if self.turn.asked.is_none() {
                    self.turn.steps += 1;
                    self.turn.results.clear();
                    self.turn.resolved = 0;
                }
                self.turn.asked = Some(note.clone());
                Ok(Vec::new())
            }
            Action::RunTool { id } => {
                let call = self.open_call(id)?;
                if self.turn.is_cleared(id) {
                    return Err(CoreError::Unexpected(format!(
                        "tool call {id} was already cleared"
                    )));
                }
                self.turn.seen.push(call_key(&call));
                self.turn.cleared.push(id.clone());
                Ok(vec![tool_call_event(&call)])
            }
            Action::RejectTool { id, code, message } => {
                let call = self.open_call(id)?;
                if code == "cyclic_call" {
                    self.turn.repeats += 1;
                }
                let result = json!({"error": {"code": code, "message": message}});
                let mut events = vec![tool_call_event(&call)];
                events.extend(self.resolve(id, &call.function.name, &result, true));
                Ok(events)
            }
            Action::SetPlan { id, change } => {
                let call = self.open_call(id)?;
                if call.function.name != PLAN_TOOL {
                    return Err(CoreError::Unexpected(format!(
                        "tool call {id} is not {PLAN_TOOL}"
                    )));
                }
                self.turn.leftover = false;
                let mut events = vec![tool_call_event(&call)];
                match change {
                    PlanChange::Accept { steps } => {
                        self.plan = steps.clone();
                        let result = json!({"plan": steps});
                        events.extend(self.resolve(id, PLAN_TOOL, &result, false));
                        events.push(plan_event("model", &self.plan));
                    }
                    PlanChange::Refuse { message } => {
                        let result = json!({"error": {"code": "invalid_plan", "message": message}});
                        events.extend(self.resolve(id, PLAN_TOOL, &result, false));
                    }
                }
                Ok(events)
            }
            Action::AutoPlan { steps } => {
                if !matches!(self.pending, Pending::Tools(_)) {
                    return Err(CoreError::Unexpected(
                        "a plan of the loop's own needs open tool calls".to_owned(),
                    ));
                }
                for AutoStep { id, text } in steps {
                    self.open_call(id)?;
                    self.plan.push(PlanStep {
                        text: text.clone(),
                        status: StepStatus::InProgress,
                    });
                    self.turn.auto.push((id.clone(), self.plan.len() - 1));
                }
                self.turn.leftover = false;
                Ok(vec![plan_event("auto", &self.plan)])
            }
            Action::Reflect { marks, notices } => {
                self.expect(Pending::Reflect, "close a step")?;
                for Mark { index, status } in marks {
                    if let Some(step) = self.plan.get_mut(*index) {
                        step.status = *status;
                    }
                }
                let mut events = Vec::new();
                for notice in notices {
                    events.push(self.notice(notice));
                }
                self.pending = Pending::Model;
                self.turn.asked = None;
                Ok(events)
            }
            Action::Retry { text, open } => {
                self.expect(Pending::Check, "send the model back")?;
                self.messages.push(message(Role::User, text.clone()));
                self.turn.completion_retries += 1;
                self.pending = Pending::Model;
                self.turn.asked = None;
                Ok(vec![Event::Goal {
                    complete: false,
                    open: open.iter().cloned().map(Value::from).collect(),
                    failed: Vec::new(),
                    retry: true,
                }])
            }
            Action::Finish { warning } => {
                self.expect(Pending::Check, "accept the answer")?;
                let mut events = Vec::new();
                if !warning.is_empty() {
                    if let Some(last) = self.messages.last_mut() {
                        let text = match &last.content {
                            Some(Content::Text(t)) => format!("{t}{warning}"),
                            _ => warning.clone(),
                        };
                        last.content = Some(Content::Text(text));
                    }
                    events.push(Event::Text {
                        delta: warning.clone(),
                    });
                }
                let answer = match self.messages.last().and_then(|m| m.content.as_ref()) {
                    Some(Content::Text(t)) => t.clone(),
                    _ => String::new(),
                };
                events.extend(self.goal_event());
                events.push(Event::Done {
                    status: "completed".to_owned(),
                    answer,
                });
                self.pending = Pending::Idle;
                self.turn.asked = None;
                Ok(events)
            }
            Action::Stop { status, notice } => {
                if self.pending == Pending::Idle {
                    return Err(CoreError::Unexpected("no turn to stop".to_owned()));
                }
                let mut events = self.seal("stopped", "the turn was stopped before this call ran");
                self.messages.push(message(Role::Assistant, notice.clone()));
                events.extend(self.goal_event());
                events.push(Event::Done {
                    status: status.clone(),
                    answer: notice.clone(),
                });
                self.pending = Pending::Idle;
                self.turn.asked = None;
                Ok(events)
            }
        }
    }

    fn expect(&self, phase: Pending, what: &str) -> Result<(), CoreError> {
        if self.pending == phase {
            Ok(())
        } else {
            Err(CoreError::Unexpected(format!(
                "cannot {what} while the session waits for {:?}",
                self.pending
            )))
        }
    }

    fn open_call(&self, id: &str) -> Result<ToolCall, CoreError> {
        let Pending::Tools(open) = &self.pending else {
            return Err(CoreError::Unexpected(format!(
                "tool call {id} while no tool was called"
            )));
        };
        if !open.iter().any(|o| o == id) {
            return Err(CoreError::Unexpected(format!("no open tool call {id}")));
        }
        self.last_calls()
            .iter()
            .find(|c| c.id.as_deref() == Some(id))
            .cloned()
            .ok_or_else(|| CoreError::Unexpected(format!("no open tool call {id}")))
    }

    fn call_name(&self, id: &str) -> String {
        self.last_calls()
            .iter()
            .find(|c| c.id.as_deref() == Some(id))
            .map(|c| c.function.name.clone())
            .unwrap_or_default()
    }

    fn goal_event(&self) -> Option<Event> {
        if self.plan.is_empty() {
            return None;
        }
        let open = open_steps(&self.plan);
        Some(Event::Goal {
            complete: open.is_empty(),
            open: open.into_iter().map(Value::from).collect(),
            failed: failed_steps(&self.plan)
                .into_iter()
                .map(Value::from)
                .collect(),
            retry: false,
        })
    }

    fn notice(&mut self, notice: &Notice) -> Event {
        self.messages.push(message(Role::User, notice.text.clone()));
        let mut data = Map::new();
        data.insert("issues".to_owned(), Value::from(notice.issues.clone()));
        match notice.kind {
            NoticeKind::Replan => {
                self.turn.replans += 1;
                data.insert("replans".to_owned(), Value::from(self.turn.replans));
            }
            NoticeKind::BudgetOut => {
                self.turn.budget_told = true;
                data.insert("budget_out".to_owned(), Value::from(true));
            }
            NoticeKind::Permanent => {
                self.turn.permanent_told = true;
                data.insert("permanent".to_owned(), Value::from(true));
            }
        }
        Event::Status {
            kind: "reflect".to_owned(),
            data,
        }
    }

    // -- model and tools -----------------------------------------------------------------------

    fn model_answer(&mut self, answer: &ModelAnswer) -> Result<Vec<Event>, CoreError> {
        if self.pending != Pending::Model || self.turn.asked.is_none() {
            return Err(CoreError::Unexpected(
                "a model answer arrived that no decision asked for".to_owned(),
            ));
        }
        let calls: Vec<ToolCall> = answer
            .tool_calls
            .iter()
            .enumerate()
            .map(|(i, call)| {
                let mut call = call.clone();
                call.id.get_or_insert_with(|| {
                    format!("call_{}_{}_{}", self.turns, self.turn.steps, i + 1)
                });
                call
            })
            .collect();
        self.messages.push(ChatMessage {
            role: Role::Assistant,
            content: (!answer.text.is_empty()).then(|| Content::Text(answer.text.clone())),
            tool_calls: calls.clone(),
            tool_call_id: None,
            name: None,
            extra: Map::new(),
        });
        self.turn.asked = None;
        let mut events = Vec::new();
        if !answer.text.is_empty() {
            events.push(Event::Text {
                delta: answer.text.clone(),
            });
        }
        self.pending = if calls.is_empty() {
            Pending::Check
        } else {
            Pending::Tools(calls.iter().filter_map(|c| c.id.clone()).collect())
        };
        Ok(events)
    }

    fn tool_outcome(
        &mut self,
        id: &str,
        name: &str,
        result: &Value,
    ) -> Result<Vec<Event>, CoreError> {
        self.open_call(id)?;
        if !self.turn.is_cleared(id) {
            return Err(CoreError::Unexpected(format!(
                "tool call {id} was not cleared to run"
            )));
        }
        Ok(self.resolve(id, name, result, true))
    }

    /// Answers the call `id` and, when it was the last open one, moves on to the progress check.
    fn resolve(&mut self, id: &str, name: &str, result: &Value, counts: bool) -> Vec<Event> {
        self.push_tool_message(id, name, result);
        if let Pending::Tools(open) = &mut self.pending {
            open.retain(|o| o != id);
            if open.is_empty() {
                self.pending = Pending::Reflect;
            }
        }
        self.turn.resolved += 1;
        if counts && name != PLAN_TOOL {
            self.turn.results.push(StepResult {
                id: id.to_owned(),
                name: name.to_owned(),
                result: result.clone(),
            });
        }
        vec![Event::ToolResult {
            id: id.to_owned(),
            name: name.to_owned(),
            result: result.clone(),
        }]
    }

    fn push_tool_message(&mut self, id: &str, name: &str, result: &Value) {
        let text = match result {
            Value::String(s) => s.clone(),
            other => other.to_string(),
        };
        self.messages.push(ChatMessage {
            role: Role::Tool,
            content: Some(Content::Text(text)),
            tool_calls: Vec::new(),
            tool_call_id: Some(id.to_owned()),
            name: Some(name.to_owned()),
            extra: Map::new(),
        });
    }
}

fn tool_call_event(call: &ToolCall) -> Event {
    Event::ToolCall {
        id: call.id.clone().unwrap_or_default(),
        name: call.function.name.clone(),
        arguments: arguments_of(&call.function.arguments),
    }
}

fn message(role: Role, text: String) -> ChatMessage {
    ChatMessage {
        role,
        content: Some(Content::Text(text)),
        tool_calls: Vec::new(),
        tool_call_id: None,
        name: None,
        extra: Map::new(),
    }
}

/// The arguments of a call as an object; anything else is an empty object.
pub fn arguments_of(json: &str) -> Map<String, Value> {
    match serde_json::from_str::<Value>(json) {
        Ok(Value::Object(map)) => map,
        _ => Map::new(),
    }
}
