//! Binary laris-server: reads `LARIS_SERVER__*` from the environment and serves until interrupted.

use laris_server::{AppState, NoBackend, ServerConfig, StderrSink, serve};
use std::collections::HashMap;
use std::process::ExitCode;
use std::sync::Arc;

#[tokio::main]
async fn main() -> ExitCode {
    let env: HashMap<String, String> = std::env::vars()
        .filter(|(k, _)| k.starts_with(laris_server::config::ENV_PREFIX))
        .collect();
    let config = match ServerConfig::from_env(&env) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("laris-server: {e}");
            return ExitCode::from(2);
        }
    };
    let listener = match tokio::net::TcpListener::bind(config.bind).await {
        Ok(l) => l,
        Err(e) => {
            eprintln!("laris-server: cannot listen: {e}");
            return ExitCode::from(1);
        }
    };
    let state = Arc::new(AppState {
        config,
        backend: Arc::new(NoBackend),
    });
    let stop = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    match serve(listener, state, Arc::new(StderrSink), stop).await {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("laris-server: {e}");
            ExitCode::from(1)
        }
    }
}
