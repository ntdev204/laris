//! Learning data derived from the event log (SR-H11, ADR-021 D40).
//!
//! When `learning.collect` is on, a finished session is folded again from its log ([`derive`]) and every completed
//! turn that passes the quality gate becomes up to three kinds of example:
//!
//! * `sft`: the conversation up to the final answer, as chat messages;
//! * `retrieval`: a query of a retrieval tool with the hits the answer cited (positives) and a few it did not;
//! * `preference`: a draft the loop sent back for another try against the answer that finally stood.
//!
//! A turn is left out when it did not complete, carried an injection warning, holds anything the [`Redactor`]
//! would hide, has an answer the evidence gate marks, or has a short answer. Examples are plain JSON objects with a
//! content-derived `id`, kept in the `learning` table of the client store (the user's home, outside every
//! repository). [`export`] turns one kind into JSONL plus a manifest; [`write_export`] refuses a file inside a Git
//! work tree. Nothing here sends anything, and nothing trains. Nothing reads the table back into a request: a model
//! request is built from the conversation alone.

use crate::redact::Redactor;
use laris_config::settings::{ExportRating, Learning};
use laris_core::{CoreError, Record, Session, decode_record};
use laris_evidence::{Evidence, Gate, Target, citation};
use laris_protocol::{ChatMessage, Content, Event, Role};
use laris_store::{Store, StoreError, StoredEvent};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

/// Version of the example layout.
pub const SCHEMA: u32 = 1;

/// Table kind of the ratings.
const FEEDBACK: &str = "feedback";

/// Retrieval hits kept as negatives of one query.
const NEGATIVES: usize = 5;

/// A kind of example.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Kind {
    /// A conversation ending in an answer.
    Sft,
    /// A query with cited and uncited passages.
    Retrieval,
    /// A rejected draft against the final answer.
    Preference,
}

/// Every kind.
pub const KINDS: [Kind; 3] = [Kind::Sft, Kind::Retrieval, Kind::Preference];

impl Kind {
    /// The name used in the table, the command line and manifests.
    pub fn name(self) -> &'static str {
        match self {
            Self::Sft => "sft",
            Self::Retrieval => "retrieval",
            Self::Preference => "preference",
        }
    }

    /// The kind called `name`.
    pub fn parse(name: &str) -> Option<Self> {
        KINDS.into_iter().find(|k| k.name() == name)
    }
}

/// What can go wrong.
#[derive(Debug)]
pub enum LearnError {
    /// The log cannot be folded.
    Log(CoreError),
    /// The store refused an operation.
    Store(StoreError),
    /// An example id nobody knows.
    UnknownExample(String),
    /// The export file would be inside a Git work tree.
    InsideRepository(PathBuf),
    /// The export file cannot be written.
    Io(String),
}

impl std::fmt::Display for LearnError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Log(e) => write!(f, "{e}"),
            Self::Store(e) => write!(f, "{e}"),
            Self::UnknownExample(id) => write!(f, "no example {id}"),
            Self::InsideRepository(p) => write!(
                f,
                "{} is inside a Git work tree; collected learning data stays outside repositories",
                p.display()
            ),
            Self::Io(m) => f.write_str(m),
        }
    }
}

impl std::error::Error for LearnError {}

impl From<CoreError> for LearnError {
    fn from(e: CoreError) -> Self {
        Self::Log(e)
    }
}

impl From<StoreError> for LearnError {
    fn from(e: StoreError) -> Self {
        Self::Store(e)
    }
}

/// One derived example.
#[derive(Clone, Debug, PartialEq)]
pub struct Example {
    /// Its kind.
    pub kind: Kind,
    /// Seconds since the epoch, taken from the log.
    pub created: f64,
    /// The row: a JSON object with `id`.
    pub row: Value,
}

impl Example {
    /// The content-derived id.
    pub fn id(&self) -> &str {
        self.row["id"].as_str().unwrap_or_default()
    }
}

