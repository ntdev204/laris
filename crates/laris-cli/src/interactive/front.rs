//! The session's side of the interface: it takes the interface's [`Command`]s and answers with [`Event`]s.
//!
//! A message runs a turn of the loop; the events of the turn go out the moment they are recorded. Around the loop
//! it answers what the loop does not know: slash commands, `!command`, `# note`, `@path` files, completion and the
//! permission mode. It is generic over the model and the tools, so tests drive it with a scripted model.

use super::commands::{CommandSet, expand};
use super::files;
use crate::headless::args::mode_of;
use crate::headless::real::SharedRegistry;
use laris_config::Catalogue;
use laris_core::{Driver, FollowModel, Model, ToolRunner};
use laris_policy::{Engine, mode_name};
use laris_protocol::events::{Mode, Trigger};
use laris_protocol::{Command, Event};
use laris_tools::Scope;
use serde_json::{Map, Value, json};
use std::path::PathBuf;
use std::rc::Rc;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

/// Most characters of a `!command`'s output kept for the next message.
const BANG_KEEP: usize = 8000;

/// Where events go.
pub type Emit = Rc<dyn Fn(Event)>;

/// What a front needs besides the loop.
pub struct Wiring {
    /// The registry the loop's tools run on (`/rewind`, `!command`).
    pub registry: SharedRegistry,
    /// The permission engine.
    pub engine: Arc<Engine>,
    /// The commands.
    pub commands: CommandSet,
    /// The messages.
    pub words: Catalogue,
    /// The project folder.
    pub project: PathBuf,
    /// The file `# note` appends to.
    pub note_file: PathBuf,
    /// The session id.
    pub session: String,
    /// The server address, for `/status`.
    pub server: String,
    /// Messages sent by the interface and not yet taken (the interface adds, the front takes).
    pub waiting: Arc<AtomicUsize>,
    /// Whether commands run in a sandbox.
    pub sandbox: bool,
    /// Where events go.
    pub emit: Emit,
}

/// The session behind the interface.
pub struct Front<M: Model + 'static, R: ToolRunner> {
    driver: Driver<M, R, FollowModel>,
    w: Wiring,
    scope: Scope,
    context: Vec<String>,
    bang: u64,
}

fn branch_of(project: &std::path::Path) -> Option<String> {
    let head = std::fs::read_to_string(project.join(".git/HEAD")).ok()?;
    let name = head.trim().strip_prefix("ref: refs/heads/")?;
    (!name.is_empty() && name.len() < 80).then(|| name.to_owned())
}

