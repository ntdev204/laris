//! Every local tool, run for real: files, search, commands, memory, the vault and the web over the real network
//! (T271). It needs the internet, so it is ignored by default:
//! `cargo test -p laris-cli --test live_tools -- --ignored --nocapture`.
#![allow(missing_docs)]

use laris_cli::headless::web::WebBridge;
use laris_config::Settings;
use laris_tools::{Context, Registry};
use serde_json::{Map, Value, json};
use std::path::PathBuf;
use std::sync::Arc;

fn temp(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("laris-live-{name}-{}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir.canonicalize().expect("canonical")
}

fn registry(base: &std::path::Path) -> Registry {
    let project = base.join("project");
    std::fs::create_dir_all(&project).expect("project");
    let settings = Settings::default();
    let web = &settings.web;
    let runtime = Arc::new(
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime"),
    );
    let client = laris_model_client::WebClient::new(laris_model_client::WebOptions {
        timeout: std::time::Duration::from_secs(web.timeout_seconds),
        max_bytes: usize::try_from(web.max_bytes).unwrap_or(usize::MAX),
        max_redirects: web.max_redirects,
        user_agent: web.user_agent.clone(),
    })
    .expect("web client");
    let ctx = Context::new(&project, &settings)
        .expect("context")
        .with_checkpoints(base.join("checkpoints"))
        .with_memory_dir(base.join("memory"))
        .with_skill_dirs(vec![base.join("skills")])
        .with_web(Arc::new(WebBridge { client, runtime }));
    Registry::with_local_tools(ctx)
}

fn args(value: Value) -> Map<String, Value> {
    value.as_object().expect("an object").clone()
}

#[test]
#[ignore = "uses the network"]
fn every_tool_works() {
    let base = temp("all");
    std::fs::create_dir_all(base.join("skills/greet")).expect("skill dir");
    std::fs::write(
        base.join("skills/greet/SKILL.md"),
        "---\nname: greet\ndescription: Say hello\n---\nSay hello politely.\n",
    )
    .expect("skill");
    let mut tools = registry(&base);
    let names: Vec<String> = tools
        .schemas()
        .iter()
        .map(|s| s.function.name.clone())
        .collect();
    println!("tools: {names:?}");
    let calls: Vec<(&str, Value)> = vec![
        ("Now", json!({})),
        (
            "Write",
            json!({"path": "notes/a.md", "content": "alpha beta\ngamma\n"}),
        ),
        ("Read", json!({"path": "notes/a.md"})),
        (
            "Edit",
            json!({"path": "notes/a.md", "old_string": "gamma", "new_string": "delta"}),
        ),
        ("Glob", json!({"pattern": "**/*.md"})),
        ("Grep", json!({"pattern": "delta"})),
        ("Bash", json!({"command": "echo hello"})),
        (
            "save_memory",
            json!({"name": "answers", "content": "The owner prefers short answers."}),
        ),
        ("use_skill", json!({"name": "greet"})),
        (
            "WebSearch",
            json!({"query": "nonlinear model predictive control embedded"}),
        ),
        ("WebSearch", json!({"query": "điều khiển dự báo mô hình"})),
        (
            "PaperSearch",
            json!({"query": "nonlinear model predictive control microcontroller"}),
        ),
        (
            "WebFetch",
            json!({"url": "https://arxiv.org/abs/2507.21259"}),
        ),
        (
            "WebFetch",
            json!({"url": "https://doi.org/10.3390/electronics14142775"}),
        ),
        (
            "WebFetch",
            json!({"url": "https://en.wikipedia.org/wiki/Model_predictive_control"}),
        ),
    ];
    let mut failed = Vec::new();
    for (name, arguments) in calls {
        if !names.iter().any(|n| n == name) {
            failed.push(format!("{name}: not offered"));
            continue;
        }
        let result = tools.call(name, &args(arguments.clone()));
        let shown: String = result.to_string().chars().take(300).collect();
        println!("{name}({arguments}) -> {shown}");
        if result.get("error").is_some() {
            failed.push(format!("{name}: {}", result["error"]));
        }
    }
    assert!(
        failed.is_empty(),
        "tools that failed:\n{}",
        failed.join("\n")
    );
}
