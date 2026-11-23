//! The brain decider in the server turn (T241, ADR-025 section 4): scenarios through the HTTP API with a scripted
//! model. The rule decider is deterministic; nothing here says anything about how well a real model answers.

use futures_util::future::BoxFuture;
use futures_util::{StreamExt, stream};
use laris_brain::gate::GateSettings;
use laris_brain::{answer::AnswerSettings, decide::RuleSettings};
use laris_protocol::p1::{ChatRequest, ChatResponseChunk, EmbedRequest, EmbedResponse};
use laris_server::mainbrain::{MainBrain, MainBrainConfig};
use laris_server::pipeline::{DeciderConfig, Grounding, Pipeline, PipelineConfig};
use laris_server::policy::{MemoryReasoning, Policy, PolicyConfig, PolicyGateway};
use laris_server::trace::MemoryTraces;
use laris_server::{
    ApiError, AppState, Backend, Caller, ChunkStream, MemorySink, ServerConfig, StreamFailure,
    serve,
};
use laris_vault::brain::Level;
use serde_json::{Value, json};
use std::collections::{HashMap, VecDeque};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::net::TcpListener;

static COUNTER: AtomicU32 = AtomicU32::new(0);

const GATE: GateSettings = GateSettings {
    min_support: 0.9,
    min_equivalence: 0.6,
    subject_overlap: 0.5,
    search_depth: 10,
    max_bytes: 100_000,
};

fn decider(compose: bool) -> DeciderConfig {
    DeciderConfig {
        rules: RuleSettings {
            required_level: Level::Sourced,
            min_coverage: 0.6,
            max_retrievals: 1,
            max_acquisitions: 0,
            max_advisor_asks: 1,
            max_repeats: 3,
        },
        answer: AnswerSettings {
            min_cover: 0.8,
            min_level: Level::Sourced,
            max_notes: 8,
            admissible: None,
        },
        max_steps: 10,
        max_seconds: 180.0,
        compose_without_model: compose,
    }
}

/// The shipped source classes (T285).
const CLASSES: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../configs/admissible-sources.json"
);

const PAPER: &str = "Aspirin reduces fever in adults. A dose of 500 mg was used in 2020.";
const FACT: &str = "Aspirin reduces fever in adults.";
const COVERED: &str = "Does aspirin reduce fever in adults?";
const PARTIAL: &str = "Does aspirin interact with warfarin in elderly patients?";
const UNKNOWN: &str = "Quantum chromodynamics lattice gauge";

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

type Script = Vec<Result<ChatResponseChunk, StreamFailure>>;

fn answer(text: &str) -> Script {
    let chunk = |delta: Value, finish: Option<&str>| -> ChatResponseChunk {
        serde_json::from_value(json!({
            "id": "m1", "object": "chat.completion.chunk", "model": "scripted",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]
        }))
        .unwrap()
    };
    vec![
        Ok(chunk(json!({"content": text}), None)),
        Ok(chunk(json!({}), Some("stop"))),
    ]
}

struct Scripted {
    scripts: Mutex<VecDeque<Script>>,
    calls: Arc<AtomicU32>,
}

impl Backend for Scripted {
    fn chat(&self, _request: ChatRequest) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let next = self.scripts.lock().unwrap().pop_front();
        Box::pin(async move {
            match next {
                Some(s) => Ok(stream::iter(s).boxed()),
                None => Err(ApiError::BadGateway("no more answers".into())),
            }
        })
    }

    fn embed(&self, _r: EmbedRequest) -> BoxFuture<'static, Result<EmbedResponse, ApiError>> {
        Box::pin(async { Err(ApiError::BadGateway("no embed".into())) })
    }
}

struct Server {
    port: u16,
    calls: Arc<AtomicU32>,
    traces: Arc<MemoryTraces>,
    brain: Arc<MainBrain>,
    _stop: tokio::sync::oneshot::Sender<()>,
}

async fn start(compose: bool, grounding: Grounding, scripts: Vec<Script>) -> Server {
    start_with(decider(compose), grounding, scripts).await
}

