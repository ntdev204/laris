//! MCP servers as remote tools (SR-H16): a minimal Model Context Protocol client over standard input and output.
//!
//! Each server is a child process started inside the OS sandbox (network on, writes only to its own cache folder)
//! and spoken to in JSON-RPC 2.0, one message per line: `initialize`, `notifications/initialized`, `tools/list` and
//! `tools/call`. Its tools reach the model as `mcp__<server>__<tool>` through [`RemoteTools`], so the registry marks
//! their output untrusted and the permission rules, hooks and the shield apply exactly as for any remote tool.
//! A server that cannot start is reported in [`McpStatus`] and left out; it never stops the client.

use crate::error::ToolError;
use crate::registry::{RemoteTools, function_schema};
use laris_protocol::ToolSchema;
use laris_sandbox::Sandbox;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Stdio};
use std::sync::Arc;
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::time::{Duration, Instant};

type Args = Map<String, Value>;

/// The protocol revision announced in `initialize`; a server may answer with an older one.
const PROTOCOL: &str = "2025-03-26";

/// One server to start.
#[derive(Clone, Debug)]
pub struct McpSpec {
    /// Name in the tool names.
    pub name: String,
    /// Program to run.
    pub command: String,
    /// Its arguments.
    pub args: Vec<String>,
    /// Environment variables handed to it, with their values.
    pub env: Vec<(String, String)>,
    /// Time allowed for the handshake and the tool list.
    pub start_timeout: Duration,
    /// Time allowed for one call.
    pub call_timeout: Duration,
}

/// What a server did at start.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum McpState {
    /// Running with this many tools.
    Running(usize),
    /// Not started on purpose (disabled, or a required variable is unset).
    Skipped(String),
    /// Could not be started.
    Failed(String),
}

/// A server and its state, as `/mcp` shows it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct McpStatus {
    /// Server name.
    pub name: String,
    /// State.
    pub state: McpState,
}

/// Where servers run.
#[derive(Clone)]
pub struct McpLaunch {
    /// The sandbox a server runs in; without one no server is started.
    pub sandbox: Option<Arc<Sandbox>>,
    /// Working folder and `HOME` of every server: the only place it may write.
    pub home: PathBuf,
}

struct Server {
    spec: McpSpec,
    launch: McpLaunch,
    child: Child,
    stdin: ChildStdin,
    lines: Receiver<String>,
    next_id: u64,
    tools: Vec<(String, Value)>,
}

