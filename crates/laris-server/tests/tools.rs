//! The scientific remote tools through the server (SR-S6, SR-M2, T149): `GET /v1/laris/tools` and
//! `POST /v1/laris/tools/{name}` against a fake model service (mechanics) and, when `LARIS_TEST_MODEL_PYTHON` names a
//! Python with the repository's dependencies, against the real Python model service, where the extraction and
//! citation fixtures must give the recorded results. No weights are loaded and nothing is trained.

use axum::Router;
use axum::body::{Body, Bytes};
use axum::extract::{Path as AxumPath, State};
use axum::http::Response;
use axum::routing::{get, post};
use laris_protocol::p1::{ToolRequest, ToolResponse};
use laris_protocol::scientific::{self, DiscourseExtraction};
use laris_server::model::{ModelBackend, ModelConfig};
use laris_server::{AppState, Backend, MemorySink, NoBackend, ServerConfig, serve};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn recorded(name: &str) -> Value {
    let path = repo()
        .join("crates/laris-protocol/tests/fixtures/scientific")
        .join(name);
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

// ---------------------------------------------------------------- the fake model service

#[derive(Clone, Default)]
struct Fake {
    /// Bodies received by tool routes, with the name.
    seen: Arc<Mutex<Vec<(String, Value)>>>,
    hits: Arc<Mutex<u32>>,
}

async fn list(State(fake): State<Fake>) -> Response<Body> {
    *fake.hits.lock().unwrap() += 1;
    reply(200, recorded("tools.list.json").to_string())
}

fn reply(status: u16, body: String) -> Response<Body> {
    Response::builder()
        .status(status)
        .header("Content-Type", "application/json")
        .body(Body::from(body))
        .unwrap()
}

async fn call(
    State(fake): State<Fake>,
    AxumPath(name): AxumPath<String>,
    body: Bytes,
) -> Response<Body> {
    let parsed: Value = serde_json::from_slice(&body).unwrap();
    fake.seen
        .lock()
        .unwrap()
        .push((name.clone(), parsed.clone()));
    match name.as_str() {
        "echo" => reply(200, json!({"result": {"got": parsed["arguments"]}}).to_string()),
        "refuses" => reply(
            200,
            json!({"error": {"message": "text must be a non-empty string", "type": "invalid_arguments"}})
                .to_string(),
        ),
        "boom" => reply(500, "{\"error\": \"MODEL-INTERNAL trace /srv/weights\"}".into()),
        "busy" => reply(503, "{}".into()),
        "junk" => reply(200, "{\"nothing\": true}".into()),
        "both" => reply(200, json!({"result": 1, "error": {"message": "m"}}).to_string()),
        "huge" => reply(200, format!("{{\"result\": \"{}\"}}", "x".repeat(20_000))),
        "hold" => {
            futures_util::future::pending::<()>().await;
            unreachable!()
        }
        _ => reply(404, "{\"error\": \"no such tool\"}".into()),
    }
}

struct Stop(#[allow(dead_code)] tokio::sync::oneshot::Sender<()>);

async fn fake_model() -> (String, Fake, Stop) {
    let fake = Fake::default();
    let app = Router::new()
        .route("/v1/tools", get(list))
        .route("/v1/tools/{name}", post(call))
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
    (url, fake, Stop(tx))
}

// ---------------------------------------------------------------- the server under test

struct Http {
    addr: std::net::SocketAddr,
    _stop: tokio::sync::oneshot::Sender<()>,
}

fn model_config(url: &str) -> ModelConfig {
    let mut c = ModelConfig::new(url);
    c.queue_wait = Duration::from_millis(150);
    c.idle = Duration::from_millis(400);
    c.header_timeout = Duration::from_millis(600);
    c.max_event_bytes = 10_000;
    c
}

async fn serve_backend(backend: Arc<dyn Backend>) -> Http {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let state = AppState::open(ServerConfig::with_bind(addr), backend);
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
    Http { addr, _stop: tx }
}

impl Http {
    async fn send(&self, method: &str, path: &str, body: Option<&Value>) -> (u16, String) {
        let mut s = TcpStream::connect(self.addr).await.unwrap();
        let payload = body.map(Value::to_string).unwrap_or_default();
        let mut head = format!(
            "{method} {path} HTTP/1.1\r\nHost: x\r\nX-Laris-Protocol: 1\r\nConnection: close\r\n"
        );
        if body.is_some() || method == "POST" {
            head.push_str(&format!(
                "Content-Type: application/json\r\nContent-Length: {}\r\n",
                payload.len()
            ));
        }
        head.push_str("\r\n");
        s.write_all(head.as_bytes()).await.unwrap();
        s.write_all(payload.as_bytes()).await.unwrap();
        let mut raw = Vec::new();
        let _ = tokio::time::timeout(Duration::from_secs(20), s.read_to_end(&mut raw)).await;
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
        let body = String::from_utf8_lossy(&raw[at..]).into_owned();
        (status, unchunk(&head_of(&text), &body))
    }

    async fn tool(&self, name: &str, arguments: Value) -> (u16, Value) {
        let (status, body) = self
            .send(
                "POST",
                &format!("/v1/laris/tools/{name}"),
                Some(&json!({ "arguments": arguments })),
            )
            .await;
        (status, serde_json::from_str(&body).unwrap_or(Value::Null))
    }
}

fn head_of(text: &str) -> String {
    text.split("\r\n\r\n").next().unwrap_or("").to_lowercase()
}

/// Removes HTTP/1.1 chunk framing when the head says the body is chunked.
fn unchunk(head: &str, body: &str) -> String {
    if !head.contains("transfer-encoding: chunked") {
        return body.to_owned();
    }
    let mut out = String::new();
    let mut rest = body;
    while let Some((size, tail)) = rest.split_once("\r\n") {
        let n = usize::from_str_radix(size.trim(), 16).unwrap_or(0);
        if n == 0 || tail.len() < n {
            break;
        }
        out.push_str(&tail[..n]);
        rest = tail[n..].trim_start_matches("\r\n");
    }
    out
}

async fn served(url: &str) -> (Http, Arc<ModelBackend>) {
    let model = Arc::new(ModelBackend::new(model_config(url)).unwrap());
    (serve_backend(model.clone()).await, model)
}

// ---------------------------------------------------------------- mechanics, with the fake

#[tokio::test]
async fn the_list_of_tools_comes_from_the_model_service() {
    let (url, fake, _stop) = fake_model().await;
    let (http, _) = served(&url).await;
    let (status, body) = http.send("GET", "/v1/laris/tools", None).await;
    assert_eq!(status, 200, "{body}");
    let list: laris_protocol::p1::ToolList = serde_json::from_str(&body).unwrap();
    let names: Vec<&str> = list
        .tools
        .iter()
        .map(|t| t.function.name.as_str())
        .collect();
    assert_eq!(names, scientific::TOOLS);
    assert_eq!(*fake.hits.lock().unwrap(), 1);
}

#[tokio::test]
async fn only_the_arguments_reach_the_tool_and_its_answer_passes_through() {
    let (url, fake, _stop) = fake_model().await;
    let (http, _) = served(&url).await;
    let request =
        json!({"arguments": {"text": "τ = 5 K"}, "laris": {"session": "s-secret"}, "x": 1});
    let (status, body) = http
        .send("POST", "/v1/laris/tools/echo", Some(&request))
        .await;
    assert_eq!(status, 200, "{body}");
    let answer: ToolResponse = serde_json::from_str(&body).unwrap();
    assert_eq!(answer.result.unwrap(), json!({"got": {"text": "τ = 5 K"}}));
    let seen = fake.seen.lock().unwrap().clone();
    assert_eq!(
        seen,
        vec![("echo".to_owned(), json!({"arguments": {"text": "τ = 5 K"}}))]
    );
    assert!(!seen[0].1.to_string().contains("s-secret"));
}

#[tokio::test]
async fn a_refusal_by_the_tool_is_a_tool_result_not_a_failure() {
    let (url, _fake, _stop) = fake_model().await;
    let (http, _) = served(&url).await;
    let (status, body) = http.tool("refuses", json!({})).await;
    assert_eq!(status, 200);
    assert_eq!(body["error"]["type"], scientific::ERR_INVALID_ARGUMENTS);
    assert!(body.get("result").is_none());
}

#[tokio::test]
async fn a_name_nobody_serves_is_a_404_and_a_bad_name_never_reaches_the_model() {
    let (url, fake, _stop) = fake_model().await;
    let (http, _) = served(&url).await;
    assert_eq!(http.tool("nope", json!({})).await.0, 404);
    let reached = fake.seen.lock().unwrap().len();
    for bad in ["Bad-Name", "a.b", "UPPER", "x%2fy", &"a".repeat(65)] {
        let (status, _) = http.tool(bad, json!({})).await;
        assert_eq!(status, 404, "{bad}");
    }
    assert_eq!(fake.seen.lock().unwrap().len(), reached);
    // the wrong method and a body that is not a request
    assert_eq!(http.send("GET", "/v1/laris/tools/echo", None).await.0, 405);
    let (status, _) = http
        .send("POST", "/v1/laris/tools/echo", Some(&json!([1])))
        .await;
    assert_eq!(status, 400);
}

#[tokio::test]
async fn failures_of_the_service_are_statuses_without_its_text_or_address() {
    let (url, _fake, _stop) = fake_model().await;
    let (http, model) = served(&url).await;
    for (name, code) in [
        ("boom", 502),
        ("busy", 503),
        ("junk", 502),
        ("both", 502),
        ("huge", 502),
        ("hold", 502),
    ] {
        let (status, body) = http
            .send(
                "POST",
                &format!("/v1/laris/tools/{name}"),
                Some(&json!({"arguments": {}})),
            )
            .await;
        assert_eq!(status, code, "{name}: {body}");
        for secret in ["MODEL-INTERNAL", "/srv", "127.0.0.1"] {
            assert!(!body.contains(secret), "{name}: {secret} in {body}");
        }
    }
    assert_eq!(model.free_places(), 4, "every call gives its place back");
}

#[tokio::test]
async fn a_dead_or_missing_model_is_a_502() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let dead = format!("http://{}", listener.local_addr().unwrap());
    drop(listener);
    let (http, _) = served(&dead).await;
    for (status, body) in [
        http.send("GET", "/v1/laris/tools", None).await,
        http.send(
            "POST",
            "/v1/laris/tools/echo",
            Some(&json!({"arguments": {}})),
        )
        .await,
    ] {
        assert_eq!(status, 502);
        assert!(!body.contains("127.0.0.1"), "{body}");
    }
    let none = serve_backend(Arc::new(NoBackend)).await;
    assert_eq!(none.send("GET", "/v1/laris/tools", None).await.0, 502);
    assert_eq!(none.tool("echo", json!({})).await.0, 502);
}

#[tokio::test]
async fn tool_calls_share_the_bounded_places_of_the_model_proxy() {
    let (url, _fake, _stop) = fake_model().await;
    let mut cfg = model_config(&url);
    cfg.max_concurrent = 1;
    cfg.header_timeout = Duration::from_secs(3);
    let model = Arc::new(ModelBackend::new(cfg).unwrap());
    let http = Arc::new(serve_backend(model.clone()).await);
    let holder = {
        let http = http.clone();
        tokio::spawn(async move { http.tool("hold", json!({})).await })
    };
    for _ in 0..100 {
        if model.free_places() == 0 {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert_eq!(model.free_places(), 0, "the held call has the only place");
    let (status, _) = http.tool("echo", json!({})).await;
    assert_eq!(status, 503, "a second call is refused after its wait");
    let _ = holder.await;
    assert_eq!(model.free_places(), 1);
}

// ---------------------------------------------------------------- the real Python model service

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

type Span = (usize, usize);
type Spans = Vec<(&'static str, Span)>;
const TYPES: [&str; 7] = [
    "claim",
    "method",
    "dataset",
    "metric",
    "result",
    "limitation",
    "assumption",
];

fn iou(a: Span, b: Span) -> f64 {
    let inter = a.1.min(b.1).saturating_sub(a.0.max(b.0));
    let union = (a.1 - a.0) + (b.1 - b.0) - inter;
    if union == 0 {
        0.0
    } else {
        inter as f64 / union as f64
    }
}

fn round4(x: f64) -> f64 {
    (x * 10_000.0).round() / 10_000.0
}

/// The evaluation of `research/evaluation/extraction.py` (one-to-one matching, IoU of at least 0.5, per-type F1
/// rounded to four places, macro average over the types that occur), on spans the server returned.
fn macro_f1(docs: &[(Spans, Spans)]) -> (BTreeMap<String, f64>, f64) {
    let mut totals: BTreeMap<&str, (u32, u32, u32)> = BTreeMap::new();
    for (predicted, gold) in docs {
        for kind in TYPES {
            let p: Vec<Span> = predicted
                .iter()
                .filter(|s| s.0 == kind)
                .map(|s| s.1)
                .collect();
            let g: Vec<Span> = gold.iter().filter(|s| s.0 == kind).map(|s| s.1).collect();
            let mut p = p;
            let mut g_sorted = g.clone();
            p.sort_unstable();
            g_sorted.sort_unstable();
            let mut used = vec![false; g_sorted.len()];
            let entry = totals.entry(kind).or_default();
            for ps in p {
                let mut best = (0.0, usize::MAX);
                for (i, gs) in g_sorted.iter().enumerate() {
                    let score = iou(ps, *gs);
                    if !used[i] && score > best.0 {
                        best = (score, i);
                    }
                }
                if best.0 >= 0.5 {
                    used[best.1] = true;
                    entry.0 += 1;
                } else {
                    entry.1 += 1;
                }
            }
            entry.2 += used.iter().filter(|u| !**u).count() as u32;
        }
    }
    let mut per_type = BTreeMap::new();
    for (kind, (tp, fp, fn_)) in totals {
        if tp + fp + fn_ == 0 {
            continue;
        }
        let precision = if tp + fp > 0 {
            f64::from(tp) / f64::from(tp + fp)
        } else {
            0.0
        };
        let recall = if tp + fn_ > 0 {
            f64::from(tp) / f64::from(tp + fn_)
        } else {
            0.0
        };
        let f1 = if precision + recall > 0.0 {
            2.0 * precision * recall / (precision + recall)
        } else {
            0.0
        };
        per_type.insert(kind.to_owned(), round4(f1));
    }
    let macro_f1 = round4(per_type.values().sum::<f64>() / per_type.len() as f64);
    (per_type, macro_f1)
}

#[tokio::test]
async fn extraction_through_the_server_reproduces_the_baseline() {
    let Some(service) = python_service().await else {
        eprintln!(
            "LARIS_TEST_MODEL_PYTHON is not set: the Python contract test proves nothing here"
        );
        return;
    };
    let (http, _) = served(&service.url).await;
    let base = repo().join("tests/fixtures/extraction");
    let annotations: Vec<Value> =
        serde_json::from_str(&std::fs::read_to_string(base.join("annotations.json")).unwrap())
            .unwrap();
    let baseline: Value =
        serde_json::from_str(&std::fs::read_to_string(base.join("baseline.json")).unwrap())
            .unwrap();
    let mut docs = Vec::new();
    for doc in &annotations {
        let text = doc["text"].as_str().unwrap();
        let chars: Vec<char> = text.chars().collect();
        // gold: each quote's first occurrence after the previous one of the same type and quote, in characters
        let mut cursor: BTreeMap<(String, String), usize> = BTreeMap::new();
        let mut gold = Vec::new();
        for item in doc["gold"].as_array().unwrap() {
            let kind = item["type"].as_str().unwrap();
            let quote = item["quote"].as_str().unwrap();
            let q: Vec<char> = quote.chars().collect();
            let from = cursor
                .get(&(kind.to_owned(), quote.to_owned()))
                .copied()
                .unwrap_or(0);
            let start = (from..chars.len())
                .find(|i| chars[*i..].starts_with(&q))
                .unwrap_or_else(|| panic!("quote not found: {quote}"));
            cursor.insert((kind.to_owned(), quote.to_owned()), start + 1);
            let kind = *TYPES.iter().find(|t| **t == kind).unwrap();
            gold.push((kind, (start, start + quote.trim_end().chars().count())));
        }
        let (status, body) = http
            .tool(
                scientific::EXTRACT_DISCOURSE,
                json!({"text": text, "document_id": "eval"}),
            )
            .await;
        assert_eq!(status, 200, "{body}");
        let found: DiscourseExtraction = serde_json::from_value(body["result"].clone()).unwrap();
        let groups = [
            ("claim", &found.claims),
            ("method", &found.methods),
            ("dataset", &found.datasets),
            ("metric", &found.metrics),
            ("result", &found.results),
            ("limitation", &found.limitations),
            ("assumption", &found.assumptions),
        ];
        let mut predicted = Vec::new();
        for (kind, entities) in groups {
            let kind = *TYPES.iter().find(|t| **t == kind).unwrap();
            for e in entities {
                let c = &e.coordinate;
                predicted.push((kind, (c.char_start as usize, c.char_end as usize)));
                let slice: String = chars[c.char_start as usize..c.char_end as usize]
                    .iter()
                    .collect();
                assert_eq!(slice.trim_end(), c.verbatim_snippet.trim_end());
            }
        }
        docs.push((predicted, gold));
    }
    let (per_type, macro_f1) = macro_f1(&docs);
    assert_eq!(
        macro_f1,
        baseline["macro_f1"].as_f64().unwrap(),
        "{per_type:?}"
    );
    for (kind, floor) in baseline["per_type"].as_object().unwrap() {
        assert_eq!(per_type[kind], floor.as_f64().unwrap(), "{kind}");
    }
    eprintln!(
        "extraction through the server: macro F1 {macro_f1} ({} documents)",
        docs.len()
    );
}

#[tokio::test]
async fn every_scientific_tool_answers_through_the_server() {
    let Some(service) = python_service().await else {
        eprintln!(
            "LARIS_TEST_MODEL_PYTHON is not set: the Python contract test proves nothing here"
        );
        return;
    };
    let (http, _) = served(&service.url).await;
    // the list is the one the protocol fixtures were recorded from
    let (status, body) = http.send("GET", "/v1/laris/tools", None).await;
    assert_eq!(status, 200);
    assert_eq!(
        serde_json::from_str::<Value>(&body).unwrap(),
        recorded("tools.list.json")
    );
    // each recorded request gives the recorded result (the extraction timestamp is the only moving part)
    for tool in scientific::TOOLS {
        let request: ToolRequest =
            serde_json::from_value(recorded(&format!("{tool}.request.json"))).unwrap();
        let (status, mut body) = http.tool(tool, Value::Object(request.arguments)).await;
        assert_eq!(status, 200, "{tool}: {body}");
        let mut expected = recorded(&format!("{tool}.response.json"));
        for v in [&mut body, &mut expected] {
            if let Some(r) = v["result"].as_object_mut() {
                r.remove("timestamp_iso");
            }
        }
        assert_eq!(body, expected, "{tool}");
    }
    // the citation fixture: the gold edges, exactly
    let data: Value = serde_json::from_str(
        &std::fs::read_to_string(repo().join("tests/fixtures/scholarly/citations.json")).unwrap(),
    )
    .unwrap();
    let mut documents: Vec<Value> = data["documents"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(id, text)| json!({"id": id, "text": text}))
        .collect();
    documents.sort_by_key(|d| d["id"].as_str().unwrap().to_owned());
    let (_, body) = http
        .tool(
            scientific::ANALYSE_CITATIONS,
            json!({"documents": documents}),
        )
        .await;
    let mut edges: Vec<(String, String)> = body["result"]["edges"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| {
            (
                e["citing"].as_str().unwrap().into(),
                e["cited"].as_str().unwrap().into(),
            )
        })
        .collect();
    let mut gold: Vec<(String, String)> = data["gold_edges"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| (e[0].as_str().unwrap().into(), e[1].as_str().unwrap().into()))
        .collect();
    edges.sort();
    gold.sort();
    assert_eq!(edges, gold);
    // refusals are tool results; an unknown tool is a 404
    let (status, body) = http
        .tool(scientific::EXTRACT_DISCOURSE, json!({"text": ""}))
        .await;
    assert_eq!(status, 200);
    assert_eq!(body["error"]["type"], scientific::ERR_INVALID_ARGUMENTS);
    assert_eq!(http.tool("nope", json!({})).await.0, 404);
}