async fn start_with(config: DeciderConfig, grounding: Grounding, scripts: Vec<Script>) -> Server {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let mut cfg = ServerConfig::with_bind(addr);
    cfg.stream_idle = Duration::from_secs(5);
    let policy =
        Arc::new(Policy::load(&PolicyConfig::with_root(repo()), std::iter::empty(), None).unwrap());
    let calls = Arc::new(AtomicU32::new(0));
    let model = Scripted {
        scripts: Mutex::new(scripts.into()),
        calls: calls.clone(),
    };
    let reasoning = Arc::new(MemoryReasoning::new(20));
    let gateway = Arc::new(PolicyGateway::new(
        policy.clone(),
        Arc::new(model),
        reasoning.clone(),
    ));
    let n = COUNTER.fetch_add(1, Ordering::Relaxed);
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join(format!("decider-{n}"));
    let _ = std::fs::remove_dir_all(&dir);
    let brain = Arc::new(MainBrain::open(&MainBrainConfig { dir, gate: GATE }).unwrap());
    let backend = Arc::new(
        Pipeline::new(
            gateway,
            PipelineConfig {
                grounding,
                ..PipelineConfig::default()
            },
            None,
            policy.harness().cloned(),
            Some(brain.clone()),
        )
        .unwrap()
        .with_decider(config)
        .unwrap(),
    );
    let traces = Arc::new(MemoryTraces::default());
    let state = AppState::open(cfg, backend)
        .with_policy(policy, reasoning)
        .with_traces(traces.clone())
        .with_main_brain(brain.clone());
    let (tx, rx) = tokio::sync::oneshot::channel::<()>();
    tokio::spawn(async move {
        let _ = serve(
            listener,
            Arc::new(state),
            Arc::new(MemorySink::default()),
            async {
                let _ = rx.await;
            },
        )
        .await;
    });
    Server {
        port: addr.port(),
        calls,
        traces,
        brain,
        _stop: tx,
    }
}

async fn post(server: &Server, path: &str, body: Value) -> (u16, Value, String) {
    let response = reqwest::Client::new()
        .post(format!("http://127.0.0.1:{}{path}", server.port))
        .header(
            "x-laris-protocol",
            laris_protocol::PROTOCOL_VERSION.to_string(),
        )
        .json(&body)
        .send()
        .await
        .unwrap();
    let status = response.status().as_u16();
    let text = response.text().await.unwrap();
    (
        status,
        serde_json::from_str(&text).unwrap_or(Value::Null),
        text,
    )
}

/// The claim path stored.
async fn store_fact(server: &Server) -> String {
    let source = json!({"title": "Paper A", "kind": "document", "identifier": "doi:10.1/a", "text": PAPER,
        "metadata": {"kind": "verified", "registry": "registry-fixture"}});
    post(server, "/v1/admin/brain/sources", source).await;
    let claim =
        json!({"statement": FACT, "quote": FACT, "requested": "sourced", "source": "Paper A"});
    let (_, body, _) = post(server, "/v1/admin/brain/claims", claim).await;
    assert_eq!(body["decision"], "accepted", "{body}");
    body["path"].as_str().unwrap().to_owned()
}

#[derive(Debug, Default)]
struct Reply {
    text: String,
    decision: Option<(String, String)>,
    steps: Vec<(String, String, String)>,
    evidence: Vec<Value>,
}

async fn chat(server: &Server, question: &str, turn: Option<Value>) -> Reply {
    let mut laris = json!({"kind": "turn", "session_id": "sess-1"});
    if let Some(turn) = turn {
        laris["turn"] = turn;
    }
    let body = json!({"stream": true, "messages": [{"role": "user", "content": question}],
        "laris": laris});
    let (status, _, wire) = post(server, "/v1/laris/chat", body).await;
    assert_eq!(status, 200, "{wire}");
    let mut reply = Reply::default();
    for line in wire.lines() {
        let Some(data) = line.strip_prefix("data: ") else {
            continue;
        };
        let Ok(value) = serde_json::from_str::<Value>(data) else {
            continue;
        };
        if let Some(list) = value.pointer("/laris/steps").and_then(Value::as_array) {
            for s in list {
                let get = |k: &str| s[k].as_str().unwrap_or("").to_owned();
                reply
                    .steps
                    .push((get("stage"), get("outcome"), get("code")));
            }
        }
        if let Some(list) = value.pointer("/laris/evidence").and_then(Value::as_array) {
            reply.evidence.extend(list.iter().cloned());
        }
        if let Some(d) = value.pointer("/laris/decision") {
            reply.decision = Some((
                d["action"].as_str().unwrap_or("").to_owned(),
                d["rule"].as_str().unwrap_or("").to_owned(),
            ));
        }
        if let Some(t) = value
            .pointer("/choices/0/delta/content")
            .and_then(Value::as_str)
        {
            reply.text.push_str(t);
        }
    }
    reply
}

