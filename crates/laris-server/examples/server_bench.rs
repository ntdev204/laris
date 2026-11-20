//! Server benchmarks for the performance budgets (T154, SR-H15): `cargo run --release -p laris-server --example server_bench`.
//!
//! No model, no database and no weights: the HTTP stack and the gateway paths run in this process against a scripted
//! backend, so the figures are the cost of the server itself, never of a model. Every figure is "lower is better".
//! `cargo xtask bench` runs this program, writes `reports/performance/server.json` and compares it with the budgets.
//!
//! ```text
//! bench [--out FILE]
//! ```

use futures_util::future::BoxFuture;
use futures_util::{StreamExt, stream};
use laris_evidence::{Evidence, Gate};
use laris_policy::Redactor;
use laris_protocol::p1::{ChatRequest, ChatResponseChunk, EmbedRequest, EmbedResponse};
use laris_server::{ApiError, AppState, Backend, ChunkStream, MemorySink, ServerConfig, serve};
use serde_json::json;
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

const CHAT: &str = r#"{"messages":[{"role":"user","content":"hello"}]}"#;
const CHUNKS: usize = 32;

struct Scripted;

fn chunk(text: &str) -> ChatResponseChunk {
    serde_json::from_value(json!({
        "id": "c1", "object": "chat.completion.chunk", "model": "m",
        "choices": [{"index": 0, "delta": {"content": text}}]
    }))
    .expect("chunk")
}

impl Backend for Scripted {
    fn chat(&self, _r: ChatRequest) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        Box::pin(async move {
            let s: ChunkStream =
                stream::iter((0..CHUNKS).map(|i| Ok(chunk(&format!("token {i} of the answer ")))))
                    .boxed();
            Ok(s)
        })
    }

    fn embed(&self, _r: EmbedRequest) -> BoxFuture<'static, Result<EmbedResponse, ApiError>> {
        Box::pin(async move { Err(ApiError::NotFound) })
    }
}

async fn exchange(addr: std::net::SocketAddr, request: &[u8]) -> (u16, usize) {
    let mut s = TcpStream::connect(addr).await.expect("connect");
    s.write_all(request).await.expect("write");
    let mut raw = Vec::new();
    s.read_to_end(&mut raw).await.expect("read");
    let text = String::from_utf8_lossy(&raw);
    let status = text
        .split_whitespace()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);
    (status, raw.len())
}

fn chat_request() -> Vec<u8> {
    format!(
        "POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Laris-Protocol: 2\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{CHAT}",
        CHAT.len()
    )
    .into_bytes()
}

fn percentile(sorted: &[f64], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let rank = ((sorted.len() as f64 - 1.0) * p).round() as usize;
    sorted[rank.min(sorted.len() - 1)]
}

fn p95(mut values: Vec<f64>) -> f64 {
    values.sort_by(f64::total_cmp);
    percentile(&values, 0.95)
}

fn round3(x: f64) -> f64 {
    (x * 1000.0).round() / 1000.0
}

/// Peak resident set of this process in MB (Linux; 0 elsewhere).
fn peak_rss_mb() -> f64 {
    std::fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|t| {
            t.lines()
                .find_map(|l| l.strip_prefix("VmHWM:").map(str::to_owned))
        })
        .and_then(|l| {
            l.split_whitespace()
                .next()
                .and_then(|n| n.parse::<f64>().ok())
        })
        .map_or(0.0, |kb| kb / 1024.0)
}

