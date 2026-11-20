//! The account and admin routes (SR-S2): `GET /v1/laris/account`, `GET /v1/admin/usage`, and key management under
//! `/v1/admin/keys`. Each starts with the same gate as chat: protocol version, key, permission. A key's text is in
//! the answer that creates it and in no other answer, log or error.

use crate::access::{Access, KeyError, KeyRecord, NewKey, perm};
use crate::app::{AppState, gate, read_json};
use crate::error::ApiError;
use crate::log::RequestScope;
use crate::trace::TraceQuery;
use axum::Extension;
use axum::body::Body;
use axum::extract::{Path, Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::Response;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::sync::Arc;

type Shared = State<Arc<AppState>>;
type Scope = Extension<Arc<RequestScope>>;

fn json<T: Serialize>(status: StatusCode, value: &T) -> Result<Response, ApiError> {
    let bytes = serde_json::to_vec(value).map_err(|_| ApiError::Internal)?;
    let mut response = Response::new(Body::from(bytes));
    *response.status_mut() = status;
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/json"),
    );
    Ok(response)
}

fn done(result: Result<Response, ApiError>) -> Response {
    result.unwrap_or_else(ApiError::into_response)
}

fn key_error(e: KeyError) -> ApiError {
    match e {
        KeyError::Invalid(m) => ApiError::BadRequest(format!("invalid request: {m}")),
        KeyError::NotFound => ApiError::NotFound,
        KeyError::Storage(_) => ApiError::Internal,
    }
}

/// An open server (tests of the HTTP layer) has no keys to show.
fn access_of(state: &AppState) -> Result<&Arc<Access>, ApiError> {
    state.access.as_ref().ok_or(ApiError::NotFound)
}

/// A key as the admin routes show it: no digest, no text.
#[derive(Debug, Serialize)]
struct KeyView {
    id: String,
    label: String,
    role: String,
    extra_permissions: BTreeSet<String>,
    token_limit: Option<i64>,
    tokens_used: i64,
    tokens_reserved: i64,
    created_at: f64,
    expires_at: Option<f64>,
    revoked_at: Option<f64>,
    last_used_at: Option<f64>,
    allowed_ips: Vec<String>,
    builtin: bool,
    status: &'static str,
}

impl KeyView {
    fn of(k: KeyRecord, now: f64) -> Self {
        let status = k.status(now);
        Self {
            id: k.id,
            label: k.label,
            role: k.role,
            extra_permissions: k.extra_permissions,
            token_limit: k.token_limit,
            tokens_used: k.tokens_used,
            tokens_reserved: k.tokens_reserved,
            created_at: k.created_at,
            expires_at: k.expires_at,
            revoked_at: k.revoked_at,
            last_used_at: k.last_used_at,
            allowed_ips: k.allowed_ips,
            builtin: k.builtin,
            status,
        }
    }
}

/// `GET /v1/laris/account`: role, permissions and tokens left.
pub async fn account(State(state): Shared, Extension(scope): Scope, request: Request) -> Response {
    scope.set_route("account");
    done(account_inner(&state, &scope, request).await)
}

async fn account_inner(
    state: &AppState,
    scope: &RequestScope,
    request: Request,
) -> Result<Response, ApiError> {
    let principal = gate(state, scope, request.headers(), perm::ACCOUNT).await?;
    let (access, principal) = (access_of(state)?, principal.ok_or(ApiError::NotFound)?);
    json(StatusCode::OK, &access.account(&principal).await?)
}

/// `GET /v1/admin/usage`: requests and tokens per key.
pub async fn usage(State(state): Shared, Extension(scope): Scope, request: Request) -> Response {
    scope.set_route("admin_usage");
    done(usage_inner(&state, &scope, request).await)
}

