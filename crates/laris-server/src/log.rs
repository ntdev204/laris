//! Content-free access log (SR-S1): one record per request with method, route name, status, sizes, time and the
//! client address. A record has no field that could hold a path, query, header, body, key or message text; the
//! route is a fixed name chosen by the handler, not the URL the client sent.

use serde_json::json;
use std::net::IpAddr;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::Instant;

/// One finished request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AccessRecord {
    /// Server-made request id (also sent as `X-Request-Id`).
    pub id: String,
    /// HTTP method.
    pub method: String,
    /// Name of the matched route: `health`, `chat`, `embed` or `unmatched`.
    pub route: &'static str,
    /// Status sent; 499 when the client left before an answer.
    pub status: u16,
    /// Body bytes received.
    pub bytes_in: u64,
    /// Milliseconds from the request's arrival to its end (end of the stream for an answer stream).
    pub duration_ms: u64,
    /// Client address after the trusted-proxy rule.
    pub client: IpAddr,
    /// How an answer stream ended when not normally: `midstream_error`, `stream_idle` or `client_gone`.
    pub outcome: Option<&'static str>,
}

impl AccessRecord {
    /// The record as one JSON line.
    pub fn to_json_line(&self, ts_ms: u64) -> String {
        json!({
            "ts_ms": ts_ms,
            "id": self.id,
            "method": self.method,
            "route": self.route,
            "status": self.status,
            "bytes_in": self.bytes_in,
            "duration_ms": self.duration_ms,
            "client": self.client.to_string(),
            "outcome": self.outcome,
        })
        .to_string()
    }
}

/// Where records go.
pub trait LogSink: Send + Sync + 'static {
    /// Takes one finished request.
    fn record(&self, record: &AccessRecord);
}

/// Writes JSON lines to standard error.
#[derive(Debug, Default)]
pub struct StderrSink;

impl LogSink for StderrSink {
    fn record(&self, record: &AccessRecord) {
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| u64::try_from(d.as_millis()).unwrap_or(u64::MAX));
        eprintln!("{}", record.to_json_line(ts));
    }
}

/// Keeps records in memory (tests and embedding).
#[derive(Debug, Default)]
pub struct MemorySink(Mutex<Vec<AccessRecord>>);

impl MemorySink {
    /// The records so far.
    pub fn records(&self) -> Vec<AccessRecord> {
        self.0.lock().map(|g| g.clone()).unwrap_or_default()
    }
}

impl LogSink for MemorySink {
    fn record(&self, record: &AccessRecord) {
        if let Ok(mut g) = self.0.lock() {
            g.push(record.clone());
        }
    }
}

/// State of one request, shared between the handler and the code that closes the log. The record is written
/// exactly once, by whichever ends the request first.
pub struct RequestScope {
    id: String,
    method: String,
    client: IpAddr,
    started: Instant,
    route: Mutex<&'static str>,
    bytes_in: AtomicU64,
    done: AtomicBool,
    sink: std::sync::Arc<dyn LogSink>,
}

impl RequestScope {
    /// Starts the scope of a request.
    pub fn new(
        id: String,
        method: String,
        client: IpAddr,
        sink: std::sync::Arc<dyn LogSink>,
    ) -> Self {
        Self {
            id,
            method,
            client,
            started: Instant::now(),
            route: Mutex::new("unmatched"),
            bytes_in: AtomicU64::new(0),
            done: AtomicBool::new(false),
            sink,
        }
    }

    /// The request id.
    pub fn id(&self) -> &str {
        &self.id
    }

    /// The client address.
    pub fn client(&self) -> IpAddr {
        self.client
    }

    /// Names the route that handles the request.
    pub fn set_route(&self, route: &'static str) {
        if let Ok(mut r) = self.route.lock() {
            *r = route;
        }
    }

    /// Records how many body bytes arrived.
    pub fn set_bytes_in(&self, n: u64) {
        self.bytes_in.store(n, Ordering::Relaxed);
    }

    /// Writes the record unless it was written already.
    pub fn finish(&self, status: u16, outcome: Option<&'static str>) {
        if self.done.swap(true, Ordering::AcqRel) {
            return;
        }
        let route = self.route.lock().map_or("unmatched", |r| *r);
        self.sink.record(&AccessRecord {
            id: self.id.clone(),
            method: self.method.clone(),
            route,
            status,
            bytes_in: self.bytes_in.load(Ordering::Relaxed),
            duration_ms: u64::try_from(self.started.elapsed().as_millis()).unwrap_or(u64::MAX),
            client: self.client,
            outcome,
        });
    }
}
