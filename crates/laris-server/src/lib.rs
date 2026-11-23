//! `laris-server`: the hardened HTTP API of the LARIS server (SR-S1).
//!
//! axum routes behind a reverse proxy; every body is checked before work starts (400, 411, 413), slow clients are
//! cut (408, header timeout), the client address comes from `X-Forwarded-For` only through trusted proxies, the
//! access log holds no content, a client that stops reading the answer is cut after `write_stall`, and a failure inside an answer stream becomes an `error` event then `[DONE]`.
//! Keys, roles and quotas (401, 403, 429) are the [`access`] module, storage (PostgreSQL) the [`storage`] module, and the
//! model sits behind the [`Backend`] trait: [`model::ModelBackend`] is the P2 proxy (SR-S6).

pub mod access;
pub mod admin;
pub mod app;
pub mod backend;
pub mod brain;
pub mod config;
pub mod error;
pub mod gap;
pub mod log;
pub mod mainbrain;
pub mod model;
pub mod pipeline;
pub mod policy;
pub mod proxy;
pub mod read;
mod serve;
mod stall;
pub mod storage;
pub mod trace;

pub use app::{AppState, router};
pub use backend::{Backend, Caller, ChunkStream, NoBackend, StreamFailure};
pub use config::{ConfigError, ServerConfig};
pub use error::ApiError;
pub use log::{AccessRecord, LogSink, MemorySink, StderrSink};
pub use serve::serve;
