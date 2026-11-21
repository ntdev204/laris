//! The interface's state and how it changes. It holds no tool, permission or storage logic (SR-C1): it shows what
//! the core's events say and sends the core's commands.
//!
//! [`App::update`] takes one [`Input`] (a key, a paste, a core event, a tick of the clock) and returns the commands
//! to send. [`App::layout`] draws the state at a width.

use crate::input::{InputBuffer, Key};
use crate::style::Theme;
use laris_config::Catalogue;
use laris_config::settings::Ui;
use laris_protocol::events::{
    CompletionItem, Decision, ENDS_COMMAND, LoginReason, Mode, Scope, Trigger,
};
use laris_protocol::{Command, Event, check_ready};
use serde_json::{Map, Value};

/// `text` with white space collapsed: two spellings of one message compare equal.
fn norm(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Milliseconds the "press Ctrl-C again" prompt stays armed.
pub const EXIT_WINDOW_MS: u64 = 3000;
/// Error codes of the loop's own refusals that are shown to the model only: the tool line is left off the screen.
const HIDDEN_ERRORS: [&str; 1] = ["too_many_calls"];

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

/// One entry of a session's log, to show a resumed session's conversation again.
#[derive(Debug, Clone, PartialEq)]
pub enum History {
    /// What the user sent.
    User(String),
    /// An event the core sent.
    Event(Event),
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
    /// A unified diff of a change that was asked about or made.
    Diff(String),
}

/// One answer the approval menu offers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Choice {
    /// Catalogue key of its label.
    pub label: &'static str,
    /// Allow or deny.
    pub decision: Decision,
    /// How long.
    pub scope: Scope,
}

/// A call waiting for the person's answer.
#[derive(Debug, Clone, PartialEq)]
pub struct Approval {
    /// Request id.
    pub id: String,
    /// Tool name.
    pub tool: String,
    /// Arguments.
    pub arguments: Map<String, Value>,
    /// Why it is asked.
    pub reason: String,
    /// The rule "always" would save.
    pub rule: String,
    /// The change, as a unified diff.
    pub diff: String,
    /// What can be answered.
    pub choices: Vec<Choice>,
    /// The highlighted choice.
    pub selected: usize,
}

/// What the login form asks for.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    /// The server address.
    Server,
    /// Whether to trust a certificate fingerprint.
    Trust,
    /// The API key (masked).
    Key,
}

/// The login form. What is typed in it is never shown, logged or kept after sending.
#[derive(Clone)]
pub struct SignIn {
    /// What is asked now.
    pub stage: Stage,
    /// The server, as far as known.
    pub server: String,
    /// The fingerprint to confirm.
    pub fingerprint: String,
    /// Why the form is shown again.
    pub note: String,
    /// The reason the core gave.
    pub reason: LoginReason,
    /// A command was sent and the answer has not come.
    pub waiting: bool,
    pub(crate) field: InputBuffer,
}

impl std::fmt::Debug for SignIn {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SignIn")
            .field("stage", &self.stage)
            .field("server", &self.server)
            .field("typed_characters", &self.field.chars().len())
            .finish_non_exhaustive()
    }
}

impl SignIn {
    /// How many characters were typed (what the mask shows).
    pub fn typed(&self) -> usize {
        self.field.chars().len()
    }
}

/// History search.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Search {
    /// What is looked for.
    pub query: String,
    /// The history entry found.
    pub found: Option<usize>,
}

