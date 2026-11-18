//! Learning data derived from the event log (SR-H11): the export matches its fixture, the quality gate leaves bad
//! turns out, a disabled collector does nothing, and collected data stays out of requests and the repository.
//! A scripted model plays the model, so nothing here says anything about a trained model (NOT QUALIFIED).

use laris_config::settings::{Agent, ExportRating, Learning};
use laris_config::{Catalogue, Settings};
use laris_core::{Driver, FollowModel, ModelAnswer, Record, Recorder, ScriptedModel, ToolRunner};
use laris_policy::Redactor;
use laris_policy::learning::{
    self, Kind, collect, derive, export, inside_repository, rate, write_export,
};
use laris_protocol::{Command, ToolCall, ToolCallFunction, ToolSchema};
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};

const ANSWER: &str = "Perovskite cells reach 25% efficiency [cells-2024 #1].";
const GOAL: &str =
    "Find the efficiency of perovskite solar cells then compare it with silicon and report";

fn temp_dir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("laris-learning-{name}-{}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir
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

fn turn(text: &str, calls: Vec<ToolCall>) -> ModelAnswer {
    ModelAnswer {
        text: text.to_owned(),
        tool_calls: calls,
        usage: None,
    }
}

fn plan(id: &str, steps: &[(&str, &str)]) -> ToolCall {
    let steps: Vec<Value> = steps
        .iter()
        .map(|(text, status)| json!({"text": text, "status": status}))
        .collect();
    call(id, "update_plan", json!({ "steps": steps }))
}

fn search(id: &str, query: &str) -> ToolCall {
    call(id, "search_corpus", json!({"query": query}))
}

fn schema(name: &str) -> ToolSchema {
    serde_json::from_value(json!({"type": "function", "function": {"name": name}})).expect("schema")
}

/// A corpus of two passages; `poison` makes its result carry what a hostile document or a leak would.
#[derive(Clone, Default)]
struct Tools {
    poison: Option<Value>,
}

impl ToolRunner for Tools {
    fn run(&mut self, name: &str, _arguments: &Map<String, Value>) -> Value {
        if let Some(p) = &self.poison {
            return p.clone();
        }
        match name {
            "search_corpus" => json!({"hits": [
                {"source": "cells-2024", "rank": 1, "title": "Perovskite cells",
                 "text": "Perovskite cells reach 25% efficiency."},
                {"source": "silicon-2023", "rank": 2, "title": "Silicon cells",
                 "text": "Silicon cells reach 27% efficiency."},
            ]}),
            _ => json!({"error": {"code": "unknown_tool", "message": name}}),
        }
    }
}

type Rig = Driver<ScriptedModel, Tools, FollowModel>;

fn rig(dir: &Path, script: Vec<ModelAnswer>, tools: Tools) -> Rig {
    let store = Store::open(dir.join("space.sqlite"), DEFAULT_BUSY_TIMEOUT).expect("store");
    let (recorder, _) = Recorder::open(store, "s1", "t", 1.0).expect("open");
    Driver::new(
        recorder,
        ScriptedModel::new(script),
        tools,
        FollowModel::new(Agent::default(), Catalogue::english()),
        ["update_plan", "search_corpus"].map(schema).to_vec(),
        || 1.0,
    )
}

fn standard() -> Redactor {
    Redactor::standard()
}

fn settings() -> Learning {
    Settings::default().learning
}

fn store_of(rig: &Rig) -> Store {
    rig.recorder().store().clone()
}

/// A session with a cited research turn, a plain chat turn and a turn whose first draft the loop sent back.
fn full_session(dir: &Path) -> Rig {
    let script = vec![
        // turn 1: search, then an answer that cites the first passage
        turn("", vec![search("a", "perovskite efficiency")]),
        turn(ANSWER, vec![]),
        // turn 2: chat, no tools
        turn(
            "Hello! I can search your documents and answer with citations.",
            vec![],
        ),
        // turn 3: a draft with a step still open, sent back, then the answer that stood
        turn(
            "",
            vec![plan(
                "p1",
                &[("find", "in_progress"), ("compare", "pending")],
            )],
        ),
        turn("", vec![search("b", "perovskite silicon comparison")]),
        turn("Draft: perovskite cells are efficient.", vec![]),
        turn(
            "",
            vec![plan("p2", &[("find", "done"), ("compare", "skipped")])],
        ),
        turn(ANSWER, vec![]),
    ];
    let mut rig = rig(dir, script, Tools::default());
    rig.send("How efficient are perovskite cells?")
        .expect("turn 1");
    rig.send("Hi").expect("turn 2");
    rig.send(GOAL).expect("turn 3");
    rig
}

fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/learning")
        .join(name)
}

