//! Traces and audit (SR-S7, T150): one content-free row per request, on success, on error and when the client
//! leaves; the operator's query; retention. The HTTP-layer tests use memory traces; the ones marked PostgreSQL need
//! `LARIS_TEST_PG_DSN` (they print a notice and pass without it, as in `tests/storage.rs`) and read the real
//! `traces` table, which they search for text that must never be there.

use futures_util::future::BoxFuture;
use futures_util::{StreamExt, stream};
use laris_protocol::p1::{
    ChatRequest, ChatResponseChunk, EmbedRequest, EmbedResponse, ToolRequest, ToolResponse,
};
use laris_server::access::{Access, AccessConfig, Master, NewKey};
use laris_server::storage::{Storage, StorageConfig};
use laris_server::trace::{MemoryTraces, PgTraces, TraceRecord, TraceSink, TraceStore};
use laris_server::{ApiError, AppState, Backend, ChunkStream, MemorySink, ServerConfig, serve};
use serde_json::{Value, json};
use sqlx::postgres::PgConnectOptions;
use sqlx::{ConnectOptions, Row};
use std::collections::HashMap;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::oneshot;

const MASTER: &str = "0123456789abcdef0123456789abcdef";
static COUNTER: AtomicU32 = AtomicU32::new(0);

/// Text of the request, the answer and the tool arguments: none of it may reach a trace.
const ASKED: &str = "ZEBRA-QUESTION-TEXT";
const ANSWERED: &str = "QUOKKA-ANSWER-TEXT";
const ARGUMENT: &str = "NARWHAL-ARGUMENT-TEXT";
const SECRET_NAME: &str = "hostile name with ZEBRA text";

#[derive(Clone, Copy, PartialEq)]
enum Model {
    /// An answer with a model name, a call to a client tool, brain titles and usage.
    Full,
    /// A first chunk, then silence until the client leaves.
    Hang,
    /// A first chunk, then a failure in the stream.
    Broken,
    /// A 502 before any chunk.
    Down,
}

struct Scripted(Model);

fn chunk(value: Value) -> ChatResponseChunk {
    serde_json::from_value(value).unwrap()
}

fn text_chunk(text: &str) -> ChatResponseChunk {
    chunk(json!({
        "id": "c1", "object": "chat.completion.chunk", "model": "tiny-model",
        "choices": [{"index": 0, "delta": {"content": text}}]
    }))
}

impl Backend for Scripted {
    fn chat(&self, _r: ChatRequest) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        let model = self.0;
        Box::pin(async move {
            Ok(match model {
                Model::Full => {
                    let call = |name: &str| {
                        chunk(json!({
                            "id": "c1", "object": "chat.completion.chunk", "model": "tiny-model",
                            "choices": [{"index": 0, "delta": {"tool_calls": [{
                                "index": 0, "id": "t1", "type": "function",
                                "function": {"name": name, "arguments": format!("{{\"q\":\"{ARGUMENT}\"}}")}
                            }]}}]
                        }))
                    };
                    let meta = chunk(json!({
                        "id": "c1", "object": "chat.completion.chunk", "model": "",
                        "laris": {"brain": ["Citing sources", "Reading a table"]},
                        "choices": []
                    }));
                    let usage = chunk(json!({
                        "id": "c1", "object": "chat.completion.chunk", "model": "tiny-model",
                        "choices": [],
                        "usage": {"prompt_tokens": 21, "completion_tokens": 8, "total_tokens": 29}
                    }));
                    stream::iter(vec![
                        Ok(meta),
                        Ok(text_chunk(ANSWERED)),
                        Ok(call("read_file")),
                        Ok(call(SECRET_NAME)),
                        Ok(usage),
                    ])
                    .boxed()
                }
                Model::Hang => stream::iter(vec![Ok(text_chunk("0123456789abcdefghij"))])
                    .chain(stream::pending())
                    .boxed(),
                Model::Broken => stream::iter(vec![
                    Ok(text_chunk("partial")),
                    Err(laris_server::StreamFailure {
                        message: "the model broke".into(),
                        kind: "ModelError".into(),
                    }),
                ])
                .boxed(),
                Model::Down => {
                    return Err(ApiError::BadGateway("the model service is down".into()));
                }
            })
        })
    }

    fn embed(&self, _r: EmbedRequest) -> BoxFuture<'static, Result<EmbedResponse, ApiError>> {
        let model = self.0;
        Box::pin(async move {
            if model == Model::Down {
                return Err(ApiError::BadGateway("the model service is down".into()));
            }
            Ok(serde_json::from_value(json!({
                "object": "list", "model": "m",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.5]}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 0, "total_tokens": 3}
            }))
            .unwrap())
        })
    }

    fn tool(
        &self,
        name: String,
        _request: ToolRequest,
    ) -> BoxFuture<'static, Result<ToolResponse, ApiError>> {
        Box::pin(async move {
            if name == "extract_discourse" {
                Ok(serde_json::from_value(json!({"result": {"spans": []}})).unwrap())
            } else {
                Err(ApiError::NotFound)
            }
        })
    }
}

