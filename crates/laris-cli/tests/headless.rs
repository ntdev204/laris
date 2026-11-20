//! `laris -p` (T156, SR-C5): every output format and every exit code, driven by a scripted model over the real
//! local tools, the real permission gate and a real session store; and the real path (the server's model and tools
//! over HTTP) against a small local server. Every test has its own home and project; none touches `~/.laris`.

#![allow(missing_docs)]

use laris_cli::headless::args::{Format, Resume, split_rules};

use laris_cli::headless::{
    Console, INPUT_LIMIT, MAX_TURNS, Options, Setup, engine, execute, exit, open_session, parse,
    read_request, real,
};
use laris_cli::start::{Started, start};
use laris_core::{Model, ModelAnswer, ModelError, ModelRequest, ScriptedModel, ToolRunner};
use laris_policy::{NoApprover, PolicyGate, writes_of};
use laris_protocol::{Event, ToolCall, ToolCallFunction, jsonl};
use laris_tools::{Context, Registry};
use serde_json::{Map, Value, json};
use std::cell::RefCell;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::rc::Rc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

// ---------------------------------------------------------------- the rig

fn fresh(name: &str) -> PathBuf {
    static COUNTER: AtomicUsize = AtomicUsize::new(0);
    let n = COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir =
        std::env::temp_dir().join(format!("laris-cli-t156-{name}-{}-{n}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir.canonicalize().expect("canonical")
}

#[derive(Clone, Default)]
struct Buf(Rc<RefCell<Vec<u8>>>);

impl Buf {
    fn text(&self) -> String {
        String::from_utf8_lossy(&self.0.borrow()).into_owned()
    }
}

impl Write for Buf {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0.borrow_mut().extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

struct Rig {
    base: PathBuf,
    project: PathBuf,
    started: Started,
}

impl Rig {
    fn new(name: &str) -> Self {
        Self::with_env(name, &[])
    }

    fn with_env(name: &str, extra: &[(&str, &str)]) -> Self {
        let base = fresh(name);
        let project = base.join("project");
        std::fs::create_dir_all(project.join(".git")).unwrap();
        let mut env = vec![(
            "LARIS_HOME".to_owned(),
            base.join(".laris").to_string_lossy().into_owned(),
        )];
        env.extend(
            extra
                .iter()
                .map(|(k, v)| ((*k).to_owned(), (*v).to_owned())),
        );
        let started = start(env, &project, None).expect("start");
        Self {
            base,
            project,
            started,
        }
    }
}

impl Drop for Rig {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.base).ok();
    }
}

struct Out {
    code: u8,
    out: String,
    err: String,
}

impl Out {
    fn events(&self) -> Vec<Event> {
        self.out
            .lines()
            .map(|l| jsonl::decode_event(l).unwrap_or_else(|e| panic!("{e}: {l}")))
            .collect()
    }

    fn json(&self) -> Value {
        serde_json::from_str(self.out.trim()).unwrap_or_else(|e| panic!("{e}: {}", self.out))
    }
}

fn options(args: &[&str]) -> Options {
    let args: Vec<String> = args.iter().map(|a| (*a).to_owned()).collect();
    parse(&args).expect("parse").expect("headless")
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

fn use_tool(text: &str, calls: Vec<ToolCall>) -> ModelAnswer {
    ModelAnswer {
        text: text.to_owned(),
        tool_calls: calls,
        usage: None,
    }
}

/// A scripted model that keeps how long the conversation was at each call.
struct Recording {
    inner: ScriptedModel,
    lengths: Rc<RefCell<Vec<usize>>>,
}

impl Model for Recording {
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        self.lengths.borrow_mut().push(request.messages.len());
        self.inner.answer(request)
    }
}

/// Runs `args` (after `-p`) with the scripted `answers` over the real local tools.
fn go(rig: &Rig, args: &[&str], answers: Vec<ModelAnswer>) -> Out {
    go_with(rig, args, answers, &Rc::default())
}

fn go_with(
    rig: &Rig,
    args: &[&str],
    answers: Vec<ModelAnswer>,
    lengths: &Rc<RefCell<Vec<usize>>>,
) -> Out {
    let mut all = vec!["-p"];
    all.extend_from_slice(args);
    let options = options(&all);
    let ctx = Context::new(&rig.project, &rig.started.settings).expect("context");
    let scope = ctx.scope.clone();
    let registry = Registry::with_local_tools(ctx);
    let engine = match engine(&rig.started, &options, scope) {
        Ok(engine) => Arc::new(engine),
        Err(message) => {
            return Out {
                code: exit::USAGE,
                out: String::new(),
                err: message,
            };
        }
    };
    let mode = laris_policy::mode_name(engine.mode()).to_owned();
    let schemas = registry.schemas();
    let gate = PolicyGate::new(engine, writes_of(&registry), NoApprover);
    let (out, err) = (Buf::default(), Buf::default());
    let mut console = Console {
        out: Box::new(out.clone()),
        err: Box::new(err.clone()),
    };
    let session = match open_session(&rig.started, &options, &mut console) {
        Ok(session) => session,
        Err(code) => {
            return Out {
                code,
                out: out.text(),
                err: err.text(),
            };
        }
    };
    let setup = Setup {
        started: &rig.started,
        server: "https://scripted.example/v1".to_owned(),
    };
    let model = Recording {
        inner: ScriptedModel::new(answers),
        lengths: Rc::clone(lengths),
    };
    let code = execute(
        &setup, &options, "do it", model, registry, schemas, gate, &mode, session, console,
    );
    Out {
        code,
        out: out.text(),
        err: err.text(),
    }
}

fn tool_results(events: &[Event]) -> Vec<(String, Value)> {
    events
        .iter()
        .filter_map(|e| match e {
            Event::ToolResult { name, result, .. } => Some((name.clone(), result.clone())),
            _ => None,
        })
        .collect()
}

// ---------------------------------------------------------------- the formats

#[test]
fn text_prints_only_the_answer_and_exits_zero() {
    let rig = Rig::new("text");
    let out = go(&rig, &[], vec![say("The answer is 42.")]);
    assert_eq!(out.code, exit::OK);
    assert_eq!(out.out, "The answer is 42.\n");
    assert_eq!(out.err, "");
}

#[test]
fn json_is_one_object_that_says_what_happened() {
    let rig = Rig::new("json");
    let mut answer = say("done");
    answer.usage = Some(laris_protocol::Usage {
        prompt_tokens: 7,
        completion_tokens: 3,
        total_tokens: 10,
        ..Default::default()
    });
    let out = go(&rig, &["--output-format", "json"], vec![answer]);
    assert_eq!(out.code, exit::OK);
    assert_eq!(out.out.lines().count(), 1, "one object, one line");
    let value = out.json();
    assert_eq!(value["type"], "result");
    assert_eq!(value["status"], "completed");
    assert_eq!(value["isError"], false);
    assert_eq!(value["result"], "done");
    assert_eq!(value["modelCalls"], 1);
    assert_eq!(value["usage"]["totalTokens"], 10);
    assert_eq!(value["exitCode"], 0);
    assert!(value["session"].as_str().unwrap().starts_with("headless-"));
}

#[test]
fn stream_json_is_the_core_events_one_per_line() {
    let rig = Rig::new("stream");
    std::fs::write(rig.project.join("notes.txt"), "hello").unwrap();
    let out = go(
        &rig,
        &["--output-format=stream-json", "--allowedTools", "Read"],
        vec![
            use_tool("", vec![call("c1", "Read", json!({"path": "notes.txt"}))]),
            say("It says hello."),
        ],
    );
    assert_eq!(out.code, exit::OK, "{}", out.err);
    let events = out.events();
    let Some(Event::Ready {
        version,
        session,
        mode,
        ..
    }) = events.first()
    else {
        panic!("the first line must be ready: {events:?}");
    };
    assert_eq!(version, "1");
    assert!(session.starts_with("headless-"));
    assert_eq!(mode, "auto", "auto is the default mode");
    let Some(Event::Done { status, answer }) = events.last() else {
        panic!("the last line must be done: {events:?}");
    };
    assert_eq!(
        (status.as_str(), answer.as_str()),
        ("completed", "It says hello.")
    );
    let call = events
        .iter()
        .position(|e| matches!(e, Event::ToolCall { .. }))
        .unwrap();
    let result = events
        .iter()
        .position(|e| matches!(e, Event::ToolResult { .. }))
        .unwrap();
    assert!(call < result);
    assert!(out.out.ends_with('\n'));
}

/// Peeks at standard output when a tool runs, to show that the lines were written before the turn ended.
struct Peek {
    out: Buf,
    seen: Rc<RefCell<Vec<String>>>,
}

impl ToolRunner for Peek {
    fn run(&mut self, _name: &str, _arguments: &Map<String, Value>) -> Value {
        self.seen.borrow_mut().push(self.out.text());
        json!({"content": "x"})
    }
}

#[test]
fn stream_json_is_written_while_the_turn_runs() {
    let rig = Rig::new("live");
    let options = options(&[
        "-p",
        "--output-format",
        "stream-json",
        "--allowedTools",
        "Read",
    ]);
    let ctx = Context::new(&rig.project, &rig.started.settings).unwrap();
    let scope = ctx.scope.clone();
    let registry = Registry::with_local_tools(ctx);
    let schemas = registry.schemas();
    let engine = Arc::new(engine(&rig.started, &options, scope).unwrap());
    let gate = PolicyGate::new(engine, writes_of(&registry), NoApprover);
    let (out, err) = (Buf::default(), Buf::default());
    let mut console = Console {
        out: Box::new(out.clone()),
        err: Box::new(err),
    };
    let session = open_session(&rig.started, &options, &mut console).unwrap();
    let seen = Rc::new(RefCell::new(Vec::new()));
    let tools = Peek {
        out: out.clone(),
        seen: Rc::clone(&seen),
    };
    let model = ScriptedModel::new(vec![
        use_tool("", vec![call("c1", "Read", json!({"path": "a.txt"}))]),
        say("ok"),
    ]);
    let setup = Setup {
        started: &rig.started,
        server: String::new(),
    };
    let code = execute(
        &setup, &options, "go", model, tools, schemas, gate, "default", session, console,
    );
    assert_eq!(code, exit::OK);
    let seen = seen.borrow();
    assert_eq!(seen.len(), 1);
    assert!(seen[0].contains("\"type\":\"ready\""), "{}", seen[0]);
    assert!(seen[0].contains("\"type\":\"tool_call\""), "{}", seen[0]);
    assert!(!seen[0].contains("\"type\":\"done\""), "{}", seen[0]);
}

// ---------------------------------------------------------------- permissions

fn write_call() -> ModelAnswer {
    use_tool(
        "",
        vec![call(
            "w1",
            "Write",
            json!({"path": "out.txt", "content": "hi"}),
        )],
    )
}

#[test]
fn a_write_that_needs_approval_is_refused_because_nobody_can_answer() {
    let rig = Rig::new("refused");
    let out = go(
        &rig,
        &[
            "--output-format",
            "stream-json",
            "--permission-mode",
            "default",
        ],
        vec![write_call(), say("could not write")],
    );
    assert_eq!(out.code, exit::OK);
    assert!(!rig.project.join("out.txt").exists());
    let results = tool_results(&out.events());
    assert_eq!(results[0].0, "Write");
    assert_eq!(results[0].1["error"]["code"], "approval_denied");
}

#[test]
fn in_auto_mode_a_write_runs_without_asking() {
    let rig = Rig::new("auto-writes");
    let out = go(
        &rig,
        &["--output-format", "stream-json"],
        vec![write_call(), say("written")],
    );
    assert_eq!(out.code, exit::OK, "{}", out.err);
    assert_eq!(
        std::fs::read_to_string(rig.project.join("out.txt")).expect("written"),
        "hi"
    );
}

#[test]
fn in_auto_mode_a_destructive_command_is_still_refused_when_nobody_can_answer() {
    let rig = Rig::new("auto-guard");
    let out = go(
        &rig,
        &["--output-format", "stream-json"],
        vec![
            use_tool(
                "",
                vec![call(
                    "b1",
                    "Bash",
                    json!({"command": "git push origin main"}),
                )],
            ),
            say("could not push"),
        ],
    );
    assert_eq!(out.code, exit::OK, "{}", out.err);
    let results = tool_results(&out.events());
    assert_eq!(results[0].1["error"]["code"], "approval_denied");
}

#[test]
fn allowed_tools_and_accept_edits_let_a_write_through_and_deny_still_wins() {
    let rig = Rig::new("allowed");
    let out = go(
        &rig,
        &["--allowedTools", "Write"],
        vec![write_call(), say("written")],
    );
    assert_eq!(out.code, exit::OK, "{}", out.err);
    assert_eq!(
        std::fs::read_to_string(rig.project.join("out.txt")).unwrap(),
        "hi"
    );

    let rig = Rig::new("accept-edits");
    let out = go(
        &rig,
        &["--permission-mode", "acceptEdits"],
        vec![write_call(), say("written")],
    );
    assert_eq!(out.code, exit::OK, "{}", out.err);
    assert!(rig.project.join("out.txt").exists());

    let rig = Rig::new("deny-wins");
    let out = go(
        &rig,
        &[
            "--output-format",
            "stream-json",
            "--allowedTools",
            "Write",
            "--disallowedTools",
            "Write",
        ],
        vec![write_call(), say("refused")],
    );
    assert!(!rig.project.join("out.txt").exists());
    assert_eq!(
        tool_results(&out.events())[0].1["error"]["code"],
        "permission_denied"
    );
}

#[test]
fn plan_mode_writes_nothing_and_bypass_is_not_available() {
    let rig = Rig::new("plan");
    let out = go(
        &rig,
        &[
            "--permission-mode",
            "plan",
            "--allowedTools",
            "Write",
            "--output-format",
            "stream-json",
        ],
        vec![write_call(), say("planned")],
    );
    assert!(!rig.project.join("out.txt").exists());
    assert_eq!(
        tool_results(&out.events())[0].1["error"]["code"],
        "permission_denied"
    );

    let rig = Rig::new("bypass");
    let out = go(&rig, &["--permission-mode", "bypass"], vec![say("x")]);
    assert_eq!(out.code, exit::USAGE);
    assert!(out.err.contains("bypass"), "{}", out.err);
    assert!(!rig.project.join("out.txt").exists());
}

#[test]
fn a_rule_that_is_not_a_rule_is_a_usage_error() {
    let rig = Rig::new("badrule");
    let out = go(&rig, &["--allowedTools", "(("], vec![say("x")]);
    assert_eq!(out.code, exit::USAGE);
    assert!(out.err.contains("not a rule"), "{}", out.err);
}

// ---------------------------------------------------------------- exit codes

#[test]
fn the_turn_limit_exits_four_and_says_so_in_every_format() {
    let calls = |n: usize| {
        (0..n)
            .map(|i| {
                use_tool(
                    "",
                    vec![call(
                        &format!("g{i}"),
                        "Glob",
                        json!({"pattern": format!("*.t{i}")}),
                    )],
                )
            })
            .collect::<Vec<_>>()
    };
    let rig = Rig::new("limit-text");
    let out = go(
        &rig,
        &["--max-turns", "2", "--allowedTools", "Glob"],
        calls(4),
    );
    assert_eq!(out.code, exit::TURN_LIMIT);
    assert_eq!(out.out, "", "no answer on standard output");
    assert!(out.err.contains("max_steps"), "{}", out.err);

    let rig = Rig::new("limit-json");
    let out = go(
        &rig,
        &[
            "--max-turns",
            "2",
            "--allowedTools",
            "Glob",
            "--output-format",
            "json",
        ],
        calls(4),
    );
    assert_eq!(out.code, exit::TURN_LIMIT);
    let value = out.json();
    assert_eq!(value["status"], "max_steps");
    assert_eq!(value["isError"], true);
    assert_eq!(value["exitCode"], 4);
    assert_eq!(value["modelCalls"], 2);

    let rig = Rig::new("limit-stream");
    let out = go(
        &rig,
        &[
            "--max-turns",
            "2",
            "--allowedTools",
            "Glob",
            "--output-format",
            "stream-json",
        ],
        calls(4),
    );
    assert_eq!(out.code, exit::TURN_LIMIT);
    assert!(
        matches!(out.events().last(), Some(Event::Done { status, .. }) if status == "max_steps")
    );
}

#[test]
fn a_model_that_fails_exits_one() {
    let rig = Rig::new("failed");
    let out = go(&rig, &[], vec![]);
    assert_eq!(out.code, exit::FAILED);
    assert_eq!(out.out, "");
    assert!(out.err.contains("provider_error"), "{}", out.err);

    let rig = Rig::new("failed-json");
    let out = go(&rig, &["--output-format", "json"], vec![]);
    assert_eq!(out.code, exit::FAILED);
    assert_eq!(out.json()["status"], "provider_error");
    assert_eq!(out.json()["exitCode"], 1);
}

#[test]
fn a_bad_turn_limit_is_a_usage_error_before_anything_runs() {
    for bad in ["0", "11", "many", "-1", ""] {
        let rig = Rig::new("turns");
        let out = go(&rig, &["--max-turns", bad], vec![say("x")]);
        assert_eq!(out.code, exit::USAGE, "{bad:?}");
        assert!(out.err.contains(&MAX_TURNS.to_string()), "{}", out.err);
        assert_eq!(out.out, "");
    }
    let rig = Rig::new("turns-json");
    let out = go(
        &rig,
        &["--max-turns", "0", "--output-format", "json"],
        vec![say("x")],
    );
    assert_eq!(out.json()["status"], "usage");
    assert_eq!(out.json()["exitCode"], 2);
    // and nothing was recorded: the store has no session
    assert!(
        laris_store::Store::open_space(
            rig.started.home.root(),
            &rig.started.project,
            None,
            laris_store::DEFAULT_BUSY_TIMEOUT
        )
        .unwrap()
        .sessions()
        .unwrap()
        .is_empty()
    );
}

// ---------------------------------------------------------------- resume and continue

fn session_of(out: &Out) -> String {
    out.json()["session"].as_str().unwrap().to_owned()
}

#[test]
fn resume_and_continue_carry_the_conversation() {
    let rig = Rig::new("resume");
    let lengths = Rc::new(RefCell::new(Vec::new()));
    let first = go_with(
        &rig,
        &["--output-format", "json"],
        vec![say("one")],
        &lengths,
    );
    assert_eq!(first.code, exit::OK);
    let id = session_of(&first);

    let second = go_with(
        &rig,
        &["--output-format", "json", "--resume", &id],
        vec![say("two")],
        &lengths,
    );
    assert_eq!(second.code, exit::OK);
    assert_eq!(session_of(&second), id);

    let third = go_with(
        &rig,
        &["-c", "--output-format", "json"],
        vec![say("three")],
        &lengths,
    );
    assert_eq!(third.code, exit::OK);
    assert_eq!(session_of(&third), id, "continue picks the latest session");

    let seen = lengths.borrow();
    assert_eq!(seen.len(), 3);
    assert!(
        seen[1] > seen[0] && seen[2] > seen[1],
        "the conversation grows: {seen:?}"
    );

    // a new run is a new session, and continue then picks that one
    let other = go(&rig, &["--output-format", "json"], vec![say("fresh")]);
    assert_ne!(session_of(&other), id);
    let next = go(
        &rig,
        &["--continue", "--output-format", "json"],
        vec![say("again")],
    );
    assert_eq!(session_of(&next), session_of(&other));
}

#[test]
fn a_session_that_does_not_exist_exits_five() {
    let rig = Rig::new("nosession");
    let out = go(&rig, &["--continue"], vec![say("x")]);
    assert_eq!(out.code, exit::NO_SESSION);
    assert!(out.err.contains("no earlier session"), "{}", out.err);

    let out = go(
        &rig,
        &["--resume", "headless-nothing", "--output-format", "json"],
        vec![say("x")],
    );
    assert_eq!(out.code, exit::NO_SESSION);
    assert_eq!(out.json()["status"], "no_session");

    let out = go(
        &rig,
        &[
            "--resume",
            "headless-nothing",
            "--output-format",
            "stream-json",
        ],
        vec![say("x")],
    );
    assert_eq!(out.code, exit::NO_SESSION);
    assert!(matches!(&out.events()[..], [Event::Error { code, .. }] if code == "no_session"));
    // none of it created a session
    assert!(
        laris_store::Store::open_space(
            rig.started.home.root(),
            &rig.started.project,
            None,
            laris_store::DEFAULT_BUSY_TIMEOUT
        )
        .unwrap()
        .sessions()
        .unwrap()
        .is_empty()
    );
}

#[test]
fn a_session_killed_in_the_middle_of_a_turn_finishes_it_when_resumed() {
    // the first run's model gives out after asking for a tool: the turn is left open in the log
    let rig = Rig::new("killed");
    let first = go(
        &rig,
        &["--output-format", "json", "--allowedTools", "Glob"],
        vec![use_tool(
            "",
            vec![call("g1", "Glob", json!({"pattern": "*.md"}))],
        )],
    );
    assert_eq!(first.code, exit::FAILED);
    let id = session_of(&first);
    let second = go(
        &rig,
        &["--resume", &id, "--output-format", "json"],
        vec![say("recovered")],
    );
    assert_eq!(second.code, exit::OK, "{} {}", second.out, second.err);
    assert_eq!(second.json()["result"], "recovered");
}

// ---------------------------------------------------------------- the command line and the input

fn strings(args: &[&str]) -> Vec<String> {
    args.iter().map(|a| (*a).to_owned()).collect()
}

#[test]
fn the_command_line_is_parsed_the_way_it_is_documented() {
    assert_eq!(parse(&strings(&["login"])).unwrap(), None);
    assert_eq!(parse(&strings(&[])).unwrap(), None);

    let o = options(&["-p", "list", "the", "files"]);
    assert_eq!(o.prompt.as_deref(), Some("list the files"));
    assert_eq!((o.format, o.resume.clone()), (Format::Text, Resume::New));

    let o = options(&["--output-format=json", "--print", "--resume=abc", "hi"]);
    assert_eq!(
        (o.format, o.resume),
        (Format::Json, Resume::Session("abc".into()))
    );

    let o = options(&[
        "-p",
        "-c",
        "--max-turns",
        "3",
        "--permission-mode",
        "acceptEdits",
    ]);
    assert_eq!(o.resume, Resume::Continue);
    assert_eq!(o.max_turns.as_deref(), Some("3"));
    assert_eq!(o.prompt, None);

    let o = options(&[
        "-p",
        "--allowedTools",
        "Read,Bash(git log --oneline) Glob",
        "--allowed-tools",
        "Grep",
        "--disallowedTools=Write(secret/**)",
        "--",
        "--not-a-flag",
    ]);
    assert_eq!(
        o.allowed,
        ["Read", "Bash(git log --oneline)", "Glob", "Grep"]
    );
    assert_eq!(o.disallowed, ["Write(secret/**)"]);
    assert_eq!(o.prompt.as_deref(), Some("--not-a-flag"));
    assert_eq!(split_rules("a, b(c, d),e"), ["a", "b(c, d)", "e"]);

    for bad in [
        vec!["-p", "--output-format", "yaml"],
        vec!["-p", "--permission-mode", "sudo"],
        vec!["-p", "--continue", "--resume", "x"],
        vec!["-p", "--resume"],
        vec!["-p", "--nope"],
    ] {
        assert!(parse(&strings(&bad)).is_err(), "{bad:?}");
    }
}

#[test]
fn the_request_is_the_argument_the_input_or_both() {
    let rig = Rig::new("input");
    let mut piped: &[u8] = b"  data from a pipe \n";
    assert_eq!(
        read_request(
            &rig.started,
            Some("summarise"),
            Some(&mut piped as &mut dyn Read)
        )
        .unwrap(),
        "summarise\n\ndata from a pipe"
    );
    let mut piped: &[u8] = b"only the pipe";
    assert_eq!(
        read_request(&rig.started, None, Some(&mut piped as &mut dyn Read)).unwrap(),
        "only the pipe"
    );
    assert_eq!(
        read_request(&rig.started, Some("just the argument"), None).unwrap(),
        "just the argument"
    );
    let mut empty: &[u8] = b" \n";
    assert!(
        read_request(&rig.started, Some("  "), Some(&mut empty as &mut dyn Read))
            .unwrap_err()
            .contains("No request")
    );
    assert!(
        read_request(&rig.started, None, None)
            .unwrap_err()
            .contains("-p")
    );
    let mut binary: &[u8] = &[0xff, 0xfe, 0x00];
    assert!(
        read_request(&rig.started, None, Some(&mut binary as &mut dyn Read))
            .unwrap_err()
            .contains("not text")
    );
    let mut huge = std::io::repeat(b'a').take(INPUT_LIMIT as u64 + 10);
    assert!(
        read_request(&rig.started, None, Some(&mut huge as &mut dyn Read))
            .unwrap_err()
            .contains("larger")
    );
}

// ---------------------------------------------------------------- not signed in

#[test]
fn without_a_server_or_a_key_nothing_is_asked_and_the_exit_code_is_three() {
    // no server at all
    let rig = Rig::new("nosrv");
    let (out, err) = (Buf::default(), Buf::default());
    let code = real::run(
        &rig.started,
        &options(&["-p", "hi", "--output-format", "json"]),
        None,
        Console {
            out: Box::new(out.clone()),
            err: Box::new(err.clone()),
        },
    );
    assert_eq!(code, exit::NOT_SIGNED_IN);
    let value: Value = serde_json::from_str(out.text().trim()).unwrap();
    assert_eq!(
        (value["status"].as_str(), value["exitCode"].as_u64()),
        (Some("login_required"), Some(3))
    );
    assert!(err.text().contains("No server address"), "{}", err.text());

    // a server but no key, in the stream format
    let rig = Rig::with_env("nokey", &[("LARIS_SERVER__URL", "http://127.0.0.1:9/v1")]);
    let (out, err) = (Buf::default(), Buf::default());
    let code = real::run(
        &rig.started,
        &options(&["-p", "hi", "--output-format", "stream-json"]),
        None,
        Console {
            out: Box::new(out.clone()),
            err: Box::new(err.clone()),
        },
    );
    assert_eq!(code, exit::NOT_SIGNED_IN);
    let events: Vec<Event> = out
        .text()
        .lines()
        .map(|l| jsonl::decode_event(l).unwrap())
        .collect();
    assert!(
        matches!(&events[..], [Event::LoginRequired { server, .. }] if server.contains("127.0.0.1:9"))
    );
    assert!(err.text().contains("laris login"), "{}", err.text());

    // no request: a usage error, before the server is looked at
    let (out, err) = (Buf::default(), Buf::default());
    let code = real::run(
        &rig.started,
        &options(&["-p"]),
        None,
        Console {
            out: Box::new(out),
            err: Box::new(err.clone()),
        },
    );
    assert_eq!(code, exit::USAGE);
    assert!(err.text().contains("No request"));
}

// ---------------------------------------------------------------- the real path

const KEY: &str = "laris-test-key-headless-0001";

/// What the local server was asked.
#[derive(Default)]
struct Seen {
    requests: Mutex<Vec<(String, String, String)>>,
}

/// A server that answers `GET /v1/laris/tools` with 404 and `POST /v1/laris/chat` with the given stream.
fn serve(stream: &'static str) -> (u16, Arc<Seen>, Arc<std::sync::atomic::AtomicBool>) {
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    let seen = Arc::new(Seen::default());
    let stop = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let (seen_in, stop_in) = (Arc::clone(&seen), Arc::clone(&stop));
    std::thread::spawn(move || {
        for connection in listener.incoming() {
            if stop_in.load(Ordering::SeqCst) {
                break;
            }
            if let Ok(connection) = connection {
                answer(connection, stream, &seen_in);
            }
        }
    });
    (port, seen, stop)
}

fn answer(mut connection: TcpStream, stream: &str, seen: &Seen) {
    let mut bytes = Vec::new();
    let mut buf = [0u8; 4096];
    let (head_end, length) = loop {
        match connection.read(&mut buf) {
            Ok(0) | Err(_) => return,
            Ok(n) => bytes.extend_from_slice(&buf[..n]),
        }
        if let Some(at) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
            let head = String::from_utf8_lossy(&bytes[..at]).to_ascii_lowercase();
            let length = head
                .lines()
                .find_map(|l| {
                    l.strip_prefix("content-length:")
                        .map(|v| v.trim().parse::<usize>().unwrap_or(0))
                })
                .unwrap_or(0);
            break (at + 4, length);
        }
    };
    while bytes.len() < head_end + length {
        match connection.read(&mut buf) {
            Ok(0) | Err(_) => break,
            Ok(n) => bytes.extend_from_slice(&buf[..n]),
        }
    }
    let head = String::from_utf8_lossy(&bytes[..head_end]).into_owned();
    let body = String::from_utf8_lossy(&bytes[head_end..]).into_owned();
    let first = head.lines().next().unwrap_or("").to_owned();
    let auth = head
        .lines()
        .find(|l| l.to_ascii_lowercase().starts_with("authorization:"))
        .unwrap_or("")
        .to_owned();
    seen.requests
        .lock()
        .unwrap()
        .push((first.clone(), auth, body));
    let (status, kind, payload) = if first.starts_with("POST /v1/laris/chat ") {
        ("200 OK", "text/event-stream", stream.to_owned())
    } else {
        (
            "404 Not Found",
            "application/json",
            r#"{"error":"no such route"}"#.to_owned(),
        )
    };
    let reply = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {kind}\r\nX-Laris-Protocol: 2\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{payload}",
        payload.len()
    );
    let _ = connection.write_all(reply.as_bytes());
    let _ = connection.flush();
}

