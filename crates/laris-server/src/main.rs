//! Binary laris-server: reads `LARIS_SERVER__*` from the environment and serves until interrupted.

use laris_server::access::{Access, deliver_key};
use laris_server::model::{ModelBackend, ModelConfig};
use laris_server::policy::{PgReasoning, Policy, PolicyConfig, PolicyGateway, integrity};
use laris_server::storage::{RetentionHandle, Storage, StorageConfig};
use laris_server::trace::PgTraces;
use laris_server::{AppState, Backend, NoBackend, ServerConfig, StderrSink, serve};
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
        _ => fail(
            "usage: laris-server [policy verify|lock | probe HOST:PORT/PATH]",
            2,
        ),
    }
}

/// `laris-server probe HOST:PORT`: asks `GET /health` over plain HTTP and exits 0 only on a 200. The image has no
/// shell and no `curl`, so the container's health check is the binary itself.
async fn probe(address: &str) -> ExitCode {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let address = address.trim_start_matches("http://");
    let (host_port, path) = address
        .split_once('/')
        .map_or((address, ""), |(h, p)| (h, p));
    let attempt = async {
        let mut stream = tokio::net::TcpStream::connect(host_port).await.ok()?;
        let request =
            format!("GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\n\r\n");
        stream.write_all(request.as_bytes()).await.ok()?;
        let mut head = [0_u8; 12];
        stream.read_exact(&mut head).await.ok()?;
        Some(head.starts_with(b"HTTP/1.1 200"))
    };
    match tokio::time::timeout(std::time::Duration::from_secs(3), attempt).await {
        Ok(Some(true)) => ExitCode::SUCCESS,
        _ => ExitCode::from(1),
    }
}

#[tokio::main]
async fn main() -> ExitCode {
    let mut env: HashMap<String, String> = std::env::vars()
        .filter(|(k, _)| k.starts_with(laris_server::config::ENV_PREFIX))
        .collect();
    if let Err(e) = laris_server::config::resolve_secret_files(&mut env) {
        return fail(e, 2);
    }
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("probe") {
        let Some(target) = args.get(1) else {
            return fail("usage: laris-server probe HOST:PORT/PATH", 2);
        };
        return probe(target).await;
    }
    if args.first().map(String::as_str) == Some("policy") {
        return policy_command(args.get(1).map_or("", String::as_str), &env);
    }
    if !args.is_empty() {
        return fail(
            "usage: laris-server [policy verify|lock | probe HOST:PORT/PATH]",
            2,
        );
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
    let model: Arc<dyn Backend> = match ModelConfig::from_env(&env) {
        Ok(Some(c)) => match ModelBackend::new(c) {
            Ok(m) => Arc::new(m),
            Err(e) => return fail(e, 2),
        },
        Ok(None) => {
            eprintln!(
                "laris-server: LARIS_SERVER__MODEL_URL is not set; chat and embed answer 502"
            );
            Arc::new(NoBackend)
        }
        Err(e) => return fail(e, 2),
    };
    let gap_model = model.clone();
    let gateway = Arc::new(PolicyGateway::new(policy.clone(), model, reasoning.clone()));
    let main_brain = match laris_server::mainbrain::MainBrainConfig::from_env(&env) {
        Ok(Some(c)) => match laris_server::mainbrain::MainBrain::open(&c) {
            Ok(b) => Some(Arc::new(b)),
            Err(e) => return fail(format!("cannot open the main brain: {}", e.kind()), 1),
        },
        Ok(None) => None,
        Err(e) => return fail(e, 2),
    };
    let decider_config = match laris_server::pipeline::DeciderConfig::from_env(&env) {
        Ok(c) => c,
        Err(e) => return fail(e, 2),
    };
    let pipeline_config = match laris_server::pipeline::PipelineConfig::from_env(&env) {
        Ok(c) => c,
        Err(e) => return fail(e, 2),
    };
    let backend: Arc<dyn Backend> = if pipeline_config.enabled() {
        let built = laris_server::pipeline::Pipeline::new(
            gateway,
            pipeline_config,
            policy.prefilter().cloned(),
            policy.harness().cloned(),
            main_brain.clone(),
        );
        let built = match (built, decider_config) {
            (Ok(p), Some(d)) => p.with_decider(d),
            (other, _) => other,
        };
        match built {
            Ok(p) => Arc::new(p),
            Err(e) => return fail(e, 1),
        }
    } else {
        gateway
    };
    let traces = Arc::new(PgTraces::spawn(storage.clone()));
    let mut state = AppState::new(config, backend, access)
        .with_policy(policy, reasoning)
        .with_traces(traces.clone())
        .with_gap_model(gap_model);
    if let Some(brain) = main_brain {
        state = state.with_main_brain(brain);
    }
    let state = Arc::new(state);
    let stop = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    let result = serve(listener, state, Arc::new(StderrSink), stop).await;
    traces.flush().await;
    retention.stop().await;
    storage.close().await;
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => fail(e, 1),
    }
}
