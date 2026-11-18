//! `laris-server`: the hardened HTTP API of the LARIS server (SR-S1).
//!
//! axum routes behind a reverse proxy; every body is checked before work starts (400, 411, 413), slow clients are
//! cut (408, header timeout), the client address comes from `X-Forwarded-For` only through trusted proxies, the
//! access log holds no content, a client that stops reading the answer is cut after `write_stall`, and a failure inside an answer stream becomes an `error` event then `[DONE]`.
//! Keys, roles and quotas (401, 403, 429) arrive in T143, the model proxy in T144; storage (PostgreSQL, T142) is the
//! [`storage`] module; the model
//! sits behind the [`Backend`] trait.

pub mod access;
pub mod admin;
pub mod app;
pub mod backend;
pub mod config;
pub mod error;
pub mod log;
pub mod proxy;
mod serve;
mod stall;
pub mod storage;

pub use app::{AppState, router};
pub use backend::{Backend, ChunkStream, NoBackend, StreamFailure};
pub use config::{ConfigError, ServerConfig};
pub use error::ApiError;
pub use log::{AccessRecord, LogSink, MemorySink, StderrSink};
pub use serve::serve;
