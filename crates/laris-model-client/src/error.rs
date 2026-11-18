//! Errors of the model client. Messages are for people; the variants are for the loop (what may be retried, what
//! must stop the turn).

use std::time::Duration;

/// A failed call to the server.
#[derive(Debug, thiserror::Error)]
pub enum ClientError {
    /// The configuration cannot make a client (bad address, bad key, bad pin).
    #[error("invalid client configuration: {0}")]
    Config(String),
    /// Client and server speak different versions of P1 (HTTP 426 or a different `X-Laris-Protocol` answer).
    #[error("{0}")]
    Version(String),
    /// The server refused the API key (HTTP 401 or 403).
    #[error("the server refused the API key: {0}")]
    Unauthorized(String),
    /// Any other HTTP error status.
    #[error("the server answered {status}: {message}")]
    Http {
        /// Status code.
        status: u16,
        /// The `error` text of the body, or the start of the body.
        message: String,
    },
    /// The connection failed before an answer arrived.
    #[error("could not reach the server: {0}")]
    Transport(String),
    /// No answer headers within the request timeout.
    #[error("the server did not answer within {0:?}")]
    Timeout(Duration),
    /// No bytes for the idle timeout while a body was being read.
    #[error("the server went silent for {0:?}")]
    IdleTimeout(Duration),
    /// The certificate authority does not match the pinned fingerprint.
    #[error("certificate authority does not match the pin: expected {expected}, found {actual}")]
    PinMismatch {
        /// The configured pin.
        expected: String,
        /// The fingerprint of the certificate that was offered.
        actual: String,
    },
    /// The caller interrupted the call.
    #[error("interrupted")]
    Interrupted,
    /// The event stream is malformed or an event is larger than the limit.
    #[error("invalid event stream: {0}")]
    Stream(String),
    /// The body ended before `[DONE]`.
    #[error("the stream ended before [DONE]")]
    Truncated,
    /// A JSON answer does not have the expected shape.
    #[error("invalid answer: {0}")]
    Decode(String),
}

impl ClientError {
    /// Whether the same request may be sent again, before any stream has started.
    pub fn is_retryable(&self) -> bool {
        match self {
            Self::Transport(_) | Self::Timeout(_) => true,
            Self::Http { status, .. } => matches!(status, 429 | 502 | 503 | 504),
            _ => false,
        }
    }
}