impl Server {
    /// Starts the process on the calling thread: the sandbox ties a child to the thread that started it
    /// (`PR_SET_PDEATHSIG`), so a short-lived worker thread must not be the one to start it.
    fn spawn(spec: McpSpec, launch: McpLaunch) -> Result<Self, String> {
        let sandbox = launch
            .sandbox
            .as_ref()
            .ok_or("no sandbox on this machine, so no server is started")?;
        std::fs::create_dir_all(&launch.home)
            .map_err(|e| format!("cannot make its folder: {e}"))?;
        let mut argv = vec![spec.command.clone().into()];
        argv.extend(spec.args.iter().map(Into::into));
        let mut process = sandbox
            .command(&argv, &launch.home)
            .map_err(|e| e.to_string())?;
        process
            .env_clear()
            .env("PATH", std::env::var_os("PATH").unwrap_or_default())
            .env("HOME", &launch.home)
            .envs(spec.env.iter().map(|(k, v)| (k, v)))
            .current_dir(&launch.home)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            process.process_group(0);
        }
        let mut child = process
            .spawn()
            .map_err(|e| format!("cannot run `{}`: {e}", spec.command))?;
        let (Some(stdin), Some(stdout)) = (child.stdin.take(), child.stdout.take()) else {
            crate::bash::kill_tree(&mut child);
            return Err("no pipes".to_owned());
        };
        let (sender, lines) = mpsc::channel();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let Ok(line) = line else { break };
                if sender.send(line).is_err() {
                    break;
                }
            }
        });
        let server = Self {
            spec,
            launch,
            child,
            stdin,
            lines,
            next_id: 0,
            tools: Vec::new(),
        };
        Ok(server)
    }

    /// The handshake and the tool list; a server that fails it is stopped.
    fn ready(mut self) -> Result<Self, String> {
        match self.handshake() {
            Ok(()) => Ok(self),
            Err(e) => {
                self.stop();
                Err(e)
            }
        }
    }

    fn start(spec: McpSpec, launch: McpLaunch) -> Result<Self, String> {
        Self::spawn(spec, launch)?.ready()
    }

    fn handshake(&mut self) -> Result<(), String> {
        let limit = self.spec.start_timeout;
        self.request(
            "initialize",
            json!({"protocolVersion": PROTOCOL, "capabilities": {},
                   "clientInfo": {"name": "laris", "version": env!("CARGO_PKG_VERSION")}}),
            limit,
        )
        .map_err(|e| e.message)?;
        self.send(&json!({"jsonrpc": "2.0", "method": "notifications/initialized"}))
            .map_err(|e| e.message)?;
        let mut cursor: Option<String> = None;
        for _ in 0..20 {
            let params = cursor.as_ref().map_or(json!({}), |c| json!({"cursor": c}));
            let page = self
                .request("tools/list", params, limit)
                .map_err(|e| e.message)?;
            for tool in page
                .get("tools")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                if let Some(name) = tool.get("name").and_then(Value::as_str) {
                    self.tools.push((name.to_owned(), tool.clone()));
                }
            }
            cursor = page
                .get("nextCursor")
                .and_then(Value::as_str)
                .map(str::to_owned);
            if cursor.is_none() {
                break;
            }
        }
        Ok(())
    }

    fn send(&mut self, message: &Value) -> Result<(), ToolError> {
        let mut text = message.to_string();
        text.push('\n');
        self.stdin
            .write_all(text.as_bytes())
            .and_then(|()| self.stdin.flush())
            .map_err(|e| ToolError::io("remote_unavailable", "the MCP server is gone", &e))
    }

    /// One request and its answer; messages that are not that answer (notifications, logs) are skipped.
    fn request(
        &mut self,
        method: &str,
        params: Value,
        limit: Duration,
    ) -> Result<Value, ToolError> {
        self.next_id += 1;
        let id = self.next_id;
        self.send(&json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params}))?;
        let end = Instant::now() + limit;
        loop {
            let left = end.saturating_duration_since(Instant::now());
            let line = match self.lines.recv_timeout(left) {
                Ok(line) => line,
                Err(RecvTimeoutError::Timeout) => {
                    return Err(ToolError::new(
                        "timeout",
                        format!("the MCP server did not answer `{method}` in time"),
                    ));
                }
                Err(RecvTimeoutError::Disconnected) => {
                    return Err(ToolError::new("remote_unavailable", "the MCP server ended"));
                }
            };
            let Ok(message) = serde_json::from_str::<Value>(&line) else {
                continue;
            };
            if message.get("id") != Some(&json!(id)) || message.get("method").is_some() {
                continue;
            }
            if let Some(error) = message.get("error") {
                let text = error
                    .get("message")
                    .and_then(Value::as_str)
                    .unwrap_or("the MCP server refused the request");
                return Err(ToolError::new("mcp_error", text));
            }
            return Ok(message.get("result").cloned().unwrap_or(Value::Null));
        }
    }

    fn alive(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }

    fn stop(&mut self) {
        crate::bash::kill_tree(&mut self.child);
        self.child.wait().ok();
    }

    fn call(&mut self, tool: &str, arguments: &Args) -> Result<Value, ToolError> {
        let limit = self.spec.call_timeout;
        let result = self.request(
            "tools/call",
            json!({"name": tool, "arguments": arguments}),
            limit,
        )?;
        let mut text = String::new();
        for part in result
            .get("content")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            match part.get("type").and_then(Value::as_str) {
                Some("text") => {
                    if let Some(t) = part.get("text").and_then(Value::as_str) {
                        if !text.is_empty() {
                            text.push('\n');
                        }
                        text.push_str(t);
                    }
                }
                Some(other) => {
                    if !text.is_empty() {
                        text.push('\n');
                    }
                    text.push_str(&format!("[{other} content left out]"));
                }
                None => {}
            }
        }
        if result.get("isError") == Some(&Value::Bool(true)) {
            return Err(ToolError::new("mcp_tool_error", text));
        }
        Ok(json!({"content": text}))
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        self.stop();
    }
}

