//! Binary laris-server: reads `LARIS_SERVER__*` from the environment and serves until interrupted.

use laris_server::access::{Access, deliver_key};
use laris_server::policy::{PgReasoning, Policy, PolicyConfig, PolicyGateway, integrity};
use laris_server::storage::{RetentionHandle, Storage, StorageConfig};
use laris_server::{AppState, NoBackend, ServerConfig, StderrSink, serve};
use std::collections::HashMap;
use std::process::ExitCode;
use std::sync::Arc;

fn fail(message: impl std::fmt::Display, code: u8) -> ExitCode {
    eprintln!("laris-server: {message}");
    ExitCode::from(code)
}

/// `laris-server policy verify|lock`: checks the policy against `integrity.toml`, or writes a new lock after the
/// owner approved a change.
fn policy_command(action: &str, env: &HashMap<String, String>) -> ExitCode {
    let config = match PolicyConfig::from_env(env) {
        Ok(c) => c,
        Err(e) => return fail(e, 2),
    };
    match action {
        "verify" => match integrity::verified(&config.root) {
            Ok(_) => {
                println!("policy intact");
                ExitCode::SUCCESS
            }
            Err(e) => fail(e, 1),
        },
        "lock" => match integrity::write_lock(&config.root) {
            Ok(_) => {
                println!("integrity.toml written");
                ExitCode::SUCCESS
            }
            Err(e) => fail(e, 1),
        },
        _ => fail("usage: laris-server [policy verify|lock]", 2),
    }
}

#[tokio::main]
async fn main() -> ExitCode {
    let env: HashMap<String, String> = std::env::vars()
        .filter(|(k, _)| k.starts_with(laris_server::config::ENV_PREFIX))
        .collect();
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("policy") {
        return policy_command(args.get(1).map_or("", String::as_str), &env);
    }
    if !args.is_empty() {
        return fail("usage: laris-server [policy verify|lock]", 2);
    }
    let policy_config = match PolicyConfig::from_env(&env) {
        Ok(c) => c,
        Err(e) => return fail(e, 2),
    };
    // a policy that differs from its lock stops the server before it listens
    let policy = match Policy::load(
        &policy_config,
        std::env::vars(),
        std::env::var("HOME").ok().as_deref(),
    ) {
        Ok(p) => Arc::new(p),
        Err(e) => return fail(e, 1),
    };
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
    let reasoning = Arc::new(PgReasoning::new(storage.clone()));
    let backend = Arc::new(PolicyGateway::new(
        policy.clone(),
        Arc::new(NoBackend),
        reasoning.clone(),
    ));
    let state = Arc::new(AppState::new(config, backend, access).with_policy(policy, reasoning));
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