const ANSWER_STREAM: &str = "data: {\"id\":\"c1\",\"object\":\"chat.completion.chunk\",\"model\":\"m\",\"choices\":[{\"index\":0,\"delta\":{\"content\":\"Served by the model.\"}}]}\n\ndata: {\"id\":\"c1\",\"object\":\"chat.completion.chunk\",\"model\":\"m\",\"choices\":[{\"index\":0,\"delta\":{},\"finish_reason\":\"stop\"}]}\n\ndata: {\"id\":\"c1\",\"object\":\"chat.completion.chunk\",\"model\":\"m\",\"choices\":[],\"usage\":{\"prompt_tokens\":5,\"completion_tokens\":4,\"total_tokens\":9}}\n\ndata: [DONE]\n\n";

const BROKEN_STREAM: &str = "data: {\"error\":{\"message\":\"the model fell over\",\"type\":\"backend_error\"}}\n\ndata: [DONE]\n\n";

fn run_real(rig: &Rig, args: &[&str], input: Option<&[u8]>) -> Out {
    let (out, err) = (Buf::default(), Buf::default());
    let mut piped = input;
    let input = piped.as_mut().map(|p| p as &mut dyn Read);
    let code = real::run(
        &rig.started,
        &options(args),
        input,
        Console {
            out: Box::new(out.clone()),
            err: Box::new(err.clone()),
        },
    );
    Out {
        code,
        out: out.text(),
        err: err.text(),
    }
}

