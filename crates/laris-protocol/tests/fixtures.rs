//! Round-trip and schema tests on every fixture (T123). `p1/` and `p2/` hold request and response pairs;
//! `authored/` holds hand-written ones (see its README).

mod common;

use common::*;
use laris_protocol::p1::*;
use laris_protocol::*;
use serde::Serialize;
use serde::de::DeserializeOwned;
use serde_json::Value;
use std::path::Path;

/// Parses `v` as `T`, serialises it, and checks that nothing was lost and the result is stable.
fn round_trip<T: Serialize + DeserializeOwned + PartialEq + std::fmt::Debug>(
    v: &Value,
    what: &str,
) {
    let typed: T = serde_json::from_value(v.clone()).unwrap_or_else(|e| panic!("{what}: {e}\n{v}"));
    let back = serde_json::to_value(&typed).expect("serialise");
    assert!(
        subset(v, &back),
        "{what}: lost data\n original {v}\n back     {back}"
    );
    let again: T = serde_json::from_value(back).expect("reparse");
    assert_eq!(typed, again, "{what}: not stable");
}

fn schema_for_type(group: &str, name: &str) -> (Value, Value) {
    let all = schema::export();
    let schema = all[group][name].clone();
    assert!(schema.is_object(), "no schema for {group}/{name}");
    (schema.clone(), schema)
}

fn assert_schema(group: &str, name: &str, v: &Value, what: &str) {
    let (root, schema) = schema_for_type(group, name);
    if let Err(e) = validate(&root, &schema, v) {
        panic!("{what} does not validate against {group}/{name}: {e}\n{v}");
    }
}

/// Reads an SSE fixture, decoding events with the incremental decoder fed in awkward slices.
fn sse_data(path: &Path) -> Vec<String> {
    let bytes = text(path).into_bytes();
    let whole = SseDecoder::new().feed(&bytes).expect("decode");
    let mut decoder = SseDecoder::new();
    let mut sliced = Vec::new();
    for piece in bytes.chunks(7) {
        sliced.extend(decoder.feed(piece).expect("decode slice"));
    }
    assert_eq!(
        whole,
        sliced,
        "{}: decoding depends on how bytes are cut",
        path.display()
    );
    assert!(
        !decoder.has_pending(),
        "{}: unfinished event",
        path.display()
    );
    whole
}

fn p1_stream(path: &Path, what: &str) -> Vec<P1Event> {
    let data = sse_data(path);
    assert_eq!(
        data.last().map(String::as_str),
        Some("[DONE]"),
        "{what}: no [DONE]"
    );
    let events: Vec<P1Event> = data
        .iter()
        .map(|d| P1Event::from_data(d).unwrap_or_else(|e| panic!("{what}: {e}\n{d}")))
        .collect();
    for (d, e) in data.iter().zip(&events) {
        if let P1Event::Chunk(_) = e {
            let original: Value = serde_json::from_str(d).expect("json");
            assert!(
                subset(
                    &original,
                    &serde_json::from_slice::<Value>(&e.encode()[6..]).expect("re-encoded")
                ),
                "{what}: lost data in {d}"
            );
            assert_schema("p1", "ChatResponseChunk", &original, what);
        }
        // the encoded bytes decode again to the same event
        let again = SseDecoder::new().feed(&e.encode()).expect("decode again");
        assert_eq!(
            P1Event::from_data(&again[0]).expect("event"),
            *e,
            "{what}: encode/decode differs"
        );
    }
    events
}

fn p2_stream(path: &Path, what: &str) -> Vec<P2Event> {
    let data = sse_data(path);
    assert_eq!(
        data.last().map(String::as_str),
        Some("[DONE]"),
        "{what}: no [DONE]"
    );
    data.iter()
        .map(|d| {
            let e = P2Event::from_data(d).unwrap_or_else(|e| panic!("{what}: {e}\n{d}"));
            if let P2Event::Chunk(_) = e {
                let original: Value = serde_json::from_str(d).expect("json");
                let back: Value = serde_json::from_slice(&e.encode()[6..]).expect("re-encoded");
                assert!(subset(&original, &back), "{what}: lost data in {d}");
                assert_schema("p2", "ChatCompletionChunk", &original, what);
            }
            e
        })
        .collect()
}

