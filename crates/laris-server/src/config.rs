//! Server configuration from the environment (SR-L1): `LARIS_SERVER__<KEY>` variables, passed in by the caller.
//!
//! The library never reads the process environment; `main` collects the variables and hands them over. There is
//! no default address: the operator must say where to listen.

use crate::proxy::{Cidr, TrustedProxies};
use std::collections::HashMap;
use std::net::SocketAddr;
use std::time::Duration;

/// Prefix of every server variable.
pub const ENV_PREFIX: &str = "LARIS_SERVER__";

/// Name of the variable that points at a file holding the database URL (a Docker secret); the URL itself is
/// `LARIS_SERVER__DATABASE_URL`.
pub const ENV_DATABASE_URL_FILE: &str = "LARIS_SERVER__DATABASE_URL_FILE";

/// Fills `LARIS_SERVER__DATABASE_URL` from the file named by `LARIS_SERVER__DATABASE_URL_FILE`, so the password
/// lives in a Docker secret and not in the environment. A URL given directly wins. The message names the
/// variable, never the file's content.
pub fn resolve_secret_files(env: &mut HashMap<String, String>) -> Result<(), ConfigError> {
    let Some(path) = env.get(ENV_DATABASE_URL_FILE).map(|v| v.trim().to_owned()) else {
        return Ok(());
    };
    if path.is_empty() || env.contains_key("LARIS_SERVER__DATABASE_URL") {
        return Ok(());
    }
    let text = std::fs::read_to_string(&path).map_err(|_| ConfigError::Invalid {
        name: ENV_DATABASE_URL_FILE,
        reason: "the file cannot be read",
    })?;
    env.insert(
        "LARIS_SERVER__DATABASE_URL".to_owned(),
        text.trim().to_owned(),
    );
    Ok(())
}

/// A setting that could not be used. The message names the variable, never its value.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ConfigError {
    /// A required variable is not set.
    #[error("{0} is required")]
    Missing(&'static str),
    /// A variable has a value of the wrong form.
    #[error("{name} is invalid: {reason}")]
    Invalid {
        /// Variable name.
        name: &'static str,
        /// What is wrong.
        reason: &'static str,
    },
}

/// Settings of `laris-server`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ServerConfig {
    /// Address to listen on (`LARIS_SERVER__BIND`, required).
    pub bind: SocketAddr,
    /// Largest request body in bytes (`LARIS_SERVER__MAX_BODY_BYTES`).
    pub max_body_bytes: u64,
    /// Proxies whose `X-Forwarded-For` is believed (`LARIS_SERVER__TRUSTED_PROXIES`, comma-separated addresses or
    /// CIDR blocks; empty by default).
    pub trusted_proxies: TrustedProxies,
    /// Time a client has to send the request line and headers (`LARIS_SERVER__HEADER_TIMEOUT_MS`).
    pub header_timeout: Duration,
    /// Time a client has to send the whole body (`LARIS_SERVER__BODY_TIMEOUT_MS`).
    pub body_timeout: Duration,
    /// Longest a write to the client may stay blocked because it does not read (`LARIS_SERVER__WRITE_STALL_MS`).
    pub write_stall: Duration,
    /// Longest silence inside an answer stream before it ends with an error event (`LARIS_SERVER__STREAM_IDLE_MS`).
    pub stream_idle: Duration,
    /// Connections served at once (`LARIS_SERVER__MAX_CONNECTIONS`).
    pub max_connections: usize,
    /// Most texts in one embed request (`LARIS_SERVER__EMBED_MAX_INPUTS`).
    pub embed_max_inputs: usize,
    /// Time open connections get to finish at shutdown (`LARIS_SERVER__SHUTDOWN_GRACE_MS`).
    pub shutdown_grace: Duration,
}

impl ServerConfig {
    /// A configuration listening on `bind` with every other setting at its default.
    pub fn with_bind(bind: SocketAddr) -> Self {
        Self {
            bind,
            max_body_bytes: 1_048_576,
            trusted_proxies: TrustedProxies::default(),
            header_timeout: Duration::from_secs(10),
            body_timeout: Duration::from_secs(30),
            write_stall: Duration::from_secs(30),
            stream_idle: Duration::from_secs(120),
            max_connections: 1024,
            embed_max_inputs: 256,
            shutdown_grace: Duration::from_secs(10),
        }
    }

    /// Reads the settings from `env` (variable name to value). Only `LARIS_SERVER__` names are looked at.
    pub fn from_env(env: &HashMap<String, String>) -> Result<Self, ConfigError> {
        let get = |name: &'static str| env.get(name).map(|v| v.trim()).filter(|v| !v.is_empty());
        let bind_name = "LARIS_SERVER__BIND";
        let bind = get(bind_name)
            .ok_or(ConfigError::Missing(bind_name))?
            .parse::<SocketAddr>()
            .map_err(|_| ConfigError::Invalid {
                name: bind_name,
                reason: "expected host:port",
            })?;
        let mut cfg = Self::with_bind(bind);
        let number = |name: &'static str, min: u64| -> Result<Option<u64>, ConfigError> {
            match get(name) {
                None => Ok(None),
                Some(v) => match v.parse::<u64>() {
                    Ok(n) if n >= min => Ok(Some(n)),
                    _ => Err(ConfigError::Invalid {
                        name,
                        reason: "expected a whole number in range",
                    }),
                },
            }
        };
        if let Some(n) = number("LARIS_SERVER__MAX_BODY_BYTES", 1)? {
            cfg.max_body_bytes = n;
        }
        if let Some(n) = number("LARIS_SERVER__HEADER_TIMEOUT_MS", 1)? {
            cfg.header_timeout = Duration::from_millis(n);
        }
        if let Some(n) = number("LARIS_SERVER__BODY_TIMEOUT_MS", 1)? {
            cfg.body_timeout = Duration::from_millis(n);
        }
        if let Some(n) = number("LARIS_SERVER__WRITE_STALL_MS", 1)? {
            cfg.write_stall = Duration::from_millis(n);
        }
        if let Some(n) = number("LARIS_SERVER__STREAM_IDLE_MS", 1)? {
            cfg.stream_idle = Duration::from_millis(n);
        }
        if let Some(n) = number("LARIS_SERVER__SHUTDOWN_GRACE_MS", 0)? {
            cfg.shutdown_grace = Duration::from_millis(n);
        }
        if let Some(n) = number("LARIS_SERVER__MAX_CONNECTIONS", 1)? {
            cfg.max_connections = usize::try_from(n).unwrap_or(usize::MAX);
        }
        if let Some(n) = number("LARIS_SERVER__EMBED_MAX_INPUTS", 1)? {
            cfg.embed_max_inputs = usize::try_from(n).unwrap_or(usize::MAX);
        }
        if let Some(list) = get("LARIS_SERVER__TRUSTED_PROXIES") {
            let mut blocks = Vec::new();
            for part in list.split(',').map(str::trim).filter(|p| !p.is_empty()) {
                blocks.push(Cidr::parse(part).ok_or(ConfigError::Invalid {
                    name: "LARIS_SERVER__TRUSTED_PROXIES",
                    reason: "expected addresses or CIDR blocks separated by commas",
                })?);
            }
            cfg.trusted_proxies = TrustedProxies::new(blocks);
        }
        Ok(cfg)
    }
}
