//! P1 step events, the decision and the evidence list (T242, ADR-025 section 6): the typed fields round-trip, a
//! chunk of an older server still parses, and fields of a newer peer are kept.

use laris_protocol::{ChatResponseChunk, LarisMeta};
use serde_json::json;

#[test]
fn steps_decision_and_evidence_round_trip() {
    let wire = json!({
        "id": "x", "object": "chat.completion.chunk", "model": "",
        "laris": {
            "brain": [],
            "steps": [{"stage": "retrieval", "outcome": "ok", "ms": 4, "code": ""}],
            "decision": {"action": "answer", "rule": "R3-covered"},
            "evidence": [{"id": "Claims/A.md", "origin": "server", "level": "sourced", "title": "A",
                          "start": 0, "end": 10, "sha256": "ab"}],
            "newer": 1
        },
        "choices": []
    });
    let chunk: ChatResponseChunk = serde_json::from_value(wire.clone()).unwrap();
    let meta = chunk.laris.clone().unwrap();
    assert_eq!(meta.steps[0].stage, "retrieval");
    assert_eq!(meta.decision.as_ref().unwrap().rule, "R3-covered");
    assert_eq!(meta.evidence[0].origin, "server");
    assert!(meta.extra.contains_key("newer"));
    assert_eq!(
        serde_json::to_value(&chunk).unwrap()["laris"],
        wire["laris"]
    );
}

#[test]
fn a_chunk_without_the_new_fields_still_parses_and_stays_small() {
    let meta: LarisMeta = serde_json::from_value(json!({"brain": ["Note"]})).unwrap();
    assert!(meta.steps.is_empty() && meta.decision.is_none() && meta.evidence.is_empty());
    let text = serde_json::to_string(&meta).unwrap();
    assert!(
        !text.contains("steps") && !text.contains("evidence"),
        "{text}"
    );
}

#[test]
fn the_protocol_version_was_bumped_for_the_new_fields() {
    assert_eq!(laris_protocol::PROTOCOL_VERSION, "2");
}
