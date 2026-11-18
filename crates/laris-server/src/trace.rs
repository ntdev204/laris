//! Traces and audit (SR-S7): one row per request with the key id, route, timings, tokens, brain note ids, tool names
//! and outcome, and no content.
//!
//! A [`TraceRecord`] has no field that could hold a message, an answer, an argument, a path or a query. Names that
//! reach it (tool names, brain note titles) are shortened and stripped of anything but plain characters by the
//! [`TraceDraft`] that collects them, so a hostile name cannot smuggle text into a row. A record is written once,
//! when the request ends, fails or the client leaves ([`crate::log::RequestScope::finish`]).
//!
//! Rows go to the `traces` table (kind `request`) through a bounded queue and one writer task: a request never waits
//! for the database, and a flood of requests fills the queue and loses rows (counted) instead of memory.

use crate::storage::Storage;
use futures_util::future::BoxFuture;
use sqlx::Row;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use tokio::sync::{mpsc, oneshot};

/// Longest tool name kept.
const MAX_TOOL_NAME: usize = 64;
/// Most tool names kept per request.
const MAX_TOOLS: usize = 32;
/// Longest brain note title kept.
const MAX_BRAIN_TITLE: usize = 120;
/// Most brain note titles kept per request.
const MAX_BRAIN: usize = 64;
/// Routes that are not traced: health checks and unknown paths would only fill the table.
const UNTRACED: [&str; 2] = ["health", "unmatched"];
/// Rows waiting for the writer before new ones are dropped.
const QUEUE: usize = 1024;

/// What is kept of one request.
#[derive(Debug, Clone, PartialEq)]
pub struct TraceRecord {
    /// Server-made request id (the one in `X-Request-Id` and the access log).
    pub request_id: String,
    /// Id of the key that asked; empty when the request came without a valid key.
    pub key_id: String,
    /// Route name chosen by the handler (`chat`, `embed`, `tools`, `admin_keys`, ...).
    pub route: String,
    /// Status sent; 499 when the client left before an answer.
    pub status: u16,
    /// `ok`, `error`, or how an answer stream ended: `midstream_error`, `stream_idle`, `client_gone`.
    pub outcome: String,
    /// Milliseconds from arrival to the end of the request (of the stream for an answer).
    pub duration_ms: u64,
    /// Session id of a chat; empty otherwise.
    pub session_id: String,
    /// Model name an answer reported.
    pub model: String,
    /// Prompt tokens charged or reported.
    pub prompt_tokens: i64,
    /// Completion tokens charged or reported.
    pub completion_tokens: i64,
    /// Names of the tools called (the model's calls to client tools, remote tools run), never their arguments.
    pub tools: Vec<String>,
    /// Titles of the system brain notes the answer drew on, never their text.
    pub brain: Vec<String>,
    /// Visible characters of the answer.
    pub answer_chars: u64,
    /// Unix seconds when the request ended.
    pub at: f64,
}

/// Where traces go.
pub trait TraceSink: Send + Sync + 'static {
    /// Takes one finished request. It never blocks and never fails the request.
    fn record(&self, record: TraceRecord);
}

/// What the operator asks of the stored traces. Every field narrows the result.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct TraceQuery {
    /// Most rows returned (1 to 500; 50 when `None`).
    pub limit: Option<usize>,
    /// Only this key.
    pub key_id: Option<String>,
    /// Only this route.
    pub route: Option<String>,
    /// Only this outcome.
    pub outcome: Option<String>,
    /// Only requests that ended at or after this time (Unix seconds).
    pub since: Option<f64>,
    /// Only requests that ended before this time (Unix seconds).
    pub until: Option<f64>,
}

impl TraceQuery {
    /// The row limit in force.
    pub fn limit(&self) -> usize {
        self.limit.map_or(50, |n| n.clamp(1, 500))
    }
}

