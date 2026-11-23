//! `POST /v1/laris/read?name=<file name>` (T273): the text of a file the web client attached. The browser cannot
//! read a PDF; the server reads it with the same built-in reader as `WebFetch` and `ingest_document` and gives the
//! text back, so the file becomes a text attachment (and, under the research-gap workflow, a paper of the answer).
//!
//! The body is the file's bytes (`Content-Length` required, at most `LARIS_SERVER__MAX_BODY_BYTES`). PDF, text and
//! Markdown are read; the server keeps nothing. A scanned PDF without a text layer is refused with `pdf_unreadable`:
//! the server image has no OCR programs.

use crate::access::perm;
use crate::app::{AppState, gate};
use crate::error::ApiError;
use crate::log::RequestScope;
use axum::Extension;
use axum::extract::{Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use laris_tools::ingest::{self, Kind, PdfLimits};
use serde_json::json;
use std::path::Path;
use std::sync::Arc;

/// Most characters of the text given back.
const MAX_CHARS: usize = 400_000;

fn name_of(query: Option<&str>) -> Option<String> {
    let raw = query?.split('&').find_map(|kv| kv.strip_prefix("name="))?;
    let decoded = percent_decode(raw);
    // a name, not a path
    let base = decoded.rsplit(['/', '\\']).next()?.trim().to_owned();
    (!base.is_empty()).then_some(base)
}

fn percent_decode(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'+' => out.push(b' '),
            b'%' if i + 2 < bytes.len() => {
                let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).ok();
                match hex.and_then(|h| u8::from_str_radix(h, 16).ok()) {
                    Some(b) => {
                        out.push(b);
                        i += 2;
                    }
                    None => out.push(b'%'),
                }
            }
            b => out.push(b),
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// `POST /v1/laris/read`.
pub async fn read_route(
    State(state): State<Arc<AppState>>,
    Extension(scope): Extension<Arc<RequestScope>>,
    request: Request,
) -> Response {
    scope.set_route("read");
    let run = async {
        let (parts, body) = request.into_parts();
        gate(&state, &scope, &parts.headers, perm::CHAT).await?;
        let name = name_of(parts.uri.query())
            .ok_or_else(|| ApiError::BadRequest("invalid request: `name` is missing".into()))?;
        let kind = match name.rsplit('.').next().map(str::to_lowercase).as_deref() {
            Some("pdf") => Kind::Pdf,
            Some("md" | "markdown") => Kind::Markdown,
            Some("txt" | "text") => Kind::Text,
            _ => {
                return Err(ApiError::BadRequest(
                    "invalid request: only PDF, text and Markdown files are read".into(),
                ));
            }
        };
        let length = parts
            .headers
            .get(header::CONTENT_LENGTH)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.trim().parse::<u64>().ok())
            .ok_or(ApiError::LengthRequired)?;
        let limit = state.config.max_body_bytes;
        if length > limit {
            return Err(ApiError::PayloadTooLarge { limit });
        }
        let max = usize::try_from(limit).unwrap_or(usize::MAX);
        let bytes =
            tokio::time::timeout(state.config.body_timeout, axum::body::to_bytes(body, max))
                .await
                .map_err(|_| ApiError::RequestTimeout)?
                .map_err(|_| ApiError::BadRequest("the request body could not be read".into()))?;
        scope.set_bytes_in(bytes.len() as u64);
        let file = name.clone();
        let read = tokio::task::spawn_blocking(move || {
            let limits = PdfLimits {
                max_stream_bytes: bytes.len().saturating_mul(8).max(1 << 20),
                max_pages: 5_000,
            };
            ingest::document_from_with(kind, Path::new(&file), &bytes, &limits, None)
        })
        .await
        .map_err(|e| ApiError::BadGateway(e.to_string()))?;
        let (doc, method) = read.map_err(|e| {
            ApiError::BadRequest(format!(
                "pdf_unreadable: {e}; a scanned PDF needs OCR, which the server does not have"
            ))
        })?;
        let text: String = doc.text.chars().take(MAX_CHARS).collect();
        let body = json!({
            "name": name,
            "title": doc.title,
            "chars": doc.text.chars().count(),
            "truncated": doc.text.chars().count() > MAX_CHARS,
            "read_by": format!("{method:?}").to_lowercase(),
            "text": text,
        });
        let mut response = Response::new(axum::body::Body::from(body.to_string()));
        *response.status_mut() = StatusCode::OK;
        response.headers_mut().insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/json"),
        );
        Ok::<_, ApiError>(response)
    };
    run.await.unwrap_or_else(IntoResponse::into_response)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_name_is_a_file_name_not_a_path() {
        assert_eq!(
            name_of(Some("name=paper%20one.pdf")).as_deref(),
            Some("paper one.pdf")
        );
        assert_eq!(
            name_of(Some("x=1&name=..%2F..%2Fetc%2Fpasswd")).as_deref(),
            Some("passwd")
        );
        assert_eq!(name_of(Some("name=")), None);
        assert_eq!(name_of(None), None);
        assert_eq!(percent_decode("a%2"), "a%2");
    }
}
