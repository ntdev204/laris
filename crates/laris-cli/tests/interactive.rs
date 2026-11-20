//! The interactive `laris` (T158, SR-C1, SR-C2): the controller, the session thread, the real local tools and the
//! real permission gate, with a scripted model and a person who types keys. No terminal is needed; the interface is
//! drawn as text. Every test has its own home and project.

#![allow(missing_docs)]

mod common;

use laris_cli::headless::real::SharedRegistry;
use laris_cli::headless::{Options, engine, parse};
use laris_cli::interactive::commands::{CommandSet, expand, parse as parse_command};
use laris_cli::interactive::control::{Controller, Starter};
use laris_cli::interactive::files;
use laris_cli::interactive::front::{Front, Wiring};
use laris_cli::interactive::worker::{Handle, spawn};
use laris_cli::start::{Started, start};
use laris_config::Catalogue;
use laris_core::{
    Driver, FollowModel, Model, ModelAnswer, ModelError, ModelRequest, Recorder, ScriptedModel,
};
use laris_policy::{PolicyGate, writes_of};
use laris_protocol::chat::Content;
use laris_protocol::chat::Role;
use laris_protocol::{Event, ToolCall, ToolCallFunction};
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use laris_tools::{Context, Registry};
use laris_tui::Key;
use serde_json::{Map, Value, json};
use std::cell::RefCell;
use std::path::PathBuf;
use std::rc::Rc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::Sender;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

// ---------------------------------------------------------------- the rig

fn fresh(name: &str) -> PathBuf {
    static COUNTER: AtomicUsize = AtomicUsize::new(0);
    let n = COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir =
        std::env::temp_dir().join(format!("laris-cli-t158-{name}-{}-{n}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir.canonicalize().expect("canonical")
}

struct Rig {
    base: PathBuf,
    project: PathBuf,
    started: Arc<Started>,
}

/// Most tests are about the approval flow, so their rig runs in the ask-first `default` mode; `auto` (the
/// settings' default) has its own rig.
const ASKING: (&str, &str) = ("LARIS_PERMISSIONS__DEFAULT_MODE", "default");

impl Rig {
    fn new(name: &str) -> Self {
        Self::with(name, Some(ASKING))
    }

    fn with(name: &str, extra: Option<(&str, &str)>) -> Self {
        let base = fresh(name);
        let project = base.join("project");
        std::fs::create_dir_all(project.join(".git")).unwrap();
        let mut env = vec![
            (
                "LARIS_HOME".to_owned(),
                base.join(".laris").to_string_lossy().into_owned(),
            ),
            (
                "LARIS_SERVER__URL".to_owned(),
                "https://scripted.example".to_owned(),
            ),
        ];
        env.extend(extra.map(|(k, v)| (k.to_owned(), v.to_owned())));
        let started = Arc::new(start(env, &project, None).expect("start"));
        Self {
            base,
            project,
            started,
        }
    }

    fn signed_in(name: &str) -> Self {
        Self::signed_in_with(name, Some(ASKING))
    }

    fn signed_in_with(name: &str, extra: Option<(&str, &str)>) -> Self {
        let mut rig = Self::with(name, extra);
        let mut env = vec![
            (
                "LARIS_HOME".to_owned(),
                rig.base.join(".laris").to_string_lossy().into_owned(),
            ),
            (
                "LARIS_SERVER__URL".to_owned(),
                "https://scripted.example".to_owned(),
            ),
            ("LARIS_API_KEY".to_owned(), "lk_test_key".to_owned()),
        ];
        env.extend(extra.map(|(k, v)| (k.to_owned(), v.to_owned())));
        rig.started = Arc::new(start(env, &rig.project, None).expect("start"));
        rig
    }
}

impl Drop for Rig {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.base).ok();
    }
}

fn call(id: &str, name: &str, arguments: Value) -> ToolCall {
    ToolCall {
        index: None,
        id: Some(id.to_owned()),
        kind: Default::default(),
        function: ToolCallFunction {
            name: name.to_owned(),
            arguments: arguments.to_string(),
            extra: Map::new(),
        },
        extra: Map::new(),
    }
}

fn say(text: &str) -> ModelAnswer {
    ModelAnswer {
        text: text.to_owned(),
        ..ModelAnswer::default()
    }
}

fn use_tool(calls: Vec<ToolCall>) -> ModelAnswer {
    ModelAnswer {
        text: String::new(),
        tool_calls: calls,
        usage: None,
    }
}

