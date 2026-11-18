//! The harness of the capability-ladder suites over the whole stack, in one process: a project folder, the system (the
//! core loop, the permission gate and the real local tools, `Bash` inside the OS sandbox), the server (HTTP, the
//! policy gateway with the system brain, the scientific remote tools at `/v1/laris/tools/{name}`, content-free
//! traces) and a model that follows a script. Used by `agent_rung.rs` and `agentic_rung.rs`.
#![allow(dead_code)]

use futures_util::future::BoxFuture;
use futures_util::{StreamExt, stream};
use laris_config::settings::Permissions;
use laris_config::{Catalogue, Settings};
use laris_core::{
    Driver, FollowModel, Model, ModelAnswer, ModelError, ModelRequest, Recorder, ToolRunner,
};
use laris_model_client::{
    ClientConfig, HttpOptions, Interrupt, ModelClient, ReqwestTransport, Trust,
};
use laris_policy::{
    Answer, ApprovalRequest, Approver, Engine, PolicyGate, ProjectState, writes_of,
};
use laris_protocol::chat::ToolCall;
use laris_protocol::events::Event;
use laris_protocol::p1::{
    ChatRequest, ChatResponseChunk, EmbedRequest, EmbedResponse, LarisMeta, ToolList, ToolRequest,
    ToolResponse,
};
use laris_protocol::sse::P1Event;
use laris_sandbox::{Backend as SandboxBackend, Policy as SandboxPolicy, Sandbox};
use laris_server::policy::{MemoryReasoning, Policy, PolicyConfig, PolicyGateway};
use laris_server::trace::{MemoryTraces, TraceRecord};
use laris_server::{
    ApiError, AppState, Backend, ChunkStream, MemorySink, ServerConfig, StreamFailure, serve,
};
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use laris_tools::knowledge::Knowledge;
use laris_tools::project_vault::ProjectVault;
use laris_tools::{Context, Registry, RemoteTools, Scope, ToolError};
use laris_vault::schema::Schema;
use laris_vault::writer::WriterLimits;
use serde_json::{Map, Value, json};
use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;
use tokio::net::TcpListener;

pub fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

pub fn fixture(name: &str) -> Value {
    let path = repo()
        .join("crates/laris-protocol/tests/fixtures/scientific")
        .join(name);
    serde_json::from_str(&std::fs::read_to_string(path).expect("fixture")).expect("json")
}

/// The text of the extraction fixture: the project holds it as `paper.txt`.
pub fn paper() -> String {
    fixture("extract_discourse.request.json")["arguments"]["text"]
        .as_str()
        .expect("text")
        .to_owned()
}

/// Text that must appear in the project and the conversation and never in a trace row.
pub const REPORT: &str =
    "ZEBRA-REPORT-TEXT: the paper makes direct claims and states one limitation.\n";
pub const SHELL_MARK: &str = "NARWHAL-SHELL-TEXT";

// ---------------------------------------------------------------- the model and the tools behind the server

pub fn chunk(delta: Value, finish: Option<&str>) -> ChatResponseChunk {
    serde_json::from_value(json!({
        "id": "m1", "object": "chat.completion.chunk", "model": "scripted",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]
    }))
    .unwrap()
}

pub type Script = Vec<Result<ChatResponseChunk, StreamFailure>>;

pub fn calls(id: &str, name: &str, arguments: Value) -> Script {
    vec![
        Ok(chunk(
            json!({"tool_calls": [{"index": 0, "id": id, "type": "function",
            "function": {"name": name, "arguments": arguments.to_string()}}]}),
            None,
        )),
        Ok(chunk(json!({}), Some("tool_calls"))),
    ]
}

pub fn answer(text: &str) -> Script {
    vec![
        Ok(chunk(json!({"content": text}), None)),
        Ok(chunk(json!({}), Some("stop"))),
    ]
}

pub type Seen = Arc<Mutex<Vec<ChatRequest>>>;

/// The model service: the script for chat, and the recorded outputs for the scientific tools.
pub struct Scripted {
    scripts: Mutex<VecDeque<Script>>,
    pub seen: Seen,
    pub tool_hits: Arc<Mutex<Vec<String>>>,
}