fn check_fixture(name: &str, actual: &str) {
    let path = fixture(name);
    if std::env::var("LARIS_BLESS_FIXTURES").is_ok() {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, actual).unwrap();
    }
    let expected =
        std::fs::read_to_string(&path).unwrap_or_else(|_| panic!("missing {}", path.display()));
    assert_eq!(actual, expected, "{name} differs from its fixture");
}

#[test]
fn the_export_matches_its_fixture() {
    let dir = temp_dir("fixture");
    let rig = full_session(&dir);
    let store = store_of(&rig);
    let got = collect(&store, "s1", &settings(), &standard()).expect("collect");
    assert!(got.enabled);
    assert_eq!(got.stored.get("sft"), Some(&3));
    assert_eq!(got.stored.get("retrieval"), Some(&2));
    assert_eq!(got.stored.get("preference"), Some(&1));
    for kind in [Kind::Sft, Kind::Retrieval, Kind::Preference] {
        let out = export(&store, kind, ExportRating::None).expect("export");
        check_fixture(&format!("expected-{}.jsonl", kind.name()), &out.jsonl);
        assert_eq!(out.manifest["count"], out.jsonl.lines().count());
        // every line is a JSON object with an id and the schema version
        for line in out.jsonl.lines() {
            let row: Value = serde_json::from_str(line).expect("json line");
            assert!(row["id"].as_str().is_some_and(|i| i.len() == 16));
            assert_eq!(row["schema"], learning::SCHEMA);
        }
    }
}

#[test]
fn the_same_log_gives_the_same_bytes() {
    let a = full_session(&temp_dir("same-a"));
    let b = full_session(&temp_dir("same-b"));
    let events = |r: &Rig| r.recorder().store().events("s1", 0).expect("events");
    let one = derive(&events(&a), &settings(), &standard(), "s1").expect("derive");
    let two = derive(&events(&b), &settings(), &standard(), "s1").expect("derive");
    assert_eq!(one, two);
    assert!(one.rejected.is_empty(), "{:?}", one.rejected);
}

#[test]
fn a_retrieval_example_has_cited_and_uncited_passages() {
    let rig = full_session(&temp_dir("pairs"));
    let events = rig.recorder().store().events("s1", 0).expect("events");
    let derived = derive(&events, &settings(), &standard(), "s1").expect("derive");
    let pair = derived
        .examples
        .iter()
        .find(|e| e.kind == Kind::Retrieval)
        .expect("pair");
    assert_eq!(pair.row["query"], "perovskite efficiency");
    assert_eq!(pair.row["positives"][0]["source"], "cells-2024");
    assert_eq!(pair.row["negatives"][0]["source"], "silicon-2023");
    let draft = derived
        .examples
        .iter()
        .find(|e| e.kind == Kind::Preference)
        .expect("preference");
    assert_eq!(
        draft.row["rejected"],
        "Draft: perovskite cells are efficient."
    );
    assert_eq!(draft.row["chosen"], ANSWER);
    // the draft is not part of the conversation example, and neither is the loop's own retry message
    let sft = derived
        .examples
        .iter()
        .rfind(|e| e.kind == Kind::Sft)
        .expect("sft");
    let all = sft.row["messages"].to_string();
    assert!(!all.contains("Draft:"), "{all}");
    let users = sft.row["messages"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|m| m["role"] == "user")
        .count();
    assert_eq!(users, 3);
}

#[test]
fn passage_text_can_be_left_out() {
    let rig = full_session(&temp_dir("hashes"));
    let events = rig.recorder().store().events("s1", 0).expect("events");
    let mut options = settings();
    options.store_passage_text = false;
    options.store_tool_results = false;
    let derived = derive(&events, &options, &standard(), "s1").expect("derive");
    let pair = derived
        .examples
        .iter()
        .find(|e| e.kind == Kind::Retrieval)
        .expect("pair");
    assert!(pair.row["positives"][0].get("text").is_none());
    assert_eq!(
        pair.row["positives"][0]["text_sha256"]
            .as_str()
            .map(str::len),
        Some(64)
    );
    let sft = derived
        .examples
        .iter()
        .find(|e| e.kind == Kind::Sft)
        .expect("sft");
    let tool = sft.row["messages"]
        .as_array()
        .unwrap()
        .iter()
        .find(|m| m["role"] == "tool")
        .expect("tool");
    assert_eq!(tool["content"], "[omitted]");
}