/// A sink the operator can also read back.
pub trait TraceStore: TraceSink {
    /// The newest rows that match, newest first.
    fn query(&self, query: TraceQuery) -> BoxFuture<'_, Vec<TraceRecord>>;
}

/// Collects what a request learns on its way (the key, the session, tokens, names) until it ends.
#[derive(Debug, Default)]
pub struct TraceDraft {
    key_id: String,
    session_id: String,
    model: String,
    prompt_tokens: i64,
    completion_tokens: i64,
    tools: Vec<String>,
    brain: Vec<String>,
    answer_chars: u64,
}

/// A name as it may appear in a row: plain characters only, at most `max` of them.
fn plain(name: &str, max: usize, allow_space: bool) -> Option<String> {
    let name = name.trim();
    let ok = !name.is_empty()
        && name.chars().count() <= max
        && name.chars().all(|c| {
            c.is_alphanumeric()
                || matches!(c, '_' | '-' | '.' | ':' | '/')
                || (allow_space && c == ' ')
        });
    ok.then(|| name.to_owned())
}

impl TraceDraft {
    /// Names the key.
    pub fn set_key(&mut self, key_id: &str) {
        self.key_id = plain(key_id, 64, false).unwrap_or_default();
    }

    /// Names the session of a chat (already validated by the handler).
    pub fn set_session(&mut self, session: &str) {
        self.session_id = plain(session, 64, false).unwrap_or_default();
    }

    /// Names the model.
    pub fn set_model(&mut self, model: &str) {
        if self.model.is_empty() {
            self.model = plain(model, 128, false).unwrap_or_default();
        }
    }

    /// Records the tokens of the request.
    pub fn set_tokens(&mut self, prompt: i64, completion: i64) {
        self.prompt_tokens = prompt.max(0);
        self.completion_tokens = completion.max(0);
    }

    /// Records the visible length of the answer.
    pub fn set_answer_chars(&mut self, chars: u64) {
        self.answer_chars = chars;
    }

    /// Adds a tool name; a name with odd characters, or one past the limit, is dropped, never kept in part.
    pub fn add_tool(&mut self, name: &str) {
        if self.tools.len() < MAX_TOOLS
            && let Some(name) = plain(name, MAX_TOOL_NAME, false)
        {
            self.tools.push(name);
        }
    }

    /// Replaces the brain titles with the latest full list the stream reported.
    pub fn set_brain(&mut self, titles: &[String]) {
        self.brain = titles
            .iter()
            .filter_map(|t| plain(t, MAX_BRAIN_TITLE, true))
            .take(MAX_BRAIN)
            .collect();
    }

    /// The record of a request that ended with `status` and `outcome`.
    pub fn finish(
        self,
        request_id: &str,
        route: &str,
        status: u16,
        outcome: Option<&str>,
        duration_ms: u64,
        at: f64,
    ) -> TraceRecord {
        let outcome = outcome
            .map(str::to_owned)
            .unwrap_or_else(|| if status < 400 { "ok" } else { "error" }.to_owned());
        TraceRecord {
            request_id: request_id.to_owned(),
            key_id: self.key_id,
            route: route.to_owned(),
            status,
            outcome,
            duration_ms,
            session_id: self.session_id,
            model: self.model,
            prompt_tokens: self.prompt_tokens,
            completion_tokens: self.completion_tokens,
            tools: self.tools,
            brain: self.brain,
            answer_chars: self.answer_chars,
            at,
        }
    }
}

/// Whether requests on `route` leave a trace.
pub fn traced(route: &str) -> bool {
    !UNTRACED.contains(&route)
}

/// Keeps traces in memory (tests and embedding).
#[derive(Debug, Default)]
pub struct MemoryTraces(Mutex<Vec<TraceRecord>>);

impl MemoryTraces {
    /// The records so far, oldest first.
    pub fn records(&self) -> Vec<TraceRecord> {
        self.0.lock().map(|g| g.clone()).unwrap_or_default()
    }
}

