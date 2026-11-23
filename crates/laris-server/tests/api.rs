//! SR-S1 over real sockets: status codes, body rules, mid-stream errors, slow clients, trusted proxies and a
//! content-free log. Requests are written as raw bytes so that 411, 413 and slow senders can be exercised.

use futures_util::future::BoxFuture;
use futures_util::{StreamExt, stream};
use laris_protocol::p1::{ChatRequest, ChatResponseChunk, EmbedRequest, EmbedResponse};
use laris_protocol::sse::{P1Event, SseDecoder};
use laris_server::proxy::Cidr;
use laris_server::{
    AccessRecord, ApiError, AppState, Backend, ChunkStream, MemorySink, ServerConfig,
    StreamFailure, serve,
};
use serde_json::json;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::oneshot;

#[derive(Clone)]
enum Script {
    /// n chunks then the end.
    Chunks(usize),
    /// 2 chunks then a failure.
    FailAfterTwo,
    /// 1 chunk then silence.
    Stall,
    /// 1 chunk, then a long wait (the client is expected to leave).
    Slow,
    /// `n` chunks of 64 KiB, made only as fast as the connection takes them.
    Big(usize),
    /// An HTTP-level refusal.
    Refuse(ApiError),
}

struct Scripted(Script);

fn chunk(text: &str) -> ChatResponseChunk {
    serde_json::from_value(json!({
        "id": "c1", "object": "chat.completion.chunk", "model": "m",
        "choices": [{"index": 0, "delta": {"content": text}}]
    }))
    .unwrap()
}

impl Backend for Scripted {
    fn chat(&self, _r: ChatRequest) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        let script = self.0.clone();
        Box::pin(async move {
            let s: ChunkStream = match script {
                Script::Chunks(n) => {
                    stream::iter((0..n).map(|i| Ok(chunk(&format!("t{i}"))))).boxed()
                }
                Script::FailAfterTwo => stream::iter(vec![
                    Ok(chunk("a")),
                    Ok(chunk("b")),
                    Err(StreamFailure {
                        message: "model died".into(),
                        kind: "ProviderError".into(),
                    }),
                ])
                .boxed(),
                Script::Stall => stream::iter(vec![Ok(chunk("a"))])
                    .chain(stream::pending())
                    .boxed(),
                Script::Slow => stream::iter(vec![Ok(chunk("a"))])
                    .chain(stream::once(async {
                        tokio::time::sleep(Duration::from_secs(30)).await;
                        Ok(chunk("late"))
                    }))
                    .boxed(),
                Script::Big(n) => {
                    let big = chunk(&"x".repeat(64 * 1024));
                    stream::iter((0..n).map(move |_| Ok(big.clone()))).boxed()
                }
                Script::Refuse(e) => return Err(e),
            };
            Ok(s)
        })
    }

    fn embed(&self, r: EmbedRequest) -> BoxFuture<'static, Result<EmbedResponse, ApiError>> {
        Box::pin(async move {
            let n = match r.input {
                laris_protocol::p1::OneOrMany::One(_) => 1,
                laris_protocol::p1::OneOrMany::Many(v) => v.len(),
            };
            let data: Vec<_> = (0..n)
                .map(|i| json!({"object": "embedding", "index": i, "embedding": [0.5, 0.25]}))
                .collect();
            Ok(
                serde_json::from_value(json!({"object": "list", "model": "m", "data": data}))
                    .unwrap(),
            )
        })
    }
}

struct Harness {
    addr: SocketAddr,
    sink: Arc<MemorySink>,
    stop: Option<oneshot::Sender<()>>,
    task: tokio::task::JoinHandle<()>,
}

