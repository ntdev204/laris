//! What sits between the interface and the session: it feeds keys and events to the [`App`], sends the commands the
//! app gives to the session thread, and answers the ones that belong to the program itself (signing in and out).
//!
//! It holds no terminal, so a test drives it with keys and a scripted session.

use super::worker::Handle;
use crate::account;
use crate::login::{KeyVerifier, Reason, Startup, decide};
use crate::start::Started;
use laris_config::Catalogue;
use laris_model_client::ApiKey;
use laris_protocol::events::LoginReason;
use laris_protocol::{Command, Event};
use laris_tui::{App, Input, Key, Theme};
use std::sync::Arc;
use std::sync::mpsc::{Receiver, Sender, channel};

/// Starts a session for `server` with `key` and gives its events to `events`.
pub type Starter = Box<dyn FnMut(&Arc<Started>, &ApiKey, &str, Sender<Event>) -> Handle>;

/// The interface and the session behind it.
pub struct Controller {
    /// The interface.
    pub app: App,
    started: Arc<Started>,
    words: Catalogue,
    handle: Option<Handle>,
    events: Sender<Event>,
    inbox: Receiver<Event>,
    start: Starter,
    verifier: Box<dyn KeyVerifier>,
    server: String,
    deferred: Option<(String, String, bool)>,
}

impl Controller {
    /// Opens the interface. With a key at hand the session starts; without one the login form opens.
    pub fn new(
        started: Arc<Started>,
        theme: Option<Theme>,
        start: Starter,
        verifier: Box<dyn KeyVerifier>,
    ) -> Self {
        let (events, inbox) = channel();
        let words = Catalogue::new(started.settings.ui.language);
        let mut app = App::new(&started.settings.ui);
        if let Some(theme) = theme {
            app = app.with_theme(theme);
        }
        let mut me = Self {
            app,
            started,
            words,
            handle: None,
            events,
            inbox,
            start,
            verifier,
            server: String::new(),
            deferred: None,
        };
        me.begin();
        me
    }

    fn say(&self, key: &str, args: &[(&str, &str)]) -> String {
        self.words.get(key, args).unwrap_or_else(|_| key.to_owned())
    }

    fn begin(&mut self) {
        match decide(
            &self.started.home,
            &self.started.settings,
            &self.started.env,
        ) {
            Startup::Ready { server, key, .. } => self.open_session(&key, &server),
            Startup::NoServer => {
                let message = self.say("login.no_server", &[("settings", "settings.json")]);
                self.ask_login(LoginReason::NoServer, "", &message);
            }
            Startup::NeedsLogin { server, reason } => {
                let (why, message) = match reason {
                    Reason::FirstRun => (LoginReason::NoKey, String::new()),
                    Reason::OtherServer(other) => (
                        LoginReason::NoKey,
                        self.say("login.other_server", &[("server", &other)]),
                    ),
                    Reason::Unreadable(detail) => (
                        LoginReason::Invalid,
                        self.say("login.unreadable", &[("detail", &detail)]),
                    ),
                };
                self.ask_login(why, &server, &message);
            }
        }
    }

    fn ask_login(&mut self, reason: LoginReason, server: &str, message: &str) {
        self.app.update(Input::Event(Event::LoginRequired {
            reason,
            server: server.to_owned(),
            fingerprint: String::new(),
            message: message.to_owned(),
        }));
    }

    fn open_session(&mut self, key: &ApiKey, server: &str) {
        // the old session ends first; its thread is not waited for
        self.handle = None;
        self.server = server.to_owned();
        let handle = (self.start)(&self.started, key, server, self.events.clone());
        self.handle = Some(handle);
    }

    /// Where background work (the updater) sends events for the interface.
    pub fn sender(&self) -> Sender<Event> {
        self.events.clone()
    }

    /// The session id the interface was told about, for `/restart` to resume.
    pub fn session(&self) -> Option<String> {
        self.app.info().map(|info| info.session.clone())
    }

    /// Takes the events the session produced. `true` when there were some.
    pub fn pump(&mut self) -> bool {
        let mut any = false;
        while let Ok(event) = self.inbox.try_recv() {
            any = true;
            if let Event::Error { code, .. } = &event
                && code == "session_failed"
            {
                self.handle = None;
            }
            self.app.update(Input::Event(event));
        }
        any
    }

