//! The interface's state and how it changes. It holds no tool, permission or storage logic (SR-C1): it shows what
//! the core's events say and sends the core's commands.
//!
//! [`App::update`] takes one [`Input`] (a key, a paste, a core event, a tick of the clock) and returns the commands
//! to send. [`App::layout`] draws the state at a width.

use crate::input::{InputBuffer, Key};
use crate::style::Theme;
use laris_config::Catalogue;
use laris_config::settings::Ui;
use laris_protocol::events::{ENDS_COMMAND, Mode};
use laris_protocol::{Command, Event, check_ready};
use serde_json::{Map, Value};

/// Milliseconds the "press Ctrl-C again" prompt stays armed.
pub const EXIT_WINDOW_MS: u64 = 3000;

/// What reaches the interface.
#[derive(Debug, Clone, PartialEq)]
pub enum Input {
    /// A key.
    Key(Key),
    /// Pasted text.
    Paste(String),
    /// An event of the core.
    Event(Event),
    /// The clock moved on by this many milliseconds.
    Tick(u64),
}

/// How a notice looks.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tone {
    /// Quiet.
    Dim,
    /// Worth a look.
    Warn,
    /// Something failed.
    Error,
}

/// One block of the conversation.
#[derive(Debug, Clone, PartialEq)]
pub enum Item {
    /// What the user sent.
    User(String),
    /// The answer, as far as it has come. `open` while it streams.
    Assistant {
        /// The Markdown text so far.
        text: String,
        /// Still streaming.
        open: bool,
    },
    /// A tool call and, when it came, its result.
    Tool {
        /// Id of the call.
        id: String,
        /// Tool name.
        name: String,
        /// Arguments.
        arguments: Map<String, Value>,
        /// The result.
        result: Option<Value>,
    },
    /// A line of information.
    Notice {
        /// The text.
        text: String,
        /// How it looks.
        tone: Tone,
    },
    /// The plan: (text, status) per step.
    Plan(Vec<(String, String)>),
}

/// What `ready` told.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Info {
    /// Program version.
    pub engine: String,
    /// Session id.
    pub session: String,
    /// Working folder.
    pub cwd: String,
    /// Permission mode.
    pub mode: String,
    /// Server address.
    pub server: String,
}

/// The interface.
#[derive(Debug, Clone)]
pub struct App {
    pub(crate) theme: Theme,
    pub(crate) words: Catalogue,
    pub(crate) show_status_line: bool,
    pub(crate) spinner: bool,
    pub(crate) items: Vec<Item>,
    pub(crate) input: InputBuffer,
    pub(crate) info: Option<Info>,
    pub(crate) line: Map<String, Value>,
    pub(crate) usage: Option<(u64, u64)>,
    pub(crate) queued: u64,
    pub(crate) running: bool,
    pub(crate) streamed: bool,
    pub(crate) armed_ms: Option<u64>,
    pub(crate) elapsed_ms: u64,
    pub(crate) frame: u64,
    quit: bool,
    pub(crate) blocked: bool,
}

impl App {
    /// An interface for the `ui` settings.
    pub fn new(ui: &Ui) -> Self {
        Self {
            theme: Theme::of(ui.theme),
            words: Catalogue::new(ui.language),
            show_status_line: ui.show_status_line,
            spinner: ui.spinner,
            items: Vec::new(),
            input: InputBuffer::new(),
            info: None,
            line: Map::new(),
            usage: None,
            queued: 0,
            running: false,
            streamed: false,
            armed_ms: None,
            elapsed_ms: 0,
            frame: 0,
            quit: false,
            blocked: false,
        }
    }

    /// Uses `theme` instead of the setting's (a terminal without colours).
    #[must_use]
    pub fn with_theme(mut self, theme: Theme) -> Self {
        self.theme = theme;
        self
    }

    /// The conversation.
    pub fn items(&self) -> &[Item] {
        &self.items
    }

    /// The text being typed.
    pub fn input_text(&self) -> String {
        self.input.text()
    }