/// A turn that did not become an example, and why.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Rejection {
    /// Which user message of the session (from 1).
    pub turn: u32,
    /// `not_completed`, `injection_flag`, `sensitive`, `unverified` or `short_answer`.
    pub reason: &'static str,
}

/// What [`derive`] found in one log.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Derived {
    /// The examples, in log order.
    pub examples: Vec<Example>,
    /// The turns left out.
    pub rejected: Vec<Rejection>,
}

/// What [`collect`] did.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Collected {
    /// Whether collection is on; when off nothing was read or written.
    pub enabled: bool,
    /// Rows written, per kind name.
    pub stored: BTreeMap<&'static str, usize>,
    /// Rows that already existed.
    pub duplicates: usize,
    /// Turns left out.
    pub rejected: Vec<Rejection>,
}

/// A written export.
#[derive(Clone, Debug, PartialEq)]
pub struct Exported {
    /// The JSONL text: one example per line.
    pub jsonl: String,
    /// The manifest: kind, schema, count, rating rule, SHA-256 of `jsonl`.
    pub manifest: Value,
}

fn digest(parts: &[&str]) -> String {
    let mut hasher = Sha256::new();
    for (i, part) in parts.iter().enumerate() {
        if i > 0 {
            hasher.update([0x1f]);
        }
        hasher.update(part.as_bytes());
    }
    hasher
        .finalize()
        .iter()
        .take(8)
        .fold(String::new(), |mut s, b| {
            s.push_str(&format!("{b:02x}"));
            s
        })
}

fn text_of(message: &ChatMessage) -> Option<&str> {
    match &message.content {
        Some(Content::Text(t)) => Some(t.as_str()),
        _ => None,
    }
}

fn cut(text: &str, limit: usize) -> String {
    match text.char_indices().nth(limit) {
        Some((end, _)) => format!("{} …[truncated]", &text[..end]),
        None => text.to_owned(),
    }
}

/// The wire form of a message, reduced to what training needs.
fn clean(messages: &[ChatMessage], options: &Learning) -> Vec<Value> {
    messages
        .iter()
        .map(|m| {
            let mut row = Map::new();
            let whole = serde_json::to_value(m).unwrap_or(Value::Null);
            for key in ["role", "content", "tool_calls", "tool_call_id"] {
                if let Some(v) = whole.get(key) {
                    row.insert(key.to_owned(), v.clone());
                }
            }
            if m.role == Role::Tool {
                let text = text_of(m).unwrap_or_default();
                let kept = if options.store_tool_results {
                    cut(text, options.max_tool_result_chars as usize)
                } else {
                    "[omitted]".to_owned()
                };
                row.insert("content".to_owned(), Value::String(kept));
            }
            Value::Object(row)
        })
        .collect()
}

/// The retrieval calls of a turn: call id → (query, hits).
struct Retrieval {
    query: String,
    evidence: Evidence,
}

fn retrievals(messages: &[ChatMessage], options: &Learning) -> Vec<Retrieval> {
    let mut queries: BTreeMap<&str, String> = BTreeMap::new();
    for m in messages {
        for call in &m.tool_calls {
            let (Some(id), name) = (call.id.as_deref(), call.function.name.as_str()) else {
                continue;
            };
            if options.retrieval_tools.iter().any(|t| t == name) {
                let args: Value =
                    serde_json::from_str(&call.function.arguments).unwrap_or(Value::Null);
                let query = args["query"].as_str().unwrap_or_default().to_owned();
                queries.insert(id, query);
            }
        }
    }
    let mut out = Vec::new();
    for m in messages.iter().filter(|m| m.role == Role::Tool) {
        let Some(query) = m.tool_call_id.as_deref().and_then(|id| queries.get(id)) else {
            continue;
        };
        let text = text_of(m).unwrap_or_default();
        let mut evidence = Evidence::new();
        match serde_json::from_str::<Value>(text) {
            Ok(value) => evidence.absorb_json(&value),
            Err(_) => evidence.absorb_text(text),
        };
        out.push(Retrieval {
            query: query.clone(),
            evidence,
        });
    }
    out
}