// ---------------------------------------------------------------- the server under test

struct Server {
    addr: std::net::SocketAddr,
    stop: Option<oneshot::Sender<()>>,
    task: tokio::task::JoinHandle<()>,
}

impl Server {
    async fn start(access: Option<Arc<Access>>, model: Model, traces: Arc<dyn TraceStore>) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let mut config = ServerConfig::with_bind(addr);
        config.shutdown_grace = Duration::from_millis(200);
        let backend = Arc::new(Scripted(model));
        let state = match access {
            Some(a) => AppState::new(config, backend, a),
            None => AppState::open(config, backend),
        }
        .with_traces(traces);
        let (tx, rx) = oneshot::channel::<()>();
        let task = tokio::spawn(async move {
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
        Self {
            addr,
            stop: Some(tx),
            task,
        }
    }

    async fn call(
        &self,
        method: &str,
        path: &str,
        key: Option<&str>,
        body: Option<&str>,
    ) -> (u16, String) {
        let mut s = TcpStream::connect(self.addr).await.unwrap();
        let auth = key
            .map(|k| format!("Authorization: Bearer {k}\r\n"))
            .unwrap_or_default();
        let (ctype, len, payload) = match body {
            Some(b) => ("Content-Type: application/json\r\n", b.len(), b),
            None => ("", 0, ""),
        };
        let req = format!(
            "{method} {path} HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Laris-Protocol: 1\r\n{auth}{ctype}Content-Length: {len}\r\n\r\n{payload}"
        );
        s.write_all(req.as_bytes()).await.unwrap();
        let mut raw = Vec::new();
        let _ = tokio::time::timeout(Duration::from_secs(5), s.read_to_end(&mut raw)).await;
        let text = String::from_utf8_lossy(&raw).into_owned();
        let status = text
            .split_whitespace()
            .nth(1)
            .and_then(|c| c.parse().ok())
            .unwrap_or(0);
        let body = text.split("\r\n\r\n").nth(1).unwrap_or("").to_string();
        (status, body)
    }

    async fn chat(&self, key: Option<&str>) -> (u16, String) {
        let body = json!({
            "messages": [{"role": "user", "content": ASKED}],
            "laris": {"session_id": "session-one"}
        })
        .to_string();
        self.call("POST", "/v1/laris/chat", key, Some(&body)).await
    }

    async fn shutdown(mut self) {
        if let Some(tx) = self.stop.take() {
            let _ = tx.send(());
        }
        let _ = tokio::time::timeout(Duration::from_secs(3), self.task).await;
    }
}

/// Waits until `traces` holds `n` rows (the stream ends after the response, so the row comes a moment later).
async fn rows(traces: &MemoryTraces, n: usize) -> Vec<TraceRecord> {
    for _ in 0..200 {
        let got = traces.records();
        if got.len() >= n {
            return got;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    panic!("expected {n} traces, got {:?}", traces.records());
}

// ---------------------------------------------------------------- HTTP layer, memory traces

#[tokio::test]
async fn an_answer_leaves_one_trace_with_names_and_numbers() {
    let traces = Arc::new(MemoryTraces::default());
    let server = Server::start(None, Model::Full, traces.clone()).await;
    let (status, body) = server.chat(None).await;
    assert_eq!(status, 200);
    assert!(body.contains(ANSWERED));
    let got = rows(&traces, 1).await;
    assert_eq!(got.len(), 1);
    let t = &got[0];
    assert_eq!((t.route.as_str(), t.status), ("chat", 200));
    assert_eq!(t.outcome, "ok");
    assert_eq!(t.session_id, "session-one");
    assert_eq!(t.model, "tiny-model");
    assert_eq!(
        (t.prompt_tokens, t.completion_tokens),
        (21, 8),
        "what the model reported"
    );
    assert_eq!(t.brain, ["Citing sources", "Reading a table"]);
    assert_eq!(t.tools, ["read_file"], "a name with text in it is dropped");
    assert_eq!(t.answer_chars, ANSWERED.chars().count() as u64);
    assert!(t.request_id.contains('-') && t.at > 1.0e9);
    // nothing of the request, the answer or the arguments is in the record
    let dump = format!("{t:?}");
    for text in [ASKED, ANSWERED, ARGUMENT, "ZEBRA", "hostile"] {
        assert!(!dump.contains(text), "{text} is in {dump}");
    }
    server.shutdown().await;
}

#[tokio::test]
async fn a_failed_request_and_a_failed_stream_leave_traces_with_their_outcome() {
    let traces = Arc::new(MemoryTraces::default());
    let down = Server::start(None, Model::Down, traces.clone()).await;
    assert_eq!(down.chat(None).await.0, 502);
    let (status, _) = down
        .call("POST", "/v1/laris/chat", None, Some("{not json"))
        .await;
    assert_eq!(status, 400);
    down.shutdown().await;
    let broken = Server::start(None, Model::Broken, traces.clone()).await;
    assert_eq!(broken.chat(None).await.0, 200);
    broken.shutdown().await;
    let got = rows(&traces, 3).await;
    let by = |status: u16| got.iter().find(|t| t.status == status).unwrap();
    assert_eq!(by(502).outcome, "error");
    assert_eq!(by(400).outcome, "error");
    assert_eq!(by(200).outcome, "midstream_error");
    assert!(got.iter().all(|t| t.route == "chat"));
}

#[tokio::test]
async fn a_client_that_leaves_leaves_a_trace() {
    let traces = Arc::new(MemoryTraces::default());
    let server = Server::start(None, Model::Hang, traces.clone()).await;
    let mut s = TcpStream::connect(server.addr).await.unwrap();
    let body = json!({"messages": [{"role": "user", "content": ASKED}]}).to_string();
    let req = format!(
        "POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nX-Laris-Protocol: 1\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}",
        body.len()
    );
    s.write_all(req.as_bytes()).await.unwrap();
    let mut seen = vec![0u8; 512];
    let n = tokio::time::timeout(Duration::from_secs(3), s.read(&mut seen))
        .await
        .unwrap()
        .unwrap();
    assert!(n > 0, "the first chunk arrived");
    drop(s);
    let got = rows(&traces, 1).await;
    assert_eq!(got[0].outcome, "client_gone");
    assert_eq!(got[0].route, "chat");
    assert_eq!(
        got[0].answer_chars, 20,
        "what was produced before the client left"
    );
    server.shutdown().await;
}

#[tokio::test]
async fn tools_are_named_only_when_the_service_served_them() {
    let traces = Arc::new(MemoryTraces::default());
    let server = Server::start(None, Model::Full, traces.clone()).await;
    let args = json!({"arguments": {"text": ARGUMENT}}).to_string();
    assert_eq!(
        server
            .call(
                "POST",
                "/v1/laris/tools/extract_discourse",
                None,
                Some(&args)
            )
            .await
            .0,
        200
    );
    assert_eq!(
        server
            .call("POST", "/v1/laris/tools/no_such_tool", None, Some(&args))
            .await
            .0,
        404
    );
    assert_eq!(
        server
            .call("POST", "/v1/laris/tools/Bad%20Name", None, Some(&args))
            .await
            .0,
        404
    );
    let got = rows(&traces, 3).await;
    assert_eq!(got[0].tools, ["extract_discourse"]);
    assert!(got[1].tools.is_empty() && got[2].tools.is_empty());
    assert!(got.iter().all(|t| t.route == "tools"));
    assert!(!format!("{got:?}").contains(ARGUMENT));
    server.shutdown().await;
}

#[tokio::test]
async fn health_checks_and_unknown_paths_leave_no_trace() {
    let traces = Arc::new(MemoryTraces::default());
    let server = Server::start(None, Model::Full, traces.clone()).await;
    assert_eq!(server.call("GET", "/health", None, None).await.0, 200);
    assert_eq!(server.call("GET", "/nowhere", None, None).await.0, 404);
    assert_eq!(server.chat(None).await.0, 200);
    let got = rows(&traces, 1).await;
    tokio::time::sleep(Duration::from_millis(100)).await;
    assert_eq!(traces.records().len(), 1, "{got:?}");
    server.shutdown().await;
}

#[tokio::test]
async fn the_trace_query_needs_a_name_and_refuses_what_it_does_not_know() {
    let traces = Arc::new(MemoryTraces::default());
    let server = Server::start(None, Model::Full, traces.clone()).await;
    assert_eq!(server.chat(None).await.0, 200);
    rows(&traces, 1).await;
    for bad in [
        "?limit=x",
        "?made_up=1",
        "?route=chat%20x",
        "?since=-5",
        "?since=nan",
    ] {
        let (status, _) = server
            .call("GET", &format!("/v1/admin/traces{bad}"), None, None)
            .await;
        assert_eq!(status, 400, "{bad}");
    }
    let (status, body) = server
        .call("GET", "/v1/admin/traces?route=chat&limit=5", None, None)
        .await;
    assert_eq!(status, 200);
    let v: Value = serde_json::from_str(&body).unwrap();
    assert_eq!(v["traces"].as_array().unwrap().len(), 1);
    assert_eq!(v["traces"][0]["tools"], json!(["read_file"]));
    let (_, none) = server
        .call("GET", "/v1/admin/traces?route=embed", None, None)
        .await;
    assert_eq!(
        serde_json::from_str::<Value>(&none).unwrap()["traces"],
        json!([])
    );
    server.shutdown().await;
}

// ---------------------------------------------------------------- PostgreSQL

struct Env {
    dsn: String,
    schema: String,
}

impl Env {
    fn new() -> Option<Self> {
        let Some(dsn) = std::env::var("LARIS_TEST_PG_DSN")
            .ok()
            .filter(|v| !v.trim().is_empty())
        else {
            eprintln!("LARIS_TEST_PG_DSN is not set: PostgreSQL test skipped");
            return None;
        };
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        Some(Self {
            dsn,
            schema: format!("t150_{}_{n}", std::process::id()),
        })
    }

    async fn storage(&self) -> Arc<Storage> {
        let mut c = StorageConfig::with_dsn(&self.dsn);
        c.schema = Some(self.schema.clone());
        c.pool_max = 8;
        Arc::new(Storage::connect(&c).await.unwrap())
    }

    async fn finish(self) {
        let mut c = PgConnectOptions::from_str(&self.dsn)
            .unwrap()
            .connect()
            .await
            .unwrap();
        sqlx::raw_sql(&format!(
            "DROP SCHEMA IF EXISTS \"{}\" CASCADE",
            self.schema
        ))
        .execute(&mut c)
        .await
        .unwrap();
    }
}

fn access_over(storage: &Arc<Storage>) -> Arc<Access> {
    let env: HashMap<String, String> =
        [("LARIS_SERVER__MASTER".to_string(), MASTER.to_string())].into();
    Arc::new(Access::new(
        storage.clone(),
        Master::new(MASTER).unwrap(),
        &AccessConfig::from_env(&env).unwrap(),
    ))
}

async fn key(access: &Access, role: &str) -> (String, String) {
    let new = NewKey {
        label: "t150".into(),
        role: role.into(),
        ..NewKey::default()
    };
    let (record, text) = access
        .keys()
        .create(&new, laris_server::access::now())
        .await
        .unwrap();
    (record.id, text)
}

/// Every row of `traces` as one text, for searching.
async fn table_text(storage: &Storage) -> String {
    sqlx::query("SELECT t::text AS row FROM traces t")
        .fetch_all(storage.pool())
        .await
        .unwrap()
        .iter()
        .map(|r| r.get::<String, _>("row"))
        .collect::<Vec<_>>()
        .join("\n")
}

async fn stored(traces: &PgTraces, query: laris_server::trace::TraceQuery) -> Vec<TraceRecord> {
    traces.flush().await;
    traces.query(query).await
}

#[tokio::test]
async fn postgres_a_request_is_traced_on_success_error_and_disconnect_with_no_text() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage);
    let (user_id, user) = key(&access, "user").await;
    let traces = Arc::new(PgTraces::spawn(storage.clone()));

    let ok = Server::start(Some(access.clone()), Model::Full, traces.clone()).await;
    assert_eq!(ok.chat(Some(&user)).await.0, 200);
    // an error after authentication, one without a key, and one the role may not make
    assert_eq!(
        ok.call("POST", "/v1/laris/chat", Some(&user), Some("{"))
            .await
            .0,
        400
    );
    assert_eq!(ok.chat(None).await.0, 401);
    let (readonly_id, readonly) = key(&access, "readonly").await;
    assert_eq!(ok.chat(Some(&readonly)).await.0, 403);
    let (embedded, _) = ok
        .call(
            "POST",
            "/v1/laris/embed",
            Some(&user),
            Some(&json!({"input": ASKED}).to_string()),
        )
        .await;
    assert_eq!(embedded, 200);
    ok.shutdown().await;

    let hang = Server::start(Some(access.clone()), Model::Hang, traces.clone()).await;
    let mut s = TcpStream::connect(hang.addr).await.unwrap();
    let body = json!({"messages": [{"role": "user", "content": ASKED}]}).to_string();
    s.write_all(
        format!(
            "POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nX-Laris-Protocol: 1\r\nAuthorization: Bearer {user}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}",
            body.len()
        )
        .as_bytes(),
    )
    .await
    .unwrap();
    let mut seen = vec![0u8; 512];
    assert!(s.read(&mut seen).await.unwrap() > 0);
    drop(s);
    for _ in 0..100 {
        traces.flush().await;
        if traces.query(Default::default()).await.len() >= 6 {
            break;
        }
        tokio::time::sleep(Duration::from_millis(30)).await;
    }
    hang.shutdown().await;

    let all = stored(&traces, Default::default()).await;
    assert_eq!(all.len(), 6, "{all:?}");
    let pick = |route: &str, status: u16, key: &str| {
        all.iter()
            .find(|t| {
                t.route == route
                    && t.status == status
                    && t.key_id == key
                    && t.outcome != "client_gone"
            })
            .unwrap_or_else(|| panic!("{route} {status} {key} not in {all:?}"))
    };
    let success = pick("chat", 200, &user_id);
    assert_eq!(success.outcome, "ok");
    assert_eq!(success.session_id, "session-one");
    assert_eq!((success.prompt_tokens, success.completion_tokens), (21, 8));
    assert_eq!(success.tools, ["read_file"]);
    assert_eq!(success.brain, ["Citing sources", "Reading a table"]);
    assert_eq!(success.model, "tiny-model");
    assert!(success.duration_ms < 5_000 && success.at > 1.0e9);
    assert_eq!(pick("chat", 400, &user_id).outcome, "error");
    assert_eq!(pick("chat", 401, "").outcome, "error");
    assert_eq!(pick("chat", 403, &readonly_id).outcome, "error");
    let embed = pick("embed", 200, &user_id);
    assert_eq!((embed.prompt_tokens, embed.completion_tokens), (3, 0));
    let gone = all.iter().find(|t| t.outcome == "client_gone").unwrap();
    assert_eq!(
        (gone.route.as_str(), gone.key_id.as_str()),
        ("chat", user_id.as_str())
    );

    // the whole table, as text, holds nothing of what was asked, answered or passed as arguments
    let text = table_text(&storage).await;
    for secret in [
        ASKED,
        ANSWERED,
        ARGUMENT,
        "ZEBRA",
        "QUOKKA",
        "NARWHAL",
        "hostile",
        user.as_str(),
    ] {
        assert!(!text.contains(secret), "{secret} is in the traces table");
    }
    assert!(text.contains(&user_id) && text.contains("read_file"));
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn postgres_the_operator_reads_traces_with_the_right_permission_only() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage);
    let (user_id, user) = key(&access, "user").await;
    let (_, auditor) = key(&access, "auditor").await;
    let (_, admin) = key(&access, "admin").await;
    let traces = Arc::new(PgTraces::spawn(storage.clone()));
    let server = Server::start(Some(access.clone()), Model::Full, traces.clone()).await;
    assert_eq!(server.chat(Some(&user)).await.0, 200);
    assert_eq!(server.chat(None).await.0, 401);
    traces.flush().await;