    /// Whether a turn is running.
    pub fn running(&self) -> bool {
        self.running
    }

    /// Whether the user asked to leave.
    pub fn should_quit(&self) -> bool {
        self.quit
    }

    /// Whether the interface refuses to go on (the core speaks another version).
    pub fn blocked(&self) -> bool {
        self.blocked
    }

    /// What `ready` told, once it came.
    pub fn info(&self) -> Option<&Info> {
        self.info.as_ref()
    }

    pub(crate) fn text(&self, key: &str, args: &[(&str, &str)]) -> String {
        self.words.get(key, args).unwrap_or_else(|_| key.to_owned())
    }

    /// Takes one input and returns the commands for the core.
    pub fn update(&mut self, input: Input) -> Vec<Command> {
        match input {
            Input::Event(event) => {
                self.on_event(event);
                Vec::new()
            }
            Input::Key(key) => self.on_key(key),
            Input::Paste(text) => {
                if !self.blocked {
                    self.armed_ms = None;
                    self.input.insert(&text);
                }
                Vec::new()
            }
            Input::Tick(ms) => {
                self.frame = self.frame.wrapping_add(1);
                if self.running {
                    self.elapsed_ms += ms;
                }
                if let Some(armed) = self.armed_ms {
                    let armed = armed + ms;
                    self.armed_ms = (armed < EXIT_WINDOW_MS).then_some(armed);
                }
                Vec::new()
            }
        }
    }

    fn notice(&mut self, text: String, tone: Tone) {
        self.close_answer();
        self.items.push(Item::Notice { text, tone });
    }

    fn close_answer(&mut self) {
        if let Some(Item::Assistant { open, .. }) = self.items.last_mut() {
            *open = false;
        }
    }

    fn on_key(&mut self, key: Key) -> Vec<Command> {
        if self.blocked {
            if matches!(key, Key::CtrlC | Key::CtrlD) {
                self.quit = true;
            }
            return Vec::new();
        }
        let was_armed = self.armed_ms.take().is_some();
        match key {
            Key::CtrlC => {
                if !self.input.is_empty() {
                    self.input.clear();
                } else if was_armed {
                    self.quit = true;
                    return vec![Command::Shutdown {}];
                } else {
                    self.armed_ms = Some(0);
                }
                Vec::new()
            }
            Key::CtrlD => {
                if self.input.is_empty() {
                    self.quit = true;
                    return vec![Command::Shutdown {}];
                }
                self.input.edit(Key::Delete);
                Vec::new()
            }
            Key::Esc => {
                if self.running {
                    vec![Command::Interrupt {}]
                } else {
                    Vec::new()
                }
            }
            Key::ShiftTab => vec![Command::SetMode { mode: Mode::Next }],
            Key::Enter => {
                if self.input.continues() {
                    self.input.continue_line();
                    return Vec::new();
                }
                let text = self.input.take();
                let text = text.trim();
                if text.is_empty() {
                    return Vec::new();
                }
                self.send(text)
            }
            other => {
                self.input.edit(other);
                Vec::new()
            }
        }
    }

    fn send(&mut self, text: &str) -> Vec<Command> {
        self.close_answer();
        self.items.push(Item::User(text.to_owned()));
        if !self.running {
            self.running = true;
            self.elapsed_ms = 0;
            self.streamed = false;
        }
        if let Some(rest) = text.strip_prefix('/')
            && !rest.starts_with(char::is_whitespace)
            && !rest.is_empty()
        {
            let (name, args) = rest.split_once(char::is_whitespace).unwrap_or((rest, ""));
            return vec![Command::Slash {
                name: name.to_owned(),
                args: args.trim().to_owned(),
            }];
        }
        vec![Command::UserMessage {
            text: text.to_owned(),
            attachments: Vec::new(),
        }]
    }