/// A scripted model that keeps the last user message of every request.
struct Watching {
    inner: ScriptedModel,
    users: Arc<Mutex<Vec<String>>>,
}

impl Model for Watching {
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        let last = request
            .messages
            .iter()
            .rev()
            .find(|m| m.role == Role::User)
            .and_then(|m| match &m.content {
                Some(Content::Text(t)) => Some(t.clone()),
                _ => None,
            })
            .unwrap_or_default();
        self.users.lock().unwrap().push(last);
        self.inner.answer(request)
    }
}

type Users = Arc<Mutex<Vec<String>>>;

/// The session thread over the real local tools and the real gate, with `answers` for a model.
fn scripted_handle(
    started: &Arc<Started>,
    answers: Vec<ModelAnswer>,
    users: Users,
    events: Sender<Event>,
) -> Handle {
    let started = Arc::clone(started);
    spawn(events, move |ports| {
        let args: Vec<String> = vec!["-p".to_owned()];
        let options: Options = parse(&args).unwrap().unwrap();
        let space = started
            .home
            .projects_dir()
            .join(laris_store::slug_of(&started.project));
        let ctx = Context::new(&started.project, &started.settings)
            .map_err(|e| e.to_string())?
            .with_checkpoints(space.join("checkpoints"));
        let scope = ctx.scope.clone();
        let registry = SharedRegistry(Rc::new(RefCell::new(Registry::with_local_tools(ctx))));
        let engine = Arc::new(engine(&started, &options, scope)?);
        let schemas = registry.0.borrow().schemas();
        let gate = PolicyGate::new(
            Arc::clone(&engine),
            writes_of(&registry.0.borrow()),
            ports.approver,
        );
        let words = Catalogue::new(started.settings.ui.language);
        let decider = FollowModel::new(started.settings.agent.clone(), words).with_gate(gate);
        let store = Store::open_space(
            started.home.root(),
            &started.project,
            None,
            DEFAULT_BUSY_TIMEOUT,
        )
        .map_err(|e| e.to_string())?;
        let id = format!("test-{}-{}", std::process::id(), rand_id());
        let (recorder, _) =
            Recorder::open(store, &id, "interactive", 1.0).map_err(|e| e.to_string())?;
        let meter = laris_cli::interactive::meter::Meter::new(1000, 0.8);
        let driver = Driver::new(
            recorder,
            laris_cli::interactive::meter::Metered::new(
                Watching {
                    inner: ScriptedModel::new(answers),
                    users,
                },
                meter.clone(),
                Rc::clone(&ports.emit),
            ),
            registry.clone(),
            decider,
            schemas,
            || 1.0,
        )
        .with_interrupt_flag(ports.interrupt);
        let commands = CommandSet::load(
            &started.home.commands_dir(),
            &started.project_folder().path().join("commands"),
            words,
        );
        Ok(Front::new(
            driver,
            Wiring {
                registry,
                engine,
                commands,
                words,
                project: started.project.clone(),
                note_file: started.project_folder().path().join("LARIS.md"),
                session: id,
                server: "https://scripted.example".to_owned(),
                waiting: ports.waiting,
                sandbox: false,
                emit: ports.emit,
                meter,
                remote: std::rc::Rc::new(|_| Err("no server in a test".to_owned())),
            },
        ))
    })
}

fn rand_id() -> usize {
    static N: AtomicUsize = AtomicUsize::new(0);
    N.fetch_add(1, Ordering::SeqCst)
}

fn controller(rig: &Rig, answers: Vec<ModelAnswer>) -> (Controller, Users) {
    let users: Users = Arc::default();
    let seen = Arc::clone(&users);
    let answers = Arc::new(Mutex::new(Some(answers)));
    let start: Starter = Box::new(move |started, _key, _server, events| {
        let answers = answers.lock().unwrap().take().unwrap_or_default();
        scripted_handle(started, answers, Arc::clone(&seen), events)
    });
    let c = Controller::new(
        Arc::clone(&rig.started),
        None,
        start,
        Box::new(common::Scripted::accepting("lk_good_key")),
    );
    (c, users)
}

fn type_text(c: &mut Controller, text: &str) {
    for ch in text.chars() {
        c.key(Key::Char(ch));
    }
}

fn send(c: &mut Controller, text: &str) {
    type_text(c, text);
    c.key(Key::Enter);
}

