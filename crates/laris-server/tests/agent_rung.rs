//! The Agent rung of the capability ladder (SR-S9, SR-H4), end to end and in one process: a project folder, the system
//! (the core loop, the permission gate and the real local tools, `Bash` inside the OS sandbox), the server (HTTP, the
//! policy gateway with the system brain, the scientific remote tools at `/v1/laris/tools/{name}`, content-free
//! traces) and a model that follows a script.
//!
//! One scenario mixes both kinds of tools: the brain (server side), `Read`, `Write` and `Bash` (local), and
//! `extract_discourse` and `normalize_quantities` (remote). The loop cannot tell local from remote tools; the traces
//! show tool names and nothing else.
//!
//! The model is scripted and the remote tools answer with the outputs recorded from the real tool box
//! (`crates/laris-protocol/tests/fixtures/scientific`; `tests/tools.rs` proves the real service reproduces them), so
//! this proves mechanics only. It says nothing about how well any model uses tools; the foundation model is NOT
//! QUALIFIED.
#![cfg(target_os = "linux")]

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
use laris_tools::{Context, Registry, RemoteTools, Scope, ToolError};
use serde_json::{Map, Value, json};
use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;
use tokio::net::TcpListener;

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn fixture(name: &str) -> Value {
    let path = repo()
        .join("crates/laris-protocol/tests/fixtures/scientific")
        .join(name);
    serde_json::from_str(&std::fs::read_to_string(path).expect("fixture")).expect("json")
}

/// The text of the extraction fixture: the project holds it as `paper.txt`.
fn paper() -> String {
    fixture("extract_discourse.request.json")["arguments"]["text"]
        .as_str()
        .expect("text")
        .to_owned()
}

/// Text that must appear in the project and the conversation and never in a trace row.
const REPORT: &str =
    "ZEBRA-REPORT-TEXT: the paper makes direct claims and states one limitation.\n";
const SHELL_MARK: &str = "NARWHAL-SHELL-TEXT";

// ---------------------------------------------------------------- the model and the tools behind the server

fn chunk(delta: Value, finish: Option<&str>) -> ChatResponseChunk {
    serde_json::from_value(json!({
        "id": "m1", "object": "chat.completion.chunk", "model": "scripted",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]
    }))
    .unwrap()
}

type Script = Vec<Result<ChatResponseChunk, StreamFailure>>;

fn calls(id: &str, name: &str, arguments: Value) -> Script {
    vec![
        Ok(chunk(
            json!({"tool_calls": [{"index": 0, "id": id, "type": "function",
            "function": {"name": name, "arguments": arguments.to_string()}}]}),
            None,
        )),
        Ok(chunk(json!({}), Some("tool_calls"))),
    ]
}

fn answer(text: &str) -> Script {
    vec![
        Ok(chunk(json!({"content": text}), None)),
        Ok(chunk(json!({}), Some("stop"))),
    ]
}

type Seen = Arc<Mutex<Vec<ChatRequest>>>;

