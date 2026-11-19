//! The loop: asks the decider for the next action, records it, and only then does what it permits.
//!
//! The model is called only after a recorded `ask_model` decision and a tool is run only after a recorded
//! `run_tool` decision (the fold refuses an answer or an outcome that no decision cleared), so what the loop does
//! is exactly what the log says, and [`crate::replay`] can check it without the decider.

use crate::action::Action;
use crate::decider::{Clock, Decider};
use crate::error::CoreError;
use crate::model::{Model, ModelRequest};
use crate::record::{ModelAnswer, Record};
use crate::recorder::Recorder;
use crate::session::{Session, arguments_of};
use laris_protocol::{Command, Event, ToolSchema};
use serde_json::{Map, Value};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Instant;

/// Runs a tool call. The tool registry of T132 is the real one; failures are returned as the typed error
/// `{"error": {"code", "message"}}`, never raised.
pub trait ToolRunner {
    /// Runs `name` with `arguments` and returns its result.
    fn run(&mut self, name: &str, arguments: &Map<String, Value>) -> Value;
}

/// Receives every event the moment it is produced.
type Sink = Box<dyn FnMut(&Event)>;

/// One session being driven.
pub struct Driver<M: Model, R: ToolRunner, D: Decider> {
    recorder: Recorder,
    model: M,
    tools: R,
    decider: D,
    schemas: Vec<ToolSchema>,
    started: Instant,
    interrupt: Arc<AtomicBool>,
    now: Box<dyn Fn() -> f64>,
    sink: Option<Sink>,
}

impl<M: Model, R: ToolRunner, D: Decider> Driver<M, R, D> {
    /// Drives `recorder` with `model`, `tools` and `decider`. `schemas` are the tools offered to the model; `now`
    /// gives the time written on each record.
    pub fn new(
        recorder: Recorder,
        model: M,
        tools: R,
        decider: D,
        schemas: Vec<ToolSchema>,
        now: impl Fn() -> f64 + 'static,
    ) -> Self {
        Self {
            recorder,
            model,
            tools,
            decider,
            schemas,
            started: Instant::now(),
            interrupt: Arc::new(AtomicBool::new(false)),
            now: Box::new(now),
            sink: None,
        }
    }

    /// Hands every event to `sink` the moment it is produced (headless `stream-json` writes it out at once). The
    /// events are still returned, in the same order.
    #[must_use]
    pub fn with_sink(mut self, sink: impl FnMut(&Event) + 'static) -> Self {
        self.sink = Some(Box::new(sink));
        self
    }

    fn push(&mut self, all: &mut Vec<Event>, new: Vec<Event>) {
        if let Some(sink) = self.sink.as_mut() {
            new.iter().for_each(sink);
        }
        all.extend(new);
    }

    /// Uses `flag` as the interrupt handle, so a front end that owns the flag can set it from another thread.
    #[must_use]
    pub fn with_interrupt_flag(mut self, flag: Arc<AtomicBool>) -> Self {
        self.interrupt = flag;
        self
    }

    /// The handle that ends the running turn: set it from anywhere; the loop notices before its next action.
    pub fn interrupt_handle(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.interrupt)
    }

    /// The state.
    pub fn session(&self) -> &Session {
        self.recorder.session()
    }

    /// The recorder (and through it the log).
    pub fn recorder(&self) -> &Recorder {
        &self.recorder
    }

    /// The model (a [`crate::ScriptedModel`] keeps what it was asked).
    pub fn model(&self) -> &M {
        &self.model
    }

    /// The tool runner.
    pub fn tools(&self) -> &R {
        &self.tools
    }

    /// Takes a user message and runs the turn until the session waits for the user again. Returns every event
    /// produced, in order.
    pub fn send(&mut self, text: &str) -> Result<Vec<Event>, CoreError> {
        let command = Record::Command {
            command: Command::UserMessage {
                text: text.to_owned(),
                attachments: Vec::new(),
            },
        };
        let first = self.recorder.record(command, (self.now)())?;
        let mut events = Vec::new();
        self.push(&mut events, first);
        self.started = Instant::now();
        events.extend(self.run()?);
        Ok(events)
    }

    /// Ends the running turn: open tool calls are answered as interrupted, so the conversation stays valid.
    pub fn interrupt(&mut self) -> Result<Vec<Event>, CoreError> {
        let events = self.recorder.record(
            Record::Command {
                command: Command::Interrupt {},
            },
            (self.now)(),
        )?;
        let mut out = Vec::new();
        self.push(&mut out, events);
        Ok(out)
    }

    /// Continues the turn the session is in (after a resume), until it waits for the user.
    pub fn run(&mut self) -> Result<Vec<Event>, CoreError> {
        let mut events = Vec::new();
        loop {
            if self.interrupt.swap(false, Ordering::SeqCst) {
                events.extend(self.interrupt()?);
                break;
            }
            let clock = Clock {
                elapsed: self.started.elapsed(),
            };
            let Some(action) = self.decider.decide(self.recorder.session(), &clock) else {
                break;
            };
            let decided = self.recorder.record(
                Record::Decision {
                    action: action.clone(),
                },
                (self.now)(),
            )?;
            self.push(&mut events, decided);
            let next = match action {
                Action::AskModel { note } => self.ask(note.as_deref())?,
                Action::RunTool { id } => self.run_tool(&id)?,
                _ => Vec::new(),
            };
            self.push(&mut events, next);
        }
        Ok(events)
    }

    fn ask(&mut self, note: Option<&str>) -> Result<Vec<Event>, CoreError> {
        let offered: Vec<ToolSchema> = self
            .schemas
            .iter()
            .filter(|t| self.decider.offers(&t.function.name))
            .cloned()
            .collect();
        let request = ModelRequest {
            messages: self.recorder.session().messages(),
            note,
            tools: &offered,
        };
        let digest = self.recorder.session().digest();
        match self.model.answer(&request) {
            Ok(answer) => self.recorder.record(
                Record::ModelAnswer {
                    request_digest: digest,
                    answer: ModelAnswer { ..answer },
                },
                (self.now)(),
            ),
            Err(error) => {
                let action = self.decider.model_failed(self.recorder.session(), &error);
                self.recorder
                    .record(Record::Decision { action }, (self.now)())
            }
        }
    }

    fn run_tool(&mut self, id: &str) -> Result<Vec<Event>, CoreError> {
        let Some(call) = self
            .recorder
            .session()
            .last_calls()
            .iter()
            .find(|c| c.id.as_deref() == Some(id))
            .cloned()
        else {
            return Err(CoreError::Unexpected(format!("no tool call {id}")));
        };
        let result = self
            .tools
            .run(&call.function.name, &arguments_of(&call.function.arguments));
        self.recorder.record(
            Record::ToolOutcome {
                id: id.to_owned(),
                name: call.function.name,
                result,
            },
            (self.now)(),
        )
    }
}
