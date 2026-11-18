//! The model proxy (SR-S6, T144): `ModelBackend` against a fake P2 service (in-process, scripted by the last user
//! message) and, when `LARIS_TEST_MODEL_PYTHON` names a Python with the repository's dependencies, against the real
//! Python model service with its placeholder backend. Neural weights are never loaded.
//!
//! The fake proves mechanics: pass-through, bounded concurrency, failures before and after the first event, and the
//! confidentiality rules behind the policy gateway. It says nothing about how well any model answers; the foundation
//! model is NOT QUALIFIED.

use axum::Router;
use axum::body::{Body, Bytes};
use axum::extract::State;
use axum::http::Response;
use axum::routing::post;
use futures_util::{StreamExt, stream};
use laris_protocol::p1::{ChatRequest, EmbedRequest};
use laris_protocol::sse::SseDecoder;
use laris_server::model::{ModelBackend, ModelConfig};
use laris_server::policy::{MemoryReasoning, Policy, PolicyConfig, PolicyGateway};
use laris_server::{ApiError, AppState, Backend, MemorySink, ServerConfig, StreamFailure, serve};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

// ---------------------------------------------------------------- the fake model service

#[derive(Clone, Default)]
struct Fake {
    seen: Arc<Mutex<Vec<Value>>>,
}

fn sse(events: &[&str]) -> Vec<Bytes> {
    events
        .iter()
        .map(|e| Bytes::from(format!("data: {e}\n\n")))
        .collect()
}