    let ask = |q: &'static str, who: Option<&'static str>| {
        let server = &server;
        let user = user.clone();
        let auditor = auditor.clone();
        let admin = admin.clone();
        async move {
            let key = who.map(|w| match w {
                "user" => user,
                "auditor" => auditor,
                _ => admin,
            });
            server
                .call("GET", &format!("/v1/admin/traces{q}"), key.as_deref(), None)
                .await
        }
    };
    assert_eq!(ask("", None).await.0, 401);
    assert_eq!(ask("", Some("user")).await.0, 403);
    for who in ["auditor", "admin"] {
        let (status, body) = ask("", Some(who)).await;
        assert_eq!(status, 200, "{who}");
        let v: Value = serde_json::from_str(&body).unwrap();
        assert!(v["traces"].as_array().unwrap().len() >= 2);
        assert!(!body.contains(ASKED) && !body.contains(ANSWERED));
    }
    // the filters narrow the rows: by key, by route and outcome, by time, and the limit bounds them
    let by_key = traces
        .query(laris_server::trace::TraceQuery {
            key_id: Some(user_id.clone()),
            route: Some("chat".into()),
            ..Default::default()
        })
        .await;
    assert!(by_key.iter().all(|t| t.key_id == user_id) && by_key.len() == 1);
    let (_, body) = ask("?outcome=error&route=chat", Some("auditor")).await;
    let v: Value = serde_json::from_str(&body).unwrap();
    let hits = v["traces"].as_array().unwrap();
    assert!(
        hits.iter()
            .all(|t| t["status"] == 401 || t["outcome"] == "error")
    );
    assert!(!hits.is_empty());
    let (_, body) = ask("?since=99999999999", Some("auditor")).await;
    assert_eq!(
        serde_json::from_str::<Value>(&body).unwrap()["traces"],
        json!([])
    );
    let (_, body) = ask("?limit=1", Some("auditor")).await;
    assert_eq!(
        serde_json::from_str::<Value>(&body).unwrap()["traces"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    // the reasoning route is its own permission and does not show request traces
    assert!(
        !traces
            .query(Default::default())
            .await
            .iter()
            .any(|t| t.route.is_empty())
    );
    server.shutdown().await;
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn postgres_old_request_traces_are_purged_by_the_retention_task() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let traces = PgTraces::spawn(storage.clone());
    let now = laris_server::access::now();
    let old = now - 90.0 * 86_400.0;
    storage
        .maintenance()
        .ensure_partitions(old, 0)
        .await
        .unwrap();
    let record = |at: f64, id: &str| TraceRecord {
        request_id: id.into(),
        key_id: "k".into(),
        route: "chat".into(),
        status: 200,
        outcome: "ok".into(),
        duration_ms: 1,
        session_id: String::new(),
        model: String::new(),
        prompt_tokens: 1,
        completion_tokens: 1,
        tools: vec![],
        brain: vec![],
        answer_chars: 0,
        stages: vec![],
        at,
    };
    traces.record(record(old, "old"));
    traces.record(record(now, "new"));
    traces.flush().await;
    assert_eq!(traces.failures(), 0);
    assert_eq!(traces.query(Default::default()).await.len(), 2);
    storage.maintenance().purge(now).await.unwrap();
    let left = traces.query(Default::default()).await;
    assert_eq!(left.len(), 1);
    assert_eq!(left[0].request_id, "new");
    storage.close().await;
    env.finish().await;
}