/// The model service: the script for chat, and the recorded outputs for the scientific tools.
struct Scripted {
    scripts: Mutex<VecDeque<Script>>,
    seen: Seen,
    tool_hits: Arc<Mutex<Vec<String>>>,
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

struct Server {
    port: u16,
    seen: Seen,
    tool_hits: Arc<Mutex<Vec<String>>>,
    traces: Arc<MemoryTraces>,
    reasoning: Arc<MemoryReasoning>,
    _stop: tokio::sync::oneshot::Sender<()>,
}

async fn start(scripts: Vec<Script>) -> Server {
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
struct ServerModel {
    client: ModelClient<ReqwestTransport>,
    handle: tokio::runtime::Handle,
    wire: Arc<Mutex<String>>,
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
struct HttpRemote {
    base: String,
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
struct Yes {
    asked: Arc<Mutex<Vec<String>>>,
    answer_no: bool,
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
struct Tools {
    registry: Registry,
    ran: Arc<Mutex<Vec<String>>>,
}

impl ToolRunner for Tools {
    fn run(&mut self, name: &str, arguments: &Map<String, Value>) -> Value {
        self.ran.lock().unwrap().push(name.to_owned());
        self.registry.call(name, arguments)
    }
}

/// The helper binary of `laris-sandbox`, built on demand (a dependency's binary is not built by `cargo test`).
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

struct Project {
    base: PathBuf,
    root: PathBuf,
}

fn project(name: &str) -> Project {
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

struct Run {
    events: Vec<Event>,
    ran: Vec<String>,
    asked: Vec<String>,
    wire: String,
}

/// Drives one request through the loop: the gate, the local tools (`Bash` sandboxed), the remote tools, the server.
async fn ask(server: &Server, project: &Project, question: &str, approver: Yes) -> Run {
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
    let ctx = Context::new(&project.root, &settings)
        .unwrap()
        .with_sandbox(Arc::new(sandbox));
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
    let recorder = Recorder::open(store, "agent-rung", "agent", 1.0).unwrap().0;
    let decider = FollowModel::new(settings.agent, Catalogue::english()).with_gate(gate);
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

fn result_of<'a>(run: &'a Run, tool: &str) -> Vec<&'a Value> {
    run.events
        .iter()
        .filter_map(|e| match e {
            Event::ToolResult { name, result, .. } if name == tool => Some(result),
            _ => None,
        })
        .collect()
}

fn done_answer(events: &[Event]) -> &str {
    match events.last() {
        Some(Event::Done { answer, .. }) => answer,
        other => panic!("the turn must end with done, ended with {other:?}"),
    }
}

async fn trace_rows(server: &Server, at_least: usize) -> Vec<TraceRecord> {
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

const QUESTION: &str = "Summarise paper.txt and write the summary to report.md.";
const SUMMARY: &str = "The paper makes direct author claims, one limitation, and reports quantities \
     (see report.md, verified with the shell).";

fn script() -> Vec<Script> {
    let quantities = fixture("normalize_quantities.request.json")["arguments"].clone();
    vec![
        // the server's own steps: its brain, never seen by the client
        calls("b1", "use_system_brain", json!({"action": "index"})),
        calls(
            "b2",
            "use_system_brain",
            json!({"action": "read", "id": "Research QA Playbook"}),
        ),
        // the client's tools
        calls("l1", "Read", json!({"path": "paper.txt"})),
        calls(
            "r1",
            "extract_discourse",
            fixture("extract_discourse.request.json")["arguments"].clone(),
        ),
        calls("r2", "normalize_quantities", quantities),
        calls(
            "w1",
            "Write",
            json!({"path": "report.md", "content": REPORT}),
        ),
        // a denied path, a command inside the sandbox, a command that tries to leave it
        calls(
            "w2",
            "Write",
            json!({"path": "secret/key.txt", "content": "HYENA-DENIED-TEXT"}),
        ),
        calls(
            "s1",
            "Bash",
            json!({"command": format!("wc -c report.md && echo {SHELL_MARK}")}),
        ),
        calls(
            "s2",
            "Bash",
            json!({"command": "echo escaped > ../outside.txt; echo done"}),
        ),
        answer(SUMMARY),
    ]
}

// ---------------------------------------------------------------- the scenario

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn the_agent_rung_mixes_local_and_remote_tools_and_the_traces_hold_names_only() {
    let server = start(script()).await;
    let project = project("good");
    let run = ask(&server, &project, QUESTION, Yes::default()).await;

    // 1. the loop ran the client's tools, local and remote alike; the server's brain never reached it
    assert_eq!(
        run.ran,
        [
            "Read",
            "extract_discourse",
            "normalize_quantities",
            "Write",
            "Bash",
            "Bash"
        ],
        "the denied write never ran: the gate stopped it"
    );
    assert!(!run.wire.contains("use_system_brain"));
    for secret in ["Decide whether the question", "LARIS-CANARY", "<brain"] {
        assert!(!run.wire.contains(secret), "{secret} reached the client");
    }

    // 2. local tools did their work on the project
    let read = result_of(&run, "Read");
    assert!(read[0].to_string().contains("BiLSTM"));
    assert_eq!(
        std::fs::read_to_string(project.root.join("report.md")).unwrap(),
        REPORT
    );
    let bash = result_of(&run, "Bash");
    assert!(bash[0].to_string().contains(SHELL_MARK), "{}", bash[0]);
    assert!(bash[0].to_string().contains("report.md"));

    // 3. remote tools returned what the tool box recorded, marked untrusted like every remote result
    let extraction = result_of(&run, "extract_discourse");
    assert_eq!(extraction.len(), 1);
    let recorded = fixture("extract_discourse.response.json")["result"].clone();
    assert_eq!(extraction[0]["claims"], recorded["claims"]);
    assert_eq!(extraction[0]["untrusted"], true);
    assert!(!extraction[0]["claims"].as_array().unwrap().is_empty());
    let quantities = result_of(&run, "normalize_quantities");
    assert_eq!(
        quantities[0]["quantities"],
        fixture("normalize_quantities.response.json")["result"]["quantities"]
    );
    assert_eq!(
        *server.tool_hits.lock().unwrap(),
        ["extract_discourse", "normalize_quantities"]
    );

    // 4. the gate: reads were free; writes, commands and remote tools were asked about; the denied path was never
    //    written and the sandboxed command could not leave the project
    assert_eq!(
        run.asked,
        [
            "extract_discourse",
            "normalize_quantities",
            "Write",
            "Bash",
            "Bash"
        ]
    );
    let denied = result_of(&run, "Write");
    assert_eq!(denied[1]["error"]["code"], "permission_denied");
    assert!(!project.root.join("secret/key.txt").exists());
    assert!(
        !project.base.join("outside.txt").exists(),
        "the sandbox kept the command inside the project"
    );

    // 5. the model saw the tools' results, and the turn ended with its answer
    let sent = server.seen.lock().unwrap().clone();
    let offered: Vec<&str> = sent[2]
        .tools
        .iter()
        .map(|s| s.function.name.as_str())
        .collect();
    for name in [
        "Read",
        "Write",
        "Bash",
        "extract_discourse",
        "mine_literature",
    ] {
        assert!(
            offered.contains(&name),
            "{name} was not offered: {offered:?}"
        );
    }
    let after_remote = serde_json::to_string(&sent[4].messages).unwrap();
    assert!(
        after_remote.contains("claim_id"),
        "the model saw the extraction"
    );
    assert_eq!(done_answer(&run.events), SUMMARY);

    // 6. traces: one row per request, tool names only, nothing from any content
    let rows = trace_rows(&server, 10).await;
    let chat: Vec<&TraceRecord> = rows.iter().filter(|r| r.route == "chat").collect();
    // the list of tools is a request of its own and names nothing; each remote call is one row with its name
    let listing: Vec<&TraceRecord> = rows
        .iter()
        .filter(|r| r.route == "tools" && r.tools.is_empty())
        .collect();
    assert_eq!(listing.len(), 1);
    let tools_rows: Vec<&TraceRecord> = rows
        .iter()
        .filter(|r| r.route == "tools" && !r.tools.is_empty())
        .collect();
    let names: Vec<Vec<&str>> = chat
        .iter()
        .map(|r| r.tools.iter().map(String::as_str).collect())
        .collect();
    assert_eq!(
        names,
        [
            vec!["Read"],
            vec!["extract_discourse"],
            vec!["normalize_quantities"],
            vec!["Write"],
            vec!["Write"],
            vec!["Bash"],
            vec!["Bash"],
            vec![]
        ],
        "the model's calls to client tools, one request each"
    );
    assert_eq!(
        tools_rows.len(),
        2,
        "one row for each remote call, plus none for the rest"
    );
    assert_eq!(tools_rows[0].tools, ["extract_discourse"]);
    assert_eq!(tools_rows[1].tools, ["normalize_quantities"]);
    assert!(
        chat[0].brain.contains(&"Research QA Playbook".to_owned()),
        "the first request names the notes it drew on: {:?}",
        chat[0].brain
    );
    assert!(rows.iter().all(|r| r.status == 200 && r.outcome == "ok"));
    let dump = format!("{rows:?}");
    for text in [
        "BiLSTM",
        "ZEBRA-REPORT-TEXT",
        SHELL_MARK,
        "HYENA-DENIED-TEXT",
        "report.md",
        "paper.txt",
        "outside.txt",
        "claim_id",
        "Decide whether the question",
        "Summarise",
        "verified with the shell",
    ] {
        assert!(!dump.contains(text), "{text} is in a trace row: {dump}");
    }
    let record = server.reasoning.newest(5);
    assert!(
        record
            .iter()
            .any(|r| r.brain.contains(&"Research QA Playbook".to_owned()))
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_call_nobody_approved_never_leaves_the_machine() {
    let server = start(vec![
        calls(
            "r1",
            "extract_discourse",
            fixture("extract_discourse.request.json")["arguments"].clone(),
        ),
        calls(
            "w1",
            "Write",
            json!({"path": "report.md", "content": REPORT}),
        ),
        answer("I could not run anything: nothing was approved."),
    ])
    .await;
    let project = project("denied");
    let no = Yes {
        answer_no: true,
        ..Yes::default()
    };
    let run = ask(&server, &project, QUESTION, no).await;
    assert!(run.ran.is_empty(), "{:?}", run.ran);
    assert_eq!(run.asked, ["extract_discourse", "Write"]);
    assert!(server.tool_hits.lock().unwrap().is_empty());
    assert!(!project.root.join("report.md").exists());
    let refused = result_of(&run, "extract_discourse");
    assert_eq!(refused[0]["error"]["code"], "approval_denied");
    let rows = trace_rows(&server, 3).await;
    assert!(
        rows.iter()
            .all(|r| r.route != "tools" || r.tools.is_empty()),
        "only the list of tools was asked of the server: {rows:?}"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_remote_tool_that_refuses_is_a_typed_result_and_the_loop_goes_on() {
    // arguments that differ from the recorded ones: the tool box refuses, the loop gets an error result
    let server = start(vec![
        calls(
            "r1",
            "extract_discourse",
            json!({"text": "A claim we make here.", "document_id": "other"}),
        ),
        answer("The extraction refused my input; I report that and stop."),
    ])
    .await;
    let project = project("refused");
    let run = ask(&server, &project, QUESTION, Yes::default()).await;
    let result = result_of(&run, "extract_discourse");
    assert_eq!(result[0]["error"]["code"], "invalid_arguments");
    assert_eq!(result[0]["untrusted"], true);
    assert_eq!(
        done_answer(&run.events),
        "The extraction refused my input; I report that and stop."
    );
    let rows = trace_rows(&server, 3).await;
    let tools: Vec<_> = rows
        .iter()
        .filter(|r| r.route == "tools" && !r.tools.is_empty())
        .collect();
    assert_eq!(tools.len(), 1);
    assert_eq!(tools[0].tools, ["extract_discourse"]);
    assert!(!format!("{rows:?}").contains("A claim we make here"));
}
