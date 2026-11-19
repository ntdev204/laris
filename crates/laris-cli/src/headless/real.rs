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
use laris_policy::{
    HookRunner, HookedRunner, PinBoard, PolicyGate, Prompted, RedactingModel, Redactor, Shield,
    ShieldedRunner, Sources, mode_name, skill_dirs, writes_of,
};
use laris_protocol::events::LoginReason;
use laris_sandbox::{Policy as SandboxPolicy, Sandbox};
use laris_store::slug_of;
use laris_tools::{Context, Registry};
use std::io::Read;
use std::sync::Arc;

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
    let runtime = match runtime() {
        Ok(runtime) => runtime,
        Err(message) => return refuse(&mut console, format, "runtime", &message, exit::FAILED),
    };
    let client = match connect(&started.settings.server, &key, true) {
        Ok(client) => Arc::new(client),
        Err(e) => {
            return refuse(
                &mut console,
                format,
                "server_unusable",
                &format!("cannot reach the server: {e}"),
                exit::FAILED,
            );
        }
    };

    let redactor = Arc::new(Redactor::from_process_env().with_secrets([key.expose().to_owned()]));
    let shield = Arc::new(Shield::new(Arc::clone(&redactor)));
    let engine_state = laris_policy::ProjectState::new(started.home.root(), &started.project);

    let mut ctx = match Context::new(&started.project, &started.settings) {
        Ok(ctx) => ctx,
        Err(e) => {
            return refuse(
                &mut console,
                format,
                "tools_unusable",
                &e.to_string(),
                exit::FAILED,
            );
        }
    };
    let scope = ctx.scope.clone();
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
    match Sandbox::detect(SandboxPolicy::workspace([started.project.clone()]), None) {
        Ok(sandbox) => ctx = ctx.with_sandbox(Arc::new(sandbox)),
        Err(e) => {
            let _ = writeln!(
                console.err,
                "laris: commands run without a sandbox on this machine: {e}"
            );
        }
    }
    let mut registry = Registry::with_local_tools(ctx);
    match HttpRemote::connect(Arc::clone(&client), Arc::clone(&runtime)) {
        Ok(remote) => {
            if let Err(e) = registry.add_remote(Box::new(remote)) {
                let _ = writeln!(console.err, "laris: remote tools left out: {e}");
            }
        }
        Err(e) => {
            let _ = writeln!(console.err, "laris: remote tools left out: {e}");
        }
    }

    let engine = match engine(started, options, scope) {
        Ok(engine) => Arc::new(engine),
        Err(message) => return refuse(&mut console, format, "usage", &message, exit::USAGE),
    };
    let mode = mode_name(engine.mode()).to_owned();
    let hooks = Arc::new(HookRunner::new(
        &started.settings,
        &started.project,
        &session.id,
    ));
    let schemas = registry.schemas();
    let gate = PolicyGate::new(
        Arc::clone(&engine),
        writes_of(&registry),
        laris_policy::NoApprover,
    )
    .with_hooks(Arc::clone(&hooks))
    .with_shield(Arc::clone(&shield));
    let tools = HookedRunner::new(ShieldedRunner::new(registry, Arc::clone(&shield)), hooks)
        .with_shield(shield);

    let model = Prompted::new(
        RedactingModel::new(ServerModel::new(client, runtime, &session.id), redactor),
        Sources {
            home: started.home.root().to_path_buf(),
            project_root: started.project.clone(),
            state: engine_state,
            extra_instructions: started.settings.extra_instructions.clone(),
        },
        started.settings.context.clone(),
        PinBoard::new(),
    );
    let setup = Setup { started, server };
    execute(
        &setup, options, &request, model, tools, schemas, gate, &mode, session, console,
    )
}
