//! Failures answered before a stream starts, with the explicit status codes of SR-S1.

use axum::body::Body;
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::Response;
use laris_protocol::p1::HttpError;

/// A failure with its HTTP status. The body is `{"error": "message"}` (generation-1 shape).
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ApiError {
    /// 400: the request is malformed or breaks a rule.
    #[error("{0}")]
    BadRequest(String),
    /// 401: no valid key (used from T143).
    #[error("{0}")]
    Unauthorized(String),
    /// 403: the key may not do this (used from T143).
    #[error("{0}")]
    Forbidden(String),
    /// 404: no such route.
    #[error("not found")]
    NotFound,
    /// 405: the route does not take this method.
    #[error("method not allowed")]
    MethodNotAllowed,
    /// 408: the client was too slow sending the request.
    #[error("request timed out")]
    RequestTimeout,
    /// 411: the body has no `Content-Length`.
    #[error("Content-Length is required")]
    LengthRequired,
    /// 413: the body is larger than the limit.
    #[error("request body is larger than {limit} bytes")]
    PayloadTooLarge {
        /// The limit in bytes.
        limit: u64,
    },
    /// 426: the protocol version differs.
    #[error("{0}")]
    UpgradeRequired(String),
    /// 429: a quota or rate limit (used from T143).
    #[error("rate limit or quota exceeded")]
    TooManyRequests {
        /// Seconds the client should wait.
        retry_after_secs: Option<u64>,
    },
    /// 502: the model service failed or is not connected.
    #[error("{0}")]
    BadGateway(String),
    /// 500: a fault of the server itself.
    #[error("internal error")]
    Internal,
}

impl ApiError {
    /// The HTTP status.
    pub fn status(&self) -> StatusCode {
        match self {
            Self::BadRequest(_) => StatusCode::BAD_REQUEST,
            Self::Unauthorized(_) => StatusCode::UNAUTHORIZED,
            Self::Forbidden(_) => StatusCode::FORBIDDEN,
            Self::NotFound => StatusCode::NOT_FOUND,
            Self::MethodNotAllowed => StatusCode::METHOD_NOT_ALLOWED,
            Self::RequestTimeout => StatusCode::REQUEST_TIMEOUT,
            Self::LengthRequired => StatusCode::LENGTH_REQUIRED,
            Self::PayloadTooLarge { .. } => StatusCode::PAYLOAD_TOO_LARGE,
            Self::UpgradeRequired(_) => StatusCode::UPGRADE_REQUIRED,
            Self::TooManyRequests { .. } => StatusCode::TOO_MANY_REQUESTS,
            Self::BadGateway(_) => StatusCode::BAD_GATEWAY,
            Self::Internal => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }

    /// The response: status, JSON body, and `Retry-After` for a 429 that has one.
    pub fn into_response(self) -> Response {
        let body = serde_json::to_vec(&HttpError {
            error: self.to_string(),
        })
        .unwrap_or_else(|_| b"{\"error\":\"internal error\"}".to_vec());
        let mut response = Response::new(Body::from(body));
        *response.status_mut() = self.status();
        response.headers_mut().insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/json"),
        );
        if let Self::TooManyRequests {
            retry_after_secs: Some(secs),
        } = &self
            && let Ok(v) = HeaderValue::from_str(&secs.to_string())
        {
            response.headers_mut().insert(header::RETRY_AFTER, v);
        }
        if matches!(
            self,
            Self::LengthRequired | Self::PayloadTooLarge { .. } | Self::RequestTimeout
        ) {
            // The body was not read; the connection is not reused.
            response
                .headers_mut()
                .insert(header::CONNECTION, HeaderValue::from_static("close"));
        }
        response
    }
}

impl axum::response::IntoResponse for ApiError {
    fn into_response(self) -> Response {
        ApiError::into_response(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_explicit_status() {
        let cases = [
            (ApiError::BadRequest("x".into()), 400),
            (ApiError::Unauthorized("x".into()), 401),
            (ApiError::Forbidden("x".into()), 403),
            (ApiError::NotFound, 404),
            (ApiError::MethodNotAllowed, 405),
            (ApiError::RequestTimeout, 408),
            (ApiError::LengthRequired, 411),
            (ApiError::PayloadTooLarge { limit: 1 }, 413),
            (ApiError::UpgradeRequired("x".into()), 426),
            (
                ApiError::TooManyRequests {
                    retry_after_secs: None,
                },
                429,
            ),
            (ApiError::BadGateway("x".into()), 502),
            (ApiError::Internal, 500),
        ];
        for (error, code) in cases {
            assert_eq!(error.status().as_u16(), code);
            assert_eq!(error.into_response().status().as_u16(), code);
        }
    }

    #[test]
    fn retry_after_only_when_known() {
        let r = ApiError::TooManyRequests {
            retry_after_secs: Some(7),
        }
        .into_response();
        assert_eq!(r.headers()[header::RETRY_AFTER], "7");
        let r = ApiError::TooManyRequests {
            retry_after_secs: None,
        }
        .into_response();
        assert!(r.headers().get(header::RETRY_AFTER).is_none());
    }
}