impl Backend for Scripted {
    fn chat(&self, request: ChatRequest) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        self.seen.lock().unwrap().push(request);
        let next = self
            .scripts
            .lock()
            .unwrap()
            .pop_front()
            .unwrap_or_else(|| answer("(script ended)"));
        Box::pin(async move { Ok(stream::iter(next).boxed()) })
    }

    fn embed(&self, _r: EmbedRequest) -> BoxFuture<'static, Result<EmbedResponse, ApiError>> {
        Box::pin(async { Err(ApiError::BadGateway("no embed".into())) })
    }

    fn tools(&self) -> BoxFuture<'static, Result<ToolList, ApiError>> {
        Box::pin(async { Ok(serde_json::from_value(fixture("tools.list.json")).unwrap()) })
    }

    fn tool(
        &self,
        name: String,
        request: ToolRequest,
    ) -> BoxFuture<'static, Result<ToolResponse, ApiError>> {
        self.tool_hits.lock().unwrap().push(name.clone());
        Box::pin(async move {
            let recorded = repo()
                .join("crates/laris-protocol/tests/fixtures/scientific")
                .join(format!("{name}.request.json"));
            let Ok(text) = std::fs::read_to_string(recorded) else {
                return Err(ApiError::NotFound);
            };
            let wanted: ToolRequest = serde_json::from_str(&text).unwrap();
            if wanted.arguments != request.arguments {
                return Ok(serde_json::from_value(
                    json!({"error": {"message": "arguments differ from the recorded ones", "type": "invalid_arguments"}}),
                )
                .unwrap());
            }
            Ok(serde_json::from_value(fixture(&format!("{name}.response.json"))).unwrap())
        })
    }
}

pub struct Server {
    pub port: u16,
    pub seen: Seen,
    pub tool_hits: Arc<Mutex<Vec<String>>>,
    pub traces: Arc<MemoryTraces>,
    pub reasoning: Arc<MemoryReasoning>,
    pub _stop: tokio::sync::oneshot::Sender<()>,
}

pub async fn start(scripts: Vec<Script>) -> Server {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let mut cfg = ServerConfig::with_bind(addr);
    cfg.stream_idle = Duration::from_secs(5);
    let policy = Arc::new(
        Policy::load(&PolicyConfig::with_root(repo()), std::iter::empty(), None)
            .expect("the repository policy loads"),
    );
    let seen: Seen = Arc::default();
    let tool_hits: Arc<Mutex<Vec<String>>> = Arc::default();
    let reasoning = Arc::new(MemoryReasoning::new(20));
    let traces = Arc::new(MemoryTraces::default());
    let model = Scripted {
        scripts: Mutex::new(scripts.into()),
        seen: seen.clone(),
        tool_hits: tool_hits.clone(),
    };
    let backend = Arc::new(PolicyGateway::new(
        policy.clone(),
        Arc::new(model),
        reasoning.clone(),
    ));
    let state = AppState::open(cfg, backend)
        .with_policy(policy, reasoning.clone())
        .with_traces(traces.clone());
    let (tx, rx) = tokio::sync::oneshot::channel::<()>();
    tokio::spawn(async move {
        let _ = serve(
            listener,
            Arc::new(state),
            Arc::new(MemorySink::default()),
            async {
                let _ = rx.await;
            },
        )
        .await;
    });
    Server {
        port: addr.port(),
        seen,
        tool_hits,
        traces,
        reasoning,
        _stop: tx,
    }
}

// ---------------------------------------------------------------- the system side

/// The loop's model: every call is a P1 chat request to the server.
pub struct ServerModel {
    client: ModelClient<ReqwestTransport>,
    handle: tokio::runtime::Handle,
    pub wire: Arc<Mutex<String>>,
}

impl Model for ServerModel {
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        let body = json!({
            "messages": request.messages,
            "tools": request.tools,
            "stream": true,
            "laris": {"kind": "turn", "session_id": "agent-rung"},
        });
        let chat: ChatRequest =
            serde_json::from_value(body).map_err(|e| ModelError::Failed(e.to_string()))?;
        let (client, wire) = (&self.client, &self.wire);
        tokio::task::block_in_place(|| {
            self.handle.block_on(async {
                let mut stream = client
                    .chat(&chat, &Interrupt::new())
                    .await
                    .map_err(|e| ModelError::Failed(e.to_string()))?;
                let mut out = ModelAnswer::default();
                while let Some(event) = stream
                    .next()
                    .await
                    .map_err(|e| ModelError::Failed(e.to_string()))?
                {
                    match event {
                        P1Event::Chunk(c) => {
                            wire.lock()
                                .unwrap()
                                .push_str(&serde_json::to_string(&c).unwrap());
                            let _: &Option<LarisMeta> = &c.laris;
                            for choice in c.choices {
                                if let Some(t) = choice.delta.content {
                                    out.text.push_str(&t);
                                }
                                out.tool_calls
                                    .extend::<Vec<ToolCall>>(choice.delta.tool_calls);
                            }
                            if c.usage.is_some() {
                                out.usage = c.usage;
                            }
                        }
                        P1Event::Error(e) => return Err(ModelError::Failed(e.error.message)),
                        P1Event::Done => break,
                    }
                }
                Ok(out)
            })
        })
    }
}