    fn on_event(&mut self, event: Event) {
        if self.blocked {
            return;
        }
        if let Err(mismatch) = check_ready(&event) {
            self.blocked = true;
            self.notice(mismatch.to_string(), Tone::Error);
            return;
        }
        match event {
            Event::Ready {
                engine,
                session,
                cwd,
                mode,
                server,
                ..
            } => {
                self.info = Some(Info {
                    engine,
                    session,
                    cwd,
                    mode,
                    server,
                });
            }
            Event::LoginRequired {
                reason,
                server,
                message,
                ..
            } => {
                let reason = format!("{reason:?}").to_lowercase();
                let mut text = self.text(
                    "ui.login_needed",
                    &[("reason", &reason), ("server", &server)],
                );
                if !message.is_empty() {
                    text.push_str(&format!(" {message}"));
                }
                self.notice(text, Tone::Warn);
            }
            Event::Text { delta } => {
                self.running = true;
                self.streamed = true;
                match self.items.last_mut() {
                    Some(Item::Assistant { text, open: true }) => text.push_str(&delta),
                    _ => self.items.push(Item::Assistant {
                        text: delta,
                        open: true,
                    }),
                }
            }
            Event::ToolCall {
                id,
                name,
                arguments,
            } => {
                self.close_answer();
                self.items.push(Item::Tool {
                    id,
                    name,
                    arguments,
                    result: None,
                });
            }
            Event::ToolResult { id, result, .. } => {
                for item in self.items.iter_mut().rev() {
                    if let Item::Tool {
                        id: found,
                        result: slot,
                        ..
                    } = item
                        && *found == id
                    {
                        *slot = Some(result);
                        break;
                    }
                }
            }
            Event::Plan { steps, .. } => {
                let steps: Vec<(String, String)> = steps
                    .iter()
                    .map(|s| {
                        let get =
                            |k: &str| s.get(k).and_then(Value::as_str).unwrap_or("").to_owned();
                        (get("text"), get("status"))
                    })
                    .collect();
                self.close_answer();
                if let Some(Item::Plan(old)) = self.items.last_mut() {
                    *old = steps;
                } else {
                    self.items.push(Item::Plan(steps));
                }
            }
            Event::PermissionRequest { tool, .. } => {
                self.notice(
                    self.text("ui.permission_wait", &[("tool", &tool)]),
                    Tone::Warn,
                );
            }
            Event::Status { kind, data } => match kind.as_str() {
                "line" => self.line = data,
                "queued" => {
                    self.queued = data.get("count").and_then(Value::as_u64).unwrap_or(0);
                }
                "notice" => {
                    if let Some(text) = data
                        .get("text")
                        .or_else(|| data.get("message"))
                        .and_then(Value::as_str)
                    {
                        self.notice(text.to_owned(), Tone::Dim);
                    }
                }
                _ => {}
            },
            Event::Usage { tokens, window } => self.usage = Some((tokens, window)),
            Event::Compact { before, after, .. } => {
                let text = self.text(
                    "ui.compacted",
                    &[
                        ("before", &before.to_string()),
                        ("after", &after.to_string()),
                    ],
                );
                self.notice(text, Tone::Dim);
            }
            Event::Goal { complete, open, .. } => {
                if !complete {
                    let text = self.text("ui.goal_open", &[("open", &open.len().to_string())]);
                    self.notice(text, Tone::Warn);
                }
            }
            Event::Completion { .. } => {}
            Event::Error { code, message } => {
                let ends = ENDS_COMMAND.contains(&code.as_str());
                self.notice(format!("{code}: {message}"), Tone::Error);
                if ends && self.queued == 0 {
                    self.running = false;
                }
            }
            Event::Done { status, answer } => {
                self.close_answer();
                if status == "interrupted" {
                    self.notice(self.text("ui.interrupted", &[]), Tone::Dim);
                } else if status != "completed" {
                    let shown = if answer.trim().is_empty() {
                        status
                    } else {
                        answer
                    };
                    self.notice(shown, Tone::Warn);
                } else if !self.streamed && !answer.trim().is_empty() {
                    self.items.push(Item::Assistant {
                        text: answer,
                        open: false,
                    });
                }
                self.running = self.queued > 0;
                self.streamed = false;
            }
        }
    }
}