impl TraceSink for MemoryTraces {
    fn record(&self, record: TraceRecord) {
        if let Ok(mut g) = self.0.lock() {
            g.push(record);
        }
    }
}

impl TraceStore for MemoryTraces {
    fn query(&self, query: TraceQuery) -> BoxFuture<'_, Vec<TraceRecord>> {
        Box::pin(async move {
            let mut rows: Vec<TraceRecord> = self
                .records()
                .into_iter()
                .filter(|r| query.key_id.as_ref().is_none_or(|k| &r.key_id == k))
                .filter(|r| query.route.as_ref().is_none_or(|k| &r.route == k))
                .filter(|r| query.outcome.as_ref().is_none_or(|k| &r.outcome == k))
                .filter(|r| query.since.is_none_or(|t| r.at >= t))
                .filter(|r| query.until.is_none_or(|t| r.at < t))
                .collect();
            rows.reverse();
            rows.truncate(query.limit());
            rows
        })
    }
}

enum Job {
    Write(Box<TraceRecord>),
    Flush(oneshot::Sender<()>),
}

/// Traces in the `traces` table.
pub struct PgTraces {
    storage: Arc<Storage>,
    queue: mpsc::Sender<Job>,
    failed: Arc<AtomicU64>,
    dropped: AtomicU64,
}

impl PgTraces {
    /// A store over `storage`, with its writer task started on the current runtime.
    pub fn spawn(storage: Arc<Storage>) -> Self {
        let (queue, mut jobs) = mpsc::channel::<Job>(QUEUE);
        let failed = Arc::new(AtomicU64::new(0));
        let writer = (storage.clone(), failed.clone());
        tokio::spawn(async move {
            let (storage, failed) = writer;
            while let Some(job) = jobs.recv().await {
                match job {
                    Job::Write(record) => {
                        if write(&storage, &record).await.is_err() {
                            failed.fetch_add(1, Ordering::Relaxed);
                        }
                    }
                    Job::Flush(done) => {
                        let _ = done.send(());
                    }
                }
            }
        });
        Self {
            storage,
            queue,
            failed,
            dropped: AtomicU64::new(0),
        }
    }

    /// Rows the database refused since the start.
    pub fn failures(&self) -> u64 {
        self.failed.load(Ordering::Relaxed)
    }

    /// Rows lost because the queue was full or the writer was gone.
    pub fn dropped(&self) -> u64 {
        self.dropped.load(Ordering::Relaxed)
    }

    /// Returns when every row handed over before this call is written (or has failed).
    pub async fn flush(&self) {
        let (tx, rx) = oneshot::channel();
        if self.queue.send(Job::Flush(tx)).await.is_ok() {
            let _ = rx.await;
        }
    }
}

async fn write(storage: &Storage, r: &TraceRecord) -> Result<(), ()> {
    let mut tx = storage.begin().await.map_err(|_| ())?;
    sqlx::query(
        "INSERT INTO traces (kind, request_id, key_id, ts, route, status, outcome, duration_ms, session_id, model, \
         prompt_tokens, completion_tokens, tool_calls, brain, answer_chars) \
         VALUES ('request', $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)",
    )
    .bind(&r.request_id)
    .bind(&r.key_id)
    .bind(r.at)
    .bind(&r.route)
    .bind(i32::from(r.status))
    .bind(&r.outcome)
    .bind(i64::try_from(r.duration_ms).unwrap_or(i64::MAX))
    .bind(&r.session_id)
    .bind(&r.model)
    .bind(r.prompt_tokens)
    .bind(r.completion_tokens)
    .bind(serde_json::to_string(&r.tools).unwrap_or_else(|_| "[]".to_owned()))
    .bind(serde_json::to_string(&r.brain).unwrap_or_else(|_| "[]".to_owned()))
    .bind(i32::try_from(r.answer_chars).unwrap_or(i32::MAX))
    .execute(&mut *tx)
    .await
    .map_err(|_| ())?;
    tx.commit().await.map_err(|_| ())
}