fn decided(reply: &Reply, action: &str, rule: &str) {
    assert_eq!(
        reply.decision,
        Some((action.to_owned(), rule.to_owned())),
        "{:?}",
        reply.steps
    );
}

fn harness_text() -> laris_policy::HarnessConfig {
    let text = std::fs::read_to_string(repo().join(".laris/harness.toml")).unwrap();
    laris_policy::HarnessConfig::from_toml(&text).unwrap()
}

fn abstain_text() -> String {
    let text = std::fs::read_to_string(repo().join(".laris/harness.toml")).unwrap();
    laris_policy::HarnessConfig::from_toml(&text)
        .unwrap()
        .abstain_no_source
}

// ---------------------------------------------------------------- the scenarios

#[tokio::test]
async fn the_turn_stops_when_the_budget_is_spent() {
    let server = start(false, Grounding::Optional, vec![answer("never")]).await;
    store_fact(&server).await;
    let reply = chat(&server, COVERED, Some(json!({"budget_left": 0.0}))).await;
    decided(&reply, "stop", "R1-limit");
    assert_eq!(reply.text, harness_text().decider_stop);
    assert_eq!(server.calls.load(Ordering::SeqCst), 0);
    assert!(
        reply
            .steps
            .contains(&("decider".into(), "stop".into(), "stop:R1-limit".into()))
    );
}

#[tokio::test]
async fn the_turn_stops_on_steps_time_and_a_cycle_whatever_the_client_claims() {
    let server = start(false, Grounding::Optional, vec![]).await;
    for turn in [
        json!({"steps_used": 10}),
        json!({"steps_used": 4_000_000_000u64}),
        json!({"seconds_used": 1e12}),
        json!({"repeats": 3}),
    ] {
        let reply = chat(&server, COVERED, Some(turn.clone())).await;
        decided(&reply, "stop", "R1-limit");
        assert_eq!(server.calls.load(Ordering::SeqCst), 0, "{turn}");
    }
}