/// Derives the examples of a session from its log. The log is folded with [`Session`], exactly as replay does; each
/// `done` event closes a turn. Output depends only on the log, `options` and `redactor`: the same log gives the same
/// bytes.
pub fn derive(
    events: &[StoredEvent],
    options: &Learning,
    redactor: &Redactor,
    session_id: &str,
) -> Result<Derived, LearnError> {
    let mut session = Session::new();
    let mut derived = Derived::default();
    // The loop adds user-role messages of its own (a retry, a notice). Only these positions are the user's.
    let mut typed: BTreeSet<usize> = BTreeSet::new();
    for stored in events {
        let record = decode_record(&stored.data).map_err(|message| CoreError::Decode {
            seq: stored.seq,
            message,
        })?;
        match record {
            Record::Emitted {
                event: Event::Done { status, answer },
            } => turn(
                &mut derived,
                (session.messages(), &typed),
                session.turns(),
                (&status, &answer),
                stored.created,
                (options, redactor, session_id),
            ),
            Record::Emitted { .. } => {}
            input => {
                let turns = session.turns();
                session.apply(&input)?;
                if session.turns() > turns {
                    typed.insert(session.messages().len() - 1);
                }
            }
        }
    }
    Ok(derived)
}

fn turn(
    out: &mut Derived,
    (everything, typed): (&[ChatMessage], &BTreeSet<usize>),
    number: u32,
    (status, answer): (&str, &str),
    created: f64,
    (options, redactor, session_id): (&Learning, &Redactor, &str),
) {
    let reject = |out: &mut Derived, reason| {
        out.rejected.push(Rejection {
            turn: number,
            reason,
        })
    };
    if status != "completed" {
        return reject(out, "not_completed");
    }
    // the conversation as the user and the model had it, without the loop's own messages
    let messages: Vec<ChatMessage> = everything
        .iter()
        .enumerate()
        .filter(|(i, m)| m.role != Role::User || typed.contains(i))
        .map(|(_, m)| m.clone())
        .collect();
    let messages = &messages[..];
    let Some(start) = messages.iter().rposition(|m| m.role == Role::User) else {
        return reject(out, "not_completed");
    };
    let this_turn = &messages[start..];
    // the final answer: what `done` carried, else the last assistant text without calls
    let last_text = this_turn
        .iter()
        .rev()
        .find(|m| m.role == Role::Assistant && m.tool_calls.is_empty())
        .and_then(text_of)
        .unwrap_or_default();
    let final_text = if answer.is_empty() { last_text } else { answer };
    let user = text_of(&messages[start]).unwrap_or_default();

    for m in everything {
        let whole = serde_json::to_string(m).unwrap_or_default();
        if m.role == Role::Tool && whole.contains("injection_warning") {
            return reject(out, "injection_flag");
        }
        if redactor.finds(&whole) {
            return reject(out, "sensitive");
        }
    }
    let found = retrievals(this_turn, options);
    let mut evidence = Evidence::new();
    for r in &found {
        for hit in r.evidence.hits() {
            evidence.add(hit.clone());
        }
    }
    if !Gate::new().check(final_text, &evidence).is_clean() {
        return reject(out, "unverified");
    }
    if final_text.chars().count() < options.min_answer_chars as usize {
        return reject(out, "short_answer");
    }

    let id = digest(&[user, final_text]);
    let tools: BTreeSet<&str> = this_turn
        .iter()
        .flat_map(|m| m.tool_calls.iter().map(|c| c.function.name.as_str()))
        .collect();
    let mut sources: Vec<&str> = Vec::new();
    for hit in evidence.hits() {
        if !sources.contains(&hit.source.as_str()) {
            sources.push(&hit.source);
        }
    }
    let ts = created.floor() as i64;
    // drafts the loop sent back: an assistant text without calls that another assistant message follows
    let drafts: BTreeSet<usize> = (start..messages.len().saturating_sub(1))
        .filter(|&i| {
            let (m, next) = (&messages[i], &messages[i + 1]);
            m.role == Role::Assistant
                && m.tool_calls.is_empty()
                && next.role == Role::Assistant
                && !text_of(m).unwrap_or_default().is_empty()
                && text_of(m) != Some(final_text)
        })
        .collect();
    let without_drafts = |end: usize| -> Vec<ChatMessage> {
        messages[..end]
            .iter()
            .enumerate()
            .filter(|(i, _)| !drafts.contains(i))
            .map(|(_, m)| m.clone())
            .collect()
    };
    out.examples.push(Example {
        kind: Kind::Sft,
        created,
        row: json!({
            "id": id, "schema": SCHEMA, "ts": ts, "session": session_id, "turn": number,
            "tools": tools, "sources": sources, "messages": clean(&without_drafts(messages.len()), options),
        }),
    });

    let cited: Vec<(String, u32)> = citation::parse(final_text)
        .into_iter()
        .filter_map(|c| match c.target {
            Target::Workspace { source, rank } => Some((source, rank)),
            Target::Brain { .. } => None,
        })
        .collect();
    for r in &found {
        let (mut positives, mut negatives) = (Vec::new(), Vec::new());
        for hit in r.evidence.hits() {
            let mut item = json!({
                "source": hit.source, "rank": hit.rank, "title": hit.title,
                "text_sha256": hex(&Sha256::digest(hit.text.as_bytes())),
            });
            if options.store_passage_text {
                item["text"] = Value::String(hit.text.clone());
            }
            // judged by source: a passage of a cited source is a positive
            let is_cited = cited.iter().any(|(source, _)| source == &hit.source);
            if is_cited {
                positives.push(item);
            } else {
                negatives.push(item);
            }
        }
        if positives.is_empty() {
            continue;
        }
        negatives.truncate(NEGATIVES);
        let keys: Vec<String> = positives
            .iter()
            .map(|p| format!("{}#{}{}", p["source"], p["rank"], p["text_sha256"]))
            .collect();
        let mut parts: Vec<&str> = vec!["retrieval", &r.query];
        parts.extend(keys.iter().map(String::as_str));
        out.examples.push(Example {
            kind: Kind::Retrieval,
            created,
            row: json!({
                "id": digest(&parts), "schema": SCHEMA, "ts": ts, "example": id,
                "query": r.query, "positives": positives, "negatives": negatives,
            }),
        });
    }

    for &index in &drafts {
        let draft_text = text_of(&messages[index]).unwrap_or_default();
        out.examples.push(Example {
            kind: Kind::Preference,
            created,
            row: json!({
                "id": digest(&["pref", draft_text, final_text]), "schema": SCHEMA, "ts": ts,
                "example": id, "prompt": clean(&without_drafts(index), options),
                "chosen": final_text, "rejected": draft_text, "reason": "rewritten after a check",
            }),
        });
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().fold(String::new(), |mut s, b| {
        s.push_str(&format!("{b:02x}"));
        s
    })
}

/// Derives the examples of one session and keeps them in the store. With `learning.collect` off it reads and writes
/// nothing.
pub fn collect(
    store: &Store,
    session: &str,
    options: &Learning,
    redactor: &Redactor,
) -> Result<Collected, LearnError> {
    let mut done = Collected {
        enabled: options.collect,
        ..Collected::default()
    };
    if !options.collect {
        return Ok(done);
    }
    let derived = derive(&store.events(session, 0)?, options, redactor, session)?;
    for example in &derived.examples {
        if store.put_learning(
            example.kind.name(),
            example.created,
            &example.row.to_string(),
        )? {
            *done.stored.entry(example.kind.name()).or_default() += 1;
        } else {
            done.duplicates += 1;
        }
    }
    done.rejected = derived.rejected;
    Ok(done)
}

fn rows(store: &Store, kind: &str) -> Result<Vec<Value>, LearnError> {
    Ok(store
        .learning(kind)?
        .iter()
        .filter_map(|r| serde_json::from_str(r).ok())
        .collect())
}

/// The latest rating of each example: `up` or `down`.
pub fn ratings(store: &Store) -> Result<BTreeMap<String, String>, LearnError> {
    let mut latest = BTreeMap::new();
    for row in rows(store, FEEDBACK)? {
        if let (Some(e), Some(r)) = (row["example"].as_str(), row["rating"].as_str()) {
            latest.insert(e.to_owned(), r.to_owned());
        }
    }
    Ok(latest)
}

/// Rates a conversation example `up` or `down`; the rating covers the pairs derived from it.
pub fn rate(store: &Store, example: &str, up: bool, now: f64) -> Result<(), LearnError> {
    if !rows(store, Kind::Sft.name())?
        .iter()
        .any(|r| r["id"] == example)
    {
        return Err(LearnError::UnknownExample(example.to_owned()));
    }
    let row =
        json!({"example": example, "rating": if up { "up" } else { "down" }, "ts": now.floor()});
    store.put_learning(FEEDBACK, now, &row.to_string())?;
    Ok(())
}

/// Counts: examples per kind, rated up, rated down.
pub fn stats(store: &Store, options: &Learning) -> Result<Value, LearnError> {
    let mut counts = Map::new();
    for kind in KINDS {
        counts.insert(
            kind.name().to_owned(),
            json!(store.learning(kind.name())?.len()),
        );
    }
    let rated = ratings(store)?;
    let n = |what: &str| rated.values().filter(|r| *r == what).count();
    Ok(json!({
        "enabled": options.collect, "examples": counts, "rated_up": n("up"), "rated_down": n("down"),
    }))
}

/// The examples of `kind` as JSONL with a manifest. An example rated down is never exported; with `Up` only the
/// ones rated up are. A pair is judged by the conversation example it came from.
pub fn export(store: &Store, kind: Kind, minimum: ExportRating) -> Result<Exported, LearnError> {
    let rated = ratings(store)?;
    let mut jsonl = String::new();
    let mut count = 0usize;
    for row in rows(store, kind.name())? {
        let owner = match kind {
            Kind::Sft => row["id"].as_str(),
            _ => row["example"].as_str(),
        }
        .unwrap_or_default();
        let rating = rated.get(owner).map(String::as_str);
        if rating == Some("down") || (minimum == ExportRating::Up && rating != Some("up")) {
            continue;
        }
        jsonl.push_str(&row.to_string());
        jsonl.push('\n');
        count += 1;
    }
    let manifest = json!({
        "kind": kind.name(), "schema": SCHEMA, "count": count,
        "min_rating": if minimum == ExportRating::Up { "up" } else { "none" },
        "sha256": hex(&Sha256::digest(jsonl.as_bytes())),
        "note": "The system prompt is not included; add it at training time. Nothing is trained here.",
    });
    Ok(Exported { jsonl, manifest })
}

/// Whether `path` lies inside a Git work tree (a `.git` entry in one of its folders).
pub fn inside_repository(path: &Path) -> bool {
    let absolute = std::path::absolute(path).unwrap_or_else(|_| path.to_path_buf());
    absolute
        .ancestors()
        .skip(1)
        .any(|dir| dir.join(".git").exists())
}

/// Writes the export to `path` and its manifest next to it (`<path>.manifest.json`). Refuses a path inside a Git
/// work tree.
pub fn write_export(path: &Path, exported: &Exported) -> Result<(), LearnError> {
    if inside_repository(path) {
        return Err(LearnError::InsideRepository(path.to_path_buf()));
    }
    let io = |e: std::io::Error| LearnError::Io(format!("{}: {e}", path.display()));
    if let Some(folder) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(folder).map_err(io)?;
    }
    std::fs::write(path, &exported.jsonl).map_err(io)?;
    let mut manifest = path.as_os_str().to_owned();
    manifest.push(".manifest.json");
    let text = serde_json::to_string_pretty(&exported.manifest).unwrap_or_default() + "\n";
    std::fs::write(PathBuf::from(manifest), text).map_err(io)
}

/// Deletes every collected row (examples and ratings) and returns how many there were.
pub fn purge(store: &Store) -> Result<usize, LearnError> {
    Ok(store.purge_learning()?)
}