/// Pumps the session's events until `done` holds (or five seconds pass).
fn until(c: &mut Controller, what: &str, done: impl Fn(&Controller) -> bool) {
    let limit = Instant::now() + Duration::from_secs(5);
    loop {
        c.pump();
        if done(c) {
            return;
        }
        assert!(
            Instant::now() < limit,
            "waited for {what}; the screen is:\n{}",
            c.app.screen_text(80)
        );
        std::thread::sleep(Duration::from_millis(5));
    }
}

fn ready(c: &mut Controller) {
    until(c, "the session to be ready", |c| c.app.info().is_some());
}

fn idle(c: &mut Controller) {
    until(c, "the turn to end", |c| !c.app.running());
}

fn screen(c: &Controller) -> String {
    c.app.screen_text(100)
}

// ---------------------------------------------------------------- a turn

#[test]
fn a_message_runs_a_turn_and_the_answer_reaches_the_screen() {
    let rig = Rig::signed_in("turn");
    let (mut c, users) = controller(&rig, vec![say("The answer is 42.")]);
    ready(&mut c);
    assert!(screen(&c).contains("Laris"), "{}", screen(&c));
    send(&mut c, "what is the answer?");
    idle(&mut c);
    let text = screen(&c);
    assert!(text.contains("> what is the answer?"), "{text}");
    assert!(text.contains("● The answer is 42."), "{text}");
    assert_eq!(users.lock().unwrap().as_slice(), ["what is the answer?"]);
}

#[test]
fn typing_while_the_agent_works_queues_the_messages_in_order() {
    let rig = Rig::signed_in("queue");
    let (mut c, users) = controller(&rig, vec![say("one"), say("two"), say("three")]);
    ready(&mut c);
    send(&mut c, "first");
    send(&mut c, "second");
    send(&mut c, "third");
    until(&mut c, "all three answers", |c| {
        !c.app.running() && screen(c).contains("● three")
    });
    assert_eq!(
        users.lock().unwrap().as_slice(),
        ["first", "second", "third"]
    );
    let text = screen(&c);
    let at = |s: &str| {
        text.find(s)
            .unwrap_or_else(|| panic!("{s} missing:\n{text}"))
    };
    assert!(
        at("● one") < at("> second") && at("● two") < at("> third"),
        "{text}"
    );
}

// ---------------------------------------------------------------- approvals

fn write_call(id: &str, path: &str, content: &str) -> ToolCall {
    call(id, "Write", json!({"path": path, "content": content}))
}

#[test]
fn an_approved_write_happens_after_the_person_says_yes() {
    let rig = Rig::signed_in("approve");
    let (mut c, _) = controller(
        &rig,
        vec![
            use_tool(vec![write_call("w1", "a.txt", "hello")]),
            say("Done."),
        ],
    );
    ready(&mut c);
    send(&mut c, "write a note");
    until(&mut c, "the approval", |c| c.app.approval().is_some());
    let asking = screen(&c);
    assert!(asking.contains("Allow Write?"), "{asking}");
    assert!(
        !rig.project.join("a.txt").exists(),
        "nothing is written before the answer"
    );
    c.key(Key::Char('y'));
    idle(&mut c);
    assert_eq!(
        std::fs::read_to_string(rig.project.join("a.txt")).unwrap(),
        "hello"
    );
    assert!(screen(&c).contains("● Done."), "{}", screen(&c));
}

#[test]
fn in_auto_mode_the_default_a_write_happens_without_asking() {
    let rig = Rig::signed_in_with("auto-write", None);
    let (mut c, _) = controller(
        &rig,
        vec![
            use_tool(vec![write_call("w1", "a.txt", "hello")]),
            say("Done."),
        ],
    );
    ready(&mut c);
    send(&mut c, "write a note");
    idle(&mut c);
    assert!(c.app.approval().is_none(), "auto asks nothing for a write");
    assert_eq!(
        std::fs::read_to_string(rig.project.join("a.txt")).unwrap(),
        "hello"
    );
    let text = screen(&c);
    assert!(text.contains("● Done."), "{text}");
    assert!(
        text.contains("auto"),
        "the status line says the mode: {text}"
    );
}

#[test]
fn a_refused_write_does_not_happen_and_the_model_is_told() {
    let rig = Rig::signed_in("refuse");
    let (mut c, _) = controller(
        &rig,
        vec![
            use_tool(vec![write_call("w1", "a.txt", "hello")]),
            say("I could not write."),
        ],
    );
    ready(&mut c);
    send(&mut c, "write a note");
    until(&mut c, "the approval", |c| c.app.approval().is_some());
    c.key(Key::Esc);
    idle(&mut c);
    assert!(!rig.project.join("a.txt").exists());
    let text = screen(&c);
    assert!(
        text.contains("approval_denied"),
        "the model's tool result shows the refusal:\n{text}"
    );
    assert!(text.contains("● I could not write."), "{text}");
}