async fn http_figures(figures: &mut BTreeMap<&'static str, f64>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let addr = listener.local_addr().expect("addr");
    let config = ServerConfig::with_bind(addr);
    let state = Arc::new(AppState::open(config, Arc::new(Scripted)));
    let sink = Arc::new(MemorySink::default());
    let (stop, rx) = tokio::sync::oneshot::channel::<()>();
    let task = tokio::spawn(async move {
        let _ = serve(listener, state, sink, async {
            let _ = rx.await;
        })
        .await;
    });

    let health = b"GET /health HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n";
    let chat = chat_request();
    // Warm up, then measure.
    for _ in 0..20 {
        exchange(addr, health).await;
        exchange(addr, &chat).await;
    }
    let mut times = Vec::new();
    for _ in 0..300 {
        let t = Instant::now();
        let (status, _) = exchange(addr, health).await;
        assert_eq!(status, 200, "health");
        times.push(t.elapsed().as_secs_f64() * 1000.0);
    }
    figures.insert("server.health_p95_ms", p95(times));

    let mut times = Vec::new();
    for _ in 0..200 {
        let t = Instant::now();
        let (status, _) = exchange(addr, &chat).await;
        assert_eq!(status, 200, "chat");
        times.push(t.elapsed().as_secs_f64() * 1000.0);
    }
    figures.insert("server.chat_p95_ms", p95(times));

    // 32 concurrent streams, four rounds: the cost of sharing the server.
    let mut times = Vec::new();
    for _ in 0..4 {
        let started = Instant::now();
        let mut jobs = Vec::new();
        for _ in 0..32 {
            let chat = chat.clone();
            jobs.push(tokio::spawn(async move {
                let t = Instant::now();
                let (status, _) = exchange(addr, &chat).await;
                assert_eq!(status, 200, "parallel chat");
                t.elapsed().as_secs_f64() * 1000.0
            }));
        }
        for job in jobs {
            times.push(job.await.expect("job"));
        }
        let _ = started;
    }
    figures.insert("server.chat_parallel_p95_ms", p95(times));
    let _ = stop.send(());
    let _ = tokio::time::timeout(Duration::from_secs(3), task).await;
}

fn gateway_figures(figures: &mut BTreeMap<&'static str, f64>) {
    // The redactor over 64 KiB of text that holds a few secrets.
    let redactor = Redactor::standard();
    let mut text = String::new();
    while text.len() < 64 * 1024 {
        text.push_str("The cohort had 120 participants. api_key=sk-abcdefghijklmnopqrstuvwxyz123456 was set.\n");
    }
    for _ in 0..5 {
        std::hint::black_box(redactor.redact(&text));
    }
    let mut times = Vec::new();
    for _ in 0..60 {
        let t = Instant::now();
        std::hint::black_box(redactor.redact(&text));
        times.push(t.elapsed().as_secs_f64() * 1000.0);
    }
    figures.insert("policy.redact_64k_p95_ms", p95(times));

    // The evidence gate: an answer with 40 cited statements against 200 hits.
    let mut tool = String::from("Evidence (200 hits):\n");
    for i in 0..200 {
        tool.push_str(&format!(
            "- [paper{i}.pdf #{i}] Results: Compound {i} reduced tumour volume by {}% in mice after 14 days.\n",
            i % 90
        ));
    }
    let mut evidence = Evidence::new();
    evidence.absorb_text(&tool);
    let mut answer = String::new();
    for i in 0..40 {
        answer.push_str(&format!(
            "Compound {i} reduced tumour volume by {}% in mice [paper{i}.pdf #{i}]. ",
            i % 90
        ));
    }
    let gate = Gate::new();
    for _ in 0..5 {
        std::hint::black_box(gate.check(&answer, &evidence));
    }
    let mut times = Vec::new();
    for _ in 0..100 {
        let t = Instant::now();
        std::hint::black_box(gate.check(&answer, &evidence));
        times.push(t.elapsed().as_secs_f64() * 1000.0);
    }
    figures.insert("evidence.gate_p95_ms", p95(times));
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let out = args
        .iter()
        .position(|a| a == "--out")
        .and_then(|i| args.get(i + 1))
        .cloned();
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .expect("runtime");
    let mut figures: BTreeMap<&'static str, f64> = BTreeMap::new();
    runtime.block_on(http_figures(&mut figures));
    gateway_figures(&mut figures);
    figures.insert("process.peak_rss_mb", peak_rss_mb());
    let rounded: BTreeMap<&str, f64> = figures.iter().map(|(k, v)| (*k, round3(*v))).collect();
    let mut text = serde_json::to_string_pretty(&json!({
        "backend": "scripted backend in one process; the cost of the server, never of a model",
        "chunks_per_answer": CHUNKS,
        "figures": rounded,
    }))
    .expect("json");
    text.push('\n');
    match out {
        Some(path) => std::fs::write(path, text).expect("write report"),
        None => print!("{text}"),
    }
}
