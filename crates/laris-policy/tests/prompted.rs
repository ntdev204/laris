//! The prompt layer from the harness (SR-H3): layers read from disk under the trust rule, pinned items, and the
//! contract test loop → harness → prompt: a driven session asks the model the assembled request, the loop's own
//! conversation and log stay as they were, and the log replays byte for byte without the prompt layer.
#![allow(missing_docs)]

mod common;

use common::{Rig, rig};
use laris_config::Catalogue;
use laris_config::settings::{Agent, Context, Settings};
use laris_core::prompt::{PinKind, SUMMARY_MARK};
use laris_core::{
    Driver, FollowModel, Model, ModelAnswer, ModelRequest, Record, Recorder, ScriptedModel,
    ToolRunner, replay,
};
use laris_policy::{
    PinBoard, ProjectState, Prompted, RedactingModel, Redactor, Sources, load_layers,
};
use laris_protocol::{ChatMessage, Content, Role, ToolCall, ToolCallFunction, ToolSchema};
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use serde_json::{Map, Value, json};
use std::sync::Arc;

fn write(path: &std::path::Path, text: &str) {
    std::fs::create_dir_all(path.parent().expect("parent")).expect("dirs");
    std::fs::write(path, text).expect("write");
}

fn sources(rig: &Rig, trusted: bool, extra: &str) -> Sources {
    let state = ProjectState::new(&rig.home, &rig.project);
    state.set_trusted(trusted).expect("trust");
    Sources {
        home: rig.home.clone(),
        project_root: rig.project.clone(),
        state,
        extra_instructions: extra.to_owned(),
    }
}

fn names(layers: &[laris_core::prompt::Layer]) -> Vec<String> {
    layers.iter().map(|l| l.name.clone()).collect()
}

fn text(m: &ChatMessage) -> String {
    match &m.content {
        Some(Content::Text(t)) => t.clone(),
        _ => String::new(),
    }
}

#[test]
fn user_layers_are_read_always_and_project_layers_only_in_a_trusted_folder() {
    let rig = rig("layers");
    write(&rig.home.join("LARIS.md"), "User rule.");
    write(&rig.project.join(".laris/LARIS.md"), "Project rule.");
    write(&rig.project.join(".laris/memory/b-note.md"), "Second note.");
    write(&rig.project.join(".laris/memory/a-note.md"), "First note.");
    write(
        &rig.project.join(".laris/memory/ignored.txt"),
        "not markdown",
    );
    let context = Context::default();

    let untrusted = load_layers(&sources(&rig, false, "Be brief."), &context);
    assert_eq!(
        names(&untrusted),
        ["LARIS.md (user)", "Extra instructions (user)"]
    );

    let trusted = load_layers(&sources(&rig, true, ""), &context);
    assert_eq!(
        names(&trusted),
        [
            "LARIS.md (user)",
            "LARIS.md (project)",
            "memory/a-note",
            "memory/b-note"
        ]
    );
}

#[test]
fn files_are_capped_links_are_skipped_and_the_note_count_is_limited() {
    let rig = rig("caps");
    write(&rig.project.join(".laris/LARIS.md"), &"x".repeat(500));
    for n in 0..5 {
        write(&rig.project.join(format!(".laris/memory/n{n}.md")), "note");
    }
    let secret = rig.base.join("outside.md");
    write(&secret, "SECRET OUTSIDE THE PROJECT");
    #[cfg(unix)]
    std::os::unix::fs::symlink(&secret, rig.project.join(".laris/memory/link.md")).expect("link");
    let context = Context {
        layer_max_chars: 100,
        memory_max_notes: 3,
        ..Context::default()
    };
    let layers = load_layers(&sources(&rig, true, ""), &context);
    let project = layers
        .iter()
        .find(|l| l.name.contains("project"))
        .expect("project");
    assert_eq!(project.text.chars().count(), 100);
    let notes: Vec<_> = layers
        .iter()
        .filter(|l| l.name.starts_with("memory/"))
        .collect();
    assert_eq!(notes.len(), 3);
    assert!(
        layers.iter().all(|l| !l.text.contains("SECRET")),
        "a symbolic link was followed"
    );
}

#[test]
fn a_missing_home_and_project_give_no_layers() {
    let rig = rig("none");
    assert!(load_layers(&sources(&rig, true, "  "), &Context::default()).is_empty());
}