/// The scientific tools of the server as the registry sees a remote source: the list comes from `GET /v1/laris/tools`,
/// a call is `POST /v1/laris/tools/{name}` with the arguments only.
pub struct HttpRemote {
    pub base: String,
    http: reqwest::Client,
    handle: tokio::runtime::Handle,
    list: ToolList,
}

impl HttpRemote {
    async fn connect(port: u16) -> Self {
        let base = format!("http://127.0.0.1:{port}/v1/laris/tools");
        let http = reqwest::Client::new();
        let list: ToolList = http
            .get(&base)
            .header("X-Laris-Protocol", "1")
            .send()
            .await
            .expect("the list of tools")
            .json()
            .await
            .expect("a tool list");
        Self {
            base,
            http,
            handle: tokio::runtime::Handle::current(),
            list,
        }
    }
}

impl RemoteTools for HttpRemote {
    fn schemas(&self) -> Vec<laris_protocol::ToolSchema> {
        self.list.tools.clone()
    }

    fn call(&mut self, name: &str, arguments: &Map<String, Value>) -> Result<Value, ToolError> {
        let url = format!("{}/{name}", self.base);
        let body = json!({"arguments": arguments});
        let (status, text) = tokio::task::block_in_place(|| {
            self.handle.block_on(async {
                let r = self
                    .http
                    .post(&url)
                    .header("X-Laris-Protocol", "1")
                    .json(&body)
                    .send()
                    .await
                    .map_err(|e| ToolError::new("remote_unavailable", e.to_string()))?;
                let status = r.status().as_u16();
                let text = r
                    .text()
                    .await
                    .map_err(|e| ToolError::new("remote_unavailable", e.to_string()))?;
                Ok::<_, ToolError>((status, text))
            })
        })?;
        if status != 200 {
            return Err(ToolError::new(
                "remote_unavailable",
                format!("the server answered {status}"),
            ));
        }
        let response: ToolResponse = serde_json::from_str(&text)
            .map_err(|e| ToolError::new("remote_unavailable", e.to_string()))?;
        match (response.result, response.error) {
            (Some(result), None) => Ok(result),
            (None, Some(error)) => Err(ToolError::new(
                error.kind.as_deref().unwrap_or("remote_error"),
                error.message,
            )),
            _ => Err(ToolError::new("remote_unavailable", "an empty answer")),
        }
    }
}

/// The gate's approver: says yes once and keeps everything it was asked.
#[derive(Clone, Default)]
pub struct Yes {
    pub asked: Arc<Mutex<Vec<String>>>,
    pub answer_no: bool,
}

impl Approver for Yes {
    fn approve(&self, request: &ApprovalRequest) -> Answer {
        self.asked.lock().unwrap().push(request.tool.clone());
        if self.answer_no {
            Answer::Deny
        } else {
            Answer::Once
        }
    }
}

/// The real tools behind the permission gate, and a note of every call that ran.
pub struct Tools {
    registry: Registry,
    pub ran: Arc<Mutex<Vec<String>>>,
}

impl ToolRunner for Tools {
    fn run(&mut self, name: &str, arguments: &Map<String, Value>) -> Value {
        self.ran.lock().unwrap().push(name.to_owned());
        self.registry.call(name, arguments)
    }
}