async fn usage_inner(
    state: &AppState,
    scope: &RequestScope,
    request: Request,
) -> Result<Response, ApiError> {
    gate(state, scope, request.headers(), perm::USAGE_READ).await?;
    let lines = access_of(state)?.usage_summary().await?;
    json(StatusCode::OK, &serde_json::json!({ "usage": lines }))
}

/// `GET /v1/admin/keys`: every key, without digest or text.
pub async fn keys_list(
    State(state): Shared,
    Extension(scope): Scope,
    request: Request,
) -> Response {
    scope.set_route("admin_keys");
    done(keys_list_inner(&state, &scope, request).await)
}

async fn keys_list_inner(
    state: &AppState,
    scope: &RequestScope,
    request: Request,
) -> Result<Response, ApiError> {
    gate(state, scope, request.headers(), perm::KEYS_MANAGE).await?;
    let now = crate::access::now();
    let keys: Vec<KeyView> = access_of(state)?
        .keys()
        .list()
        .await
        .map_err(key_error)?
        .into_iter()
        .map(|k| KeyView::of(k, now))
        .collect();
    json(StatusCode::OK, &serde_json::json!({ "keys": keys }))
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CreateBody {
    #[serde(default)]
    label: String,
    role: String,
    /// `null` or absent is unlimited.
    #[serde(default)]
    token_limit: Option<i64>,
    #[serde(default)]
    permissions: BTreeSet<String>,
    #[serde(default)]
    expires_in_days: Option<f64>,
    #[serde(default)]
    allowed_ips: Vec<String>,
}

/// `POST /v1/admin/keys`: makes a key; the answer holds its text once.
pub async fn keys_create(
    State(state): Shared,
    Extension(scope): Scope,
    request: Request,
) -> Response {
    scope.set_route("admin_keys");
    done(keys_create_inner(&state, &scope, request).await)
}

async fn keys_create_inner(
    state: &AppState,
    scope: &RequestScope,
    request: Request,
) -> Result<Response, ApiError> {
    let (body, _, _) = read_json::<CreateBody>(state, scope, request, perm::KEYS_MANAGE).await?;
    let new = NewKey {
        label: body.label,
        role: body.role,
        token_limit: body.token_limit,
        extra_permissions: body.permissions,
        expires_in_days: body.expires_in_days,
        allowed_ips: body.allowed_ips,
        builtin: false,
    };
    let now = crate::access::now();
    let (record, text) = access_of(state)?
        .keys()
        .create(&new, now)
        .await
        .map_err(key_error)?;
    json(
        StatusCode::CREATED,
        &serde_json::json!({ "key": text, "record": KeyView::of(record, now) }),
    )
}

/// `POST /v1/admin/keys/{id}/revoke`.
pub async fn key_revoke(
    State(state): Shared,
    Extension(scope): Scope,
    Path(id): Path<String>,
    request: Request,
) -> Response {
    scope.set_route("admin_key_revoke");
    done(key_revoke_inner(&state, &scope, &id, request).await)
}

async fn key_revoke_inner(
    state: &AppState,
    scope: &RequestScope,
    id: &str,
    request: Request,
) -> Result<Response, ApiError> {
    gate(state, scope, request.headers(), perm::KEYS_MANAGE).await?;
    let now = crate::access::now();
    let record = access_of(state)?
        .keys()
        .revoke(id, now)
        .await
        .map_err(key_error)?;
    json(
        StatusCode::OK,
        &serde_json::json!({ "record": KeyView::of(record, now) }),
    )
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct LimitBody {
    /// `null` is unlimited.
    token_limit: Option<i64>,
    #[serde(default)]
    add: bool,
}

/// `POST /v1/admin/keys/{id}/limit`: sets, adds to or lifts the token limit.
pub async fn key_limit(
    State(state): Shared,
    Extension(scope): Scope,
    Path(id): Path<String>,
    request: Request,
) -> Response {
    scope.set_route("admin_key_limit");
    done(key_limit_inner(&state, &scope, &id, request).await)
}

async fn key_limit_inner(
    state: &AppState,
    scope: &RequestScope,
    id: &str,
    request: Request,
) -> Result<Response, ApiError> {
    let (body, _, _) = read_json::<LimitBody>(state, scope, request, perm::KEYS_MANAGE).await?;
    let now = crate::access::now();
    let record = access_of(state)?
        .keys()
        .set_limit(id, body.token_limit, body.add)
        .await
        .map_err(key_error)?;
    json(
        StatusCode::OK,
        &serde_json::json!({ "record": KeyView::of(record, now) }),
    )
}

/// What a trace row looks like to the operator: names and numbers only.
#[derive(Debug, Serialize)]
struct TraceView {
    request_id: String,
    key_id: String,
    route: String,
    status: u16,
    outcome: String,
    duration_ms: u64,
    session_id: String,
    model: String,
    prompt_tokens: i64,
    completion_tokens: i64,
    tools: Vec<String>,
    brain: Vec<String>,
    answer_chars: u64,
    stages: Vec<crate::trace::StageRecord>,
    at: f64,
}

/// The query of `GET /v1/admin/traces`. An unknown name or a value of the wrong form is a 400, never ignored.
fn trace_query(query: Option<&str>) -> Result<TraceQuery, ApiError> {
    let bad = |m: &str| ApiError::BadRequest(format!("invalid request: {m}"));
    let name = |v: &str| {
        let ok = !v.is_empty()
            && v.len() <= 64
            && v.bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-' | b'.'));
        ok.then(|| v.to_owned())
            .ok_or_else(|| bad("a filter is not a plain name"))
    };
    let time = |v: &str| {
        v.parse::<f64>()
            .ok()
            .filter(|t| t.is_finite() && *t >= 0.0)
            .ok_or_else(|| bad("a time is not a number of seconds"))
    };
    let mut q = TraceQuery::default();
    for pair in query
        .unwrap_or_default()
        .split('&')
        .filter(|p| !p.is_empty())
    {
        let (key, value) = pair.split_once('=').unwrap_or((pair, ""));
        match key {
            "limit" => {
                q.limit = Some(value.parse().map_err(|_| bad("limit is not a number"))?);
            }
            "key_id" => q.key_id = Some(name(value)?),
            "route" => q.route = Some(name(value)?),
            "outcome" => q.outcome = Some(name(value)?),
            "since" => q.since = Some(time(value)?),
            "until" => q.until = Some(time(value)?),
            _ => return Err(bad("unknown query parameter")),
        }
    }
    Ok(q)
}

/// `GET /v1/admin/traces`: the newest request traces, for the operator (`traces.read`). Filters: `limit` (1 to 500,
/// default 50), `key_id`, `route`, `outcome`, `since` and `until` (Unix seconds).
pub async fn traces(State(state): Shared, Extension(scope): Scope, request: Request) -> Response {
    scope.set_route("admin_traces");
    let headers = request.headers().clone();
    let query = request.uri().query().map(str::to_owned);
    drop(request);
    let result = async {
        gate(&state, &scope, &headers, perm::TRACES_READ).await?;
        let store = state.traces.as_ref().ok_or(ApiError::NotFound)?;
        let rows = store.query(trace_query(query.as_deref())?).await;
        let items: Vec<TraceView> = rows
            .into_iter()
            .map(|r| TraceView {
                request_id: r.request_id,
                key_id: r.key_id,
                route: r.route,
                status: r.status,
                outcome: r.outcome,
                duration_ms: r.duration_ms,
                session_id: r.session_id,
                model: r.model,
                prompt_tokens: r.prompt_tokens,
                completion_tokens: r.completion_tokens,
                tools: r.tools,
                brain: r.brain,
                answer_chars: r.answer_chars,
                stages: r.stages,
                at: r.at,
            })
            .collect();
        json(StatusCode::OK, &serde_json::json!({ "traces": items }))
    }
    .await;
    done(result)
}