/// The tools of every started MCP server.
pub struct McpRemote {
    servers: Vec<Server>,
    /// Name the model sees → (server index, the server's own tool name).
    names: BTreeMap<String, (usize, String)>,
    schemas: Vec<ToolSchema>,
}

/// A tool-name part kept to letters, digits, `_` and `-`.
fn clean(part: &str) -> String {
    part.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '_' || c == '-' {
                c
            } else {
                '_'
            }
        })
        .collect()
}

impl McpRemote {
    /// Starts every server in `specs` at the same time and returns the bridge with what happened to each one.
    /// A spec with `Err` is a server that was skipped before starting, with the reason.
    pub fn start(
        specs: Vec<Result<McpSpec, McpStatus>>,
        launch: &McpLaunch,
    ) -> (Self, Vec<McpStatus>) {
        let mut statuses = Vec::new();
        let mut handles = Vec::new();
        for spec in specs {
            match spec {
                Err(status) => statuses.push(status),
                Ok(spec) => {
                    let name = spec.name.clone();
                    match Server::spawn(spec, launch.clone()) {
                        Ok(server) => {
                            handles.push((name, std::thread::spawn(move || server.ready())));
                        }
                        Err(why) => statuses.push(McpStatus {
                            name,
                            state: McpState::Failed(why),
                        }),
                    }
                }
            }
        }
        let mut remote = Self {
            servers: Vec::new(),
            names: BTreeMap::new(),
            schemas: Vec::new(),
        };
        for (name, handle) in handles {
            let state = match handle.join() {
                Ok(Ok(server)) => McpState::Running(remote.adopt(server)),
                Ok(Err(why)) => McpState::Failed(why),
                Err(_) => McpState::Failed("the start failed".to_owned()),
            };
            statuses.push(McpStatus { name, state });
        }
        statuses.sort_by(|a, b| a.name.cmp(&b.name));
        (remote, statuses)
    }

    /// Takes a started server and registers its tools; returns how many were taken.
    fn adopt(&mut self, server: Server) -> usize {
        let at = self.servers.len();
        let mut taken = 0;
        for (tool, definition) in &server.tools {
            let exposed = format!("mcp__{}__{}", clean(&server.spec.name), clean(tool));
            if self.names.contains_key(&exposed) {
                continue;
            }
            let description = definition
                .get("description")
                .and_then(Value::as_str)
                .unwrap_or("An MCP tool.");
            let mut parameters = definition
                .get("inputSchema")
                .cloned()
                .filter(Value::is_object)
                .unwrap_or_else(|| json!({"type": "object", "properties": {}}));
            if let Some(map) = parameters.as_object_mut() {
                map.remove("$schema");
            }
            self.schemas
                .push(function_schema(&exposed, description, parameters));
            self.names.insert(exposed, (at, tool.clone()));
            taken += 1;
        }
        self.servers.push(server);
        taken
    }

    /// Whether any server is running.
    pub fn is_empty(&self) -> bool {
        self.servers.is_empty()
    }
}

impl RemoteTools for McpRemote {
    fn schemas(&self) -> Vec<ToolSchema> {
        self.schemas.clone()
    }

    fn call(&mut self, name: &str, arguments: &Args) -> Result<Value, ToolError> {
        let Some((at, tool)) = self.names.get(name).cloned() else {
            return Err(ToolError::new(
                "unknown_tool",
                format!("unknown tool: {name}"),
            ));
        };
        let server = &mut self.servers[at];
        if !server.alive() {
            // one restart, then the failure is reported
            let spec = server.spec.clone();
            let launch = server.launch.clone();
            match Server::start(spec, launch) {
                Ok(fresh) => *server = fresh,
                Err(why) => return Err(ToolError::new("remote_unavailable", why)),
            }
        }
        let result = server.call(&tool, arguments);
        if matches!(&result, Err(e) if e.code == "timeout") {
            // a server stuck on one call would answer late and block the next; the next call starts it afresh
            server.stop();
        }
        result
    }
}