#[test]
fn p1_requests_round_trip_and_validate() {
    for path in files("p1")
        .iter()
        .filter(|p| p.to_string_lossy().ends_with(".request.json"))
    {
        let name = stem(path);
        let v = json(path);
        let what = format!("p1/{name} request");
        match name.as_str() {
            "embed" => {
                round_trip::<EmbedRequest>(&v, &what);
                assert_schema("p1", "EmbedRequest", &v, &what);
            }
            "error_invalid_request" => {
                // the server refuses it (400: messages required); so must the Rust type
                assert!(
                    serde_json::from_value::<ChatRequest>(v.clone()).is_err(),
                    "{what} must be refused"
                );
            }
            n if n.starts_with("chat_") || n == "error_protocol_mismatch" => {
                round_trip::<ChatRequest>(&v, &what);
                assert_schema("p1", "ChatRequest", &v, &what);
            }
            _ => assert!(v.is_null(), "{what}: GET routes have no body"),
        }
    }
}

#[test]
fn p1_responses_round_trip_and_validate() {
    let mut seen = 0;
    for path in files("p1")
        .iter()
        .filter(|p| p.to_string_lossy().contains(".response."))
    {
        let name = stem(path);
        let what = format!("p1/{name} response");
        seen += 1;
        if path.extension().is_some_and(|e| e == "sse") {
            p1_stream(path, &what);
            continue;
        }
        let v = json(path);
        match name.as_str() {
            "embed" => {
                round_trip::<EmbedResponse>(&v, &what);
                assert_schema("p1", "EmbedResponse", &v, &what);
            }
            "models" => {
                round_trip::<ModelList>(&v, &what);
                assert_schema("p1", "ModelList", &v, &what);
            }
            "workflows" => {
                round_trip::<WorkflowsResponse>(&v, &what);
                assert_schema("p1", "WorkflowsResponse", &v, &what);
            }
            "help" => {
                round_trip::<HelpResponse>(&v, &what);
                assert_schema("p1", "HelpResponse", &v, &what);
            }
            "account" => {
                round_trip::<AccountResponse>(&v, &what);
                assert_schema("p1", "AccountResponse", &v, &what);
            }
            n if n.starts_with("error_") || n == "chat_refused_before_stream" => {
                round_trip::<HttpError>(&v, &what);
                assert_schema("p1", "HttpError", &v, &what);
            }
            other => panic!("p1/{other}: no type assigned to this fixture"),
        }
    }
    assert!(
        seen == 16,
        "expected the recorded P1 responses, found {seen}"
    );
}

#[test]
fn p1_streams_carry_evidence_usage_and_errors() {
    let dir = fixtures().join("p1");
    let brain = p1_stream(&dir.join("chat_brain.response.sse"), "chat_brain");
    let evidence: Vec<&Vec<String>> = brain
        .iter()
        .filter_map(|e| match e {
            P1Event::Chunk(c) => c.laris.as_ref().map(|l| &l.brain),
            _ => None,
        })
        .collect();
    assert_eq!(
        evidence,
        [&vec![
            "Brain Index".to_owned(),
            "Citation Analysis".to_owned(),
            "Citation Analysis Playbook".to_owned()
        ]]
    );
    let usage = brain.iter().find_map(|e| match e {
        P1Event::Chunk(c) => c.usage.clone(),
        _ => None,
    });
    assert!(usage.is_some_and(|u| u.total_tokens == u.prompt_tokens + u.completion_tokens));

    let text = p1_stream(&dir.join("chat_text.response.sse"), "chat_text");
    assert!(matches!(text.last(), Some(P1Event::Done)));
    assert!(text.iter().all(|e| !matches!(e, P1Event::Error(_))));

    let tool = p1_stream(&dir.join("chat_tool_call.response.sse"), "chat_tool_call");
    let calls: Vec<_> = tool
        .iter()
        .filter_map(|e| match e {
            P1Event::Chunk(c) => Some(
                c.choices
                    .iter()
                    .flat_map(|ch| ch.delta.tool_calls.clone())
                    .collect::<Vec<_>>(),
            ),
            _ => None,
        })
        .flatten()
        .collect();
    assert_eq!(calls.len(), 1);
    assert_eq!(calls[0].function.name, "read_file");
    let args: Value =
        serde_json::from_str(&calls[0].function.arguments).expect("arguments are JSON");
    assert_eq!(args["path"], "notes/a.md");

    // an error after the stream started is an `error` event, then [DONE]
    let failed = p1_stream(
        &dir.join("chat_midstream_error.response.sse"),
        "chat_midstream_error",
    );
    let n = failed.len();
    assert!(matches!(&failed[n - 2], P1Event::Error(e) if e.error.message == "model died"));
    assert!(matches!(failed[n - 1], P1Event::Done));
    assert!(
        failed[..n - 2]
            .iter()
            .all(|e| matches!(e, P1Event::Chunk(_)))
    );
}

