//! The parts of a real run: the server for the model and the remote tools, the local tools in their sandbox, and
//! every guard the loop has (redaction, injection shield, hooks, permissions, the prompt layers).

use super::run::{
    Console, Setup, engine, execute, open_session, read_request, refuse, refuse_login,
};
use super::server::{HttpRemote, ServerModel, runtime};
use super::{Options, exit};
use crate::login::{Reason, Startup, connect, decide};
use crate::start::Started;
use laris_config::Catalogue;
use laris_core::ToolRunner;
use laris_model_client::ApiKey;
use laris_policy::{
    Approver, Engine, HookRunner, HookedRunner, PinBoard, PolicyGate, Prompted, RedactingModel,
    Redactor, Shield, ShieldedRunner, Sources, mode_name, skill_dirs, writes_of,
};
use laris_protocol::ToolSchema;
use laris_protocol::events::LoginReason;
use laris_sandbox::{Policy as SandboxPolicy, Sandbox};
use laris_store::slug_of;
use laris_tools::{Context, McpLaunch, McpRemote, McpSpec, McpState, McpStatus, Registry, Scope};
use serde_json::{Map, Value};
use std::cell::RefCell;
use std::io::Read;
use std::rc::Rc;
use std::sync::Arc;

/// The registry the loop runs tools on, which the interface also reaches for `/rewind` and `!command`.
#[derive(Clone)]
pub struct SharedRegistry(pub Rc<RefCell<Registry>>);

impl ToolRunner for SharedRegistry {
    fn run(&mut self, name: &str, arguments: &Map<String, Value>) -> Value {
        self.0.borrow_mut().call(name, arguments)
    }
}

/// The model of a real run.
pub type RealModel = Prompted<RedactingModel<ServerModel>>;
/// The tools of a real run.
pub type RealTools = HookedRunner<ShieldedRunner<SharedRegistry>>;

/// Why the parts could not be built: a code for events and messages, the text, and the exit code of a headless run.
#[derive(Debug)]
pub struct BuildError {
    /// Short code.
    pub code: &'static str,
    /// What is wrong.
    pub message: String,
    /// The exit code a headless run ends with.
    pub exit: u8,
}

/// Everything a run needs once the key is known: the model, the guarded tools, the gate.
pub struct Built {
    /// The model, talking to the server.
    pub model: RealModel,
    /// The tools, behind hooks and the injection shield.
    pub tools: RealTools,
    /// The tools offered to the model.
    pub schemas: Vec<ToolSchema>,
    /// The permission gate.
    pub gate: PolicyGate,
    /// The permission engine, for changing the mode.
    pub engine: Arc<Engine>,
    /// The mode's name.
    pub mode: String,
    /// The registry, shared with the interface.
    pub registry: SharedRegistry,
    /// What the machine lacks (no sandbox, no remote tools): worth a line to the user.
    pub warnings: Vec<String>,
    /// What became of each MCP server (`/mcp`).
    pub mcp: Vec<McpStatus>,
}