/// The candidates of a completion.
#[derive(Debug, Clone, PartialEq)]
pub struct Menu {
    /// Candidates.
    pub items: Vec<CompletionItem>,
    /// The highlighted one.
    pub selected: usize,
    pub(crate) trigger: Trigger,
    pub(crate) start: usize,
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
    /// Messages typed while a turn runs: shown below the conversation until the core starts them.
    pub(crate) pending: Vec<String>,
    pub(crate) running: bool,
    pub(crate) streamed: bool,
    pub(crate) armed_ms: Option<u64>,
    pub(crate) elapsed_ms: u64,
    pub(crate) frame: u64,
    /// Milliseconds since the spinner last advanced.
    pub(crate) frame_ms: u64,
    quit: bool,
    pub(crate) blocked: bool,
    pub(crate) approval: Option<Approval>,
    pub(crate) sign_in: Option<SignIn>,
    pub(crate) search: Option<Search>,
    pub(crate) menu: Option<Menu>,
    pub(crate) asked: Option<(String, Trigger, usize, bool)>,
    pub(crate) flash: Option<String>,
    /// The version an automatic update installed, once it is on disk and this session still runs the old one.
    pub(crate) update: Option<String>,
    restart: bool,
    next_id: u64,
    next_live: u64,
    clear: bool,
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
            pending: Vec::new(),
            running: false,
            streamed: false,
            armed_ms: None,
            elapsed_ms: 0,
            frame: 0,
            frame_ms: 0,
            quit: false,
            blocked: false,
            approval: None,
            sign_in: None,
            search: None,
            menu: None,
            asked: None,
            flash: None,
            update: None,
            restart: false,
            next_id: 0,
            next_live: 0,
            clear: false,
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

    /// Whether the person asked for `/restart`: the program leaves and starts again (with the new version).
    pub fn restart_requested(&self) -> bool {
        self.restart
    }

