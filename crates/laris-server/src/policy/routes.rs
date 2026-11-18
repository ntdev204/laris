//! `GET /v1/laris/workflows`, `GET /v1/laris/help` and `GET /v1/admin/reasoning`.
//!
//! The first two tell the client what it may know (a workflow's limits, the prepared guide); the phases and
//! instructions stay on the server. The third is for the operator: it needs the `reasoning.read` permission, which
//! only privileged roles hold.

use crate::access::perm;
use crate::app::{AppState, gate};
use crate::error::ApiError;
use crate::log::RequestScope;
use axum::Extension;
use axum::body::Body;
use axum::extract::{Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::Response;
use laris_protocol::p1::{HelpResponse, WorkflowsResponse};
use serde::Serialize;
use std::sync::Arc;

type Shared = State<Arc<AppState>>;
type Scope = Extension<Arc<RequestScope>>;

fn json<T: Serialize>(value: &T) -> Result<Response, ApiError> {
    let bytes = serde_json::to_vec(value).map_err(|_| ApiError::Internal)?;
    let mut response = Response::new(Body::from(bytes));
    *response.status_mut() = StatusCode::OK;
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/json"),
    );
    Ok(response)
}

/// `GET /v1/laris/workflows`.
pub async fn workflows(
    State(state): Shared,
    Extension(scope): Scope,
    request: Request,
) -> Response {
    scope.set_route("workflows");
    let headers = request.headers().clone();
    drop(request);
    let result = async {
        gate(&state, &scope, &headers, perm::WORKFLOWS).await?;
        let policy = state.policy.as_ref().ok_or(ApiError::NotFound)?;
        json(&WorkflowsResponse {
            workflows: policy.workflows().all().map(|w| w.info()).collect(),
        })
    }
    .await;
    result.unwrap_or_else(ApiError::into_response)
}

/// `GET /v1/laris/help`.
pub async fn help(State(state): Shared, Extension(scope): Scope, request: Request) -> Response {
    scope.set_route("help");
    let headers = request.headers().clone();
    drop(request);
    let result = async {
        gate(&state, &scope, &headers, perm::HELP).await?;
        let policy = state.policy.as_ref().ok_or(ApiError::NotFound)?;
        json(&HelpResponse {
            text: policy.help().to_owned(),
        })
    }
    .await;
    result.unwrap_or_else(ApiError::into_response)
}

#[derive(Serialize)]
struct ReasoningView {
    key_id: String,
    session_id: String,
    model: String,
    prompt_sha256: String,
    reasoning: String,
    at: f64,
}

/// `GET /v1/admin/reasoning`: the newest reasoning records (at most 50, or `?limit=`), for the operator.
pub async fn reasoning(
    State(state): Shared,
    Extension(scope): Scope,
    request: Request,
) -> Response {
    scope.set_route("admin_reasoning");
    let headers = request.headers().clone();
    let query = request.uri().query().map(str::to_owned);
    drop(request);
    let result = async {
        gate(&state, &scope, &headers, perm::REASONING_READ).await?;
        let store = state.reasoning.as_ref().ok_or(ApiError::NotFound)?;
        let limit = query
            .as_deref()
            .and_then(|q| q.split('&').find_map(|p| p.strip_prefix("limit=")))
            .and_then(|v| v.parse::<usize>().ok())
            .map_or(50, |n| n.clamp(1, 500));
        let items: Vec<ReasoningView> = store
            .recent(limit)
            .await
            .into_iter()
            .map(|r| ReasoningView {
                key_id: r.key_id,
                session_id: r.session_id,
                model: r.model,
                prompt_sha256: r.prompt_sha256,
                reasoning: r.reasoning,
                at: r.at,
            })
            .collect();
        json(&serde_json::json!({ "reasoning": items }))
    }
    .await;
    result.unwrap_or_else(ApiError::into_response)
}