/// Starts the MCP servers of the settings (SR-H12), each inside a sandbox that has a network and may write only to
/// its own folder under the home folder. Servers that cannot start are reported, never fatal.
fn start_mcp(
    started: &Started,
    registry: &mut Registry,
    warnings: &mut Vec<String>,
) -> Vec<McpStatus> {
    let settings = &started.settings.mcp;
    if !settings.enabled {
        return Vec::new();
    }
    let home = started.home.root().join("mcp");
    let sandbox = match Sandbox::detect(
        SandboxPolicy::workspace([home.clone()]).with_network(true),
        None,
    ) {
        Ok(sandbox) => Some(Arc::new(sandbox)),
        Err(e) => {
            warnings.push(format!("MCP servers are not started: {e}"));
            None
        }
    };
    let specs: Vec<Result<McpSpec, McpStatus>> = settings
        .servers
        .iter()
        .map(|(name, server)| {
            let status = |state| McpStatus {
                name: name.clone(),
                state,
            };
            if !server.enabled || server.command.is_empty() {
                return Err(status(McpState::Skipped("disabled".to_owned())));
            }
            let mut env = Vec::new();
            for var in &server.env {
                let value = started
                    .env
                    .iter()
                    .find(|(k, _)| k == var)
                    .map(|(_, v)| v.clone())
                    .or_else(|| std::env::var(var).ok())
                    .filter(|v| !v.is_empty());
                match value {
                    Some(value) => env.push((var.clone(), value)),
                    None => {
                        return Err(status(McpState::Skipped(format!("{var} is not set"))));
                    }
                }
            }
            Ok(McpSpec {
                name: name.clone(),
                command: server.command.clone(),
                args: server.args.clone(),
                env,
                start_timeout: std::time::Duration::from_secs(server.start_timeout_seconds),
                call_timeout: std::time::Duration::from_secs(server.call_timeout_seconds),
            })
        })
        .collect();
    let (remote, statuses) = McpRemote::start(specs, &McpLaunch { sandbox, home });
    if !remote.is_empty()
        && let Err(e) = registry.add_remote(Box::new(remote))
    {
        warnings.push(format!("MCP tools left out: {e}"));
    }
    statuses
}

/// Builds the parts of a run for `session_id` against the server with `key`. `approver` answers calls that need
/// approval (nobody, for a headless run).
pub fn build(
    started: &Started,
    options: &Options,
    key: &ApiKey,
    session_id: &str,
    approver: impl Approver + 'static,
    progress: Option<std::rc::Rc<dyn Fn(laris_protocol::Event)>>,
) -> Result<Built, BuildError> {
    let fail = |code: &'static str, message: String, exit: u8| BuildError {
        code,
        message,
        exit,
    };
    let mut warnings = Vec::new();
    let runtime = runtime().map_err(|m| fail("runtime", m, exit::FAILED))?;
    let client = connect(&started.settings.server, key, true).map_err(|e| {
        fail(
            "server_unusable",
            format!("cannot reach the server: {e}"),
            exit::FAILED,
        )
    })?;
    let client = Arc::new(client);

    let redactor = Arc::new(Redactor::from_process_env().with_secrets([key.expose().to_owned()]));
    let shield = Arc::new(Shield::new(Arc::clone(&redactor)));
    let engine_state = laris_policy::ProjectState::new(started.home.root(), &started.project);

    let mut ctx = Context::new(&started.project, &started.settings)
        .map_err(|e| fail("tools_unusable", e.to_string(), exit::FAILED))?;
    let scope: Scope = ctx.scope.clone();
    let space = started.home.projects_dir().join(slug_of(&started.project));
    ctx = ctx
        .with_checkpoints(space.join("checkpoints"))
        .with_memory_dir(started.project_folder().path().join("memory"))
        .with_skill_dirs(skill_dirs(
            started.home.root(),
            &started.project,
            &engine_state,
        ))
        .with_redactor(redactor.for_tools());
    let web = &started.settings.web;
    if web.enabled {
        let options = laris_model_client::WebOptions {
            timeout: std::time::Duration::from_secs(web.timeout_seconds),
            max_bytes: usize::try_from(web.max_bytes).unwrap_or(usize::MAX),
            max_redirects: web.max_redirects,
            user_agent: web.user_agent.clone(),
        };
        match laris_model_client::WebClient::new(options) {
            Ok(client) => {
                ctx = ctx.with_web(Arc::new(super::web::WebBridge {
                    client,
                    runtime: Arc::clone(&runtime),
                }));
            }
            Err(e) => warnings.push(format!("web tools left out: {}", e.message)),
        }
    }
    match Sandbox::detect(SandboxPolicy::workspace([started.project.clone()]), None) {
        Ok(sandbox) => ctx = ctx.with_sandbox(Arc::new(sandbox)),
        Err(e) => warnings.push(format!(
            "commands run without a sandbox on this machine: {e}"
        )),
    }
    let mut registry = Registry::with_local_tools(ctx);
    match HttpRemote::connect(Arc::clone(&client), Arc::clone(&runtime)) {
        Ok(remote) => {
            if let Err(e) = registry.add_remote(Box::new(remote)) {
                warnings.push(format!("remote tools left out: {e}"));
            }
        }
        Err(e) => warnings.push(format!("remote tools left out: {e}")),
    }

    let mcp = start_mcp(started, &mut registry, &mut warnings);

    let engine =
        Arc::new(engine(started, options, scope).map_err(|m| fail("usage", m, exit::USAGE))?);
    let mode = mode_name(engine.mode()).to_owned();
    let hooks = Arc::new(HookRunner::new(
        &started.settings,
        &started.project,
        session_id,
    ));
    let schemas = registry.schemas();
    let gate = PolicyGate::new(Arc::clone(&engine), writes_of(&registry), approver)
        .with_hooks(Arc::clone(&hooks))
        .with_shield(Arc::clone(&shield));
    let shared = SharedRegistry(Rc::new(RefCell::new(registry)));
    let tools = HookedRunner::new(
        ShieldedRunner::new(shared.clone(), Arc::clone(&shield)),
        hooks,
    )
    .with_shield(shield);

    let model = Prompted::new(
        RedactingModel::new(
            {
                let model = ServerModel::new(client, runtime, session_id);
                match progress {
                    Some(p) => model.with_progress(p),
                    None => model,
                }
            },
            redactor,
        ),
        Sources {
            home: started.home.root().to_path_buf(),
            project_root: started.project.clone(),
            state: engine_state,
            extra_instructions: started.settings.extra_instructions.clone(),
        },
        started.settings.context.clone(),
        PinBoard::new(),
    );
    Ok(Built {
        model,
        tools,
        schemas,
        gate,
        engine,
        mode,
        registry: shared,
        warnings,
        mcp,
    })
}