#[tokio::test]
async fn with_no_evidence_the_turn_abstains_without_the_model() {
    let server = start(false, Grounding::Required, vec![answer("from memory")]).await;
    let reply = chat(&server, UNKNOWN, None).await;
    decided(&reply, "abstain", "R6-abstain");
    assert_eq!(reply.text, abstain_text());
    assert_eq!(server.calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn an_answer_from_accepted_claims_does_not_call_the_model() {
    let server = start(true, Grounding::Required, vec![answer("never")]).await;
    store_fact(&server).await;
    let reply = chat(&server, COVERED, None).await;
    decided(&reply, "answer", "R3-covered");
    assert!(reply.text.contains(FACT), "{}", reply.text);
    assert!(
        reply.text.contains("[["),
        "the note id is on the sentence: {}",
        reply.text
    );
    assert_eq!(server.calls.load(Ordering::SeqCst), 0);
    let stages: Vec<_> = reply.steps.iter().map(|s| s.0.as_str()).collect();
    assert_eq!(stages, ["prefilter", "retrieval", "decider", "assembly"]);
    // the Claims the answer rests on are sent as evidence, with the span the write gate checked
    assert_eq!(reply.evidence.len(), 1, "{:?}", reply.evidence);
    let e = &reply.evidence[0];
    assert_eq!(e["origin"], "server");
    assert_eq!(e["level"], "sourced");
    assert!(e["sha256"].as_str().is_some_and(|h| h.len() == 64), "{e}");
    assert!(e["end"].as_u64() > e["start"].as_u64(), "{e}");
}

#[tokio::test]
async fn with_source_classes_a_claim_without_an_admission_record_does_not_answer_alone() {
    let mut config = decider(true);
    config.answer.admissible = Some(Arc::new(
        laris_brain::certain::Admissibility::load(Path::new(CLASSES)).unwrap(),
    ));
    let server = start_with(config, Grounding::Required, vec![answer("from the model")]).await;
    store_fact(&server).await;
    let reply = chat(&server, COVERED, None).await;
    let (action, rule) = reply.decision.clone().expect("a decision");
    assert_ne!(
        (action.as_str(), rule.as_str()),
        ("answer", "R3-covered"),
        "the stored Source has no admission record, so its Claim is not certain"
    );
    assert!(reply.evidence.is_empty(), "{:?}", reply.evidence);
}

#[tokio::test]
async fn a_covered_question_goes_to_the_model_when_composing_is_off() {
    let server = start(false, Grounding::Required, vec![]).await;
    let path = store_fact(&server).await;
    let draft = format!("Aspirin reduces fever in adults [{path} #1].");
    server.calls.store(0, Ordering::SeqCst);
    // the scripted model is built before the claim exists, so give it its answer by restarting with a script
    drop(server);
    let server = start(false, Grounding::Required, vec![answer(&draft)]).await;
    store_fact(&server).await;
    let reply = chat(&server, COVERED, None).await;
    decided(&reply, "answer", "R3-covered");
    assert_eq!(server.calls.load(Ordering::SeqCst), 1);
    assert_eq!(reply.text, draft);
    assert!(
        reply
            .steps
            .contains(&("gate".into(), "ok".into(), "".into()))
    );
}

#[tokio::test]
async fn a_partly_covered_question_asks_the_advisor_and_the_gate_still_decides() {
    let server = start(false, Grounding::Optional, vec![answer("A free answer.")]).await;
    store_fact(&server).await;
    let reply = chat(&server, PARTIAL, None).await;
    decided(&reply, "ask_advisor", "R7-ask-advisor");
    assert!(
        server.calls.load(Ordering::SeqCst) >= 1,
        "the model was asked"
    );
    assert!(
        !reply.text.contains("A free answer."),
        "an ungrounded draft never reaches the user when passages exist"
    );
}

#[tokio::test]
async fn forged_counters_cannot_skip_a_stage_or_widen_the_choice() {
    let server = start(false, Grounding::Required, vec![answer("never")]).await;
    // the advisor "already asked" and everything else absurd: the stages still run, the turn only ends earlier
    let turn = json!({"advisor_asks": 9999, "steps_used": -5, "seconds_used": "soon", "budget_left": 7.5,
        "repeats": null, "extra": [1, 2, 3]});
    let reply = chat(&server, UNKNOWN, Some(turn)).await;
    let stages: Vec<_> = reply.steps.iter().map(|s| s.0.as_str()).collect();
    assert_eq!(stages, ["prefilter", "retrieval", "decider"]);
    decided(&reply, "abstain", "R6-abstain");
    // a counter that says "nothing has happened" is the default and gives the same choice
    let again = chat(&server, UNKNOWN, None).await;
    assert_eq!(again.decision, reply.decision);
    assert_eq!(server.calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn every_decision_is_logged_with_its_rule_and_without_text() {
    let server = start(true, Grounding::Required, vec![]).await;
    store_fact(&server).await;
    chat(&server, COVERED, None).await;
    chat(&server, UNKNOWN, Some(json!({"budget_left": 0.0}))).await;
    let rows: Vec<_> = {
        let mut rows = Vec::new();
        for _ in 0..100 {
            rows = server
                .traces
                .records()
                .into_iter()
                .filter(|r| r.route == "chat")
                .collect();
            if rows.len() >= 2 {
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        rows
    };
    let codes: Vec<String> = rows
        .iter()
        .flat_map(|r| r.stages.iter())
        .filter(|s| s.stage == "decider")
        .map(|s| s.code.clone())
        .collect();
    assert_eq!(codes, ["answer:R3-covered", "stop:R1-limit"]);
    let wire = format!("{rows:?}");
    assert!(!wire.contains("aspirin") && !wire.contains("Aspirin") && !wire.contains("Quantum"));
    let _ = &server.brain;
}

#[tokio::test]
async fn a_caller_without_brain_read_is_not_decided_by_the_brain() {
    let server_less = {
        let policy =
            Policy::load(&PolicyConfig::with_root(repo()), std::iter::empty(), None).unwrap();
        let n = COUNTER.fetch_add(1, Ordering::Relaxed);
        let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join(format!("decider-direct-{n}"));
        let _ = std::fs::remove_dir_all(&dir);
        let brain = Arc::new(MainBrain::open(&MainBrainConfig { dir, gate: GATE }).unwrap());
        Pipeline::new(
            Arc::new(Scripted {
                scripts: Mutex::new(vec![answer("free")].into()),
                calls: Arc::default(),
            }),
            PipelineConfig {
                grounding: Grounding::Optional,
                ..PipelineConfig::default()
            },
            None,
            policy.harness().cloned(),
            Some(brain),
        )
        .unwrap()
        .with_decider(decider(true))
        .unwrap()
    };
    let request: ChatRequest = serde_json::from_value(json!({
        "messages": [{"role": "user", "content": COVERED}], "stream": true,
        "laris": {"kind": "turn", "session_id": "sess-1"}
    }))
    .unwrap();
    let who = Caller {
        key_id: Some("k1".into()),
        brain_read: false,
    };
    let mut out = server_less.chat_as(request, &who).await.unwrap();
    let mut wire = String::new();
    while let Some(Ok(c)) = out.next().await {
        wire.push_str(&serde_json::to_string(&c).unwrap());
    }
    assert!(wire.contains("no_permission"), "{wire}");
    assert!(!wire.contains("R3-covered") && wire.contains("free"));
}

#[test]
fn the_settings_are_required_together_and_the_network_cannot_be_enabled() {
    let all: HashMap<String, String> = [
        ("LARIS_SERVER__DECIDER_ENABLED", "true"),
        ("LARIS_SERVER__DECIDER_REQUIRED_LEVEL", "sourced"),
        ("LARIS_SERVER__DECIDER_MIN_COVERAGE", "0.6"),
        ("LARIS_SERVER__DECIDER_MAX_RETRIEVALS", "1"),
        ("LARIS_SERVER__DECIDER_MAX_ADVISOR_ASKS", "1"),
        ("LARIS_SERVER__DECIDER_MAX_REPEATS", "3"),
        ("LARIS_SERVER__DECIDER_ANSWER_MIN_COVER", "0.8"),
        ("LARIS_SERVER__DECIDER_ANSWER_MIN_LEVEL", "sourced"),
        ("LARIS_SERVER__DECIDER_ANSWER_MAX_NOTES", "8"),
        ("LARIS_SERVER__DECIDER_MAX_STEPS", "10"),
        ("LARIS_SERVER__DECIDER_MAX_SECONDS", "180"),
        ("LARIS_SERVER__DECIDER_ADMISSIBLE_SOURCES", CLASSES),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_owned(), v.to_owned()))
    .collect();
    let mut expected = decider(false);
    expected.answer.admissible = Some(std::sync::Arc::new(
        laris_brain::certain::Admissibility::load(std::path::Path::new(CLASSES)).unwrap(),
    ));
    assert_eq!(DeciderConfig::from_env(&all).unwrap(), Some(expected));
    let mut unreadable = all.clone();
    unreadable.insert(
        "LARIS_SERVER__DECIDER_ADMISSIBLE_SOURCES".into(),
        "/nonexistent/classes.json".into(),
    );
    let error = DeciderConfig::from_env(&unreadable)
        .unwrap_err()
        .to_string();
    assert!(error.contains("ADMISSIBLE_SOURCES"), "{error}");
    assert_eq!(DeciderConfig::from_env(&HashMap::new()).unwrap(), None);
    for name in all.keys().filter(|k| !k.ends_with("ENABLED")) {
        let mut less = all.clone();
        less.remove(name);
        let error = DeciderConfig::from_env(&less).unwrap_err().to_string();
        assert!(error.contains(name.as_str()), "{error}");
    }
    let mut bad = all.clone();
    bad.insert("LARIS_SERVER__DECIDER_MIN_COVERAGE".into(), "1.5".into());
    assert!(DeciderConfig::from_env(&bad).is_err());
    let mut candidate = all.clone();
    candidate.insert(
        "LARIS_SERVER__DECIDER_REQUIRED_LEVEL".into(),
        "candidate".into(),
    );
    assert!(DeciderConfig::from_env(&candidate).is_err());
    let mut network = all.clone();
    network.insert("LARIS_SERVER__DECIDER_NETWORK".into(), "true".into());
    assert!(
        DeciderConfig::from_env(&network).is_err(),
        "the network is not promoted"
    );
}