fn reasons(rig: &Rig) -> Vec<&'static str> {
    let events = rig.recorder().store().events("s1", 0).expect("events");
    let derived = derive(&events, &settings(), &standard(), "s1").expect("derive");
    assert!(derived.examples.is_empty(), "a bad turn became an example");
    derived.rejected.iter().map(|r| r.reason).collect()
}

fn one_turn(name: &str, tools: Tools, text: &str) -> Rig {
    let script = vec![
        turn("", vec![search("a", "perovskite efficiency")]),
        turn(text, vec![]),
    ];
    let mut rig = rig(&temp_dir(name), script, tools);
    rig.send("How efficient are perovskite cells?")
        .expect("turn");
    rig
}

#[test]
fn bad_turns_are_left_out() {
    // an injection flag in a tool result
    let flagged = Tools {
        poison: Some(json!({"hits": [], "injection_warning": "this result gives orders"})),
    };
    assert_eq!(
        reasons(&one_turn("flag", flagged, ANSWER)),
        ["injection_flag"]
    );

    // a credential that reached the log
    let leaked = Tools {
        poison: Some(json!({"hits": [], "note": "key AKIAIOSFODNN7EXAMPLE"})),
    };
    assert_eq!(reasons(&one_turn("leak", leaked, ANSWER)), ["sensitive"]);

    // a citation that names nothing the turn retrieved
    let fabricated = "Perovskite cells reach 31% efficiency [ghost-2020 #4].";
    assert_eq!(
        reasons(&one_turn("fake", Tools::default(), fabricated)),
        ["unverified"]
    );

    // an answer too short to teach anything
    let rig = {
        let mut rig = rig(
            &temp_dir("short"),
            vec![turn("Ok.", vec![])],
            Tools::default(),
        );
        rig.send("Hi").expect("turn");
        rig
    };
    assert_eq!(reasons(&rig), ["short_answer"]);
}

#[test]
fn an_interrupted_turn_is_left_out() {
    let dir = temp_dir("interrupt");
    let store = Store::open(dir.join("space.sqlite"), DEFAULT_BUSY_TIMEOUT).expect("store");
    let (mut recorder, _) = Recorder::open(store.clone(), "s1", "t", 1.0).expect("open");
    let say = Command::UserMessage {
        text: "Start a long job".to_owned(),
        attachments: Vec::new(),
    };
    recorder
        .record(Record::Command { command: say }, 1.0)
        .expect("user");
    recorder
        .record(
            Record::Command {
                command: Command::Interrupt {},
            },
            1.0,
        )
        .expect("interrupt");
    let derived = derive(
        &store.events("s1", 0).unwrap(),
        &settings(),
        &standard(),
        "s1",
    )
    .expect("derive");
    assert!(derived.examples.is_empty());
    assert_eq!(
        derived
            .rejected
            .iter()
            .map(|r| r.reason)
            .collect::<Vec<_>>(),
        ["not_completed"]
    );
}

#[test]
fn nothing_is_read_or_written_when_collection_is_off() {
    let rig = full_session(&temp_dir("off"));
    let store = store_of(&rig);
    let mut options = settings();
    options.collect = false;
    let got = collect(&store, "s1", &options, &standard()).expect("collect");
    assert!(!got.enabled && got.stored.is_empty() && got.rejected.is_empty());
    for kind in [Kind::Sft, Kind::Retrieval, Kind::Preference] {
        assert!(store.learning(kind.name()).unwrap().is_empty());
    }
}

#[test]
fn collecting_twice_stores_each_example_once() {
    let rig = full_session(&temp_dir("twice"));
    let store = store_of(&rig);
    let first = collect(&store, "s1", &settings(), &standard()).expect("first");
    let second = collect(&store, "s1", &settings(), &standard()).expect("second");
    assert_eq!(first.duplicates, 0);
    assert!(second.stored.is_empty());
    assert_eq!(second.duplicates, 6);
}

