//! Client configuration. Every value comes from the caller (settings file, environment, package defaults, see
//! `laris-config`); nothing here is a built-in endpoint, key or limit.

use crate::error::ClientError;
use laris_config::settings::Server;
use std::fmt;
use std::time::Duration;

/// Environment variable that holds the API key.
pub const API_KEY_ENV: &str = "LARIS_API_KEY";

/// The user's API key. Never printed: `Debug` hides it.
#[derive(Clone, PartialEq, Eq)]
pub struct ApiKey(String);

impl ApiKey {
    /// Wraps a key; refuses an empty key or one that cannot travel in a header.
    pub fn new(key: impl Into<String>) -> Result<Self, ClientError> {
        let key = key.into();
        if key.trim().is_empty() || key.chars().any(|c| c.is_control() || c.is_whitespace()) {
            return Err(ClientError::Config(
                "the API key is empty or contains whitespace or control characters".to_owned(),
            ));
        }
        Ok(Self(key))
    }

    /// Reads [`API_KEY_ENV`]; `None` when unset or empty.
    pub fn from_env() -> Result<Option<Self>, ClientError> {
        match std::env::var(API_KEY_ENV) {
            Ok(value) if !value.trim().is_empty() => Self::new(value.trim()).map(Some),
            _ => Ok(None),
        }
    }

    /// The key as text. Only for hiding it: a redactor must know the key to mask it in what leaves the machine.
    /// Never print or log the result.
    pub fn expose(&self) -> &str {
        &self.0
    }

    pub(crate) fn bearer(&self) -> String {
        format!("Bearer {}", self.0)
    }
}

impl fmt::Debug for ApiKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("ApiKey(***)")
    }
}

/// How the client behaves on the wire.
#[derive(Debug, Clone)]
pub struct ClientConfig {
    /// Server address as the settings give it, `https://host/v1` (no trailing slash needed).
    pub base_url: String,
    /// API key, if the server needs one.
    pub api_key: Option<ApiKey>,
    /// Longest wait for the answer headers of one attempt.
    pub request_timeout: Duration,
    /// Longest silence between two chunks of a body.
    pub idle_timeout: Duration,
    /// Extra attempts after the first, only before a stream has started.
    pub max_retries: u32,
    /// Wait before the first retry; doubles each time.
    pub backoff_base: Duration,
    /// The wait never exceeds this, a `Retry-After` of the server included.
    pub backoff_max: Duration,
    /// Largest accepted event of a stream and largest accepted JSON or error body, in bytes.
    pub max_body_bytes: usize,
}

impl ClientConfig {
    /// The client configuration of the `server` block of the settings; the key comes from the credentials.
    pub fn from_server(server: &Server, api_key: Option<ApiKey>) -> Result<Self, ClientError> {
        let seconds = |name: &str, value: f64| {
            Duration::try_from_secs_f64(value).map_err(|_| {
                ClientError::Config(format!("server.{name} is not a usable number of seconds"))
            })
        };
        Ok(Self {
            base_url: server.url.clone(),
            api_key,
            request_timeout: seconds("timeoutSeconds", server.timeout_seconds)?,
            idle_timeout: seconds("idleTimeoutSeconds", server.idle_timeout_seconds)?,
            max_retries: server.max_retries,
            backoff_base: seconds("retryBackoffSeconds", server.retry_backoff_seconds)?,
            backoff_max: seconds("retryBackoffMaxSeconds", server.retry_backoff_max_seconds)?,
            max_body_bytes: usize::try_from(server.max_response_bytes).map_err(|_| {
                ClientError::Config("server.maxResponseBytes is too large".to_owned())
            })?,
        })
    }

    /// Checks the values and returns the address without a trailing slash.
    pub(crate) fn validated_base(&self) -> Result<String, ClientError> {
        let base = self.base_url.trim().trim_end_matches('/');
        if !(base.starts_with("https://") || base.starts_with("http://")) {
            return Err(ClientError::Config(
                "the server address must start with http:// or https://".to_owned(),
            ));
        }
        if self.request_timeout.is_zero() || self.idle_timeout.is_zero() {
            return Err(ClientError::Config(
                "timeouts must be above zero".to_owned(),
            ));
        }
        if self.backoff_base > self.backoff_max {
            return Err(ClientError::Config(
                "the first retry wait is longer than the longest one".to_owned(),
            ));
        }
        if self.max_body_bytes == 0 {
            return Err(ClientError::Config(
                "the body limit must be above zero".to_owned(),
            ));
        }
        Ok(base.to_owned())
    }
}