#[test]
fn allowing_for_the_session_is_remembered_and_the_second_write_is_not_asked() {
    let rig = Rig::signed_in("session");
    let (mut c, _) = controller(
        &rig,
        vec![
            use_tool(vec![write_call("w1", "a.txt", "one")]),
            use_tool(vec![write_call("w2", "a.txt", "two")]),
            say("Both written."),
        ],
    );
    ready(&mut c);
    send(&mut c, "write twice");
    until(&mut c, "the first approval", |c| c.app.approval().is_some());
    c.key(Key::Char('2'));
    idle(&mut c);
    assert_eq!(
        std::fs::read_to_string(rig.project.join("a.txt")).unwrap(),
        "two"
    );
    assert!(screen(&c).contains("● Both written."), "{}", screen(&c));
}

#[test]
fn the_request_carries_a_diff_of_the_change() {
    let rig = Rig::signed_in("diff");
    std::fs::write(rig.project.join("a.txt"), "old\n").unwrap();
    let (mut c, _) = controller(
        &rig,
        vec![
            use_tool(vec![call(
                "e1",
                "Edit",
                json!({"path": "a.txt", "old_string": "old", "new_string": "new"}),
            )]),
            say("Edited."),
        ],
    );
    ready(&mut c);
    send(&mut c, "edit it");
    until(&mut c, "the approval", |c| c.app.approval().is_some());
    let text = screen(&c);
    assert!(
        text.contains("-old") && text.contains("+new"),
        "the diff is shown:\n{text}"
    );
    c.key(Key::Enter);
    idle(&mut c);
    assert_eq!(
        std::fs::read_to_string(rig.project.join("a.txt")).unwrap(),
        "new\n"
    );
}

// ---------------------------------------------------------------- commands

#[test]
fn slash_help_lists_the_commands_and_an_unknown_command_says_so() {
    let rig = Rig::signed_in("help");
    let (mut c, users) = controller(&rig, vec![]);
    ready(&mut c);
    send(&mut c, "/help");
    idle(&mut c);
    let text = screen(&c);
    for name in [
        "/help", "/mode", "/rewind", "/status", "/login", "/logout", "/exit", "/clear",
    ] {
        assert!(text.contains(name), "{name} is in /help:\n{text}");
    }
    assert!(
        text.contains("@path") && text.contains("!command") && text.contains("# note"),
        "{text}"
    );
    send(&mut c, "/nope x y");
    idle(&mut c);
    assert!(
        screen(&c).contains("unknown_command: unknown command /nope"),
        "{}",
        screen(&c)
    );
    assert!(
        users.lock().unwrap().is_empty(),
        "no command reaches the model"
    );
}

#[test]
fn a_custom_command_sends_its_body_with_the_arguments() {
    let rig = Rig::signed_in("custom");
    let project_commands = rig.project.join(".laris/commands");
    std::fs::create_dir_all(project_commands.join("git")).unwrap();
    std::fs::write(
        project_commands.join("review.md"),
        "---\ndescription: Review a file\n---\nPlease review $1 and mention $2. All: $ARGUMENTS",
    )
    .unwrap();
    std::fs::write(project_commands.join("git/log.md"), "Show the log").unwrap();
    // a custom command never replaces a built-in one
    std::fs::write(project_commands.join("help.md"), "hijacked").unwrap();
    let (mut c, users) = controller(&rig, vec![say("Reviewed."), say("Logged.")]);
    ready(&mut c);
    send(&mut c, "/review src/a.rs speed");
    idle(&mut c);
    assert_eq!(
        users.lock().unwrap().as_slice(),
        ["Please review src/a.rs and mention speed. All: src/a.rs speed"]
    );
    send(&mut c, "/git:log -3");
    idle(&mut c);
    assert_eq!(users.lock().unwrap()[1], "Show the log\n\n-3");
    send(&mut c, "/help");
    idle(&mut c);
    let text = screen(&c);
    assert!(text.contains("/review — Review a file"), "{text}");
    assert!(!text.contains("hijacked"));
    // completion offers them
    c.app.clear_input();
    type_text(&mut c, "/rev");
    c.key(Key::Tab);
    until(&mut c, "the completion", |c| {
        c.app.input_text() == "/review "
    });
}