#[test]
fn p2_fixtures_round_trip_and_validate() {
    let mut seen = 0;
    for path in files("p2") {
        let name = stem(&path);
        let file = path.to_string_lossy().to_string();
        if file.ends_with(".status") {
            continue;
        }
        seen += 1;
        let what = format!("p2/{name}");
        if file.ends_with(".request.json") {
            let v = json(&path);
            if name == "embeddings" {
                round_trip::<EmbedRequest>(&v, &what);
                assert_schema("p2", "EmbedRequest", &v, &what);
            } else if name == "models" {
                assert!(v.is_null());
            } else {
                round_trip::<ModelChatRequest>(&v, &what);
                assert_schema("p2", "ModelChatRequest", &v, &what);
            }
        } else if file.ends_with(".sse") {
            let events = p2_stream(&path, &what);
            assert!(matches!(events.last(), Some(P2Event::Done)));
        } else {
            let v = json(&path);
            match name.as_str() {
                "embeddings" => {
                    round_trip::<EmbedResponse>(&v, &what);
                    assert_schema("p2", "EmbedResponse", &v, &what);
                }
                "models" => round_trip::<ModelList>(&v, &what),
                _ => {
                    round_trip::<ChatCompletion>(&v, &what);
                    assert_schema("p2", "ChatCompletion", &v, &what);
                }
            }
        }
    }
    assert!(
        seen == 16,
        "expected the recorded P2 fixtures, found {seen}"
    );
}

#[test]
fn p2_reasoning_and_tool_calls_survive() {
    let dir = fixtures().join("p2");
    let events = p2_stream(
        &dir.join("stream_reasoning.response.sse"),
        "stream_reasoning",
    );
    let reasoning: String = events
        .iter()
        .filter_map(|e| match e {
            P2Event::Chunk(c) => Some(
                c.choices
                    .iter()
                    .filter_map(|ch| ch.delta.reasoning_content.clone())
                    .collect::<String>(),
            ),
            _ => None,
        })
        .collect();
    assert_eq!(reasoning, "The user asks about stability. ");
    let events = p2_stream(
        &dir.join("stream_tool_call.response.sse"),
        "stream_tool_call",
    );
    let reasons: Vec<_> = events
        .iter()
        .filter_map(|e| match e {
            P2Event::Chunk(c) => c.choices.first().and_then(|ch| ch.finish_reason),
            _ => None,
        })
        .collect();
    assert_eq!(reasons, [FinishReason::ToolCalls]);
    let events = p2_stream(&dir.join("stream_error.response.sse"), "stream_error");
    assert!(events.iter().any(|e| matches!(e, P2Event::Error(_))));
}