#[test]
fn the_real_path_asks_the_server_with_the_key_and_prints_the_answer() {
    let (port, seen, stop) = serve(ANSWER_STREAM);
    let url = format!("http://127.0.0.1:{port}/v1");
    let rig = Rig::with_env(
        "real",
        &[("LARIS_SERVER__URL", &url), ("LARIS_API_KEY", KEY)],
    );
    let out = run_real(&rig, &["-p", "what is this?"], Some(b"file contents"));
    stop.store(true, Ordering::SeqCst);
    let _ = TcpStream::connect(("127.0.0.1", port));
    assert_eq!(out.code, exit::OK, "{}", out.err);
    assert_eq!(out.out, "Served by the model.\n");
    assert!(out.err.contains("remote tools left out"), "{}", out.err);

    let requests = seen.requests.lock().unwrap();
    let chat = requests
        .iter()
        .find(|(first, ..)| first.starts_with("POST /v1/laris/chat"))
        .expect("a chat request");
    assert_eq!(
        chat.1.to_ascii_lowercase(),
        format!("authorization: bearer {KEY}").to_ascii_lowercase()
    );
    let body: Value = serde_json::from_str(&chat.2).unwrap();
    assert_eq!(body["laris"]["kind"], "turn");
    assert!(
        body["laris"]["session_id"]
            .as_str()
            .unwrap()
            .starts_with("headless-")
    );
    let sent = body["messages"].to_string();
    assert!(
        sent.contains("what is this?") && sent.contains("file contents"),
        "{sent}"
    );
    let tools: Vec<&str> = body["tools"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|t| t["function"]["name"].as_str())
        .collect();
    for name in ["Read", "Write", "Edit", "Glob", "Grep", "Bash"] {
        assert!(tools.contains(&name), "{name} not offered: {tools:?}");
    }
    assert!(
        !chat.2.contains(KEY),
        "the key must never be in a request body"
    );
}

