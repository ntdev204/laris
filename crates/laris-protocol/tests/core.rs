//! Core event protocol (T124): round trip per message, schema, faults, line decoding, the channel, and the
//! eleven interface scenarios of `tests/golden/ink_scenarios/` translated and replayed.

mod common;

use common::{subset, validate};
use laris_protocol::events::{COMMAND_TYPES, EVENT_TYPES};
use laris_protocol::scenario::{Scenario, replay};
use laris_protocol::{Command, Event, channel, check_ready, jsonl, schema};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

fn lines(name: &str) -> Vec<String> {
    let path = common::fixtures().join("core").join(name);
    common::text(&path)
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(str::to_owned)
        .collect()
}

fn scenario_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/golden/ink_scenarios")
}

fn scenarios() -> Vec<(String, Scenario, Value)> {
    let mut out = Vec::new();
    let mut files: Vec<_> = std::fs::read_dir(scenario_dir())
        .expect("scenario dir")
        .filter_map(Result::ok)
        .map(|e| e.path())
        .collect();
    files.sort();
    for p in files {
        let text = common::text(&p);
        let name = common::stem(&p);
        let parsed = Scenario::parse(&text).unwrap_or_else(|e| panic!("{name}: {e}"));
        out.push((name, parsed, serde_json::from_str(&text).expect("json")));
    }
    out
}

fn root_schema(kind: &str) -> Value {
    schema::export()["core"][kind].clone()
}

/// Every message of both kinds: fixtures plus every message written in the scenarios.
fn all_messages() -> (Vec<Value>, Vec<Value>) {
    let mut events: Vec<Value> = lines("events.jsonl")
        .iter()
        .map(|l| serde_json::from_str(l).expect("event json"))
        .collect();
    let mut commands: Vec<Value> = lines("commands.jsonl")
        .iter()
        .map(|l| serde_json::from_str(l).expect("command json"))
        .collect();
    for (_, _, raw) in scenarios() {
        for step in raw["steps"].as_array().unwrap_or(&vec![]) {
            if let Some(c) = step.get("expect") {
                let mut c = c.clone();
                if c["type"] == "complete" && c.get("id").is_none() {
                    c["id"] = json!("c");
                }
                commands.push(c);
            }
            events.extend(step["emit"].as_array().cloned().unwrap_or_default());
        }
    }
    (events, commands)
}

#[test]
fn every_message_round_trips_and_validates() {
    let (events, commands) = all_messages();
    let (event_schema, command_schema) = (root_schema("Event"), root_schema("Command"));
    for v in &events {
        let typed = jsonl::decode_event(&v.to_string()).unwrap_or_else(|e| panic!("{e}: {v}"));
        let back = serde_json::to_value(&typed).expect("value");
        assert!(subset(v, &back), "event lost data\n {v}\n {back}");
        assert_eq!(
            typed,
            jsonl::decode_event(&jsonl::encode(&typed)).expect("again")
        );
        validate(&event_schema, &event_schema, &back).unwrap_or_else(|e| panic!("{e}: {back}"));
    }
    for v in &commands {
        let typed = jsonl::decode_command(&v.to_string()).unwrap_or_else(|e| panic!("{e}: {v}"));
        let back = serde_json::to_value(&typed).expect("value");
        assert!(subset(v, &back), "command lost data\n {v}\n {back}");
        assert_eq!(
            typed,
            jsonl::decode_command(&jsonl::encode(&typed)).expect("again")
        );
        validate(&command_schema, &command_schema, &back).unwrap_or_else(|e| panic!("{e}: {back}"));
    }
}

#[test]
fn fixtures_cover_every_type() {
    let (events, commands) = all_messages();
    let seen = |m: &[Value]| -> BTreeSet<String> {
        m.iter()
            .filter_map(|v| v["type"].as_str().map(str::to_owned))
            .collect()
    };
    for t in EVENT_TYPES {
        assert!(seen(&events).contains(t), "no event fixture of type {t}");
    }
    for t in COMMAND_TYPES {
        assert!(
            seen(&commands).contains(t),
            "no command fixture of type {t}"
        );
    }
    // the type list and the Rust enums agree
    for line in lines("events.jsonl") {
        let e = jsonl::decode_event(&line).expect("event");
        assert!(EVENT_TYPES.contains(&e.type_name()));
    }
    for line in lines("commands.jsonl") {
        let c = jsonl::decode_command(&line).expect("command");
        assert!(COMMAND_TYPES.contains(&c.type_name()));
    }
}

#[test]
fn seeded_faults_fail_the_type_and_the_schema() {
    let event_schema = root_schema("Event");
    let command_schema = root_schema("Command");
    let bad_events = [
        json!({"type":"ready","engine":"e","session":"s","cwd":"/"}),
        json!({"type":"text"}),
        json!({"type":"text","delta":"x","extra":1}),
        json!({"type":"usage","tokens":-1,"window":1}),
        json!({"type":"login_required","reason":"nope"}),
        json!({"type":"tool_call","id":"a"}),
        json!({"type":"done","status":3}),
    ];
    for v in &bad_events {
        assert!(jsonl::decode_event(&v.to_string()).is_err(), "{v}");
        assert!(validate(&event_schema, &event_schema, v).is_err(), "{v}");
    }
    let bad_commands = [
        json!({"type":"user_message"}),
        json!({"type":"permission_response","id":"p","decision":"maybe"}),
        json!({"type":"set_mode","mode":"yolo"}),
        json!({"type":"complete","id":"c","trigger":"#"}),
        json!({"type":"interrupt","x":1}),
        json!({"type":"user_message","text":"a","attachments":[{"kind":"video","data_base64":""}]}),
    ];
    for v in &bad_commands {
        assert!(jsonl::decode_command(&v.to_string()).is_err(), "{v}");
        assert!(
            validate(&command_schema, &command_schema, v).is_err(),
            "{v}"
        );
    }
}