#[test]
fn pins_are_shared_deduplicated_and_removable() {
    let board = PinBoard::new();
    let other = board.clone();
    board.pin(PinKind::Goal, "  ship the report ");
    other.pin(PinKind::Goal, "ship the report");
    other.pin(PinKind::Decision, "");
    other.pin(PinKind::Constraint, "no network");
    assert_eq!(board.list().len(), 2);
    assert!(board.unpin(0));
    assert!(!board.unpin(5));
    assert_eq!(other.list()[0].text, "no network");
}

// -- the contract: loop -> harness -> prompt ---------------------------------------------------

fn schema(name: &str) -> ToolSchema {
    serde_json::from_value(json!({"type": "function", "function": {"name": name}})).expect("schema")
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

fn answer(text: &str, calls: Vec<ToolCall>) -> ModelAnswer {
    ModelAnswer {
        text: text.to_owned(),
        tool_calls: calls,
        usage: None,
    }
}

struct Corpus(String);

impl ToolRunner for Corpus {
    fn run(&mut self, _name: &str, _arguments: &Map<String, Value>) -> Value {
        json!({"hits": [{"text": self.0}]})
    }
}

type Rigged = Driver<Prompted<ScriptedModel>, Corpus, FollowModel>;

fn driver(
    rig: &Rig,
    script: Vec<ModelAnswer>,
    context: Context,
    bulk: usize,
    pins: &PinBoard,
) -> Rigged {
    let store = Store::open(rig.base.join("space.sqlite"), DEFAULT_BUSY_TIMEOUT).expect("store");
    let recorder = Recorder::open(store, "s1", "t", 1.0).expect("open").0;
    let prompted = Prompted::new(
        ScriptedModel::new(script),
        sources(rig, true, ""),
        context,
        pins.clone(),
    );
    // plan off: the scripted turns are plain tool use and answers
    let mut agent = Agent::default();
    agent.plan.mode = laris_config::settings::PlanMode::Off;
    let decider = FollowModel::new(agent, Catalogue::english());
    Driver::new(
        recorder,
        prompted,
        Corpus("hit ".repeat(bulk)),
        decider,
        vec![schema("search_corpus")],
        || 1.0,
    )
}

#[test]
fn a_driven_session_asks_the_model_the_assembled_request() {
    let rig = rig("contract");
    write(&rig.home.join("LARIS.md"), "Answer in British English.");
    write(
        &rig.project.join(".laris/memory/units.md"),
        "Prefers SI units.",
    );
    let pins = PinBoard::new();
    pins.pin(PinKind::Goal, "Compare perovskite with silicon");
    pins.pin(PinKind::Constraint, "Cite every number");
    let script = vec![
        answer(
            "",
            vec![call("c1", "search_corpus", json!({"query": "perovskite"}))],
        ),
        answer("Perovskite reaches 25% [source #1].", vec![]),
    ];
    let mut rigged = driver(&rig, script, Context::default(), 3, &pins);
    rigged
        .send("What is the efficiency of perovskite?")
        .expect("turn");

    let seen = rigged.model().inner().seen().to_vec();
    assert_eq!(seen.len(), 2);
    for request in &seen {
        let head = text(&request.messages[0]);
        assert_eq!(request.messages[0].role, Role::User);
        assert!(head.contains("Answer in British English."));
        assert!(head.contains("Prefers SI units."));
        assert!(head.contains("goal: Compare perovskite with silicon"));
        assert!(head.contains("constraint: Cite every number"));
        assert!(request.messages.iter().all(|m| m.role != Role::System));
        assert!(
            request.note.is_none(),
            "the plan note travels in the head, not beside it"
        );
    }
    // the second request carries the tool result after the same head
    assert_eq!(seen[0].messages[0], seen[1].messages[0]);
    assert!(seen[1].messages.iter().any(|m| m.role == Role::Tool));
    // the loop's own conversation is the bare one
    let session = rigged.session().messages();
    assert_eq!(session[0].role, Role::User);
    assert_eq!(text(&session[0]), "What is the efficiency of perovskite?");
    let report = rigged.model().last().expect("report");
    assert!(report.compaction.is_none() && report.tokens < report.window);
}

#[test]
fn the_log_of_a_prompted_session_replays_without_the_prompt_layer() {
    let rig = rig("replay");
    write(&rig.home.join("LARIS.md"), "Rule.");
    let pins = PinBoard::new();
    pins.pin(PinKind::Goal, "g");
    let script = vec![
        answer("", vec![call("c1", "search_corpus", json!({"query": "q"}))]),
        answer("Done.", vec![]),
    ];
    let mut rigged = driver(&rig, script, Context::default(), 2, &pins);
    rigged.send("go").expect("turn");
    let events = rigged.recorder().store().events("s1", 0).expect("events");
    let records: Vec<Record> = events
        .iter()
        .map(|e| laris_core::decode_record(&e.data).expect("record"))
        .collect();
    let mut model = ScriptedModel::from_records(records.iter());
    let replayed = replay(&events, Some(&mut model)).expect("replay");
    let recorded: String = events
        .iter()
        .filter(|e| e.kind == "event")
        .map(|e| format!("{}\n", e.data))
        .collect();
    assert_eq!(replayed.output, recorded);
    assert_eq!(&replayed.session, rigged.session());
}

#[test]
fn a_long_session_is_compacted_in_the_request_only_and_pins_survive() {
    let rig = rig("long");
    let pins = PinBoard::new();
    pins.pin(PinKind::Goal, "Compare perovskite with silicon");
    pins.pin(PinKind::Decision, "BM25 only, no dense retrieval");
    let context = Context {
        window_tokens: 2048,
        reserve_tokens: 256,
        ..Context::default()
    };
    let mut script = Vec::new();
    for n in 0..10 {
        script.push(answer(
            "",
            vec![call(
                &format!("c{n}"),
                "search_corpus",
                json!({"query": format!("q{n}")}),
            )],
        ));
        script.push(answer(&format!("answer {n}"), vec![]));
    }
    let mut rigged = driver(&rig, script, context, 120, &pins);
    for n in 0..10 {
        rigged.send(&format!("question {n}")).expect("turn");
    }
    let seen = rigged.model().inner().seen().to_vec();
    let last = seen.last().expect("last request");
    assert!(
        last.messages
            .iter()
            .any(|m| text(m).starts_with(SUMMARY_MARK)),
        "the old turns were not summarised"
    );
    let head = text(&last.messages[0]);
    assert!(head.contains("goal: Compare perovskite with silicon"));
    assert!(head.contains("decision: BM25 only, no dense retrieval"));
    assert!(rigged.model().last().expect("report").compaction.is_some());
    // the loop's conversation kept every turn
    assert_eq!(
        rigged
            .session()
            .messages()
            .iter()
            .filter(|m| m.role == Role::User)
            .count(),
        10
    );
    // and it still replays
    let events = rigged.recorder().store().events("s1", 0).expect("events");
    let records: Vec<Record> = events
        .iter()
        .map(|e| laris_core::decode_record(&e.data).expect("record"))
        .collect();
    let mut model = ScriptedModel::from_records(records.iter());
    replay(&events, Some(&mut model)).expect("replay");
}

#[test]
fn a_request_that_cannot_fit_stops_the_turn_with_a_model_failure() {
    let rig = rig("toolarge");
    let pins = PinBoard::new();
    pins.pin(PinKind::Goal, &"must ".repeat(12000));
    let mut rigged = driver(
        &rig,
        vec![answer("never asked", vec![])],
        Context::default(),
        1,
        &pins,
    );
    let events = rigged.send("hello").expect("the turn ends cleanly");
    assert!(
        rigged.model().inner().seen().is_empty(),
        "the model must not be asked"
    );
    assert!(!events.is_empty());
}

#[test]
fn credentials_in_a_layer_are_masked_when_the_redacting_model_is_inside() {
    let rig = rig("redact");
    write(
        &rig.home.join("LARIS.md"),
        "api_key = sk-abcdefghijklmnopqrstuvwxyz0123456789",
    );
    let inner = RedactingModel::new(
        ScriptedModel::new([answer("ok", vec![])]),
        Arc::new(Redactor::default()),
    );
    let mut prompted = Prompted::new(
        inner,
        sources(&rig, true, ""),
        Context::default(),
        PinBoard::new(),
    );
    let messages = [ChatMessage {
        role: Role::User,
        content: Some(Content::Text("hi".to_owned())),
        tool_calls: Vec::new(),
        tool_call_id: None,
        name: None,
        extra: Map::new(),
    }];
    prompted
        .answer(&ModelRequest {
            messages: &messages,
            note: None,
            tools: &[],
        })
        .expect("answer");
    let seen = prompted.inner().inner().seen();
    assert!(!text(&seen[0].messages[0]).contains("sk-abcdefghijklmnopqrstuvwxyz"));
    let _ = Settings::default();
}