#[test]
fn the_real_path_exits_one_when_the_model_stream_breaks() {
    let (port, _seen, stop) = serve(BROKEN_STREAM);
    let url = format!("http://127.0.0.1:{port}/v1");
    let rig = Rig::with_env(
        "broken",
        &[("LARIS_SERVER__URL", &url), ("LARIS_API_KEY", KEY)],
    );
    let out = run_real(&rig, &["-p", "hi", "--output-format", "json"], None);
    stop.store(true, Ordering::SeqCst);
    let _ = TcpStream::connect(("127.0.0.1", port));
    assert_eq!(out.code, exit::FAILED);
    assert_eq!(out.json()["status"], "provider_error");
    assert!(!out.out.contains(KEY) && !out.err.contains(KEY));
}

// ---------------------------------------------------------------- the compiled binary

fn binary(rig: &Rig, args: &[&str], stdin: &str, env: &[(&str, &str)]) -> std::process::Output {
    use std::process::{Command, Stdio};
    let mut child = Command::new(env!("CARGO_BIN_EXE_laris"))
        .args(args)
        .current_dir(&rig.project)
        .env_clear()
        .env("PATH", std::env::var("PATH").unwrap_or_default())
        .env("HOME", &rig.base)
        .env("LARIS_HOME", rig.base.join(".laris"))
        .envs(env.iter().copied())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn laris");
    child
        .stdin
        .take()
        .unwrap()
        .write_all(stdin.as_bytes())
        .unwrap();
    child.wait_with_output().unwrap()
}