#[test]
fn the_mode_can_be_asked_set_and_cycled() {
    let rig = Rig::signed_in("mode");
    let (mut c, _) = controller(&rig, vec![]);
    ready(&mut c);
    send(&mut c, "/mode plan");
    idle(&mut c);
    assert!(
        screen(&c).contains("Permission mode: plan"),
        "{}",
        screen(&c)
    );
    assert!(
        screen(&c).contains("plan ·") || screen(&c).contains(" plan"),
        "{}",
        screen(&c)
    );
    send(&mut c, "/mode bogus");
    idle(&mut c);
    assert!(screen(&c).contains("Unknown mode bogus"), "{}", screen(&c));
    send(&mut c, "/mode bypass");
    idle(&mut c);
    assert!(
        screen(&c).contains("bypass mode is not allowed"),
        "{}",
        screen(&c)
    );
    // Shift+Tab: plan goes on to the next mode in the cycle (auto)
    c.key(Key::ShiftTab);
    until(&mut c, "the mode to change", |c| {
        screen(c).contains("Permission mode: auto")
    });
}

#[test]
fn bang_runs_a_shell_command_shows_it_and_tells_the_model_next_time() {
    let rig = Rig::signed_in("bang");
    let (mut c, users) = controller(&rig, vec![say("I saw it.")]);
    ready(&mut c);
    send(&mut c, "!echo hello-from-shell");
    idle(&mut c);
    let text = screen(&c);
    assert!(
        text.contains("● Bash(command: \"echo hello-from-shell\")"),
        "{text}"
    );
    assert!(text.contains("hello-from-shell"), "{text}");
    assert!(
        users.lock().unwrap().is_empty(),
        "the command alone does not call the model"
    );
    send(&mut c, "what did you see?");
    idle(&mut c);
    let sent = users.lock().unwrap()[0].clone();
    assert!(
        sent.contains("$ echo hello-from-shell") && sent.contains("hello-from-shell"),
        "{sent}"
    );
    assert!(sent.ends_with("what did you see?"), "{sent}");
    // an empty command is refused
    send(&mut c, "!");
    idle(&mut c);
    assert!(
        screen(&c).contains("Nothing to run after !"),
        "{}",
        screen(&c)
    );
}

#[test]
fn a_note_is_added_to_the_project_file_one_line_each() {
    let rig = Rig::signed_in("note");
    let (mut c, users) = controller(&rig, vec![]);
    ready(&mut c);
    send(&mut c, "# prefer small functions");
    idle(&mut c);
    send(&mut c, "#   use   snake_case ");
    idle(&mut c);
    let file = std::fs::read_to_string(rig.project.join(".laris/LARIS.md")).unwrap();
    assert_eq!(file, "- prefer small functions\n- use snake_case\n");
    assert!(screen(&c).contains("Noted in LARIS.md"), "{}", screen(&c));
    assert!(users.lock().unwrap().is_empty());
    send(&mut c, "#");
    idle(&mut c);
    assert!(
        screen(&c).contains("Nothing to note after #"),
        "{}",
        screen(&c)
    );
}

#[test]
fn at_path_attaches_the_file_and_completes_paths() {
    let rig = Rig::signed_in("at");
    std::fs::create_dir_all(rig.project.join("src")).unwrap();
    std::fs::write(rig.project.join("src/main.rs"), "fn main() {}\n").unwrap();
    std::fs::write(rig.project.join("src/lib.rs"), "// lib\n").unwrap();
    std::fs::write(rig.project.join(".env"), "SECRET=1\n").unwrap();
    let (mut c, users) = controller(&rig, vec![say("Read it.")]);
    ready(&mut c);
    send(&mut c, "explain @src/main.rs and @.env and @../outside");
    idle(&mut c);
    let sent = users.lock().unwrap()[0].clone();
    assert!(
        sent.contains("<file path=\"src/main.rs\">\nfn main() {}\n\n</file>"),
        "{sent}"
    );
    assert!(
        !sent.contains("SECRET"),
        "a secret file is never attached: {sent}"
    );
    assert!(
        screen(&c).contains("Attached: @src/main.rs"),
        "{}",
        screen(&c)
    );
    // completion: a folder, then its files
    c.app.clear_input();
    type_text(&mut c, "look at @sr");
    c.key(Key::Tab);
    until(&mut c, "the folder to complete", |c| {
        c.app.input_text() == "look at @src/"
    });
    c.key(Key::Tab);
    until(&mut c, "the menu", |c| c.app.menu().is_some());
    let items: Vec<String> = c
        .app
        .menu()
        .unwrap()
        .items
        .iter()
        .map(|i| i.value.clone())
        .collect();
    assert_eq!(items, ["src/lib.rs", "src/main.rs"]);
}

