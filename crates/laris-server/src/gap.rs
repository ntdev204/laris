//! The research-gap routes (T272): the server owns the prompts and the analysis of the `research-gap` workflow.
//!
//! * `GET /v1/laris/gap/policy`: the policy in force (`.laris/gap.toml`: version, weights, rules, prompts).
//! * `POST /v1/laris/gap/extract` `{paper}`: step 2 for one paper. The server cuts the excerpts by rule, fills the
//!   policy's prompt, asks the model (temperature 0, no tools, no system prompt) and reads the record back. The
//!   answer keeps the raw model text, the blocks taken and the time, so a run can be checked afterwards.
//! * `POST /v1/laris/gap/baseline` `{mode, question, papers}`: the baselines `closed`, `context` and `rag` with the
//!   same model; `rag` also returns the passages retrieval fused.
//! * `POST /v1/laris/gap/analyze` `{topic, papers, records}`: steps 3–5 ([`laris_gap::analyze`]), the report and
//!   its citation audit. No model is called.
//!
//! The model is called directly, not through the chat pipeline: these turns are the server's own, with prompts from
//! the locked policy, and the paper text is data. The model stays NOT QUALIFIED; the routes check the citations and
//! quotations they can, not whether a cited passage supports a sentence.

use crate::access::perm;
use crate::app::{AppState, read_json};
use crate::backend::Backend;
use crate::error::ApiError;
use crate::log::RequestScope;
use axum::Extension;
use axum::extract::{Request, State};
use axum::http::{HeaderMap, HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use futures_util::StreamExt;
use laris_gap::{Paper, Record, Settings, Topic, audit, baseline, extract, report, sections};
use laris_protocol::chat::{ChatMessage, Content, Role};
use laris_protocol::p1::{ChatRequest, LarisRequest};
use serde::Deserialize;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Instant;

type Shared = State<Arc<AppState>>;
type Scope = Extension<Arc<RequestScope>>;

fn json_ok(value: &Value) -> Response {
    let mut response = Response::new(axum::body::Body::from(value.to_string()));
    *response.status_mut() = StatusCode::OK;
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/json"),
    );
    response
}

fn parts(state: &AppState) -> Result<(Arc<dyn Backend>, Arc<Settings>), ApiError> {
    let settings = state
        .policy
        .as_ref()
        .and_then(|p| p.gap())
        .cloned()
        .ok_or(ApiError::NotFound)?;
    let model = state
        .gap_model
        .clone()
        .ok_or_else(|| ApiError::BadGateway("the model service is not connected".into()))?;
    Ok((model, settings))
}

/// The model's whole answer to one user message.
async fn complete(model: &Arc<dyn Backend>, prompt: String) -> Result<String, ApiError> {
    let mut extra = Map::new();
    extra.insert("temperature".into(), json!(0.0));
    let request = ChatRequest {
        messages: vec![ChatMessage {
            role: Role::User,
            content: Some(Content::Text(prompt)),
            tool_calls: Vec::new(),
            tool_call_id: None,
            name: None,
            extra: Map::new(),
        }],
        tools: Vec::new(),
        stream: true,
        laris: LarisRequest::default(),
        extra,
    };
    let mut stream = model.chat(request).await?;
    let mut out = String::new();
    while let Some(item) = stream.next().await {
        match item {
            Ok(chunk) => {
                for c in chunk.choices {
                    if let Some(t) = c.delta.content {
                        out.push_str(&t);
                    }
                }
            }
            Err(f) => {
                return Err(ApiError::BadGateway(format!(
                    "the model failed: {}",
                    f.message
                )));
            }
        }
    }
    Ok(out)
}

/// `GET /v1/laris/gap/policy`.
pub async fn policy(State(state): Shared, Extension(scope): Scope, headers: HeaderMap) -> Response {
    scope.set_route("gap");
    if let Err(e) = crate::app::gate(&state, &scope, &headers, perm::CHAT).await {
        return e.into_response();
    }
    match state.policy.as_ref().and_then(|p| p.gap()) {
        Some(settings) => json_ok(&json!(settings.as_ref())),
        None => ApiError::NotFound.into_response(),
    }
}

#[derive(Deserialize)]
struct ExtractBody {
    paper: Paper,
}