#[test]
fn the_binary_reads_a_pipe_and_sets_the_exit_code() {
    let (port, seen, stop) = serve(ANSWER_STREAM);
    let url = format!("http://127.0.0.1:{port}/v1");
    let rig = Rig::new("binary");
    let ok = binary(
        &rig,
        &["-p", "summarise", "--output-format", "json"],
        "piped text",
        &[
            ("LARIS_SERVER__URL", &url),
            ("LARIS_API_KEY", KEY),
            ("NO_PROXY", "127.0.0.1"),
        ],
    );
    stop.store(true, Ordering::SeqCst);
    let _ = TcpStream::connect(("127.0.0.1", port));
    assert_eq!(
        ok.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&ok.stderr)
    );
    let value: Value = serde_json::from_slice(&ok.stdout).unwrap();
    assert_eq!(value["result"], "Served by the model.");
    let requests = seen.requests.lock().unwrap();
    let chat = requests
        .iter()
        .find(|(f, ..)| f.starts_with("POST /v1/laris/chat"))
        .unwrap();
    assert!(chat.2.contains("summarise") && chat.2.contains("piped text"));

    // not signed in
    let out = binary(
        &rig,
        &["-p", "hi"],
        "",
        &[("LARIS_SERVER__URL", "http://127.0.0.1:9/v1")],
    );
    assert_eq!(out.status.code(), Some(3));
    assert!(String::from_utf8_lossy(&out.stderr).contains("laris login"));
    assert!(out.stdout.is_empty());

    // a wrong command line
    let out = binary(&rig, &["-p", "--output-format", "yaml", "hi"], "", &[]);
    assert_eq!(out.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&out.stderr).contains("usage: laris -p"));
}
