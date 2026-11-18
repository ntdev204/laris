//! Session state: a pure fold of input records.

use crate::error::CoreError;
use crate::model::digest_of;
use crate::record::{ModelAnswer, Record};
use laris_protocol::{ChatMessage, Command, Content, Event, Role, ToolCall};
use serde_json::{Map, Value};

/// What the session waits for.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Pending {
    /// Nothing: the next input is a user message.
    Idle,
    /// The model has to answer the conversation.
    Model,
    /// Tool calls (their ids, in order) have to be answered.
    Tools(Vec<String>),
}

/// The state of one session, rebuilt from its log.
#[derive(Clone, Debug, PartialEq)]
pub struct Session {
    messages: Vec<ChatMessage>,
    pending: Pending,
    turns: u32,
    closed: bool,
}

impl Default for Session {
    fn default() -> Self {
        Self::new()
    }
}

impl Session {
    /// An empty session.
    pub fn new() -> Self {
        Self {
            messages: Vec::new(),
            pending: Pending::Idle,
            turns: 0,
            closed: false,
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

    /// SHA-256 of the conversation: what a model answer is bound to.
    pub fn digest(&self) -> String {
        digest_of(&self.messages)
    }

    /// Applies one input record and returns the events it produces. On `Err` the state is unchanged.
    ///
    /// Login, permission answers, slash commands, mode changes and completions do not change the conversation; the
    /// loop of T131 and the harness give them their effect.
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
            Record::ModelAnswer { answer, .. } => self.model_answer(answer),
            Record::ToolOutcome { id, name, result } => self.tool_outcome(id, name, result),
        }
    }

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
                Vec::new()
            }
            Command::Interrupt {} => {
                if self.pending == Pending::Idle {
                    return Vec::new();
                }
                self.pending = Pending::Idle;
                vec![Event::Done {
                    status: "interrupted".to_owned(),
                    answer: String::new(),
                }]
            }
            Command::Shutdown {} => {
                self.closed = true;
                Vec::new()
            }
            _ => Vec::new(),
        }
    }

    fn model_answer(&mut self, answer: &ModelAnswer) -> Result<Vec<Event>, CoreError> {
        if self.pending != Pending::Model {
            return Err(CoreError::Unexpected(
                "a model answer arrived while the model was not asked".to_owned(),
            ));
        }
        let calls: Vec<ToolCall> = answer
            .tool_calls
            .iter()
            .enumerate()
            .map(|(i, call)| {
                let mut call = call.clone();
                call.id
                    .get_or_insert_with(|| format!("call_{}_{}", self.turns, i + 1));
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
        let mut events = Vec::new();
        if !answer.text.is_empty() {
            events.push(Event::Text {
                delta: answer.text.clone(),
            });
        }
        for call in &calls {
            events.push(Event::ToolCall {
                id: call.id.clone().unwrap_or_default(),
                name: call.function.name.clone(),
                arguments: arguments_of(&call.function.arguments),
            });
        }
        if calls.is_empty() {
            self.pending = Pending::Idle;
            events.push(Event::Done {
                status: "completed".to_owned(),
                answer: answer.text.clone(),
            });
        } else {
            self.pending = Pending::Tools(calls.iter().filter_map(|c| c.id.clone()).collect());
        }
        Ok(events)
    }

    fn tool_outcome(
        &mut self,
        id: &str,
        name: &str,
        result: &Value,
    ) -> Result<Vec<Event>, CoreError> {
        let Pending::Tools(open) = &mut self.pending else {
            return Err(CoreError::Unexpected(format!(
                "tool outcome {id} arrived while no tool was called"
            )));
        };
        let Some(at) = open.iter().position(|o| o == id) else {
            return Err(CoreError::Unexpected(format!("no open tool call {id}")));
        };
        open.remove(at);
        let all_answered = open.is_empty();
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
        if all_answered {
            self.pending = Pending::Model;
        }
        Ok(vec![Event::ToolResult {
            id: id.to_owned(),
            name: name.to_owned(),
            result: result.clone(),
        }])
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

fn arguments_of(json: &str) -> Map<String, Value> {
    match serde_json::from_str::<Value>(json) {
        Ok(Value::Object(map)) => map,
        _ => Map::new(),
    }
}
