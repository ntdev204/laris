//! The event log: byte-identical replay with a scripted model, refusal of divergence, resume after a killed process.

use laris_core::{
    Action, CoreError, Model, ModelAnswer, ModelError, ModelRequest, Pending, Record, Recorder,
    ScriptedModel, replay,
};
use laris_protocol::{ChatMessage, Command, Event, ToolCall, ToolCallFunction};
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store, StoredEvent};
use serde_json::{Map, Value, json};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command as Process, Stdio};

const CHILD_ENV: &str = "LARIS_CORE_TEST_CHILD";

fn temp_dir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("laris-core-{name}-{}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir
}

fn open_store(dir: &Path) -> Store {
    Store::open(dir.join("space.sqlite"), DEFAULT_BUSY_TIMEOUT).expect("store")
}

fn user(text: &str) -> Record {
    Record::Command {
        command: Command::UserMessage {
            text: text.to_owned(),
            attachments: Vec::new(),
        },
    }
}

fn call(name: &str, arguments: &str) -> ToolCall {
    ToolCall {
        index: None,
        id: None,
        kind: Default::default(),
        function: ToolCallFunction {
            name: name.to_owned(),
            arguments: arguments.to_owned(),
            extra: Map::new(),
        },
        extra: Map::new(),
    }
}

fn answer(rec: &Recorder, text: &str, calls: Vec<ToolCall>) -> Record {
    Record::ModelAnswer {
        request_digest: rec.session().digest(),
        answer: ModelAnswer {
            text: text.to_owned(),
            tool_calls: calls,
            usage: None,
        },
    }
}

fn decide(rec: &mut Recorder, action: Action, now: f64) {
    rec.record(Record::Decision { action }, now)
        .expect("decision");
}

fn ask(rec: &mut Recorder, now: f64) {
    decide(rec, Action::AskModel { note: None }, now);
}

fn close_step(rec: &mut Recorder, now: f64) {
    decide(
        rec,
        Action::Reflect {
            marks: Vec::new(),
            notices: Vec::new(),
        },
        now,
    );
}

fn finish(rec: &mut Recorder, now: f64) {
    decide(
        rec,
        Action::Finish {
            warning: String::new(),
        },
        now,
    );
}