/// The helper binary of `laris-sandbox`, built on demand (a dependency's binary is not built by `cargo test`).
pub fn helper() -> PathBuf {
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

pub struct Project {
    pub base: PathBuf,
    pub root: PathBuf,
}

pub fn project(name: &str) -> Project {
    let base = std::env::temp_dir().join(format!("laris-agent-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&base);
    let root = base.join("project");
    std::fs::create_dir_all(root.join("secret")).unwrap();
    std::fs::write(root.join("paper.txt"), paper()).unwrap();
    let base = base.canonicalize().unwrap();
    Project {
        root: base.join("project"),
        base,
    }
}

pub struct Run {
    pub events: Vec<Event>,
    pub ran: Vec<String>,
    pub asked: Vec<String>,
    pub wire: String,
}

/// What differs between the scenarios of a rung.
#[derive(Clone)]
pub struct Options {
    /// The session in the loop's store; the same id in a later call resumes it.
    pub session: String,
    /// The loop's limits.
    pub agent: laris_config::settings::Agent,
    /// Give the project a vault (`vault/`) and a database, so `write_vault_note` works.
    pub vault: bool,
    /// Give the project a memory folder (`.laris/memory`), so `save_memory` works.
    pub memory: bool,
}

impl Default for Options {
    fn default() -> Self {
        Self {
            session: "agent-rung".into(),
            agent: laris_config::settings::Agent::default(),
            vault: false,
            memory: false,
        }
    }
}

/// Drives one request through the loop: the gate, the local tools (`Bash` sandboxed), the remote tools, the server.
pub async fn ask(server: &Server, project: &Project, question: &str, approver: Yes) -> Run {
    ask_with(server, project, question, approver, &Options::default()).await
}

/// [`ask`] with options.
pub async fn ask_with(
    server: &Server,
    project: &Project,
    question: &str,
    approver: Yes,
    options: &Options,
) -> Run {
    let transport = ReqwestTransport::new(&HttpOptions {
        connect_timeout: Duration::from_secs(5),
        trust: Trust::System,
        use_env_proxy: false,
    })
    .unwrap();
    let client = ModelClient::new(
        transport,
        ClientConfig {
            base_url: format!("http://127.0.0.1:{}/v1", server.port),
            api_key: None,
            request_timeout: Duration::from_secs(10),
            idle_timeout: Duration::from_secs(10),
            max_retries: 0,
            backoff_base: Duration::from_millis(10),
            backoff_max: Duration::from_millis(10),
            max_body_bytes: 1 << 20,
        },
    )
    .unwrap();

    let settings = Settings::default();
    let backend = if laris_sandbox::sandbox::bwrap_works() {
        SandboxBackend::Bubblewrap
    } else {
        SandboxBackend::Landlock
    };
    let sandbox = Sandbox::with_backend(
        SandboxPolicy::workspace([project.root.clone()]),
        backend,
        Some(helper()),
    )
    .expect("sandbox");
    let mut ctx = Context::new(&project.root, &settings)
        .unwrap()
        .with_sandbox(Arc::new(sandbox));
    if options.vault {
        let limits = WriterLimits {
            max_chars: 60_000,
            backup: true,
            max_writes_per_minute: 0,
        };
        let (vault, _) =
            ProjectVault::init(&project.root.join("vault"), Schema::builtin(), limits).unwrap();
        let store = Store::open(
            project.base.join("space/local.sqlite"),
            DEFAULT_BUSY_TIMEOUT,
        )
        .unwrap();
        ctx = ctx.with_knowledge(Knowledge { vault, store });
    }
    if options.memory {
        ctx = ctx.with_memory_dir(project.root.join(".laris/memory"));
    }
    let mut registry = Registry::with_local_tools(ctx);
    registry
        .add_remote(Box::new(HttpRemote::connect(server.port).await))
        .unwrap();

    // `Read` is free, a write into `secret/` is denied, everything else that changes state is asked about
    let permissions = Permissions {
        allow: vec!["Read".into()],
        deny: vec!["Write(secret/**)".into()],
        ..Permissions::default()
    };
    let home = project.base.join("home");
    std::fs::create_dir_all(&home).unwrap();
    let scope = Scope::new(&project.root, &[], &settings.tools.denied_files).unwrap();
    let engine = Arc::new(Engine::new(
        permissions,
        scope,
        ProjectState::new(&home, &project.root),
        Some(home.join("settings.json")),
        false,
    ));
    let asked = approver.asked.clone();
    let gate = PolicyGate::new(engine, writes_of(&registry), approver);
    let offered = registry.schemas();

    let wire: Arc<Mutex<String>> = Arc::default();
    let ran: Arc<Mutex<Vec<String>>> = Arc::default();
    let model = ServerModel {
        client,
        handle: tokio::runtime::Handle::current(),
        wire: wire.clone(),
    };
    let tools = Tools {
        registry,
        ran: ran.clone(),
    };
    let store = Store::open(project.base.join("loop.sqlite"), DEFAULT_BUSY_TIMEOUT).unwrap();
    let recorder = Recorder::open(store, &options.session, "agent", 1.0)
        .unwrap()
        .0;
    let decider = FollowModel::new(options.agent.clone(), Catalogue::english()).with_gate(gate);
    let mut driver = Driver::new(recorder, model, tools, decider, offered, || 1.0);
    let events = tokio::task::block_in_place(|| driver.send(question)).unwrap();
    drop(driver);
    let wire_text = wire.lock().unwrap().clone();
    let ran_tools = ran.lock().unwrap().clone();
    let asked_tools = asked.lock().unwrap().clone();
    Run {
        events,
        ran: ran_tools,
        asked: asked_tools,
        wire: wire_text,
    }
}

pub fn result_of<'a>(run: &'a Run, tool: &str) -> Vec<&'a Value> {
    run.events
        .iter()
        .filter_map(|e| match e {
            Event::ToolResult { name, result, .. } if name == tool => Some(result),
            _ => None,
        })
        .collect()
}

pub fn done_answer(events: &[Event]) -> &str {
    match events.last() {
        Some(Event::Done { answer, .. }) => answer,
        other => panic!("the turn must end with done, ended with {other:?}"),
    }
}

pub async fn trace_rows(server: &Server, at_least: usize) -> Vec<TraceRecord> {
    for _ in 0..100 {
        let rows = server.traces.records();
        if rows.len() >= at_least {
            return rows;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    panic!(
        "expected {at_least} traces, got {:?}",
        server.traces.records()
    );
}