impl<M: Model + 'static, R: ToolRunner> Front<M, R> {
    /// A front over `driver`. Its events are handed to `wiring.emit` as they are produced.
    pub fn new(driver: Driver<M, R, FollowModel>, wiring: Wiring) -> Self {
        let sink = Rc::clone(&wiring.emit);
        let driver = driver.with_sink(move |event| sink(event.clone()));
        let scope = wiring.registry.0.borrow().context().scope.clone();
        Self {
            driver,
            w: wiring,
            scope,
            context: Vec::new(),
            bang: 0,
        }
    }

    fn emit(&self, event: Event) {
        (self.w.emit)(event);
    }

    fn text(&self, key: &str, args: &[(&str, &str)]) -> String {
        self.w
            .words
            .get(key, args)
            .unwrap_or_else(|_| key.to_owned())
    }

    fn done(&self) {
        self.emit(Event::Done {
            status: "completed".to_owned(),
            answer: String::new(),
        });
    }

    fn error(&self, code: &str, message: String) {
        self.emit(Event::Error {
            code: code.to_owned(),
            message,
        });
    }

    fn notice(&self, text: String) {
        self.emit(Event::Status {
            kind: "notice".to_owned(),
            data: json!({ "text": text })
                .as_object()
                .cloned()
                .unwrap_or_default(),
        });
    }

    /// The `ready` event: version, session, folder, mode and server.
    pub fn ready(&self, engine_version: &str) -> Event {
        Event::Ready {
            version: laris_protocol::CORE_VERSION.to_owned(),
            engine: engine_version.to_owned(),
            session: self.w.session.clone(),
            cwd: home_short(&self.w.project),
            mode: mode_name(self.w.engine.mode()).to_owned(),
            server: self.w.server.clone(),
        }
    }

    /// The status line's values.
    pub fn line(&self) -> Event {
        let mut data = Map::new();
        data.insert(
            "mode".into(),
            Value::String(mode_name(self.w.engine.mode()).to_owned()),
        );
        if let Some(branch) = branch_of(&self.w.project) {
            data.insert("branch".into(), Value::String(branch));
        }
        data.insert(
            "sandbox".into(),
            Value::String(if self.w.sandbox { "on" } else { "off" }.to_owned()),
        );
        Event::Status {
            kind: "line".to_owned(),
            data,
        }
    }

    /// Handles one command. `false` when the session ends.
    pub fn handle(&mut self, command: Command) -> bool {
        match command {
            Command::UserMessage { text, .. } => {
                self.taken(&text);
                self.message(&text);
            }
            Command::Slash { name, args } => {
                self.taken(&format!("/{name} {args}"));
                self.slash(&name, &args);
            }
            Command::SetMode { mode } => self.set_mode(mode),
            Command::Complete { id, trigger, text } => {
                let items = match trigger {
                    Trigger::Slash => self.w.commands.complete(&text),
                    Trigger::At => files::complete(&self.scope, &text),
                };
                self.emit(Event::Completion { id, items });
            }
            Command::Shutdown {} => return false,
            Command::Interrupt {} | Command::Login { .. } | Command::PermissionResponse { .. } => {}
        }
        true
    }

    /// The interface counted this message when it sent it; the front takes it off and says how many wait.
    fn taken(&self, shown: &str) {
        let before = self
            .w
            .waiting
            .try_update(Ordering::SeqCst, Ordering::SeqCst, |n| {
                Some(n.saturating_sub(1))
            })
            .unwrap_or(0);
        let left = before.saturating_sub(1);
        self.emit(Event::Status {
            kind: "queued".to_owned(),
            data: json!({ "count": left, "started": shown })
                .as_object()
                .cloned()
                .unwrap_or_default(),
        });
    }

    fn message(&mut self, text: &str) {
        let text = text.trim();
        if let Some(command) = text.strip_prefix('!') {
            self.shell(command.trim());
        } else if let Some(note) = text.strip_prefix('#') {
            self.note(note.trim());
        } else {
            self.turn(text);
        }
    }

    fn turn(&mut self, text: &str) {
        // an Esc pressed before this turn began must not end it
        self.driver
            .interrupt_handle()
            .store(false, Ordering::SeqCst);
        let (mut full, attached) = files::attach(&self.scope, text);
        if !attached.is_empty() {
            let list = attached.join(", ");
            self.notice(self.text("commands.attached", &[("files", &list)]));
        }
        if !self.context.is_empty() {
            let before = self.context.join("\n\n");
            self.context.clear();
            full = format!("{before}\n\n{full}");
        }
        if let Err(e) = self.driver.send(&full) {
            let detail = e.to_string();
            let message = self.text("commands.failed", &[("detail", &detail)]);
            self.error("core_error", message.clone());
            self.emit(Event::Done {
                status: "failed".to_owned(),
                answer: message,
            });
        }
    }

    /// `!command`: runs the shell command the way the Bash tool does, shows it as a tool block, and keeps its output
    /// for the next message so the model knows what the person saw.
    fn shell(&mut self, command: &str) {
        if command.is_empty() {
            self.error("bad_command", self.text("ui.bang_empty", &[]));
            return;
        }
        self.bang += 1;
        let id = format!("bang-{}", self.bang);
        let mut arguments = Map::new();
        arguments.insert("command".into(), Value::String(command.to_owned()));
        self.emit(Event::ToolCall {
            id: id.clone(),
            name: "Bash".to_owned(),
            arguments: arguments.clone(),
        });
        let result = self.w.registry.0.borrow_mut().call("Bash", &arguments);
        let mut shown = String::new();
        if let Some(error) = result.get("error") {
            shown = error.to_string();
        } else if let Some(output) = result.get("output").and_then(Value::as_str) {
            shown = output.to_owned();
        }
        let kept: String = shown.chars().take(BANG_KEEP).collect();
        self.context.push(format!(
            "The user ran this command in the shell:\n$ {command}\n{kept}"
        ));
        self.emit(Event::ToolResult {
            id,
            name: "Bash".to_owned(),
            result,
        });
        self.done();
    }

    /// `# note`: adds a line to the project's `LARIS.md`.
    fn note(&mut self, note: &str) {
        if note.is_empty() {
            self.error("bad_command", self.text("ui.note_empty", &[]));
            return;
        }
        let one_line: String = note.split_whitespace().collect::<Vec<_>>().join(" ");
        let result = (|| -> std::io::Result<()> {
            use std::io::Write;
            if let Some(folder) = self.w.note_file.parent() {
                std::fs::create_dir_all(folder)?;
            }
            let mut file = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&self.w.note_file)?;
            // a file that does not end in a new line gets one first, so the note stays on its own line
            let existing = std::fs::read_to_string(&self.w.note_file).unwrap_or_default();
            let lead = if existing.is_empty() || existing.ends_with('\n') {
                ""
            } else {
                "\n"
            };
            writeln!(file, "{lead}- {one_line}")
        })();
        match result {
            Ok(()) => {
                let name = self
                    .w
                    .note_file
                    .file_name()
                    .map(|n| n.to_string_lossy().into_owned())
                    .unwrap_or_default();
                self.notice(self.text("commands.noted", &[("file", &name)]));
                self.done();
            }
            Err(e) => self.error(
                "command_failed",
                self.text("commands.note_failed", &[("detail", &e.to_string())]),
            ),
        }
    }

    fn slash(&mut self, name: &str, args: &str) {
        match name {
            "help" => {
                self.emit(Event::Text {
                    delta: self.w.commands.help(),
                });
                self.done();
            }
            "mode" => self.mode_command(args),
            "status" => {
                let text = self.text(
                    "commands.status_line",
                    &[
                        ("session", &self.w.session),
                        ("mode", mode_name(self.w.engine.mode())),
                        ("server", &self.w.server),
                        ("project", &self.w.project.display().to_string()),
                    ],
                );
                self.emit(Event::Text {
                    delta: format!("{text}\n"),
                });
                self.done();
            }
            "rewind" => self.rewind(args),
            "login" | "logout" | "exit" | "quit" | "clear" => {
                // the interface and the loop around the session answer these; one that reaches here is a mistake
                self.error(
                    "command_failed",
                    self.text("commands.unknown", &[("name", name)]),
                );
            }
            other => match self.w.commands.find(other).cloned() {
                Some(custom) => {
                    let body = expand(&custom.body, args);
                    self.turn(&body);
                }
                None => self.error(
                    "unknown_command",
                    self.text("commands.unknown", &[("name", other)]),
                ),
            },
        }
    }

    fn line_changed(&self) {
        self.emit(self.line());
    }

    fn mode_command(&mut self, args: &str) {
        let args = args.trim();
        if args.is_empty() {
            let now = mode_name(self.w.engine.mode());
            self.notice(self.text("ui.mode_set", &[("mode", now)]));
            self.done();
            return;
        }
        match mode_of(args) {
            Ok(mode) => match self.w.engine.set_mode(mode) {
                Ok(()) => {
                    self.notice(self.text("ui.mode_set", &[("mode", mode_name(mode))]));
                    self.line_changed();
                    self.done();
                }
                Err(e) => self.error("bad_mode", e.0),
            },
            Err(_) => self.error("bad_mode", self.text("ui.mode_unknown", &[("mode", args)])),
        }
    }

    fn set_mode(&mut self, mode: Mode) {
        let chosen = match mode {
            Mode::Next => {
                let next = self.w.engine.cycle();
                Ok(next)
            }
            Mode::Auto => self.pick(laris_config::settings::PermissionMode::Auto),
            Mode::Default => self.pick(laris_config::settings::PermissionMode::Default),
            Mode::AcceptEdits => self.pick(laris_config::settings::PermissionMode::AcceptEdits),
            Mode::Plan => self.pick(laris_config::settings::PermissionMode::Plan),
            Mode::Bypass => self.pick(laris_config::settings::PermissionMode::Bypass),
        };
        match chosen {
            Ok(now) => {
                self.notice(self.text("ui.mode_set", &[("mode", mode_name(now))]));
                self.line_changed();
            }
            Err(message) => self.error("bad_mode", message),
        }
    }

    fn pick(
        &self,
        mode: laris_config::settings::PermissionMode,
    ) -> Result<laris_config::settings::PermissionMode, String> {
        self.w.engine.set_mode(mode).map_err(|e| e.0)?;
        Ok(mode)
    }

    fn rewind(&mut self, args: &str) {
        let steps = match args.trim() {
            "" => Some(1),
            text => match text.parse::<usize>() {
                Ok(n) if n > 0 => Some(n),
                _ => {
                    self.error("bad_command", self.text("commands.rewind", &[]));
                    return;
                }
            },
        };
        let result = self.w.registry.0.borrow().rewind(steps);
        match result {
            Ok(done) if done.is_empty() => {
                self.notice(self.text("commands.rewind_none", &[]));
                self.done();
            }
            Ok(done) => {
                let mut text = self.text("commands.rewound", &[("count", &done.len().to_string())]);
                for item in &done {
                    if let Some(path) = item.get("path").and_then(Value::as_str) {
                        text.push_str(&format!("\n  {path}"));
                    }
                }
                self.notice(text);
                self.done();
            }
            Err(e) => self.error("command_failed", e.message.clone()),
        }
    }

    /// The driver, for tests.
    pub fn driver(&self) -> &Driver<M, R, FollowModel> {
        &self.driver
    }
}

/// A folder as the banner shows it: the home directory is written `~`.
fn home_short(path: &std::path::Path) -> String {
    let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE"));
    match home
        .as_deref()
        .map(std::path::Path::new)
        .and_then(|h| path.strip_prefix(h).ok())
    {
        Some(rest) if rest.as_os_str().is_empty() => "~".to_owned(),
        Some(rest) => format!("~{}{}", std::path::MAIN_SEPARATOR, rest.display()),
        None => path.display().to_string(),
    }
}