#[test]
fn rewind_restores_the_files_the_session_changed() {
    let rig = Rig::signed_in("rewind");
    std::fs::write(rig.project.join("a.txt"), "original").unwrap();
    let (mut c, _) = controller(
        &rig,
        vec![
            use_tool(vec![write_call("w1", "a.txt", "changed")]),
            say("Changed."),
        ],
    );
    ready(&mut c);
    send(&mut c, "/mode acceptEdits");
    idle(&mut c);
    send(&mut c, "change it");
    idle(&mut c);
    assert_eq!(
        std::fs::read_to_string(rig.project.join("a.txt")).unwrap(),
        "changed"
    );
    send(&mut c, "/rewind");
    idle(&mut c);
    assert_eq!(
        std::fs::read_to_string(rig.project.join("a.txt")).unwrap(),
        "original"
    );
    assert!(screen(&c).contains("Restored 1 files"), "{}", screen(&c));
    send(&mut c, "/rewind");
    idle(&mut c);
    assert!(
        screen(&c).contains("Nothing to rewind") || screen(&c).contains("no_checkpoints"),
        "{}",
        screen(&c)
    );
}

#[test]
fn status_names_the_session_and_the_server() {
    let rig = Rig::signed_in("status");
    let (mut c, _) = controller(&rig, vec![]);
    ready(&mut c);
    send(&mut c, "/status");
    idle(&mut c);
    let text = screen(&c);
    assert!(
        text.contains("https://scripted.example") && text.contains("mode default"),
        "{text}"
    );
}

// ---------------------------------------------------------------- signing in

#[test]
fn a_fresh_home_asks_for_the_key_in_the_interface_and_a_wrong_key_asks_again() {
    let rig = Rig::new("login");
    let (mut c, _) = controller(&rig, vec![say("Hi.")]);
    assert!(c.app.sign_in().is_some());
    assert!(!c.has_session());
    assert!(
        screen(&c).contains("Sign in to https://scripted.example"),
        "{}",
        screen(&c)
    );
    // a message before signing in is not possible: the form has the keyboard
    type_text(&mut c, "lk_wrong_key");
    assert!(!screen(&c).contains("lk_wrong"), "{}", screen(&c));
    c.key(Key::Enter);
    assert!(c.app.sign_in().is_some(), "the form stays open");
    assert!(
        screen(&c).contains("did not accept this key"),
        "{}",
        screen(&c)
    );
    assert!(!c.has_session());
    assert!(
        !rig.started.home.credentials_path().exists(),
        "a refused key is not saved"
    );
    type_text(&mut c, "lk_good_key");
    c.key(Key::Enter);
    assert!(c.has_session());
    ready(&mut c);
    assert!(
        c.app.sign_in().is_none(),
        "the form closes when the session is ready"
    );
    assert!(rig.started.home.credentials_path().exists());
    send(&mut c, "hello");
    idle(&mut c);
    assert!(screen(&c).contains("● Hi."), "{}", screen(&c));
    let saved = std::fs::read_to_string(rig.started.home.credentials_path()).unwrap();
    assert!(saved.contains("lk_good_key"));
    assert!(!screen(&c).contains("lk_good_key"));
}

#[test]
fn logout_removes_the_key_and_the_form_comes_back() {
    let rig = Rig::new("logout");
    let (mut c, _) = controller(&rig, vec![say("Hi.")]);
    type_text(&mut c, "lk_good_key");
    c.key(Key::Enter);
    ready(&mut c);
    assert!(rig.started.home.credentials_path().exists());
    send(&mut c, "/logout");
    assert!(!rig.started.home.credentials_path().exists());
    assert!(!c.has_session());
    assert!(c.app.sign_in().is_some());
    assert!(screen(&c).contains("Signed out"), "{}", screen(&c));
}