#[test]
fn authored_fixtures_round_trip_and_validate() {
    let dir = fixtures().join("authored");
    let load = |n: &str| json(&dir.join(n));
    for n in ["account_metered.json", "account_unlimited.json"] {
        round_trip::<AccountResponse>(&load(n), n);
        assert_schema("p1", "AccountResponse", &load(n), n);
    }
    round_trip::<AdminUsage>(&load("admin_usage.json"), "admin_usage");
    assert_schema("p1", "AdminUsage", &load("admin_usage.json"), "admin_usage");
    for n in ["admin_reasoning_list.json", "admin_reasoning_one.json"] {
        round_trip::<AdminReasoning>(&load(n), n);
        assert_schema("p1", "AdminReasoning", &load(n), n);
    }
    round_trip::<ToolRequest>(&load("tool_request.json"), "tool_request");
    assert_schema(
        "p1",
        "ToolRequest",
        &load("tool_request.json"),
        "tool_request",
    );
    for n in ["tool_response_ok.json", "tool_response_error.json"] {
        round_trip::<ToolResponse>(&load(n), n);
        assert_schema("p1", "ToolResponse", &load(n), n);
    }
    // comments are skipped, unknown fields and non-ASCII text survive
    let events = p1_stream(
        &dir.join("stream_unicode_and_extras.sse"),
        "stream_unicode_and_extras",
    );
    match &events[0] {
        P1Event::Chunk(c) => {
            assert_eq!(
                c.choices[0].delta.content.as_deref(),
                Some("Tiếng Việt: nguồn #1 ✓")
            );
            assert_eq!(c.extra["future_field"]["a"], 1);
        }
        other => panic!("{other:?}"),
    }
    let account: AccountResponse =
        serde_json::from_value(load("account_unlimited.json")).expect("account");
    assert_eq!((account.token_limit, account.tokens_left), (None, None));
}

#[test]
fn every_recorded_fixture_has_a_status_and_a_known_shape() {
    for group in ["p1", "p2"] {
        for path in files(group)
            .iter()
            .filter(|p| p.to_string_lossy().ends_with(".status"))
        {
            let code: u16 = text(path).trim().parse().expect("status is a number");
            let stem = stem(path);
            let sse = path.with_file_name(format!("{stem}.response.sse")).exists();
            assert!(
                !sse || code == 200,
                "{group}/{stem}: a stream starts with 200, got {code}"
            );
            if code != 200 {
                let body = json(&path.with_file_name(format!("{stem}.response.json")));
                assert!(
                    body["error"].is_string(),
                    "{group}/{stem}: HTTP errors carry a string `error`"
                );
            }
        }
    }
}

#[test]
fn seeded_faults_are_caught() {
    // a fixture with a wrong shape must fail the schema check and the typed parse
    let (root, schema) = schema_for_type("p1", "ChatRequest");
    for bad in [
        serde_json::json!({"stream": true}),
        serde_json::json!({"messages": [{"role": "robot", "content": "x"}]}),
        serde_json::json!({"messages": "hello"}),
        serde_json::json!({"messages": [{"role": "user", "content": 7}]}),
    ] {
        assert!(
            validate(&root, &schema, &bad).is_err(),
            "schema accepted {bad}"
        );
        assert!(
            serde_json::from_value::<ChatRequest>(bad.clone()).is_err(),
            "type accepted {bad}"
        );
    }
    let (root, schema) = schema_for_type("p2", "ChatCompletion");
    let wrong_reason = serde_json::json!({"id": "x", "object": "chat.completion", "created": 1, "model": "m",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "a"}, "finish_reason": "banana"}]});
    assert!(validate(&root, &schema, &wrong_reason).is_err());
    assert!(serde_json::from_value::<ChatCompletion>(wrong_reason).is_err());
    // a broken event payload is an error, not a silent skip
    assert!(P1Event::from_data("{not json").is_err());
    assert!(P2Event::from_data(r#"{"id": 5}"#).is_err());
}

// ---------------------------------------------------------------- scientific tools (T149)
//
// Recorded from the Python tool box by `scripts/record_scientific_fixtures.py`: every request and result parses as its
// type, survives a round trip, and validates against the exported schema.

fn scientific(name: &str) -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/scientific")
        .join(name);
    serde_json::from_str(
        &std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{path:?}: {e}")),
    )
    .unwrap_or_else(|e| panic!("{name}: {e}"))
}