/// One turn with a tool call, as the loop drives it: 9 inputs and 5 outputs.
fn tool_turn(rec: &mut Recorder, n: usize, now: f64) {
    rec.record(user(&format!("question {n}")), now)
        .expect("user");
    ask(rec, now);
    let a = answer(rec, "looking", vec![call("read", r#"{"path":"notes.md"}"#)]);
    rec.record(a, now).expect("answer");
    let Pending::Tools(open) = rec.session().pending().clone() else {
        panic!("tool calls expected");
    };
    decide(
        rec,
        Action::RunTool {
            id: open[0].clone(),
        },
        now,
    );
    rec.record(
        Record::ToolOutcome {
            id: open[0].clone(),
            name: "read".to_owned(),
            result: json!({"text": "héllo ✓", "n": n}),
        },
        now,
    )
    .expect("tool");
    close_step(rec, now);
    ask(rec, now);
    let a = answer(rec, &format!("answer {n} — ok"), Vec::new());
    rec.record(a, now).expect("final");
    finish(rec, now);
}

fn stored(store: &Store, id: &str) -> Vec<StoredEvent> {
    store.events(id, 0).expect("events")
}

/// The recorded outputs as the replay writes them: stored form, one per line.
fn recorded_output(events: &[StoredEvent]) -> String {
    events
        .iter()
        .filter(|e| e.kind == "event")
        .map(|e| format!("{}\n", e.data))
        .collect()
}

#[test]
fn replay_with_a_scripted_model_is_byte_identical() {
    let dir = temp_dir("replay");
    let (mut rec, resumed) = Recorder::open(open_store(&dir), "s1", "t", 1.0).expect("open");
    assert_eq!((resumed.events, resumed.repaired), (0, 0));
    for n in 1..=3 {
        tool_turn(&mut rec, n, 1.0 + n as f64);
    }
    let events = stored(rec.store(), "s1");
    assert_eq!(events.len(), 3 * 14);
    let mut model = ScriptedModel::from_records(
        events
            .iter()
            .map(|e| laris_core::decode_record(&e.data).expect("record"))
            .collect::<Vec<_>>()
            .iter(),
    );
    assert_eq!(model.remaining(), 6);
    let replayed = replay(&events, Some(&mut model)).expect("replay");
    assert_eq!(replayed.output, recorded_output(&events), "bytes differ");
    assert!(replayed.output.contains("héllo ✓"));
    assert_eq!(&replayed.session, rec.session());
    assert_eq!(model.remaining(), 0);
    assert!(replayed.missing.is_empty());
    // Replaying again gives the same bytes.
    assert_eq!(
        replay(&events, None).expect("again").output,
        replayed.output
    );
}

#[test]
fn replay_refuses_a_changed_conversation_or_output() {
    let dir = temp_dir("diverge");
    let (mut rec, _) = Recorder::open(open_store(&dir), "s1", "t", 1.0).expect("open");
    tool_turn(&mut rec, 1, 1.0);
    let events = stored(rec.store(), "s1");
    let records: Vec<Record> = events
        .iter()
        .map(|e| laris_core::decode_record(&e.data).expect("record"))
        .collect();

    // A model asked about another conversation is refused.
    let mut script = ScriptedModel::from_records(records.iter());
    let other = [ChatMessage {
        role: laris_protocol::Role::User,
        content: Some(laris_protocol::Content::Text("something else".into())),
        tool_calls: Vec::new(),
        tool_call_id: None,
        name: None,
        extra: Map::new(),
    }];
    assert!(matches!(
        script.answer(&ModelRequest {
            messages: &other,
            note: None,
            tools: &[]
        }),
        Err(ModelError::RequestDiverged { .. })
    ));

    // A recorded output that the fold does not produce is refused, at its position.
    let mut tampered = events.clone();
    let at = tampered
        .iter()
        .position(|e| e.kind == "event")
        .expect("event");
    tampered[at].data = tampered[at].data.replace("looking", "lurking");
    match replay(&tampered, None) {
        Err(CoreError::Diverged { seq, .. }) => assert_eq!(seq, tampered[at].seq),
        other => panic!("expected divergence, got {other:?}"),
    }

    // A recorded answer that differs from the script is refused.
    let mut different = ScriptedModel::new([ModelAnswer {
        text: "other".into(),
        ..ModelAnswer::default()
    }]);
    assert!(matches!(
        replay(&events, Some(&mut different)),
        Err(CoreError::Diverged { .. })
    ));

    // An exhausted script is refused.
    let mut empty = ScriptedModel::new([]);
    assert!(matches!(
        replay(&events, Some(&mut empty)),
        Err(CoreError::Model { .. })
    ));
}

#[test]
fn an_input_that_does_not_fit_is_refused_and_leaves_no_trace() {
    let dir = temp_dir("refuse");
    let (mut rec, _) = Recorder::open(open_store(&dir), "s1", "t", 1.0).expect("open");
    let before = stored(rec.store(), "s1").len();
    let a = answer(&rec, "nobody asked", Vec::new());
    assert!(matches!(rec.record(a, 1.0), Err(CoreError::Unexpected(_))));
    let o = Record::ToolOutcome {
        id: "x".into(),
        name: "read".into(),
        result: Value::Null,
    };
    assert!(matches!(rec.record(o, 1.0), Err(CoreError::Unexpected(_))));
    assert!(matches!(
        rec.record(
            Record::Emitted {
                event: Event::Text { delta: "x".into() }
            },
            1.0
        ),
        Err(CoreError::NotInput)
    ));
    assert_eq!(stored(rec.store(), "s1").len(), before);

    // A second message while a turn runs is answered with `busy`; interrupt ends the turn consistently.
    rec.record(user("one"), 2.0).expect("first");
    let busy = rec.record(user("two"), 2.0).expect("second");
    assert!(matches!(&busy[..], [Event::Error { code, .. }] if code == "busy"));
    assert_eq!(rec.session().turns(), 1);
    let done = rec
        .record(
            Record::Command {
                command: Command::Interrupt {},
            },
            3.0,
        )
        .expect("interrupt");
    assert!(matches!(&done[..], [Event::Done { status, .. }] if status == "interrupted"));
    assert_eq!(rec.session().pending(), &Pending::Idle);
    let events = stored(rec.store(), "s1");
    assert_eq!(
        replay(&events, None).expect("replay").output,
        recorded_output(&events)
    );
}

#[test]
fn a_log_cut_between_an_input_and_its_outputs_is_repaired_on_open() {
    let dir = temp_dir("torn");
    // The reference: a clean run.
    let clean_dir = temp_dir("torn-clean");
    let (mut clean, _) = Recorder::open(open_store(&clean_dir), "s1", "t", 1.0).expect("open");
    tool_turn(&mut clean, 1, 1.0);
    let reference = stored(clean.store(), "s1");

    // The same run, but the process dies after each input before its outputs: write the inputs only.
    let store = open_store(&dir);
    store.create_session("s1", "t", 1.0).expect("session");
    // Cut after the decision to run the tool: its `tool_call` output is lost.
    for e in reference.iter().take_while(|e| e.seq <= 5) {
        store
            .append_event("s1", &e.kind, 1.0, &e.data)
            .expect("append");
    }
    assert_eq!(reference[4].kind, "decision");
    assert_eq!(reference[5].kind, "event");
    let cut = stored(&store, "s1");
    assert_eq!(cut.len(), 5); // user, ask, answer, its text, run_tool; the tool_call output is missing

    let (mut rec, resumed) = Recorder::open(store, "s1", "t", 9.0).expect("resume");
    assert_eq!(resumed.events, 5);
    assert_eq!(resumed.repaired, 1);
    // Continue the same run: the log now equals the clean one, byte for byte.
    let Pending::Tools(open) = rec.session().pending().clone() else {
        panic!("tool calls pending after resume");
    };
    rec.record(
        Record::ToolOutcome {
            id: open[0].clone(),
            name: "read".to_owned(),
            result: json!({"text": "héllo ✓", "n": 1}),
        },
        1.0,
    )
    .expect("tool");
    close_step(&mut rec, 1.0);
    ask(&mut rec, 1.0);
    let a = answer(&rec, "answer 1 — ok", Vec::new());
    rec.record(a, 1.0).expect("final");
    finish(&mut rec, 1.0);
    let resumed_log: Vec<(String, String)> = stored(rec.store(), "s1")
        .into_iter()
        .map(|e| (e.kind, e.data))
        .collect();
    let clean_log: Vec<(String, String)> =
        reference.into_iter().map(|e| (e.kind, e.data)).collect();
    assert_eq!(resumed_log, clean_log);
}

/// The process that is killed: it drives a session forever from whatever state the log holds.
#[test]
fn child_writer() {
    let Ok(dir) = std::env::var(CHILD_ENV) else {
        return; // not the child: nothing to do
    };
    let (mut rec, _) = Recorder::open(open_store(Path::new(&dir)), "s1", "t", 1.0).expect("open");
    for step in 0..1_000_000 {
        let now = 2.0 + step as f64;
        match rec.session().pending().clone() {
            Pending::Idle => {
                let n = rec.session().turns() + 1;
                rec.record(user(&format!("question {n}")), now)
                    .expect("user");
            }
            Pending::Model if rec.session().asked().is_none() => ask(&mut rec, now),
            Pending::Model => {
                let last_is_tool = rec
                    .session()
                    .messages()
                    .last()
                    .is_some_and(|m| m.role == laris_protocol::Role::Tool);
                let a = if last_is_tool {
                    answer(&rec, "final", Vec::new())
                } else {
                    answer(
                        &rec,
                        "looking",
                        vec![
                            call("read", r#"{"path":"a"}"#),
                            call("read", r#"{"path":"b"}"#),
                        ],
                    )
                };
                rec.record(a, now).expect("answer");
            }
            Pending::Tools(open) if !rec.session().turn().is_cleared(&open[0]) => {
                decide(
                    &mut rec,
                    Action::RunTool {
                        id: open[0].clone(),
                    },
                    now,
                );
            }
            Pending::Tools(open) => {
                rec.record(
                    Record::ToolOutcome {
                        id: open[0].clone(),
                        name: "read".into(),
                        result: json!("ok"),
                    },
                    now,
                )
                .expect("tool");
            }
            Pending::Reflect => close_step(&mut rec, now),
            Pending::Check => finish(&mut rec, now),
        }
        println!("step {step}");
    }
}

fn run_child_until_killed(dir: &Path, steps: usize) {
    let mut child = Process::new(std::env::current_exe().expect("exe"))
        .args(["--exact", "child_writer", "--nocapture", "--test-threads=1"])
        .env(CHILD_ENV, dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("spawn child");
    let mut lines = BufReader::new(child.stdout.take().expect("stdout")).lines();
    let mut seen = 0;
    while seen < steps {
        let line = lines.next().expect("child ended early").expect("line");
        if line.starts_with("step ") {
            seen += 1;
        }
    }
    child.kill().expect("kill"); // SIGKILL: no chance to clean up
    child.wait().expect("wait");
}

#[test]
fn resume_after_a_killed_process_continues_from_the_last_event() {
    let dir = temp_dir("killed");
    let mut last_len = 0;
    for round in 0..3 {
        run_child_until_killed(&dir, 40);
        // Whatever the kill cut, the log reads cleanly and replays.
        let store = open_store(&dir);
        let events = stored(&store, "s1");
        assert!(
            events.len() > last_len,
            "round {round}: nothing was written"
        );
        for (i, e) in events.iter().enumerate() {
            assert_eq!(e.seq, i as i64 + 1, "gap in the log");
        }
        let replayed = replay(&events, None).expect("the log of a killed process replays");
        // Resume: state equals the fold; any lost outputs are written; the log then replays with nothing missing.
        let (rec, resumed) = Recorder::open(store, "s1", "t", 1.0).expect("resume");
        assert_eq!(resumed.repaired, replayed.missing.len());
        assert_eq!(rec.session(), &replayed.session);
        let after = stored(rec.store(), "s1");
        assert_eq!(after.len(), events.len() + resumed.repaired);
        let again = replay(&after, None).expect("replay after resume");
        assert!(again.missing.is_empty());
        assert_eq!(
            again.output,
            recorded_output(&after),
            "bytes differ after resume"
        );
        last_len = after.len();
    }
}