impl TraceSink for PgTraces {
    fn record(&self, record: TraceRecord) {
        if self.queue.try_send(Job::Write(Box::new(record))).is_err() {
            self.dropped.fetch_add(1, Ordering::Relaxed);
        }
    }
}

impl TraceStore for PgTraces {
    fn query(&self, query: TraceQuery) -> BoxFuture<'_, Vec<TraceRecord>> {
        Box::pin(async move {
            let limit = i64::try_from(query.limit()).unwrap_or(500);
            let rows = sqlx::query(
                "SELECT request_id, key_id, ts, route, status, outcome, duration_ms, session_id, model, \
                 prompt_tokens, completion_tokens, tool_calls, brain, answer_chars FROM traces \
                 WHERE kind = 'request' \
                 AND ($1::text IS NULL OR key_id = $1) AND ($2::text IS NULL OR route = $2) \
                 AND ($3::text IS NULL OR outcome = $3) \
                 AND ($4::float8 IS NULL OR ts >= $4) AND ($5::float8 IS NULL OR ts < $5) \
                 ORDER BY ts DESC, id DESC LIMIT $6",
            )
            .bind(query.key_id.as_deref())
            .bind(query.route.as_deref())
            .bind(query.outcome.as_deref())
            .bind(query.since)
            .bind(query.until)
            .bind(limit)
            .fetch_all(self.storage.pool())
            .await
            .unwrap_or_default();
            let names =
                |text: String| serde_json::from_str::<Vec<String>>(&text).unwrap_or_default();
            rows.into_iter()
                .map(|r| TraceRecord {
                    request_id: r.get("request_id"),
                    key_id: r.get("key_id"),
                    route: r.get("route"),
                    status: u16::try_from(r.get::<i32, _>("status")).unwrap_or(0),
                    outcome: r.get("outcome"),
                    duration_ms: u64::try_from(r.get::<i64, _>("duration_ms")).unwrap_or(0),
                    session_id: r.get("session_id"),
                    model: r.get("model"),
                    prompt_tokens: r.get("prompt_tokens"),
                    completion_tokens: r.get("completion_tokens"),
                    tools: names(r.get("tool_calls")),
                    brain: names(r.get("brain")),
                    answer_chars: u64::try_from(r.get::<i32, _>("answer_chars")).unwrap_or(0),
                    at: r.get("ts"),
                })
                .collect()
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_with_text_in_them_are_dropped_not_cut() {
        let mut d = TraceDraft::default();
        d.add_tool("read_file");
        d.add_tool("say hello to bob");
        d.add_tool("x\"; DROP TABLE traces; --");
        d.add_tool(&"a".repeat(65));
        d.add_tool("");
        assert_eq!(d.tools, ["read_file"]);
    }

    #[test]
    fn tools_and_brain_are_capped() {
        let mut d = TraceDraft::default();
        for i in 0..100 {
            d.add_tool(&format!("tool_{i}"));
        }
        assert_eq!(d.tools.len(), MAX_TOOLS);
        let titles: Vec<String> = (0..100).map(|i| format!("Note {i}")).collect();
        d.set_brain(&titles);
        assert_eq!(d.brain.len(), MAX_BRAIN);
        assert_eq!(d.brain[0], "Note 0");
    }

    #[test]
    fn outcome_defaults_follow_the_status() {
        let d = |s, o| {
            TraceDraft::default()
                .finish("r", "chat", s, o, 1, 1.0)
                .outcome
        };
        assert_eq!(d(200, None), "ok");
        assert_eq!(d(403, None), "error");
        assert_eq!(d(200, Some("client_gone")), "client_gone");
    }

    #[test]
    fn health_and_unknown_paths_are_not_traced() {
        assert!(!traced("health") && !traced("unmatched"));
        assert!(traced("chat") && traced("admin_keys"));
    }
}