#[test]
fn ratings_decide_what_is_exported() {
    let rig = full_session(&temp_dir("ratings"));
    let store = store_of(&rig);
    collect(&store, "s1", &settings(), &standard()).expect("collect");
    let ids: Vec<String> = export(&store, Kind::Sft, ExportRating::None)
        .unwrap()
        .jsonl
        .lines()
        .map(|l| {
            serde_json::from_str::<Value>(l).unwrap()["id"]
                .as_str()
                .unwrap()
                .to_owned()
        })
        .collect();
    assert_eq!(ids.len(), 3);
    rate(&store, &ids[0], true, 2.0).expect("up");
    rate(&store, &ids[1], false, 2.0).expect("down");
    assert_eq!(
        export(&store, Kind::Sft, ExportRating::None)
            .unwrap()
            .manifest["count"],
        2
    );
    assert_eq!(
        export(&store, Kind::Sft, ExportRating::Up)
            .unwrap()
            .manifest["count"],
        1
    );
    // pairs follow the example they came from
    let pairs = export(&store, Kind::Retrieval, ExportRating::Up).unwrap();
    assert!(
        pairs
            .jsonl
            .lines()
            .all(|l| serde_json::from_str::<Value>(l).unwrap()["example"] == ids[0])
    );
    assert!(rate(&store, "nope", true, 3.0).is_err());
    let stats = learning::stats(&store, &settings()).unwrap();
    assert_eq!(
        (stats["rated_up"].as_u64(), stats["rated_down"].as_u64()),
        (Some(1), Some(1))
    );
    assert!(learning::purge(&store).unwrap() > 0);
    assert!(
        store.learning("sft").unwrap().is_empty() && store.learning("feedback").unwrap().is_empty()
    );
}

#[test]
fn collected_data_does_not_reach_a_request_or_the_log() {
    let dir = temp_dir("p1");
    let rig = full_session(&dir);
    let store = store_of(&rig);
    let before = store.events("s1", 0).unwrap();
    collect(&store, "s1", &settings(), &standard()).expect("collect");
    assert_eq!(
        store.events("s1", 0).unwrap(),
        before,
        "collecting changed the log"
    );

    // a later session in the same store: what the model is shown is the conversation and nothing else
    let (recorder, _) = Recorder::open(store.clone(), "s2", "t", 2.0).expect("open");
    let mut next = Driver::new(
        recorder,
        ScriptedModel::new([turn(
            "Hello again, how can I help you today with your documents?",
            vec![],
        )]),
        Tools::default(),
        FollowModel::new(Agent::default(), Catalogue::english()),
        Vec::new(),
        || 2.0,
    );
    next.send("Hi").expect("turn");
    let ids: Vec<String> = store
        .learning("sft")
        .unwrap()
        .iter()
        .map(|r| {
            serde_json::from_str::<Value>(r).unwrap()["id"]
                .as_str()
                .unwrap()
                .to_owned()
        })
        .collect();
    let shown = format!("{:?}", next.model().seen());
    for id in &ids {
        assert!(
            !shown.contains(id.as_str()),
            "an example id reached a request"
        );
    }
    assert!(
        !shown.contains("Draft: perovskite"),
        "a collected draft reached a request"
    );
    assert!(
        !shown.contains("perovskite"),
        "collected text reached a request"
    );
}

#[test]
fn an_export_never_lands_inside_a_repository() {
    let dir = temp_dir("repo");
    let rig = full_session(&dir);
    let store = store_of(&rig);
    collect(&store, "s1", &settings(), &standard()).expect("collect");
    let out = export(&store, Kind::Sft, ExportRating::None).unwrap();

    let work_tree = dir.join("project");
    std::fs::create_dir_all(work_tree.join(".git")).unwrap();
    let inside = work_tree.join("data/sft.jsonl");
    assert!(inside_repository(&inside));
    assert!(write_export(&inside, &out).is_err());
    assert!(!inside.exists());

    let outside = dir.join("exports/sft.jsonl");
    assert!(!inside_repository(&outside));
    write_export(&outside, &out).expect("write");
    assert_eq!(std::fs::read_to_string(&outside).unwrap(), out.jsonl);
    let manifest: Value = serde_json::from_str(
        &std::fs::read_to_string(dir.join("exports/sft.jsonl.manifest.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(manifest, out.manifest);
}

#[test]
fn the_repository_holds_no_collected_data() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut found = Vec::new();
    let mut stack = vec![root];
    while let Some(dir) = stack.pop() {
        for entry in std::fs::read_dir(&dir).expect("dir").flatten() {
            let path = entry.path();
            let name = entry.file_name().to_string_lossy().into_owned();
            if path.is_dir() {
                if !matches!(
                    name.as_str(),
                    ".git" | "target" | "node_modules" | ".venv" | "artifacts" | "data"
                ) {
                    stack.push(path);
                }
            } else if matches!(
                name.as_str(),
                "sft.jsonl"
                    | "preference.jsonl"
                    | "retrieval.jsonl"
                    | "learning.sqlite"
                    | "feedback.jsonl"
            ) {
                found.push(path);
            }
        }
    }
    assert!(
        found.is_empty(),
        "collected data in the repository: {found:?}"
    );
}