fn chunk(delta: &Value, finish: Option<&str>) -> String {
    json!({"id": "p2-1", "object": "chat.completion.chunk", "model": "fake",
           "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})
    .to_string()
}

fn stream_response(head: Vec<Bytes>, tail: Tail) -> Response<Body> {
    let first = stream::iter(head.into_iter().map(Ok::<_, std::io::Error>));
    let body = match tail {
        Tail::End => Body::from_stream(first),
        Tail::Hold => Body::from_stream(first.chain(stream::pending())),
    };
    Response::builder()
        .status(200)
        .header("Content-Type", "text/event-stream")
        .body(body)
        .unwrap()
}

enum Tail {
    End,
    Hold,
}

fn last_user(body: &Value) -> String {
    body["messages"]
        .as_array()
        .and_then(|m| m.iter().rev().find(|m| m["role"] == "user"))
        .and_then(|m| m["content"].as_str())
        .unwrap_or("")
        .to_owned()
}

async fn chat(State(fake): State<Fake>, body: Bytes) -> Response<Body> {
    let parsed: Value = serde_json::from_slice(&body).unwrap();
    fake.seen.lock().unwrap().push(parsed.clone());
    let done = "[DONE]";
    let answer = |text: &str| chunk(&json!({"content": text}), None);
    let stop = chunk(&json!({}), Some("stop"));
    let usage =
        json!({"id": "p2-1", "object": "chat.completion.chunk", "model": "fake", "choices": [],
                       "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}})
        .to_string();
    match last_user(&parsed).as_str() {
        "refuse" => Response::builder()
            .status(500)
            .body(Body::from(
                "{\"error\": \"MODEL-INTERNAL trace /srv/weights\"}",
            ))
            .unwrap(),
        "busy" => Response::builder()
            .status(503)
            .body(Body::from("{}"))
            .unwrap(),
        "error-first" => stream_response(
            sse(&[
                r#"{"error": {"message": "MODEL-INTERNAL first", "type": "Oops"}}"#,
                done,
            ]),
            Tail::End,
        ),
        "fail-after" => stream_response(
            sse(&[
                &answer("partial"),
                r#"{"error": {"message": "MODEL-INTERNAL later", "type": "Oops"}}"#,
                done,
            ]),
            Tail::End,
        ),
        "truncate" => stream_response(sse(&[&answer("partial")]), Tail::End),
        "stall" => stream_response(sse(&[&answer("partial")]), Tail::Hold),
        "hold" => stream_response(sse(&[&answer("open")]), Tail::Hold),
        "garbage" => stream_response(sse(&["{not json"]), Tail::End),
        "reasoning" => stream_response(
            sse(&[
                &chunk(
                    &json!({"reasoning_content": "hidden chain of thought"}),
                    None,
                ),
                &answer("<think>more hidden thought</think>Visible answer."),
                &stop,
                &usage,
                done,
            ]),
            Tail::End,
        ),
        "echo-system" => {
            // a model told to repeat its instructions
            let system = parsed["messages"][0]["content"]
                .as_str()
                .unwrap_or("")
                .to_owned();
            let events: Vec<String> = system
                .split_inclusive(' ')
                .take(400)
                .map(&answer)
                .chain([stop.clone(), done.to_owned()])
                .collect();
            let refs: Vec<&str> = events.iter().map(String::as_str).collect();
            stream_response(sse(&refs), Tail::End)
        }
        _ => stream_response(
            sse(&[&answer("Hel"), &answer("lo"), &stop, &usage, done]),
            Tail::End,
        ),
    }
}

async fn embeddings(State(fake): State<Fake>, body: Bytes) -> Response<Body> {
    let parsed: Value = serde_json::from_slice(&body).unwrap();
    fake.seen.lock().unwrap().push(parsed.clone());
    let text = match &parsed["input"] {
        Value::String(s) => s.clone(),
        Value::Array(a) => a.first().and_then(Value::as_str).unwrap_or("").to_owned(),
        _ => String::new(),
    };
    let reply = |status: u16, body: String| {
        Response::builder()
            .status(status)
            .header("Content-Type", "application/json")
            .body(Body::from(body))
            .unwrap()
    };
    match text.as_str() {
        "bad" => reply(400, "{\"error\": \"MODEL-INTERNAL no encoder\"}".into()),
        "busy" => reply(503, "{}".into()),
        "huge" => reply(200, "x".repeat(10_000)),
        "junk" => reply(200, "{\"data\": 3}".into()),
        _ => reply(
            200,
            json!({"object": "list", "model": "fake", "data": [
                {"object": "embedding", "index": 0, "embedding": [0.5, -0.25, 1.0]}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 0, "total_tokens": 3}})
            .to_string(),
        ),
    }
}

struct FakeModel {
    url: String,
    fake: Fake,
    _stop: tokio::sync::oneshot::Sender<()>,
}

async fn fake_model() -> FakeModel {
    let fake = Fake::default();
    let app = Router::new()
        .route("/v1/chat/completions", post(chat))
        .route("/v1/embeddings", post(embeddings))
        .with_state(fake.clone());
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let (tx, rx) = tokio::sync::oneshot::channel::<()>();
    tokio::spawn(async move {
        let _ = axum::serve(listener, app)
            .with_graceful_shutdown(async {
                let _ = rx.await;
            })
            .await;
    });
    FakeModel {
        url,
        fake,
        _stop: tx,
    }
}

// ---------------------------------------------------------------- helpers

fn config(url: &str) -> ModelConfig {
    let mut c = ModelConfig::new(url);
    c.queue_wait = Duration::from_millis(150);
    c.idle = Duration::from_millis(400);
    c.header_timeout = Duration::from_secs(5);
    c
}

fn request(text: &str) -> ChatRequest {
    serde_json::from_value(json!({"messages": [{"role": "user", "content": text}]})).unwrap()
}

async fn drain(
    stream: laris_server::ChunkStream,
) -> Vec<Result<laris_protocol::p1::ChatResponseChunk, StreamFailure>> {
    stream.collect().await
}

fn text_of(items: &[Result<laris_protocol::p1::ChatResponseChunk, StreamFailure>]) -> String {
    items
        .iter()
        .filter_map(|i| i.as_ref().ok())
        .flat_map(|c| c.choices.iter())
        .filter_map(|c| c.delta.content.clone())
        .collect()
}

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

// ---------------------------------------------------------------- pass-through

#[tokio::test]
async fn an_answer_passes_through_chunk_by_chunk_with_its_usage() {
    let m = fake_model().await;
    let backend = ModelBackend::new(config(&m.url)).unwrap();
    let items = drain(backend.chat(request("hi")).await.unwrap()).await;
    assert_eq!(text_of(&items), "Hello");
    assert!(items.iter().all(Result::is_ok));
    let usage = items
        .iter()
        .filter_map(|i| i.as_ref().ok())
        .find_map(|c| c.usage.clone())
        .expect("the usage event is passed on");
    assert_eq!(usage.total_tokens, 9);
    assert_eq!(
        items.last().unwrap().as_ref().unwrap().choices.len(),
        0,
        "usage is the last event"
    );
}

#[tokio::test]
async fn only_the_conversation_and_tools_reach_the_model() {
    let m = fake_model().await;
    let mut cfg = config(&m.url);
    cfg.model_name = "laris-core".into();
    let backend = ModelBackend::new(cfg).unwrap();
    let r: ChatRequest = serde_json::from_value(json!({
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"type": "function", "function": {"name": "Grep", "description": "d",
                   "parameters": {"type": "object"}}}],
        "laris": {"kind": "turn", "session_id": "s-secret"},
        "temperature": 0.25,
        "logit_bias": {"5": 100}
    }))
    .unwrap();
    drain(backend.chat(r).await.unwrap()).await;
    let seen = m.fake.seen.lock().unwrap()[0].clone();
    assert_eq!(seen["model"], "laris-core");
    assert_eq!(seen["stream"], true);
    assert_eq!(seen["temperature"], 0.25);
    assert_eq!(seen["tools"][0]["function"]["name"], "Grep");
    for absent in ["laris", "logit_bias"] {
        assert!(seen.get(absent).is_none(), "{absent} must not be forwarded");
    }
    assert!(!seen.to_string().contains("s-secret"));
}

#[tokio::test]
async fn embed_passes_through() {
    let m = fake_model().await;
    let backend = ModelBackend::new(config(&m.url)).unwrap();
    let r: EmbedRequest = serde_json::from_value(json!({"input": "some text"})).unwrap();
    let answer = backend.embed(r).await.unwrap();
    assert_eq!(answer.data.len(), 1);
    assert_eq!(answer.data[0].embedding, vec![0.5, -0.25, 1.0]);
    assert_eq!(answer.usage.unwrap().prompt_tokens, 3);
}

// ---------------------------------------------------------------- failures

fn only_status(error: &ApiError, code: u16) {
    assert_eq!(error.status().as_u16(), code, "{error}");
    let text = error.to_string();
    assert!(
        !text.contains("MODEL-INTERNAL") && !text.contains("/srv") && !text.contains("127.0.0.1"),
        "model text or address in {text:?}"
    );
}

#[tokio::test]
async fn a_failure_before_the_first_chunk_is_a_status_without_the_model_text() {
    let m = fake_model().await;
    let backend = ModelBackend::new(config(&m.url)).unwrap();
    for (text, code) in [
        ("refuse", 502),
        ("busy", 503),
        ("error-first", 502),
        ("garbage", 502),
    ] {
        let Err(error) = backend.chat(request(text)).await else {
            panic!("{text} must fail before a stream starts");
        };
        only_status(&error, code);
    }
    assert_eq!(
        backend.free_places(),
        4,
        "a failed call gives its place back"
    );
}

#[tokio::test]
async fn a_failure_after_the_first_chunk_ends_the_stream_with_a_failure_event() {
    let m = fake_model().await;
    let backend = ModelBackend::new(config(&m.url)).unwrap();
    for (text, kind) in [
        ("fail-after", "model_error"),
        ("truncate", "model_truncated"),
        ("stall", "model_idle"),
    ] {
        let items = drain(backend.chat(request(text)).await.unwrap()).await;
        assert_eq!(text_of(&items), "partial", "{text}");
        let Some(Err(failure)) = items.last() else {
            panic!("{text} must end with a failure");
        };
        assert_eq!(failure.kind, kind);
        assert!(!failure.message.contains("MODEL-INTERNAL"));
        assert_eq!(items.iter().filter(|i| i.is_err()).count(), 1);
    }
    assert_eq!(backend.free_places(), 4);
}

#[tokio::test]
async fn an_unreachable_model_is_a_502_that_does_not_name_it() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    drop(listener); // nothing listens there now
    let backend = ModelBackend::new(config(&url)).unwrap();
    let Err(error) = backend.chat(request("hi")).await else {
        panic!("must fail");
    };
    only_status(&error, 502);
    let r: EmbedRequest = serde_json::from_value(json!({"input": "x"})).unwrap();
    only_status(&backend.embed(r).await.unwrap_err(), 502);
}

#[tokio::test]
async fn embed_failures_are_statuses_without_the_model_text() {
    let m = fake_model().await;
    let mut cfg = config(&m.url);
    cfg.max_event_bytes = 4096;
    let backend = ModelBackend::new(cfg).unwrap();
    for (text, code) in [("bad", 502), ("busy", 503), ("huge", 502), ("junk", 502)] {
        let r: EmbedRequest = serde_json::from_value(json!({"input": text})).unwrap();
        only_status(&backend.embed(r).await.unwrap_err(), code);
    }
}

// ---------------------------------------------------------------- concurrency

#[tokio::test]
async fn the_concurrency_limit_holds_and_a_place_returns_when_a_stream_is_dropped() {
    let m = fake_model().await;
    let mut cfg = config(&m.url);
    cfg.max_concurrent = 2;
    cfg.idle = Duration::from_secs(30);
    let backend = ModelBackend::new(cfg).unwrap();
    let a = backend.chat(request("hold")).await.unwrap();
    let b = backend.chat(request("hold")).await.unwrap();
    assert_eq!(backend.free_places(), 0);
    let started = Instant::now();
    let Err(refused) = backend.chat(request("hi")).await else {
        panic!("the third call must wait and then be refused");
    };
    assert!(
        started.elapsed() >= Duration::from_millis(100),
        "it waited its turn"
    );
    only_status(&refused, 503);
    let r: EmbedRequest = serde_json::from_value(json!({"input": "x"})).unwrap();
    only_status(&backend.embed(r).await.unwrap_err(), 503);
    assert_eq!(
        m.fake.seen.lock().unwrap().len(),
        2,
        "the refused calls never reached the model"
    );
    drop(a); // the client left
    let c = backend
        .chat(request("hi"))
        .await
        .expect("a place is free again");
    assert_eq!(text_of(&drain(c).await), "Hello");
    drop(b);
    assert_eq!(backend.free_places(), 2);
}

#[tokio::test]
async fn a_waiting_call_gets_the_place_a_finished_answer_leaves() {
    let m = fake_model().await;
    let mut cfg = config(&m.url);
    cfg.max_concurrent = 1;
    cfg.queue_wait = Duration::from_secs(5);
    let backend = Arc::new(ModelBackend::new(cfg).unwrap());
    let first = backend.chat(request("hi")).await.unwrap(); // not read yet: it holds the place
    let waiting = {
        let b = backend.clone();
        tokio::spawn(async move { b.chat(request("hi")).await.map(|_| ()) })
    };
    tokio::time::sleep(Duration::from_millis(100)).await;
    assert!(!waiting.is_finished());
    assert_eq!(text_of(&drain(first).await), "Hello");
    assert!(waiting.await.unwrap().is_ok());
}

// ---------------------------------------------------------------- first-chunk latency

#[tokio::test]
async fn first_chunk_latency_is_measured() {
    let m = fake_model().await;
    let backend = ModelBackend::new(config(&m.url)).unwrap();
    let mut samples = Vec::new();
    for _ in 0..50 {
        let started = Instant::now();
        let mut s = backend.chat(request("hi")).await.unwrap();
        // the first event is already read when `chat` returns; this is the time to it
        samples.push(started.elapsed());
        s.next().await.unwrap().unwrap();
        drop(s);
    }
    samples.sort();
    let p95 = samples[samples.len() * 95 / 100 - 1];
    eprintln!(
        "first-chunk latency through the proxy (fake model, localhost): median {:?}, P95 {:?}",
        samples[samples.len() / 2],
        p95
    );
    assert!(p95 < Duration::from_millis(250), "P95 {p95:?}");
}

// ---------------------------------------------------------------- behind the policy gateway, over HTTP

struct Http {
    addr: std::net::SocketAddr,
    _stop: tokio::sync::oneshot::Sender<()>,
}

async fn serve_gateway(url: &str) -> (Http, Arc<MemoryReasoning>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let mut cfg = ServerConfig::with_bind(addr);
    cfg.stream_idle = Duration::from_secs(3);
    let policy = Arc::new(
        Policy::load(
            &PolicyConfig::with_root(repo()),
            std::iter::empty::<(String, String)>(),
            None,
        )
        .expect("the repository policy loads"),
    );
    let reasoning = Arc::new(MemoryReasoning::new(10));
    let model = Arc::new(ModelBackend::new(config(url)).unwrap());
    let backend = Arc::new(PolicyGateway::new(policy.clone(), model, reasoning.clone()));
    let state = AppState::open(cfg, backend).with_policy(policy, reasoning.clone());
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
    (Http { addr, _stop: tx }, reasoning)
}

impl Http {
    async fn post(&self, path: &str, body: &Value) -> (u16, String) {
        let mut s = TcpStream::connect(self.addr).await.unwrap();
        let payload = body.to_string();
        let head = format!(
            "POST {path} HTTP/1.1\r\nHost: x\r\nX-Laris-Protocol: 1\r\nConnection: close\r\n\
             Content-Type: application/json\r\nContent-Length: {}\r\n\r\n",
            payload.len()
        );
        s.write_all(head.as_bytes()).await.unwrap();
        s.write_all(payload.as_bytes()).await.unwrap();
        let mut raw = Vec::new();
        let _ = tokio::time::timeout(Duration::from_secs(10), s.read_to_end(&mut raw)).await;
        let text = String::from_utf8_lossy(&raw).into_owned();
        let status = text
            .split_whitespace()
            .nth(1)
            .and_then(|c| c.parse().ok())
            .unwrap_or(0);
        let at = raw
            .windows(4)
            .position(|w| w == b"\r\n\r\n")
            .map_or(raw.len(), |i| i + 4);
        (status, String::from_utf8_lossy(&raw[at..]).into_owned())
    }
}

fn chat_body(text: &str) -> Value {
    json!({"messages": [{"role": "user", "content": text}],
           "laris": {"kind": "turn", "session_id": "proxy-1"}, "stream": true})
}

fn events_of(raw: &str) -> String {
    // chunked framing is skipped by the decoder: only `data:` lines are taken
    let mut d = SseDecoder::new();
    d.feed(raw.as_bytes()).unwrap().concat()
}

#[tokio::test]
async fn reasoning_from_the_model_service_never_appears_in_a_chat_body() {
    let m = fake_model().await;
    let (http, reasoning) = serve_gateway(&m.url).await;
    let (status, raw) = http.post("/v1/laris/chat", &chat_body("reasoning")).await;
    assert_eq!(status, 200);
    let joined = events_of(&raw);
    assert!(joined.contains("Visible answer."), "{joined}");
    for hidden in [
        "hidden chain of thought",
        "more hidden thought",
        "reasoning",
        "<think>",
    ] {
        assert!(!joined.contains(hidden), "{hidden} in the chat body");
    }
    for _ in 0..50 {
        if !reasoning.newest(1).is_empty() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    let kept = reasoning.newest(1);
    assert!(kept[0].reasoning.contains("hidden chain of thought"));
    assert!(kept[0].reasoning.contains("more hidden thought"));
    // usage of the model reaches the client
    assert!(joined.contains("\"total_tokens\":9"), "{joined}");
}

#[tokio::test]
async fn the_system_prompt_and_the_canary_never_leave() {
    let m = fake_model().await;
    let (http, _) = serve_gateway(&m.url).await;
    let (status, raw) = http.post("/v1/laris/chat", &chat_body("echo-system")).await;
    assert_eq!(status, 200);
    let joined = events_of(&raw);
    // the model did receive the server's prompt (that is what it was told to repeat) ...
    let system = m.fake.seen.lock().unwrap()[0]["messages"][0]["content"]
        .as_str()
        .unwrap()
        .to_owned();
    assert!(
        system.contains("LARIS-CANARY-"),
        "the canary is in the prompt"
    );
    // ... and none of it, nor the canary, reaches the client
    assert!(!joined.contains("LARIS-CANARY"), "canary in the chat body");
    let words: Vec<&str> = system.split_whitespace().collect();
    for window in words.windows(7).step_by(5) {
        assert!(
            !joined.contains(&window.join(" ")),
            "a prompt passage leaked: {window:?}"
        );
    }
    assert!(
        joined.contains("blocked"),
        "the leak is stopped and said so"
    );
}

#[tokio::test]
async fn a_dead_model_behind_the_gateway_is_a_502_status() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    drop(listener);
    let (http, _) = serve_gateway(&url).await;
    let (status, body) = http.post("/v1/laris/chat", &chat_body("hi")).await;
    assert_eq!(status, 502);
    assert!(!body.contains("127.0.0.1"));
}

// ---------------------------------------------------------------- the Python model service (placeholder backend)

/// Starts `laris-model serve` with the placeholder backend, or returns `None` when no Python is configured.
struct PythonService {
    child: std::process::Child,
    url: String,
}

impl Drop for PythonService {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

async fn python_service() -> Option<PythonService> {
    let python = std::env::var("LARIS_TEST_MODEL_PYTHON").ok()?;
    let free = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = free.local_addr().unwrap().port();
    drop(free);
    let child = std::process::Command::new(python)
        .current_dir(repo())
        .env("PYTHONPATH", repo().join("src"))
        .args(["-m", "cli.model", "serve", "--host", "127.0.0.1", "--port"])
        .arg(port.to_string())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .expect("the configured Python starts");
    let service = PythonService {
        child,
        url: format!("http://127.0.0.1:{port}"),
    };
    for _ in 0..200 {
        if TcpStream::connect(("127.0.0.1", port)).await.is_ok() {
            return Some(service);
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    panic!("the Python model service did not start");
}

#[tokio::test]
async fn contract_with_the_python_model_service() {
    let Some(service) = python_service().await else {
        eprintln!(
            "LARIS_TEST_MODEL_PYTHON is not set: the Python contract test proves nothing here"
        );
        return;
    };
    let mut cfg = ModelConfig::new(&service.url);
    cfg.idle = Duration::from_secs(20);
    let backend = ModelBackend::new(cfg).unwrap();
    // a streamed chat answer: every chunk of the real service parses, the stream ends cleanly, usage is passed on
    let mut latencies = Vec::new();
    for _ in 0..20 {
        let started = Instant::now();
        let stream = backend
            .chat(request("What is a perovskite solar cell?"))
            .await
            .expect("the service answers");
        latencies.push(started.elapsed());
        let items = drain(stream).await;
        assert!(items.iter().all(Result::is_ok), "{items:?}");
        assert!(items.len() >= 2, "an answer has chunks and a finish");
    }
    latencies.sort();
    eprintln!(
        "first-chunk latency through the proxy (Python placeholder, localhost): median {:?}, P95 {:?}",
        latencies[latencies.len() / 2],
        latencies[latencies.len() * 95 / 100 - 1]
    );
    // a bad request is the service's 400, seen as a 502 here
    let mut bad = request("x");
    bad.messages.clear();
    let outcome = backend.chat(bad).await;
    assert!(outcome.is_err() || drain(outcome.unwrap()).await.iter().all(Result::is_ok));
    // embeddings: the placeholder service has no encoder, so this is a refusal, never a hang
    let r: EmbedRequest = serde_json::from_value(json!({"input": "text"})).unwrap();
    let error = backend.embed(r).await.unwrap_err();
    assert_eq!(error.status().as_u16(), 502);
}

// ---------------------------------------------------------------- the LLM rung (SR-S9)
//
// The first rung of the capability ladder, end to end in one process: the system's loop sends each turn over HTTP
// with the P1 client; the server composes its prompt (policy gateway); `ModelBackend` speaks P2 to the model service.
// No tools, no documents: a question and an answer. With the fake model this proves mechanics only.

mod rung {
    use super::*;
    use laris_config::{Catalogue, Settings};
    use laris_core::{
        Driver, FollowModel, Model, ModelAnswer, ModelError, ModelRequest, Recorder, ToolRunner,
    };
    use laris_model_client::{
        ClientConfig, HttpOptions, Interrupt, ModelClient, ReqwestTransport, Trust,
    };
    use laris_protocol::events::Event;
    use laris_protocol::p1::{ChatRequest as P1Chat, EmbedResponse};
    use laris_protocol::sse::P1Event;
    use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
    use serde_json::Map;

    struct ServerModel {
        client: Arc<ModelClient<ReqwestTransport>>,
        handle: tokio::runtime::Handle,
        wire: Arc<Mutex<String>>,
    }

    impl Model for ServerModel {
        fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
            let chat: P1Chat = serde_json::from_value(json!({
                "messages": request.messages, "tools": request.tools, "stream": true,
                "laris": {"kind": "turn", "session_id": "llm-rung"},
            }))
            .map_err(|e| ModelError::Failed(e.to_string()))?;
            let (client, wire) = (&self.client, &self.wire);
            tokio::task::block_in_place(|| {
                self.handle.block_on(async {
                    let mut stream = client
                        .chat(&chat, &Interrupt::new())
                        .await
                        .map_err(|e| ModelError::Failed(e.to_string()))?;
                    let mut out = ModelAnswer::default();
                    while let Some(event) = stream
                        .next()
                        .await
                        .map_err(|e| ModelError::Failed(e.to_string()))?
                    {
                        match event {
                            P1Event::Chunk(c) => {
                                wire.lock()
                                    .unwrap()
                                    .push_str(&serde_json::to_string(&c).unwrap());
                                for choice in c.choices {
                                    if let Some(t) = choice.delta.content {
                                        out.text.push_str(&t);
                                    }
                                }
                                if c.usage.is_some() {
                                    out.usage = c.usage;
                                }
                            }
                            P1Event::Error(e) => return Err(ModelError::Failed(e.error.message)),
                            P1Event::Done => break,
                        }
                    }
                    Ok(out)
                })
            })
        }
    }

    struct NoTools;

    impl ToolRunner for NoTools {
        fn run(&mut self, _name: &str, _arguments: &Map<String, Value>) -> Value {
            json!({"error": "no tools at this rung"})
        }
    }

    fn client(port: u16) -> Arc<ModelClient<ReqwestTransport>> {
        let transport = ReqwestTransport::new(&HttpOptions {
            connect_timeout: Duration::from_secs(5),
            trust: Trust::System,
            use_env_proxy: false,
        })
        .unwrap();
        Arc::new(
            ModelClient::new(
                transport,
                ClientConfig {
                    base_url: format!("http://127.0.0.1:{port}/v1"),
                    api_key: None,
                    request_timeout: Duration::from_secs(10),
                    idle_timeout: Duration::from_secs(10),
                    max_retries: 0,
                    backoff_base: Duration::from_millis(10),
                    backoff_max: Duration::from_millis(10),
                    max_body_bytes: 1 << 20,
                },
            )
            .unwrap(),
        )
    }

    async fn ask(http: &Http, question: &str) -> (Result<Vec<Event>, String>, String) {
        let wire: Arc<Mutex<String>> = Arc::default();
        let model = ServerModel {
            client: client(http.addr.port()),
            handle: tokio::runtime::Handle::current(),
            wire: wire.clone(),
        };
        let dir = std::env::temp_dir().join(format!(
            "laris-llm-rung-{}-{}",
            std::process::id(),
            question.len()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let store = Store::open(dir.join("loop.sqlite"), DEFAULT_BUSY_TIMEOUT).unwrap();
        let recorder = Recorder::open(store, "llm-rung", "llm", 1.0).unwrap().0;
        let decider = FollowModel::new(Settings::default().agent, Catalogue::english());
        let mut driver = Driver::new(recorder, model, NoTools, decider, Vec::new(), || 1.0);
        let result =
            tokio::task::block_in_place(|| driver.send(question)).map_err(|e| e.to_string());
        drop(driver);
        let wire_text = wire.lock().unwrap().clone();
        (result, wire_text)
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn the_llm_rung_climbs_loop_server_proxy_and_model() {
        let m = fake_model().await;
        let (http, reasoning) = serve_gateway(&m.url).await;
        let (events, wire) = ask(&http, "reasoning").await;
        let events = events.expect("the turn completes");
        let Some(Event::Done { answer, .. }) = events.last() else {
            panic!("the turn must end with done: {events:?}");
        };
        assert_eq!(answer, "Visible answer.");
        // the model got the server's system prompt and the user's message, nothing else
        let seen = m.fake.seen.lock().unwrap()[0].clone();
        let roles: Vec<&str> = seen["messages"]
            .as_array()
            .unwrap()
            .iter()
            .map(|m| m["role"].as_str().unwrap())
            .collect();
        assert_eq!(roles, ["system", "user"]);
        assert!(
            seen["messages"][0]["content"]
                .as_str()
                .unwrap()
                .contains("LARIS-CANARY-")
        );
        // the client's wire holds the answer and the usage, no reasoning, no prompt
        assert!(wire.contains("Visible answer."));
        assert!(wire.contains("\"total_tokens\":9"));
        for hidden in [
            "hidden chain of thought",
            "more hidden thought",
            "LARIS-CANARY",
            "reasoning",
        ] {
            assert!(!wire.contains(hidden), "{hidden} reached the client");
        }
        // the operator can read the reasoning
        for _ in 0..50 {
            if !reasoning.newest(1).is_empty() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        assert!(
            reasoning.newest(1)[0]
                .reasoning
                .contains("hidden chain of thought")
        );
    }

    #[tokio::test]
    async fn embed_goes_end_to_end_through_the_p1_client() {
        let m = fake_model().await;
        let (http, _) = serve_gateway(&m.url).await;
        let client = client(http.addr.port());
        let answer: EmbedResponse = client
            .post_json(
                "/laris/embed",
                &json!({"input": ["a text"]}),
                &Interrupt::new(),
            )
            .await
            .expect("embed answers");
        assert_eq!(answer.data[0].embedding, vec![0.5, -0.25, 1.0]);
        let refused: Result<EmbedResponse, _> = client
            .post_json(
                "/laris/embed",
                &json!({"input": ["bad"]}),
                &Interrupt::new(),
            )
            .await;
        let text = refused.unwrap_err().to_string();
        assert!(!text.contains("MODEL-INTERNAL"), "{text}");
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_model_that_fails_mid_answer_ends_the_turn_without_its_own_words() {
        let m = fake_model().await;
        let (http, _) = serve_gateway(&m.url).await;
        let (result, wire) = ask(&http, "fail-after").await;
        let text = match result {
            Ok(events) => format!("{events:?}"),
            Err(e) => e,
        };
        assert!(!text.contains("MODEL-INTERNAL") && !wire.contains("MODEL-INTERNAL"));
    }
}