    /// A key, with anything slow it asks for done at once.
    pub fn key(&mut self, key: Key) {
        self.key_deferred(key);
        self.settle();
    }

    /// A key. Checking a key with the server takes a while, so it is only noted here: the terminal draws "checking"
    /// first and then calls [`Controller::settle`].
    pub fn key_deferred(&mut self, key: Key) {
        let commands = self.app.update(Input::Key(key));
        self.dispatch(commands);
    }

    /// Whether [`Controller::settle`] has something to do.
    pub fn has_deferred(&self) -> bool {
        self.deferred.is_some()
    }

    /// Does what [`Controller::key_deferred`] put off (asking the server about a key).
    pub fn settle(&mut self) {
        if let Some((server, key, trust)) = self.deferred.take() {
            self.login(&server, &key, trust);
        }
    }

    /// Pasted text.
    pub fn paste(&mut self, text: String) {
        self.app.update(Input::Paste(text));
    }

    /// The clock moved by `ms`.
    pub fn tick(&mut self, ms: u64) {
        self.app.update(Input::Tick(ms));
    }

    /// Whether the person asked to leave.
    pub fn should_quit(&self) -> bool {
        self.app.should_quit()
    }

    /// Whether a session is attached.
    pub fn has_session(&self) -> bool {
        self.handle.is_some()
    }

    fn dispatch(&mut self, commands: Vec<Command>) {
        for command in commands {
            match command {
                Command::Login { server, key, trust } => self.deferred = Some((server, key, trust)),
                Command::Slash { name, .. } if name == "logout" => self.logout(),
                Command::Slash { name, .. } if name == "login" => {
                    let server = self.server.clone();
                    self.ask_login(LoginReason::NoKey, &server, "");
                }
                Command::Shutdown {} => {
                    if let Some(handle) = &self.handle {
                        handle.send(Command::Shutdown {});
                    }
                }
                other => match &self.handle {
                    Some(handle) => {
                        if !handle.send(other) {
                            self.fail("session_ended");
                        }
                    }
                    None => self.no_session(&other),
                },
            }
        }
    }

    fn fail(&mut self, code: &str) {
        self.handle = None;
        let message = self.say("ui.no_worker", &[]);
        self.app.update(Input::Event(Event::Error {
            code: code.to_owned(),
            message,
        }));
    }

    /// A command with nobody to take it: a message or a slash command says so and ends.
    fn no_session(&mut self, command: &Command) {
        let message = self.say("ui.no_worker", &[]);
        let code = match command {
            Command::UserMessage { .. } | Command::Slash { .. } => "command_failed",
            _ => return,
        };
        self.app.update(Input::Event(Event::Error {
            code: code.to_owned(),
            message,
        }));
    }

    fn login(&mut self, server: &str, key: &str, trust: bool) {
        // this client uses the packaged or configured address and no pinned certificate prompt
        if !server.is_empty() || trust {
            let message = self.say("login.no_server", &[("settings", "settings.json")]);
            let current = self.server.clone();
            self.ask_login(LoginReason::NoServer, &current, &message);
            return;
        }
        match account::login(&self.started, key, &*self.verifier) {
            Ok(saved) => {
                match decide(
                    &self.started.home,
                    &self.started.settings,
                    &self.started.env,
                ) {
                    Startup::Ready { server, key, .. } => self.open_session(&key, &server),
                    _ => self.begin(),
                }
                self.app.update(Input::Event(Event::Status {
                    kind: "notice".to_owned(),
                    data: serde_json::json!({ "text": saved })
                        .as_object()
                        .cloned()
                        .unwrap_or_default(),
                }));
            }
            Err(message) => {
                let server = self.server_for_form();
                self.ask_login(LoginReason::Rejected, &server, &message);
            }
        }
    }

    fn server_for_form(&self) -> String {
        if self.server.is_empty() {
            laris_config::settings::server_address(&self.started.settings.server.url)
        } else {
            self.server.clone()
        }
    }

    fn logout(&mut self) {
        let text = match account::logout(&self.started) {
            Ok(text) => text,
            Err(e) => e,
        };
        self.handle = None;
        self.server.clear();
        let signed_out = self.say("commands.signed_out", &[]);
        let server = self.server_for_form();
        self.ask_login(LoginReason::NoKey, &server, &format!("{text} {signed_out}"));
    }
}