/// Runs `options` against the real server. `input` is standard input when it is a pipe or a file, `None` for a
/// terminal. Returns the exit code.
pub fn run(
    started: &Started,
    options: &Options,
    input: Option<&mut dyn Read>,
    mut console: Console,
) -> u8 {
    let words = Catalogue::new(started.settings.ui.language);
    let format = options.format;
    let request = match read_request(started, options.prompt.as_deref(), input) {
        Ok(request) => request,
        Err(message) => return refuse(&mut console, format, "usage", &message, exit::USAGE),
    };
    let (server, key) = match decide(&started.home, &started.settings, &started.env) {
        Startup::Ready { server, key, .. } => (server, key),
        Startup::NoServer => {
            let message = words.get("headless.no_server", &[]).unwrap_or_default();
            return refuse_login(&mut console, format, LoginReason::NoServer, "", &message);
        }
        Startup::NeedsLogin { server, reason } => {
            let message = words
                .get("headless.login_required", &[("server", &server)])
                .unwrap_or_default();
            let why = match reason {
                Reason::FirstRun | Reason::OtherServer(_) => LoginReason::NoKey,
                Reason::Unreadable(_) => LoginReason::Invalid,
            };
            return refuse_login(&mut console, format, why, &server, &message);
        }
    };
    let session = match open_session(started, options, &mut console) {
        Ok(session) => session,
        Err(code) => return code,
    };
    let built = match build(
        started,
        options,
        &key,
        &session.id,
        laris_policy::NoApprover,
        None,
    ) {
        Ok(built) => built,
        Err(e) => return refuse(&mut console, format, e.code, &e.message, e.exit),
    };
    for warning in &built.warnings {
        let _ = writeln!(console.err, "laris: {warning}");
    }
    let setup = Setup { started, server };
    execute(
        &setup,
        options,
        &request,
        built.model,
        built.tools,
        built.schemas,
        built.gate,
        &built.mode,
        session,
        console,
    )
}