#[test]
fn a_session_that_cannot_start_says_why_instead_of_hanging() {
    let rig = Rig::signed_in("broken");
    let start: Starter = Box::new(|_, _, _, events| {
        spawn(
            events,
            |_ports| -> Result<Front<ScriptedModel, SharedRegistry>, String> {
                Err("the store is locked".to_owned())
            },
        )
    });
    let mut c = Controller::new(
        Arc::clone(&rig.started),
        None,
        start,
        Box::new(common::Scripted::accepting("x")),
    );
    until(&mut c, "the failure", |c| {
        screen(c).contains("the store is locked")
    });
    assert!(!c.has_session(), "the dead session is dropped");
    send(&mut c, "hello");
    assert!(screen(&c).contains("Not signed in"), "{}", screen(&c));
}

// ---------------------------------------------------------------- small parts

#[test]
fn a_command_file_has_a_header_a_body_and_arguments() {
    let c = parse_command(
        "fix",
        "---\ndescription: \"Fix it\"\n---\n\nFix $ARGUMENTS now\n",
        "user",
    );
    assert_eq!(
        (c.description.as_str(), c.body.as_str()),
        ("Fix it", "Fix $ARGUMENTS now")
    );
    let plain = parse_command("x", "# Title line\nbody", "user");
    assert_eq!(plain.description, "Title line");
    assert_eq!(expand("a $1 b $2 c $3", "one two"), "a one b two c ");
    assert_eq!(expand("no placeholder", "extra"), "no placeholder\n\nextra");
    assert_eq!(expand("no placeholder", ""), "no placeholder");
    assert_eq!(expand("$ARGUMENTS and $ARGUMENTS", "x y"), "x y and x y");
}

#[test]
fn path_references_are_the_words_that_start_with_at() {
    assert_eq!(
        files::references("see @a/b.rs, then @c.rs. email me@x.com @a/b.rs"),
        ["a/b.rs", "c.rs"]
    );
}

#[test]
fn the_person_closing_the_interface_refuses_a_waiting_approval() {
    use laris_cli::interactive::worker::ChannelApprover;
    use laris_policy::{Answer, ApprovalRequest, Approver};
    let (events, inbox) = std::sync::mpsc::channel();
    let (answers, answered) = std::sync::mpsc::channel();
    let approver = ChannelApprover::new(events, answered);
    let request = ApprovalRequest {
        tool: "Write".into(),
        arguments: Map::new(),
        reason: String::new(),
        suggested_rule: "Write".into(),
        preview: None,
    };
    drop(answers);
    assert_eq!(approver.approve(&request), Answer::Deny);
    assert!(matches!(
        inbox.try_recv(),
        Ok(Event::PermissionRequest { .. })
    ));
    // and with the whole interface gone
    drop(inbox);
    let (_keep, answered) = std::sync::mpsc::channel();
    let (events, inbox) = std::sync::mpsc::channel();
    drop(inbox);
    assert_eq!(
        ChannelApprover::new(events, answered).approve(&request),
        Answer::Deny
    );
}

#[test]
fn an_answer_to_an_older_request_does_not_answer_the_new_one() {
    use laris_cli::interactive::worker::ChannelApprover;
    use laris_policy::{Answer, ApprovalRequest, Approver};
    use laris_protocol::events::{Decision, Scope};
    let (events, inbox) = std::sync::mpsc::channel();
    let (answers, answered) = std::sync::mpsc::channel();
    let approver = ChannelApprover::new(events, answered);
    let request = ApprovalRequest {
        tool: "Write".into(),
        arguments: Map::new(),
        reason: String::new(),
        suggested_rule: String::new(),
        preview: None,
    };
    answers
        .send(("p0".into(), Decision::Allow, Scope::Everywhere))
        .unwrap();
    answers
        .send(("p1".into(), Decision::Allow, Scope::Once))
        .unwrap();
    assert_eq!(approver.approve(&request), Answer::Once);
    drop(inbox);
}

#[test]
fn every_built_in_command_and_input_form_is_in_the_guide() {
    let guide = std::fs::read_to_string(format!(
        "{}/../../docs/guide/CLIENT.md",
        env!("CARGO_MANIFEST_DIR")
    ))
    .expect("the guide");
    for (name, _) in laris_cli::interactive::commands::BUILTIN {
        assert!(
            guide.contains(&format!("`/{name}")),
            "/{name} is not in docs/guide/CLIENT.md"
        );
    }
    for form in [
        "`@path`",
        "`!command`",
        "`# note`",
        "Ctrl+R",
        "Shift+Tab",
        "Esc",
    ] {
        assert!(guide.contains(form), "{form} is not in the guide");
    }
}

