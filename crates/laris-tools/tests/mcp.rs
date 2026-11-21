//! The MCP bridge (T253, SR-H16) against a scripted server run through the real standard-input path and the OS
//! sandbox: handshake, tool list, call, tool error, timeout, crash and restart, skipped and failed servers.
#![cfg(target_os = "linux")]
#![allow(missing_docs)]

mod common;

use common::temp_dir;
use laris_sandbox::{Backend, Policy, Sandbox};
use laris_tools::{McpLaunch, McpRemote, McpSpec, McpState, McpStatus, RemoteTools};
use serde_json::{Value, json};
use std::path::PathBuf;
use std::sync::{Arc, OnceLock};
use std::time::Duration;

const SERVER: &str = r#"
import json, sys, os
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    method, i = m["method"], m["id"]
    def reply(r): print(json.dumps({"jsonrpc": "2.0", "id": i, "result": r}), flush=True)
    if method == "initialize":
        print("not json, a log line", flush=True)
        reply({"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "t", "version": "1"}})
    elif method == "tools/list":
        reply({"tools": [{"name": "search", "description": "find", "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}},
                         {"name": "bad.name", "inputSchema": {"type": "object"}}]})
    elif method == "tools/call":
        n, a = m["params"]["name"], m["params"]["arguments"]
        if a.get("q") == "boom":
            reply({"isError": True, "content": [{"type": "text", "text": "it broke"}]})
        elif a.get("q") == "slow":
            import time; time.sleep(30)
        elif a.get("q") == "die":
            os._exit(1)
        else:
            reply({"content": [{"type": "text", "text": "result for " + a.get("q", "")}, {"type": "image", "data": "x"}]})
"#;

fn helper() -> PathBuf {
    static BUILT: OnceLock<PathBuf> = OnceLock::new();
    BUILT
        .get_or_init(|| {
            let cargo = std::env::var("CARGO").unwrap_or_else(|_| "cargo".into());
            let status = std::process::Command::new(cargo)
                .args([
                    "build",
                    "--offline",
                    "-p",
                    "laris-sandbox",
                    "--bin",
                    "laris-sandbox-helper",
                ])
                .status()
                .expect("cargo build");
            assert!(status.success(), "the helper did not build");
            let exe = std::env::current_exe().expect("exe");
            exe.ancestors()
                .map(|dir| dir.join("laris-sandbox-helper"))
                .find(|path| path.is_file())
                .expect("the helper is not under the target folder")
        })
        .clone()
}

fn launch(name: &str) -> (McpLaunch, PathBuf) {
    let home = temp_dir(name).join("mcp-home");
    std::fs::create_dir_all(&home).expect("home");
    let backend = if laris_sandbox::sandbox::bwrap_works() {
        Backend::Bubblewrap
    } else {
        Backend::Landlock
    };
    let policy = Policy::workspace([home.clone()]).with_network(true);
    let sandbox = Sandbox::with_backend(policy, backend, Some(helper())).expect("sandbox");
    (
        McpLaunch {
            sandbox: Some(Arc::new(sandbox)),
            home: home.clone(),
        },
        home,
    )
}

fn spec(name: &str, home: &std::path::Path, call: u64) -> McpSpec {
    let script = home.join("server.py");
    std::fs::write(&script, SERVER).expect("script");
    McpSpec {
        name: name.to_owned(),
        command: "python3".to_owned(),
        args: vec![script.to_string_lossy().into_owned()],
        env: Vec::new(),
        start_timeout: Duration::from_secs(20),
        call_timeout: Duration::from_secs(call),
    }
}

fn args(v: Value) -> serde_json::Map<String, Value> {
    v.as_object().cloned().expect("object")
}

#[test]
fn a_server_is_listed_called_and_its_errors_are_typed() {
    let (launch, home) = launch("mcp-basic");
    let (mut remote, statuses) = McpRemote::start(vec![Ok(spec("web", &home, 5))], &launch);
    assert_eq!(
        statuses,
        vec![McpStatus {
            name: "web".into(),
            state: McpState::Running(2)
        }]
    );
    let names: Vec<String> = remote
        .schemas()
        .iter()
        .map(|s| s.function.name.clone())
        .collect();
    assert_eq!(names, ["mcp__web__search", "mcp__web__bad_name"]);

    let ok = remote
        .call("mcp__web__search", &args(json!({"q": "rust"})))
        .expect("ok");
    assert_eq!(ok["content"], "result for rust\n[image content left out]");
    let err = remote
        .call("mcp__web__search", &args(json!({"q": "boom"})))
        .expect_err("error");
    assert_eq!(
        (err.code.as_str(), err.message.as_str()),
        ("mcp_tool_error", "it broke")
    );
    assert_eq!(
        remote
            .call("mcp__web__nope", &args(json!({})))
            .expect_err("unknown")
            .code,
        "unknown_tool"
    );
}

#[test]
fn a_slow_call_times_out_and_a_dead_server_is_restarted_once() {
    let (launch, home) = launch("mcp-timeout");
    let (mut remote, st) = McpRemote::start(vec![Ok(spec("web", &home, 1))], &launch);
    eprintln!("{st:?}");
    let slow = remote
        .call("mcp__web__search", &args(json!({"q": "slow"})))
        .expect_err("slow");
    assert_eq!(slow.code, "timeout", "{slow:?}");
    // the server dies during a call; the next call starts it again
    let _ = remote.call("mcp__web__search", &args(json!({"q": "die"})));
    std::thread::sleep(Duration::from_millis(300));
    let again = remote
        .call("mcp__web__search", &args(json!({"q": "back"})))
        .expect("restarted");
    assert_eq!(
        again["content"],
        "result for back\n[image content left out]"
    );
}

#[test]
fn skipped_and_failed_servers_are_reported_and_leave_the_rest_working() {
    let (launch, home) = launch("mcp-failed");
    let mut missing = spec("ghost", &home, 5);
    missing.command = "definitely-not-a-program".to_owned();
    let skipped = McpStatus {
        name: "keyed".into(),
        state: McpState::Skipped("KEY is not set".into()),
    };
    let (remote, statuses) = McpRemote::start(
        vec![Ok(spec("web", &home, 5)), Ok(missing), Err(skipped.clone())],
        &launch,
    );
    assert!(statuses.contains(&skipped));
    assert!(
        statuses
            .iter()
            .any(|s| s.name == "web" && s.state == McpState::Running(2))
    );
    assert!(
        statuses
            .iter()
            .any(|s| s.name == "ghost" && matches!(s.state, McpState::Failed(_)))
    );
    assert!(!remote.is_empty());
}

#[test]
fn without_a_sandbox_no_server_starts() {
    let (mut launch, home) = launch("mcp-nosandbox");
    launch.sandbox = None;
    let (remote, statuses) = McpRemote::start(vec![Ok(spec("web", &home, 5))], &launch);
    assert!(remote.is_empty());
    assert!(matches!(statuses[0].state, McpState::Failed(_)));
}