    /// The version waiting to be applied by `/restart`, if an update was installed.
    pub fn update_ready(&self) -> Option<&str> {
        self.update.as_deref()
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
                // the spinner moves only while something runs, and slowly: every step redraws the live block
                if self.running {
                    self.elapsed_ms += ms;
                    self.frame_ms += ms;
                    if self.frame_ms >= crate::view::SPINNER_STEP_MS {
                        self.frame = self
                            .frame
                            .wrapping_add(self.frame_ms / crate::view::SPINNER_STEP_MS);
                        self.frame_ms %= crate::view::SPINNER_STEP_MS;
                    }
                } else {
                    self.frame_ms = 0;
                }
                if let Some(armed) = self.armed_ms {
                    let armed = armed + ms;
                    self.armed_ms = (armed < EXIT_WINDOW_MS).then_some(armed);
                }
                Vec::new()
            }
        }
    }

    /// Shows the conversation of a session that is resumed: what the user sent and what the core answered, from the
    /// event log. Only what belongs to the conversation is taken (no login, approval or completion).
    pub fn show_history(&mut self, entries: Vec<History>) {
        for entry in entries {
            match entry {
                History::User(text) => {
                    self.close_answer();
                    self.items.push(Item::User(text));
                }
                History::Event(event) => {
                    let shown = match &event {
                        Event::Status { kind, .. } => kind == "notice",
                        other => matches!(
                            other,
                            Event::Text { .. }
                                | Event::ToolCall { .. }
                                | Event::ToolResult { .. }
                                | Event::Plan { .. }
                                | Event::Compact { .. }
                                | Event::Error { .. }
                                | Event::Done { .. }
                        ),
                    };
                    if shown {
                        self.on_event(event);
                    }
                }
            }
        }
        self.close_answer();
        self.running = false;
        self.streamed = false;
        self.elapsed_ms = 0;
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

    /// The login form, while it is open.
    pub fn sign_in(&self) -> Option<&SignIn> {
        self.sign_in.as_ref()
    }

    /// The call waiting for an answer.
    pub fn approval(&self) -> Option<&Approval> {
        self.approval.as_ref()
    }

    /// The open completion menu.
    pub fn menu(&self) -> Option<&Menu> {
        self.menu.as_ref()
    }

    /// The history search, while it is open.
    pub fn search(&self) -> Option<&Search> {
        self.search.as_ref()
    }

    /// Empties the input box (a scripted replay starts each typed step from nothing).
    pub fn clear_input(&mut self) {
        self.input.clear();
        self.menu = None;
    }

    /// `true` once after `/clear`: the terminal driver forgets what it printed and clears the screen.
    pub fn take_clear(&mut self) -> bool {
        std::mem::take(&mut self.clear)
    }

    fn on_key(&mut self, key: Key) -> Vec<Command> {
        if self.blocked {
            if matches!(key, Key::CtrlC | Key::CtrlD) {
                self.quit = true;
            }
            return Vec::new();
        }
        self.flash = None;
        if self.approval.is_some() {
            return self.approval_key(key);
        }
        if self.sign_in.is_some() {
            return self.sign_in_key(key);
        }
        if self.search.is_some() {
            return self.search_key(key);
        }
        if self.menu.is_some() && self.menu_key(key) {
            return Vec::new();
        }
        let was_armed = self.armed_ms.take().is_some();
        match key {
            Key::CtrlC => {
                if !self.input.is_empty() {
                    self.input.clear();
                    self.menu = None;
                    self.asked = None;
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
            Key::CtrlR => {
                if !self.input.history().is_empty() {
                    let found = self.input.search("", None);
                    self.search = Some(Search {
                        query: String::new(),
                        found,
                    });
                }
                Vec::new()
            }
            Key::Tab => self.complete(),
            Key::Enter => {
                if self.input.continues() {
                    self.input.continue_line();
                    return Vec::new();
                }
                self.menu = None;
                self.asked = None;
                let text = self.input.take();
                let text = text.trim();
                if text.is_empty() {
                    return Vec::new();
                }
                self.send(text)
            }
            other => {
                self.input.edit(other);
                self.suggest()
            }
        }
    }

    // -- approval ------------------------------------------------------------------------------

    fn approval_key(&mut self, key: Key) -> Vec<Command> {
        let Some(approval) = self.approval.as_mut() else {
            return Vec::new();
        };
        let last = approval.choices.len().saturating_sub(1);
        match key {
            Key::Up => approval.selected = approval.selected.saturating_sub(1),
            Key::Down | Key::Tab => approval.selected = (approval.selected + 1).min(last),
            Key::Char('y' | 'Y') => approval.selected = 0,
            Key::Char('n' | 'N') | Key::Esc | Key::CtrlC => {
                approval.selected = last;
                return self.answer();
            }
            Key::Char(c @ '1'..='9') => {
                let at = c as usize - '1' as usize;
                if at <= last {
                    approval.selected = at;
                } else {
                    return Vec::new();
                }
            }
            Key::Enter => return self.answer(),
            _ => return Vec::new(),
        }
        if matches!(key, Key::Char('y' | 'Y' | '1'..='9')) {
            return self.answer();
        }
        Vec::new()
    }

    fn answer(&mut self) -> Vec<Command> {
        let Some(approval) = self.approval.take() else {
            return Vec::new();
        };
        let choice = approval.choices[approval.selected.min(approval.choices.len() - 1)];
        let label = self.text(choice.label, &[]);
        let tone = if choice.decision == Decision::Allow {
            Tone::Dim
        } else {
            Tone::Warn
        };
        self.close_answer();
        if !approval.diff.trim().is_empty() {
            self.items.push(Item::Diff(approval.diff.clone()));
        }
        self.items.push(Item::Notice {
            text: format!("{}: {label}", approval.tool),
            tone,
        });
        vec![Command::PermissionResponse {
            id: approval.id,
            decision: choice.decision,
            scope: choice.scope,
            remember: choice.scope != Scope::Once,
        }]
    }

    /// What the approval menu offers for the scopes the core allows: once, then each wider scope, then no.
    fn choices(scopes: &[String]) -> Vec<Choice> {
        let mut out = vec![Choice {
            label: "ui.approval_once",
            decision: Decision::Allow,
            scope: Scope::Once,
        }];
        for (name, label, scope) in [
            ("session", "ui.approval_session", Scope::Session),
            ("project", "ui.approval_project", Scope::Project),
            ("everywhere", "ui.approval_everywhere", Scope::Everywhere),
        ] {
            if scopes.iter().any(|s| s == name) {
                out.push(Choice {
                    label,
                    decision: Decision::Allow,
                    scope,
                });
            }
        }
        out.push(Choice {
            label: "ui.approval_deny",
            decision: Decision::Deny,
            scope: Scope::Once,
        });
        out
    }

    // -- login ---------------------------------------------------------------------------------

    fn sign_in_key(&mut self, key: Key) -> Vec<Command> {
        let Some(form) = self.sign_in.as_mut() else {
            return Vec::new();
        };
        if matches!(key, Key::CtrlC | Key::CtrlD | Key::Esc) {
            self.quit = true;
            return vec![Command::Shutdown {}];
        }
        if form.waiting {
            return Vec::new();
        }
        match form.stage {
            Stage::Trust => match key {
                Key::Char('y' | 'Y') => {
                    form.waiting = true;
                    vec![Command::Login {
                        server: String::new(),
                        key: String::new(),
                        trust: true,
                    }]
                }
                Key::Char('n' | 'N') => {
                    self.quit = true;
                    vec![Command::Shutdown {}]
                }
                _ => Vec::new(),
            },
            Stage::Server | Stage::Key => {
                if key == Key::Enter {
                    let typed = form.field.text();
                    let typed = typed.trim().to_owned();
                    form.field.clear();
                    if typed.is_empty() {
                        return Vec::new();
                    }
                    form.waiting = true;
                    return vec![if form.stage == Stage::Server {
                        Command::Login {
                            server: typed,
                            key: String::new(),
                            trust: false,
                        }
                    } else {
                        Command::Login {
                            server: String::new(),
                            key: typed,
                            trust: false,
                        }
                    }];
                }
                if !matches!(key, Key::Newline | Key::Up | Key::Down) {
                    form.field.edit(key);
                }
                Vec::new()
            }
        }
    }

    fn open_sign_in(
        &mut self,
        reason: LoginReason,
        server: String,
        fingerprint: String,
        message: String,
    ) {
        let stage = match reason {
            LoginReason::NoServer => Stage::Server,
            LoginReason::UntrustedCertificate | LoginReason::CertificateMismatch => Stage::Trust,
            LoginReason::NoKey | LoginReason::Rejected | LoginReason::Invalid => Stage::Key,
        };
        let note = if !message.is_empty() {
            message
        } else if reason == LoginReason::Rejected {
            self.text("login.rejected", &[])
        } else {
            String::new()
        };
        self.sign_in = Some(SignIn {
            stage,
            server,
            fingerprint,
            note,
            reason,
            waiting: false,
            field: InputBuffer::new(),
        });
    }

    // -- history search ------------------------------------------------------------------------

    fn search_key(&mut self, key: Key) -> Vec<Command> {
        let Some(search) = self.search.as_mut() else {
            return Vec::new();
        };
        match key {
            Key::Esc | Key::CtrlC => self.search = None,
            Key::Enter => {
                let entry = search
                    .found
                    .and_then(|i| self.input.history().get(i).cloned());
                self.search = None;
                if let Some(entry) = entry {
                    self.input.set(&entry);
                }
            }
            Key::CtrlR | Key::Up => {
                if let Some(found) = search.found {
                    search.found = self
                        .input
                        .search(&search.query, Some(found))
                        .or(Some(found));
                }
            }
            Key::Backspace => {
                search.query.pop();
                search.found = self.input.search(&search.query, None);
            }
            Key::Char(c) if !c.is_control() => {
                search.query.push(c);
                search.found = self.input.search(&search.query, None);
            }
            _ => {}
        }
        Vec::new()
    }

    // -- completion ----------------------------------------------------------------------------

    /// Tab: asks the core for completions of the word at the cursor when it starts with `/` (first word) or `@`.
    fn complete(&mut self) -> Vec<Command> {
        self.ask_completion(false)
    }

    /// After an edit: the suggestions follow what is typed. A `/` first word or an `@` word opens (or narrows) the
    /// menu as each character arrives; any other word closes it.
    fn suggest(&mut self) -> Vec<Command> {
        let commands = self.ask_completion(true);
        if commands.is_empty() {
            self.menu = None;
            self.asked = None;
        }
        commands
    }

    fn ask_completion(&mut self, live: bool) -> Vec<Command> {
        let chars = self.input.chars();
        let cursor = self.input.cursor();
        let start = chars[..cursor]
            .iter()
            .rposition(|c| c.is_whitespace())
            .map_or(0, |p| p + 1);
        let word: String = chars[start..cursor].iter().collect();
        let trigger = match word.chars().next() {
            Some('/') if start == 0 => Trigger::Slash,
            Some('@') => Trigger::At,
            _ => return Vec::new(),
        };
        // Suggestions while typing have their own ids, so the ids of Tab requests stay what a scenario recorded.
        self.next_live += u64::from(live);
        self.next_id += u64::from(!live);
        let id = if live {
            format!("s{}", self.next_live)
        } else {
            format!("c{}", self.next_id)
        };
        self.asked = Some((id.clone(), trigger, start, live));
        vec![Command::Complete {
            id,
            trigger,
            text: word.chars().skip(1).collect(),
        }]
    }

    fn accept(&mut self, value: &str, trigger: Trigger, start: usize) {
        let mut text = match trigger {
            Trigger::Slash => format!("/{value}"),
            Trigger::At => format!("@{value}"),
        };
        if !text.ends_with('/') {
            text.push(' ');
        }
        self.input.replace_before_cursor(start, &text);
    }

    /// `true` when the menu used the key.
    fn menu_key(&mut self, key: Key) -> bool {
        let Some(menu) = self.menu.as_mut() else {
            return false;
        };
        let last = menu.items.len().saturating_sub(1);
        match key {
            // Tab takes the highlighted suggestion; the arrows move the highlight; Enter is not used here, it sends.
            Key::Tab => {
                if let Some(menu) = self.menu.take()
                    && let Some(item) = menu.items.get(menu.selected)
                {
                    self.accept(&item.value.clone(), menu.trigger, menu.start);
                }
            }
            Key::Down => {
                menu.selected = if menu.selected >= last {
                    0
                } else {
                    menu.selected + 1
                };
            }
            Key::Up => {
                menu.selected = if menu.selected == 0 {
                    last
                } else {
                    menu.selected - 1
                };
            }
            Key::Esc => {
                self.menu = None;
                self.asked = None;
            }
            // Typing goes on with the menu open: the edit asks again and narrows it.
            _ => return false,
        }
        true
    }

    fn on_completion(&mut self, id: &str, items: Vec<CompletionItem>) {
        let Some((asked, trigger, start, live)) = self.asked.take() else {
            return;
        };
        if asked != id {
            self.asked = Some((asked, trigger, start, live));
            return;
        }
        if live {
            self.menu = (!items.is_empty()).then_some(Menu {
                items,
                selected: 0,
                trigger,
                start,
            });
            return;
        }
        match items.len() {
            0 => self.flash = Some(self.text("ui.completion_none", &[])),
            1 => self.accept(&items[0].value.clone(), trigger, start),
            _ => {
                self.menu = Some(Menu {
                    items,
                    selected: 0,
                    trigger,
                    start,
                });
            }
        }
    }

    fn send(&mut self, text: &str) -> Vec<Command> {
        if let Some(rest) = text.strip_prefix('/')
            && !rest.starts_with(char::is_whitespace)
            && !rest.is_empty()
        {
            let (name, args) = rest.split_once(char::is_whitespace).unwrap_or((rest, ""));
            match name {
                "exit" => {
                    self.quit = true;
                    return vec![Command::Shutdown {}];
                }
                "restart" => {
                    self.quit = true;
                    self.restart = true;
                    return vec![Command::Shutdown {}];
                }
                "clear" => {
                    self.items.clear();
                    self.clear = true;
                    self.notice(self.text("ui.cleared", &[]), Tone::Dim);
                    return Vec::new();
                }
                _ => {}
            }
            self.user_line(text);
            return vec![Command::Slash {
                name: name.to_owned(),
                args: args.trim().to_owned(),
            }];
        }
        self.user_line(text);
        vec![Command::UserMessage {
            text: text.to_owned(),
            attachments: Vec::new(),
        }]
    }

    /// What the person sent: part of the conversation now when nothing runs, else waiting below it until the core
    /// starts it.
    fn user_line(&mut self, text: &str) {
        if self.running {
            self.pending.push(text.to_owned());
            return;
        }
        self.close_answer();
        self.items.push(Item::User(text.to_owned()));
        self.running = true;
        self.elapsed_ms = 0;
        self.streamed = false;
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
                self.sign_in = None;
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
                fingerprint,
                message,
            } => {
                self.running = false;
                self.open_sign_in(reason, server, fingerprint, message);
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
                // a refusal that is only the loop's own bookkeeping is for the model, not for the person
                if result
                    .pointer("/error/code")
                    .and_then(Value::as_str)
                    .is_some_and(|code| HIDDEN_ERRORS.contains(&code))
                {
                    self.items.retain(
                        |item| !matches!(item, Item::Tool { id: found, .. } if *found == id),
                    );
                    return;
                }
                for item in self.items.iter_mut().rev() {
                    if let Item::Tool {
                        id: found,
                        result: slot,
                        ..
                    } = item
                        && *found == id
                    {
                        *slot = Some(result.clone());
                        break;
                    }
                }
                if let Some(diff) = result.get("diff").and_then(Value::as_str)
                    && !diff.trim().is_empty()
                    && !matches!(self.items.last(), Some(Item::Diff(last)) if last == diff)
                {
                    self.items.push(Item::Diff(diff.to_owned()));
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
            Event::PermissionRequest {
                id,
                tool,
                arguments,
                reason,
                rule,
                diff,
                scopes,
            } => {
                self.close_answer();
                self.menu = None;
                self.approval = Some(Approval {
                    id,
                    tool,
                    arguments,
                    reason,
                    rule,
                    diff,
                    choices: Self::choices(&scopes),
                    selected: 0,
                });
            }
            Event::Status { kind, data } => match kind.as_str() {
                "line" => self.line = data,
                "update" => {
                    self.update = data
                        .get("version")
                        .and_then(Value::as_str)
                        .map(crate::view::clean)
                        .filter(|v| !v.is_empty());
                }
                "queued" => {
                    self.queued = data.get("count").and_then(Value::as_u64).unwrap_or(0);
                    // the core says which message it took; only the one waiting first moves into the conversation
                    let started = data.get("started").and_then(Value::as_str).map(norm);
                    if started.is_some() && self.pending.first().map(|p| norm(p)) == started {
                        let text = self.pending.remove(0);
                        self.close_answer();
                        self.items.push(Item::User(text));
                        self.elapsed_ms = 0;
                    }
                }
                "pipeline" => {
                    let stage = data.get("stage").and_then(Value::as_str).unwrap_or("");
                    let failed = data.get("outcome").and_then(Value::as_str) == Some("error");
                    // the working stages (checking, deciding, asking) stay out of the client; only a failed one shows
                    if !stage.is_empty() && failed {
                        let key = match stage {
                            "prefilter" | "retrieval" | "decider" | "model" | "gate"
                            | "assembly" => {
                                format!("ui.stage_{stage}")
                            }
                            _ => "ui.stage_other".to_owned(),
                        };
                        let text = self.text(&key, &[("stage", stage)]);
                        self.notice(text, if failed { Tone::Warn } else { Tone::Dim });
                    }
                }
                "sources" => {
                    let list: Vec<&str> = data
                        .get("items")
                        .and_then(Value::as_array)
                        .map(|a| a.iter().filter_map(Value::as_str).collect())
                        .unwrap_or_default();
                    if !list.is_empty() {
                        let text = self.text("ui.sources", &[("list", &list.join(", "))]);
                        self.notice(text, Tone::Dim);
                    }
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
            Event::Completion { id, items } => self.on_completion(&id, items),
            Event::Error { code, message } => {
                let ends = ENDS_COMMAND.contains(&code.as_str());
                self.notice(format!("{code}: {message}"), Tone::Error);
                if ends && self.queued == 0 {
                    self.running = !self.pending.is_empty();
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
                self.running = self.queued > 0 || !self.pending.is_empty();
                self.streamed = false;
            }
        }
    }
}