/// `POST /v1/laris/gap/extract`.
pub async fn extract_route(
    State(state): Shared,
    Extension(scope): Scope,
    request: Request,
) -> Response {
    scope.set_route("gap");
    let run = async {
        let (body, _, _) = read_json::<ExtractBody>(&state, &scope, request, perm::CHAT).await?;
        let (model, settings) = parts(&state)?;
        let paper = body.paper;
        let secs = sections::split(&paper.text);
        let (excerpts, taken) = extract::excerpts(
            &paper.text,
            &secs,
            &settings.limitation_cues,
            settings.budget.extract_chars,
        );
        let prompt = extract::prompt(&settings.prompts.extract, &excerpts);
        let started = Instant::now();
        let raw = complete(&model, prompt.clone()).await?;
        let seconds = started.elapsed().as_secs_f64();
        let parsed = extract::parse_record(&raw);
        Ok::<_, ApiError>(json_ok(&json!({
            "paper": paper.id,
            "policy_version": settings.version,
            "sections": secs,
            "blocks": taken,
            "prompt_chars": prompt.len(),
            "prompt": prompt,
            "raw": raw,
            "record": parsed.as_ref().ok(),
            "error": parsed.as_ref().err(),
            "seconds": (seconds * 10.0).round() / 10.0,
        })))
    };
    run.await.unwrap_or_else(IntoResponse::into_response)
}

#[derive(Deserialize)]
struct BaselineBody {
    mode: String,
    question: String,
    #[serde(default)]
    papers: Vec<Paper>,
}

/// `POST /v1/laris/gap/baseline`.
pub async fn baseline_route(
    State(state): Shared,
    Extension(scope): Scope,
    request: Request,
) -> Response {
    scope.set_route("gap");
    let run = async {
        let (body, _, _) = read_json::<BaselineBody>(&state, &scope, request, perm::CHAT).await?;
        let (model, settings) = parts(&state)?;
        let mut retrieved = Vec::new();
        let prompt = match body.mode.as_str() {
            "closed" => baseline::closed(&settings, &body.question),
            "context" => baseline::context(&settings, &body.question, &body.papers),
            "rag" => {
                retrieved = baseline::retrieve(&settings, &body.question, &body.papers);
                baseline::rag(&settings, &body.question, &body.papers, &retrieved)
            }
            other => {
                return Err(ApiError::BadRequest(format!(
                    "unknown baseline mode {other}; use closed, context or rag"
                )));
            }
        };
        let started = Instant::now();
        let answer = complete(&model, prompt.clone()).await?;
        let seconds = started.elapsed().as_secs_f64();
        let cleaned = strip_think(&answer);
        let audit = audit::audit(&cleaned, &body.papers, &settings);
        Ok(json_ok(&json!({
            "mode": body.mode,
            "policy_version": settings.version,
            "prompt_chars": prompt.len(),
            "prompt": prompt,
            "retrieved": retrieved,
            "answer": cleaned,
            "audit": audit,
            "seconds": (seconds * 10.0).round() / 10.0,
        })))
    };
    run.await.unwrap_or_else(IntoResponse::into_response)
}

fn strip_think(text: &str) -> String {
    let mut t = text.to_owned();
    while let (Some(a), Some(b)) = (t.find("<think>"), t.find("</think>")) {
        if b < a {
            break;
        }
        t.replace_range(a..b + "</think>".len(), "");
    }
    t.trim().to_owned()
}

#[derive(Deserialize)]
struct RecordResult {
    #[serde(default)]
    record: Option<Record>,
    #[serde(default)]
    error: Option<String>,
}

#[derive(Deserialize)]
struct AnalyzeBody {
    topic: Topic,
    papers: Vec<Paper>,
    records: BTreeMap<String, RecordResult>,
}

/// `POST /v1/laris/gap/analyze`.
pub async fn analyze_route(
    State(state): Shared,
    Extension(scope): Scope,
    request: Request,
) -> Response {
    scope.set_route("gap");
    let run = async {
        let (body, _, _) = read_json::<AnalyzeBody>(&state, &scope, request, perm::CHAT).await?;
        let settings = state
            .policy
            .as_ref()
            .and_then(|p| p.gap())
            .cloned()
            .ok_or(ApiError::NotFound)?;
        let records: BTreeMap<String, Result<Record, String>> = body
            .records
            .into_iter()
            .map(|(k, r)| {
                let v = match (r.record, r.error) {
                    (Some(rec), _) => Ok(rec),
                    (None, e) => Err(e.unwrap_or_else(|| "no record".into())),
                };
                (k, v)
            })
            .collect();
        let started = Instant::now();
        let analysis = laris_gap::analyze(&body.topic, &settings, &body.papers, &records);
        let text = report::render(&analysis, &body.topic.title);
        let audit = audit::audit(&text, &body.papers, &settings);
        Ok::<_, ApiError>(json_ok(&json!({
            "analysis": analysis,
            "report": text,
            "audit": audit,
            "milliseconds": started.elapsed().as_millis() as u64,
        })))
    };
    run.await.unwrap_or_else(IntoResponse::into_response)
}
