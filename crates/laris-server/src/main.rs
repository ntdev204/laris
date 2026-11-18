//! Binary laris-server: reads `LARIS_SERVER__*` from the environment and serves until interrupted.

use laris_server::access::{Access, deliver_key};
use laris_server::storage::{RetentionHandle, Storage, StorageConfig};
use laris_server::{AppState, NoBackend, ServerConfig, StderrSink, serve};
use std::collections::HashMap;
use std::process::ExitCode;
use std::sync::Arc;

fn fail(message: impl std::fmt::Display, code: u8) -> ExitCode {
    eprintln!("laris-server: {message}");
    ExitCode::from(code)
}

#[tokio::main]
async fn main() -> ExitCode {
    let env: HashMap<String, String> = std::env::vars()
        .filter(|(k, _)| k.starts_with(laris_server::config::ENV_PREFIX))
        .collect();
    let config = match ServerConfig::from_env(&env) {
        Ok(c) => c,
        Err(e) => return fail(e, 2),
    };
    let storage_config = match StorageConfig::from_env(&env) {
        Ok(c) => c,
        Err(e) => return fail(e, 2),
    };
    let access_config = match laris_server::access::AccessConfig::from_env(&env) {
        Ok(c) => c,
        Err(e) => return fail(e, 2),
    };
    let master = match access_config.load_master() {
        Ok(m) => m,
        Err(e) => return fail(e, 2),
    };
    let storage = match Storage::connect(&storage_config).await {
        Ok(s) => Arc::new(s),
        Err(e) => return fail(e, 1),
    };
    let access = Arc::new(Access::new(storage.clone(), master, &access_config));
    match access.keys().builtin().await {
        Ok(Some(_)) => {}
        Ok(None) => {
            let Some(path) = &access_config.first_admin_file else {
                return fail(
                    "LARIS_SERVER__FIRST_ADMIN_FILE is required until the first key exists",
                    2,
                );
            };
            match access.ensure_builtin_key("default (server only)").await {
                Ok(Some(text)) => {
                    if let Err(e) = deliver_key(path, &text) {
                        return fail(format!("cannot write the first key file: {}", e.kind()), 1);
                    }
                    eprintln!("laris-server: first admin key written to the configured file");
                }
                Ok(None) => {}
                Err(e) => return fail(e, 1),
            }
        }
        Err(e) => return fail(e, 1),
    }
    let retention = RetentionHandle::spawn(storage.clone(), storage_config.retention_interval);
    let listener = match tokio::net::TcpListener::bind(config.bind).await {
        Ok(l) => l,
        Err(e) => return fail(format!("cannot listen: {e}"), 1),
    };
    let state = Arc::new(AppState::new(config, Arc::new(NoBackend), access));
    let stop = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    let result = serve(listener, state, Arc::new(StderrSink), stop).await;
    retention.stop().await;
    storage.close().await;
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => fail(e, 1),
    }
}