#[test]
fn bad_lines_are_errors_not_crashes() {
    assert_eq!(
        jsonl::decode_event("{oops").unwrap_err().0,
        "not JSON: {oops"
    );
    assert_eq!(
        jsonl::decode_event("[1]").unwrap_err().0,
        "event must be a JSON object"
    );
    assert_eq!(
        jsonl::decode_event(r#"{"type":"warp"}"#).unwrap_err().0,
        "unknown event type \"warp\""
    );
    assert_eq!(
        jsonl::decode_event("{}").unwrap_err().0,
        "unknown event type null"
    );
    assert!(jsonl::decode_command(r#"{"type":"text","delta":"x"}"#).is_err());
}

#[test]
fn line_buffer_gives_the_same_lines_however_bytes_are_cut() {
    let stream: String = lines("events.jsonl")
        .iter()
        .map(|l| format!("{l}\n"))
        .collect();
    let bytes = stream.as_bytes();
    let whole = jsonl::LineBuffer::new().feed(bytes);
    for size in [1, 2, 3, 7, 64] {
        let mut buf = jsonl::LineBuffer::new();
        let mut got = Vec::new();
        for piece in bytes.chunks(size) {
            got.extend(buf.feed(piece));
        }
        assert_eq!(got, whole, "chunk size {size}");
        assert_eq!(buf.finish(), None);
    }
    let mut buf = jsonl::LineBuffer::new();
    assert!(buf.feed(b"\r\n\n{\"type\":\"interrupt\"}").is_empty());
    assert_eq!(buf.finish().as_deref(), Some("{\"type\":\"interrupt\"}"));
}

#[test]
fn version_in_ready_is_checked() {
    let ok = jsonl::decode_event(&lines("events.jsonl")[2]).expect("ready");
    assert!(check_ready(&ok).is_ok());
    let old = jsonl::decode_event(
        r#"{"type":"ready","version":"9","engine":"9","session":"s","cwd":"/","mode":"default"}"#,
    )
    .expect("ready");
    assert_eq!(
        check_ready(&old).unwrap_err().to_string(),
        "this front end speaks engine protocol E1 version 1 but the engine reports \"9\"; update the laris program and the front end together"
    );
}

#[test]
fn channel_carries_the_same_messages() {
    let (interface, core) = channel();
    interface
        .commands
        .send(Command::Slash {
            name: "help".into(),
            args: String::new(),
        })
        .expect("send");
    core.events
        .send(Event::Text { delta: "x".into() })
        .expect("send");
    assert_eq!(core.commands.recv().expect("recv").type_name(), "command");
    assert_eq!(interface.events.recv().expect("recv").type_name(), "text");
}

#[test]
fn error_codes_that_end_a_command() {
    let e = jsonl::decode_event(
        &lines("events.jsonl")
            .iter()
            .find(|l| l.contains("unknown_command"))
            .expect("line")
            .clone(),
    )
    .expect("event");
    assert!(e.ends_command());
    let other = Event::Error {
        code: "model_down".into(),
        message: "x".into(),
    };
    assert!(!other.ends_command());
}

#[test]
fn the_eleven_scenarios_are_translated_and_replayed() {
    let all = scenarios();
    assert_eq!(all.len(), 11);
    for (name, scenario, raw) in &all {
        let played = replay(scenario).unwrap_or_else(|e| panic!("{name}: {e}"));
        // every emitted event of the file came back, in order, unless the version stopped the replay
        let written: Vec<Value> = raw["steps"]
            .as_array()
            .expect("steps")
            .iter()
            .flat_map(|s| s["emit"].as_array().cloned().unwrap_or_default())
            .collect();
        if name == "mismatch" {
            let m = played.version_mismatch.as_ref().expect("mismatch detected");
            assert_eq!(m.reported, "9");
        } else {
            assert!(played.version_mismatch.is_none(), "{name}");
            assert_eq!(played.events.len(), written.len(), "{name}");
        }
        for (got, want) in played.events.iter().zip(&written) {
            let back = serde_json::to_value(got).expect("value");
            assert!(subset(want, &back), "{name}: {want} vs {back}");
        }
    }
}

#[test]
fn broken_scenarios_are_refused() {
    let unknown_result =
        r#"{"name":"x","steps":[{"emit":[{"type":"tool_result","id":"c","name":"t"}]}]}"#;
    assert!(
        Scenario::parse(unknown_result)
            .unwrap_err()
            .0
            .contains("unknown call")
    );
    let unknown_response = r#"{"name":"x","steps":[{"expect":{"type":"permission_response","id":"p","decision":"allow"},"emit":[]}]}"#;
    assert!(
        Scenario::parse(unknown_response)
            .unwrap_err()
            .0
            .contains("unknown permission request")
    );
    let bad_event = r#"{"name":"x","steps":[{"emit":[{"type":"warp"}]}]}"#;
    assert!(Scenario::parse(bad_event).is_err());
    let wrong = Scenario::parse(
        r#"{"name":"x","steps":[{"expect":{"type":"user_message","text":"a"},"emit":[]}]}"#,
    )
    .expect("parse");
    let mut tampered = wrong.clone();
    tampered.steps[0].command = Some(Command::UserMessage {
        text: "b".into(),
        attachments: vec![],
    });
    assert!(replay(&tampered).is_err());
}