impl Harness {
    async fn start(script: Script, tweak: impl FnOnce(&mut ServerConfig)) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let mut config = ServerConfig::with_bind(addr);
        config.header_timeout = Duration::from_millis(400);
        config.body_timeout = Duration::from_millis(400);
        config.stream_idle = Duration::from_millis(400);
        config.shutdown_grace = Duration::from_millis(200);
        tweak(&mut config);
        let sink = Arc::new(MemorySink::default());
        let state = Arc::new(AppState::open(config, Arc::new(Scripted(script))));
        let (tx, rx) = oneshot::channel::<()>();
        let sink2 = sink.clone();
        let task = tokio::spawn(async move {
            let _ = serve(listener, state, sink2, async {
                let _ = rx.await;
            })
            .await;
        });
        Self {
            addr,
            sink,
            stop: Some(tx),
            task,
        }
    }

    async fn send(&self, bytes: &[u8]) -> Reply {
        let mut s = TcpStream::connect(self.addr).await.unwrap();
        s.write_all(bytes).await.unwrap();
        Reply::read(&mut s).await
    }

    /// Waits for a record that matches, since a stream's record is written when its body ends.
    async fn record(&self, want: impl Fn(&AccessRecord) -> bool) -> AccessRecord {
        for _ in 0..100 {
            if let Some(r) = self.sink.records().into_iter().find(|r| want(r)) {
                return r;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        panic!("no matching access record in {:?}", self.sink.records());
    }

    async fn shutdown(mut self) {
        if let Some(tx) = self.stop.take() {
            let _ = tx.send(());
        }
        tokio::time::timeout(Duration::from_secs(3), self.task)
            .await
            .expect("server stops")
            .unwrap();
    }
}

struct Reply {
    raw: Vec<u8>,
}

impl Reply {
    async fn read(s: &mut TcpStream) -> Self {
        let mut raw = Vec::new();
        let _ = tokio::time::timeout(Duration::from_secs(5), s.read_to_end(&mut raw)).await;
        Self { raw }
    }
    fn text(&self) -> String {
        String::from_utf8_lossy(&self.raw).into_owned()
    }
    fn status(&self) -> u16 {
        self.text()
            .split_whitespace()
            .nth(1)
            .and_then(|c| c.parse().ok())
            .unwrap_or(0)
    }
    fn header(&self, name: &str) -> Option<String> {
        let t = self.text();
        let head = t.split("\r\n\r\n").next()?;
        head.lines().find_map(|l| {
            let (k, v) = l.split_once(':')?;
            k.eq_ignore_ascii_case(name).then(|| v.trim().to_owned())
        })
    }
    fn body(&self) -> Vec<u8> {
        let Some(at) = self.raw.windows(4).position(|w| w == b"\r\n\r\n") else {
            return Vec::new();
        };
        let body = &self.raw[at + 4..];
        let chunked = self
            .header("transfer-encoding")
            .is_some_and(|v| v.eq_ignore_ascii_case("chunked"));
        if chunked {
            dechunk(body)
        } else {
            body.to_vec()
        }
    }
    fn json(&self) -> serde_json::Value {
        serde_json::from_slice(&self.body()).expect("JSON body")
    }
    fn events(&self) -> Vec<P1Event> {
        let mut d = SseDecoder::new();
        d.feed(&self.body())
            .unwrap()
            .iter()
            .map(|e| P1Event::from_data(e).unwrap())
            .collect()
    }
}

fn dechunk(mut b: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    while let Some(end) = b.windows(2).position(|w| w == b"\r\n") {
        let size =
            usize::from_str_radix(std::str::from_utf8(&b[..end]).unwrap().trim(), 16).unwrap_or(0);
        b = &b[end + 2..];
        if size == 0 || b.len() < size {
            break;
        }
        out.extend_from_slice(&b[..size]);
        b = b.get(size + 2..).unwrap_or(&[]);
    }
    out
}

fn post(path: &str, body: &str, extra: &str) -> Vec<u8> {
    format!(
        "POST {path} HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Laris-Protocol: 2\r\nContent-Type: application/json\r\nContent-Length: {}\r\n{extra}\r\n{body}",
        body.len()
    )
    .into_bytes()
}

const CHAT: &str = r#"{"messages":[{"role":"user","content":"hello"}]}"#;

#[tokio::test]
async fn health_and_unknown_routes() {
    let h = Harness::start(Script::Chunks(1), |_| {}).await;
    let r = h
        .send(b"GET /health HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
        .await;
    assert_eq!(r.status(), 200);
    assert_eq!(r.json(), json!({"status": "ok"}));
    assert!(r.header("x-request-id").is_some());
    let r = h
        .send(b"GET /nope HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
        .await;
    assert_eq!(r.status(), 404);
    assert_eq!(r.json(), json!({"error": "not found"}));
    let r = h
        .send(b"GET /v1/laris/chat HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
        .await;
    assert_eq!(r.status(), 405);
    assert_eq!(r.json(), json!({"error": "method not allowed"}));
    h.shutdown().await;
}

#[tokio::test]
async fn protocol_version_is_checked_first() {
    let h = Harness::start(Script::Chunks(1), |_| {}).await;
    let bad = format!(
        "POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{CHAT}",
        CHAT.len()
    );
    let r = h.send(bad.as_bytes()).await;
    assert_eq!(r.status(), 426);
    assert!(
        r.json()["error"]
            .as_str()
            .unwrap()
            .contains("unsupported protocol version")
    );
    let r = h.send(&post("/v1/laris/chat", CHAT, "")).await;
    assert_eq!(r.status(), 200);
    h.shutdown().await;
}

#[tokio::test]
async fn bad_bodies_are_400() {
    let h = Harness::start(Script::Chunks(1), |_| {}).await;
    let cases = [
        ("not json", "{"),
        ("missing messages", r#"{"stream":true}"#),
        ("empty messages", r#"{"messages":[]}"#),
        (
            "system role",
            r#"{"messages":[{"role":"system","content":"x"}]}"#,
        ),
        (
            "unknown role",
            r#"{"messages":[{"role":"root","content":"x"}]}"#,
        ),
        (
            "stream off",
            r#"{"messages":[{"role":"user","content":"x"}],"stream":false}"#,
        ),
        (
            "session id",
            r#"{"messages":[{"role":"user","content":"x"}],"laris":{"session_id":"a b"}}"#,
        ),
        (
            "session id short",
            r#"{"messages":[{"role":"user","content":"x"}],"laris":{"session_id":"ab"}}"#,
        ),
        ("wrong type", r#"{"messages":"hello"}"#),
    ];
    for (name, body) in cases {
        let r = h.send(&post("/v1/laris/chat", body, "")).await;
        assert_eq!(r.status(), 400, "{name}");
        assert!(
            r.json()["error"]
                .as_str()
                .unwrap()
                .starts_with("invalid request"),
            "{name}"
        );
    }
    // the message for a missing field
    let r = h
        .send(&post("/v1/laris/chat", r#"{"stream":true}"#, ""))
        .await;
    assert!(r.json()["error"].as_str().unwrap().contains("messages"));
    // wrong content type
    let wrong = format!(
        "POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Laris-Protocol: 2\r\nContent-Type: text/plain\r\nContent-Length: {}\r\n\r\n{CHAT}",
        CHAT.len()
    );
    assert_eq!(h.send(wrong.as_bytes()).await.status(), 400);
    // Content-Type parameters and case are fine
    let ok = post("/v1/laris/chat", CHAT, "");
    let ok = String::from_utf8(ok)
        .unwrap()
        .replace("application/json", "Application/JSON; charset=utf-8");
    assert_eq!(h.send(ok.as_bytes()).await.status(), 200);
    h.shutdown().await;
}

#[tokio::test]
async fn embed_rules() {
    let h = Harness::start(Script::Chunks(1), |c| c.embed_max_inputs = 2).await;
    let r = h
        .send(&post("/v1/laris/embed", r#"{"input":["a","b"]}"#, ""))
        .await;
    assert_eq!(r.status(), 200);
    assert_eq!(r.json()["data"].as_array().unwrap().len(), 2);
    let r = h
        .send(&post("/v1/laris/embed", r#"{"input":"one"}"#, ""))
        .await;
    assert_eq!(r.status(), 200);
    for body in [
        r#"{"input":[]}"#,
        r#"{"input":["a","b","c"]}"#,
        r#"{}"#,
        r#"{"input":5}"#,
    ] {
        assert_eq!(
            h.send(&post("/v1/laris/embed", body, "")).await.status(),
            400,
            "{body}"
        );
    }
    h.shutdown().await;
}

#[tokio::test]
async fn length_required_is_411() {
    let h = Harness::start(Script::Chunks(1), |_| {}).await;
    let none = b"POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Laris-Protocol: 2\r\nContent-Type: application/json\r\n\r\n";
    let r = h.send(none).await;
    assert_eq!(r.status(), 411);
    assert_eq!(r.json(), json!({"error": "Content-Length is required"}));
    let chunked = format!(
        "POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Laris-Protocol: 2\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n{:x}\r\n{CHAT}\r\n0\r\n\r\n",
        CHAT.len()
    );
    assert_eq!(h.send(chunked.as_bytes()).await.status(), 411);
    h.shutdown().await;
}

#[tokio::test]
async fn oversize_is_413_before_the_body_is_read() {
    let h = Harness::start(Script::Chunks(1), |c| c.max_body_bytes = 64).await;
    // Only the headers are sent; the answer must not wait for the body.
    let head = "POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Laris-Protocol: 2\r\nContent-Type: application/json\r\nContent-Length: 65\r\n\r\n";
    let mut s = TcpStream::connect(h.addr).await.unwrap();
    s.write_all(head.as_bytes()).await.unwrap();
    let mut buf = vec![0u8; 1024];
    let n = tokio::time::timeout(Duration::from_millis(300), s.read(&mut buf))
        .await
        .expect("answered without the body")
        .unwrap();
    let text = String::from_utf8_lossy(&buf[..n]);
    assert!(text.starts_with("HTTP/1.1 413"), "{text}");
    assert!(text.contains("larger than 64 bytes"));
    // exactly at the limit passes
    let pad = " ".repeat(64 - CHAT.len());
    let at_limit = format!("{CHAT}{pad}");
    assert_eq!(at_limit.len(), 64);
    assert_eq!(
        h.send(&post("/v1/laris/chat", &at_limit, ""))
            .await
            .status(),
        200
    );
    // a declared length that lies (more bytes than declared) cannot grow the body
    let lying = "POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Laris-Protocol: 2\r\nContent-Type: application/json\r\nContent-Length: 5\r\n\r\n{\"a\":1}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx";
    assert_eq!(h.send(lying.as_bytes()).await.status(), 400);
    // not a number
    let nan = "POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Laris-Protocol: 2\r\nContent-Type: application/json\r\nContent-Length: abc\r\n\r\n";
    assert_eq!(h.send(nan.as_bytes()).await.status(), 400);
    h.shutdown().await;
}

#[tokio::test]
async fn answer_stream_ends_with_done() {
    let h = Harness::start(Script::Chunks(3), |_| {}).await;
    let r = h.send(&post("/v1/laris/chat", CHAT, "")).await;
    assert_eq!(r.status(), 200);
    assert_eq!(
        r.header("content-type").as_deref(),
        Some("text/event-stream")
    );
    assert_eq!(r.header("cache-control").as_deref(), Some("no-cache"));
    let events = r.events();
    assert_eq!(events.len(), 4);
    assert!(events[..3].iter().all(|e| matches!(e, P1Event::Chunk(_))));
    assert_eq!(events[3], P1Event::Done);
    let rec = h.record(|r| r.route == "chat").await;
    assert_eq!((rec.status, rec.outcome), (200, None));
    h.shutdown().await;
}

#[tokio::test]
async fn failure_inside_the_stream_is_an_error_event_then_done() {
    let h = Harness::start(Script::FailAfterTwo, |_| {}).await;
    let r = h.send(&post("/v1/laris/chat", CHAT, "")).await;
    assert_eq!(r.status(), 200, "the status is already sent");
    let events = r.events();
    assert_eq!(events.len(), 4, "{events:?}");
    assert!(matches!(events[0], P1Event::Chunk(_)));
    assert!(matches!(events[1], P1Event::Chunk(_)));
    let P1Event::Error(e) = &events[2] else {
        panic!("{events:?}")
    };
    assert_eq!(e.error.message, "model died");
    assert_eq!(e.error.kind.as_deref(), Some("ProviderError"));
    assert_eq!(events[3], P1Event::Done);
    let rec = h.record(|r| r.route == "chat").await;
    assert_eq!(rec.outcome, Some("midstream_error"));
    h.shutdown().await;
}

#[tokio::test]
async fn stalled_stream_ends_with_an_error_event() {
    let h = Harness::start(Script::Stall, |c| {
        c.stream_idle = Duration::from_millis(150)
    })
    .await;
    let r = h.send(&post("/v1/laris/chat", CHAT, "")).await;
    let events = r.events();
    assert_eq!(events.len(), 3, "{events:?}");
    let P1Event::Error(e) = &events[1] else {
        panic!("{events:?}")
    };
    assert_eq!(e.error.kind.as_deref(), Some("StreamIdle"));
    assert_eq!(events[2], P1Event::Done);
    assert_eq!(
        h.record(|r| r.route == "chat").await.outcome,
        Some("stream_idle")
    );
    h.shutdown().await;
}

#[tokio::test]
async fn a_silent_stream_keeps_the_connection_with_comments_until_the_idle_limit() {
    let h = Harness::start(Script::Stall, |c| {
        c.stream_idle = Duration::from_millis(400);
        c.stream_keepalive = Duration::from_millis(100);
    })
    .await;
    let r = h.send(&post("/v1/laris/chat", CHAT, "")).await;
    let raw = String::from_utf8_lossy(&r.body()).into_owned();
    assert!(raw.matches(": keep-alive").count() >= 2, "{raw}");
    // the comments are not events, and the idle limit still ends the answer
    let events = r.events();
    assert_eq!(events.len(), 3, "{events:?}");
    assert_eq!(
        h.record(|r| r.route == "chat").await.outcome,
        Some("stream_idle")
    );
    h.shutdown().await;
}

#[tokio::test]
async fn client_leaving_mid_stream_is_logged() {
    let h = Harness::start(Script::Slow, |c| c.stream_idle = Duration::from_secs(20)).await;
    let mut s = TcpStream::connect(h.addr).await.unwrap();
    s.write_all(&post("/v1/laris/chat", CHAT, ""))
        .await
        .unwrap();
    let mut buf = [0u8; 512];
    let n = s.read(&mut buf).await.unwrap();
    assert!(n > 0);
    drop(s);
    let rec = h.record(|r| r.route == "chat").await;
    assert_eq!(rec.outcome, Some("client_gone"));
    h.shutdown().await;
}

#[tokio::test]
async fn backend_refusal_before_the_stream_is_a_status() {
    for (error, code) in [
        (ApiError::BadGateway("model is down".into()), 502),
        (
            ApiError::TooManyRequests {
                retry_after_secs: Some(9),
            },
            429,
        ),
        (ApiError::Unauthorized("no key".into()), 401),
        (ApiError::Forbidden("no role".into()), 403),
    ] {
        let h = Harness::start(Script::Refuse(error), |_| {}).await;
        let r = h.send(&post("/v1/laris/chat", CHAT, "")).await;
        assert_eq!(r.status(), code);
        assert!(r.json()["error"].is_string());
        if code == 429 {
            assert_eq!(r.header("retry-after").as_deref(), Some("9"));
        }
        h.shutdown().await;
    }
}

#[tokio::test]
async fn slow_body_is_cut_with_408() {
    let h = Harness::start(Script::Chunks(1), |c| {
        c.body_timeout = Duration::from_millis(300)
    })
    .await;
    let head = format!(
        "POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Laris-Protocol: 2\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",
        CHAT.len()
    );
    let mut s = TcpStream::connect(h.addr).await.unwrap();
    s.write_all(head.as_bytes()).await.unwrap();
    s.write_all(&CHAT.as_bytes()[..10]).await.unwrap(); // then silence
    let started = std::time::Instant::now();
    let r = Reply::read(&mut s).await;
    assert_eq!(r.status(), 408);
    assert!(started.elapsed() < Duration::from_secs(2));
    assert_eq!(h.record(|r| r.status == 408).await.route, "chat");
    h.shutdown().await;
}

#[tokio::test]
async fn slow_headers_are_cut() {
    let h = Harness::start(Script::Chunks(1), |c| {
        c.header_timeout = Duration::from_millis(250)
    })
    .await;
    let mut s = TcpStream::connect(h.addr).await.unwrap();
    s.write_all(b"POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\n")
        .await
        .unwrap(); // never finished
    let started = std::time::Instant::now();
    let r = Reply::read(&mut s).await;
    assert!(
        started.elapsed() < Duration::from_secs(2),
        "connection stayed open"
    );
    assert!(r.raw.is_empty() || r.status() == 408, "{}", r.text());
    h.shutdown().await;
}

#[tokio::test]
async fn connection_limit_sheds_the_extra_connection() {
    let h = Harness::start(Script::Chunks(1), |c| {
        c.max_connections = 1;
        c.header_timeout = Duration::from_secs(5);
    })
    .await;
    let _held = TcpStream::connect(h.addr).await.unwrap(); // takes the only slot
    tokio::time::sleep(Duration::from_millis(100)).await;
    let r = h
        .send(b"GET /health HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
        .await;
    assert!(
        r.raw.is_empty(),
        "the extra connection is closed unanswered"
    );
    h.shutdown().await;
}

fn health_from(h: &Harness, xff: &str) -> Vec<u8> {
    let _ = h;
    format!("GET /health HTTP/1.1\r\nHost: t\r\nConnection: close\r\n{xff}\r\n").into_bytes()
}

#[tokio::test]
async fn untrusted_peer_cannot_set_its_address() {
    let h = Harness::start(Script::Chunks(1), |_| {}).await; // no trusted proxies
    h.send(&health_from(&h, "X-Forwarded-For: 203.0.113.9\r\n"))
        .await;
    let rec = h.record(|r| r.route == "health").await;
    assert_eq!(rec.client.to_string(), "127.0.0.1");
    h.shutdown().await;
}

#[tokio::test]
async fn trusted_proxy_forwards_the_client_address() {
    let h = Harness::start(Script::Chunks(1), |c| {
        c.trusted_proxies =
            laris_server::proxy::TrustedProxies::new(vec![Cidr::parse("127.0.0.0/8").unwrap()]);
    })
    .await;
    h.send(&health_from(
        &h,
        "X-Forwarded-For: 6.6.6.6, 203.0.113.9\r\n",
    ))
    .await;
    h.send(&health_from(&h, "")).await;
    h.send(&health_from(&h, "X-Forwarded-For: nonsense\r\n"))
        .await;
    let seen: Vec<String> = {
        let _ = h.record(|r| r.route == "health").await;
        tokio::time::sleep(Duration::from_millis(100)).await;
        h.sink
            .records()
            .iter()
            .map(|r| r.client.to_string())
            .collect()
    };
    assert_eq!(seen, ["203.0.113.9", "127.0.0.1", "127.0.0.1"]);
    h.shutdown().await;
}

#[tokio::test]
async fn log_holds_no_content() {
    let h = Harness::start(Script::FailAfterTwo, |_| {}).await;
    let secret_body = "SECRETBODYMARKER";
    let body = format!(r#"{{"messages":[{{"role":"user","content":"{secret_body}"}}]}}"#);
    let extra = "Authorization: Bearer SECRETKEYMARKER\r\nCookie: s=SECRETCOOKIEMARKER\r\nX-Forwarded-For: 198.51.100.77\r\n";
    h.send(&post("/v1/laris/chat?q=SECRETQUERYMARKER", &body, extra))
        .await;
    h.send(b"GET /SECRETPATHMARKER?x=SECRETQUERYMARKER HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n").await;
    h.send(&post("/v1/laris/chat", "{ SECRETBADJSONMARKER", extra))
        .await;
    h.record(|r| r.route == "chat" && r.outcome.is_some()).await;
    tokio::time::sleep(Duration::from_millis(100)).await;
    let records = h.sink.records();
    assert!(records.len() >= 3);
    let all: String = records
        .iter()
        .map(|r| r.to_json_line(0))
        .collect::<Vec<_>>()
        .join("\n");
    for marker in [
        "SECRETBODYMARKER",
        "SECRETKEYMARKER",
        "SECRETCOOKIEMARKER",
        "SECRETQUERYMARKER",
        "SECRETPATHMARKER",
        "SECRETBADJSONMARKER",
        "model died",
        "hello",
    ] {
        assert!(!all.contains(marker), "{marker} leaked into the log: {all}");
    }
    // the unmatched route is a fixed name, not the URL
    assert!(
        records
            .iter()
            .any(|r| r.route == "unmatched" && r.status == 404)
    );
    h.shutdown().await;
}

#[tokio::test]
async fn request_ids_are_unique_and_server_made() {
    let h = Harness::start(Script::Chunks(1), |_| {}).await;
    let mut ids = Vec::new();
    for _ in 0..5 {
        let r = h
            .send(b"GET /health HTTP/1.1\r\nHost: t\r\nX-Request-Id: client-chosen\r\nConnection: close\r\n\r\n")
            .await;
        ids.push(r.header("x-request-id").unwrap());
    }
    ids.sort();
    ids.dedup();
    assert_eq!(ids.len(), 5);
    assert!(ids.iter().all(|i| i != "client-chosen"));
    h.shutdown().await;
}

#[tokio::test]
async fn shutdown_waits_for_open_work_then_stops() {
    let h = Harness::start(Script::Chunks(2), |_| {}).await;
    let r = h.send(&post("/v1/laris/chat", CHAT, "")).await;
    assert_eq!(r.events().last(), Some(&P1Event::Done));
    h.shutdown().await;
}

#[tokio::test]
async fn client_that_stops_reading_is_cut_and_its_slot_freed() {
    let h = Harness::start(Script::Big(5000), |c| {
        c.write_stall = Duration::from_millis(300);
        c.max_connections = 1;
        c.stream_idle = Duration::from_secs(20);
        c.header_timeout = Duration::from_secs(5);
    })
    .await;
    let mut s = TcpStream::connect(h.addr).await.unwrap();
    s.write_all(&post("/v1/laris/chat", CHAT, ""))
        .await
        .unwrap();
    let mut buf = [0u8; 256];
    assert!(s.read(&mut buf).await.unwrap() > 0); // the answer started; now read nothing more
    let started = std::time::Instant::now();
    let rec = h.record(|r| r.route == "chat").await;
    assert_eq!(rec.outcome, Some("client_gone"));
    assert!(
        started.elapsed() < Duration::from_secs(3),
        "{:?}",
        started.elapsed()
    );
    // the only slot is free again while the silent client still holds its socket open
    let r = h
        .send(b"GET /health HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
        .await;
    assert_eq!(r.status(), 200);
    drop(s);
    h.shutdown().await;
}

#[tokio::test]
async fn slow_but_steady_reader_is_not_cut() {
    let h = Harness::start(Script::Big(160), |c| {
        c.write_stall = Duration::from_millis(500)
    })
    .await;
    let mut s = TcpStream::connect(h.addr).await.unwrap();
    s.write_all(&post("/v1/laris/chat", CHAT, ""))
        .await
        .unwrap();
    let mut total = 0usize;
    let mut tail = Vec::new();
    let mut buf = vec![0u8; 64 * 1024];
    loop {
        let n = s.read(&mut buf).await.unwrap();
        if n == 0 {
            break;
        }
        total += n;
        tail.extend_from_slice(&buf[..n]);
        if tail.len() > 64 {
            tail.drain(..tail.len() - 64);
        }
        tokio::time::sleep(Duration::from_millis(15)).await; // slower than the server, never stuck
    }
    assert!(total > 160 * 64 * 1024, "{total}");
    assert!(String::from_utf8_lossy(&tail).contains("[DONE]"));
    assert_eq!(h.record(|r| r.route == "chat").await.outcome, None);
    h.shutdown().await;
}