#[cfg(unix)]
#[test]
fn links_in_the_commands_folder_and_in_paths_are_not_followed() {
    use std::os::unix::fs::symlink;
    let rig = Rig::new("links");
    let commands = rig.project.join(".laris/commands");
    std::fs::create_dir_all(&commands).unwrap();
    let outside = rig.base.join("outside.md");
    std::fs::write(&outside, "stolen").unwrap();
    symlink(&outside, commands.join("linked.md")).unwrap();
    std::fs::write(commands.join("plain.md"), "plain").unwrap();
    let set = CommandSet::load(
        &rig.started.home.commands_dir(),
        &commands,
        Catalogue::new(rig.started.settings.ui.language),
    );
    let names: Vec<&str> = set.custom().iter().map(|c| c.name.as_str()).collect();
    assert_eq!(names, ["plain"], "a link is not read");
    // a link inside the project that leads out is not attached or offered
    std::fs::write(rig.project.join("ok.txt"), "fine").unwrap();
    symlink(&outside, rig.project.join("leak.txt")).unwrap();
    let ctx = Context::new(&rig.project, &rig.started.settings).unwrap();
    let (text, notes) = files::attach(&ctx.scope, "see @ok.txt and @leak.txt");
    assert!(text.contains("fine") && !text.contains("stolen"), "{text}");
    assert_eq!(notes, ["@ok.txt"]);
    let offered: Vec<String> = files::complete(&ctx.scope, "")
        .into_iter()
        .map(|i| i.value)
        .collect();
    assert!(
        offered.contains(&"ok.txt".to_owned()) && !offered.contains(&"leak.txt".to_owned()),
        "{offered:?}"
    );
}

#[test]
fn a_huge_command_file_and_a_huge_attachment_are_left_out() {
    let rig = Rig::new("huge");
    let commands = rig.project.join(".laris/commands");
    std::fs::create_dir_all(&commands).unwrap();
    std::fs::write(commands.join("big.md"), "x".repeat(70 * 1024)).unwrap();
    std::fs::write(commands.join("small.md"), "ok").unwrap();
    let set = CommandSet::load(
        &rig.started.home.commands_dir(),
        &commands,
        Catalogue::new(rig.started.settings.ui.language),
    );
    assert_eq!(set.custom().len(), 1);
    std::fs::write(rig.project.join("big.txt"), "y".repeat(100 * 1024)).unwrap();
    let ctx = Context::new(&rig.project, &rig.started.settings).unwrap();
    let (text, notes) = files::attach(&ctx.scope, "read @big.txt");
    assert_eq!(text, "read @big.txt");
    assert!(notes.is_empty());
}

#[test]
fn context_usage_model_config_and_export_answer_from_what_the_session_knows() {
    let rig = Rig::signed_in("commands");
    let counted = ModelAnswer {
        text: "Forty-two.".to_owned(),
        usage: Some(laris_protocol::Usage {
            prompt_tokens: 150,
            completion_tokens: 50,
            total_tokens: 200,
            ..Default::default()
        }),
        ..ModelAnswer::default()
    };
    let (mut c, _users) = controller(&rig, vec![counted]);
    ready(&mut c);
    send(&mut c, "/context");
    idle(&mut c);
    assert!(screen(&c).contains("No answer yet"), "{}", screen(&c));
    send(&mut c, "/export");
    idle(&mut c);
    assert!(screen(&c).contains("Nothing to export"), "{}", screen(&c));
    send(&mut c, "what is the answer?");
    idle(&mut c);
    // the status line follows the usage event: 200 of 1000 tokens
    assert!(screen(&c).contains("context 20%"), "{}", screen(&c));
    send(&mut c, "/context");
    idle(&mut c);
    assert!(
        screen(&c).contains("200 / 1000 tokens (compacts at 80%)"),
        "{}",
        screen(&c)
    );
    send(&mut c, "/usage");
    idle(&mut c);
    let text = screen(&c);
    assert!(
        text.contains("150 prompt + 50 answer = 200 tokens in 1 requests"),
        "{text}"
    );
    assert!(text.contains("Cannot ask the server"), "{text}");
    send(&mut c, "/model");
    idle(&mut c);
    assert!(
        screen(&c).contains("Cannot ask the server"),
        "{}",
        screen(&c)
    );
    send(&mut c, "/config");
    idle(&mut c);
    assert!(
        screen(&c).contains("context window 1000 tokens"),
        "{}",
        screen(&c)
    );
    send(&mut c, "/export");
    idle(&mut c);
    assert!(screen(&c).contains("Saved to"), "{}", screen(&c));
}