fn tool_pair<A, R>(tool: &str, args: &str, result: &str)
where
    A: Serialize + DeserializeOwned + PartialEq + std::fmt::Debug,
    R: Serialize + DeserializeOwned + PartialEq + std::fmt::Debug,
{
    let request = scientific(&format!("{tool}.request.json"));
    round_trip::<ToolRequest>(&request, tool);
    assert_schema("p1", "ToolRequest", &request, tool);
    round_trip::<A>(&request["arguments"], tool);
    assert_schema("scientific", args, &request["arguments"], tool);
    let response = scientific(&format!("{tool}.response.json"));
    round_trip::<ToolResponse>(&response, tool);
    assert_schema("p1", "ToolResponse", &response, tool);
    round_trip::<R>(&response["result"], tool);
    assert_schema("scientific", result, &response["result"], tool);
}

#[test]
fn scientific_tool_fixtures_round_trip_and_validate() {
    use laris_protocol::scientific::*;
    tool_pair::<ExtractDiscourseArgs, DiscourseExtraction>(
        EXTRACT_DISCOURSE,
        "ExtractDiscourseArgs",
        "DiscourseExtraction",
    );
    tool_pair::<DetectLimitationsArgs, LimitationReport>(
        DETECT_LIMITATIONS,
        "DetectLimitationsArgs",
        "LimitationReport",
    );
    tool_pair::<NormalizeQuantitiesArgs, Quantities>(
        NORMALIZE_QUANTITIES,
        "NormalizeQuantitiesArgs",
        "Quantities",
    );
    tool_pair::<ParseBibliographyArgs, BibliographyResult>(
        PARSE_BIBLIOGRAPHY,
        "ParseBibliographyArgs",
        "BibliographyResult",
    );
    tool_pair::<AnalyseCitationsArgs, CitationResult>(
        ANALYSE_CITATIONS,
        "AnalyseCitationsArgs",
        "CitationResult",
    );
    tool_pair::<SolveStemArgs, SolveStemResult>(SOLVE_STEM, "SolveStemArgs", "SolveStemResult");
    let solved: SolveStemResult =
        serde_json::from_value(scientific("solve_stem.response.json")["result"].clone()).unwrap();
    assert_eq!(solved.status, STATUS_VERIFIED);
    assert!(solved.checks.iter().all(|c| c.passed));
    let mining = scientific("mine_literature.request.json");
    round_trip::<MineLiteratureArgs>(&mining["arguments"], MINE_LITERATURE);
    assert_schema(
        "scientific",
        "MineLiteratureArgs",
        &mining["arguments"],
        "mine",
    );
    let error = scientific("error.response.json");
    round_trip::<ToolResponse>(&error, "error");
    assert_eq!(error["error"]["type"], ERR_INVALID_ARGUMENTS);
}

#[test]
fn the_tool_list_names_the_scientific_tools() {
    let list = scientific("tools.list.json");
    round_trip::<ToolList>(&list, "tools.list");
    assert_schema("p1", "ToolList", &list, "tools.list");
    let typed: ToolList = serde_json::from_value(list).unwrap();
    let names: Vec<&str> = typed
        .tools
        .iter()
        .map(|t| t.function.name.as_str())
        .collect();
    assert_eq!(names, laris_protocol::scientific::TOOLS);
}

#[test]
fn scientific_offsets_slice_the_text_in_scalar_values() {
    let request = scientific("extract_discourse.request.json");
    let text: Vec<char> = request["arguments"]["text"]
        .as_str()
        .unwrap()
        .chars()
        .collect();
    let found: laris_protocol::scientific::DiscourseExtraction =
        serde_json::from_value(scientific("extract_discourse.response.json")["result"].clone())
            .unwrap();
    let entities = found.claims.iter().chain(&found.limitations);
    let mut checked = 0;
    for e in entities {
        let c = &e.coordinate;
        let slice: String = text[c.char_start as usize..c.char_end as usize]
            .iter()
            .collect();
        assert_eq!(slice.trim_end(), c.verbatim_snippet.trim_end());
        checked += 1;
    }
    assert!(checked >= 2);
}
