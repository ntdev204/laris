//! One headless run: the request, the session, the turn and what is written.

use super::args::{Format, Options, Resume};
use super::{exit, exit_code_of};
use crate::start::Started;
use laris_config::Catalogue;
use laris_core::{
    Driver, FollowModel, Model, ModelAnswer, ModelError, ModelRequest, Pending, Recorder,
    ToolRunner,
};
use laris_policy::{Engine, PolicyGate, ProjectState, mode_name, parse_rule};
use laris_protocol::jsonl;
use laris_protocol::{Event, ToolSchema, Usage};
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use laris_tools::Scope;
use serde_json::json;
use std::cell::RefCell;
use std::io::{Read, Write};
use std::rc::Rc;

/// Most model calls one turn may have (`agent.maxSteps` is capped at the same number).
pub const MAX_TURNS: u32 = 10;

/// Most bytes read from standard input.
pub const INPUT_LIMIT: usize = 4 * 1024 * 1024;

/// Where the run writes. Standard output carries the answer; standard error carries what is wrong.
pub struct Console {
    /// Standard output.
    pub out: Box<dyn Write>,
    /// Standard error.
    pub err: Box<dyn Write>,
}

/// What the run is for.
pub struct Setup<'a> {
    /// Home, settings, project, environment.
    pub started: &'a Started,
    /// The server address shown in `ready` (empty when none).
    pub server: String,
}

fn words(started: &Started) -> Catalogue {
    Catalogue::new(started.settings.ui.language)
}

fn say(console: &mut Console, text: &str) {
    let _ = writeln!(console.err, "laris: {text}");
}

/// Builds the request from the argument and standard input: the argument, then a blank line, then the input; the
/// input alone when there is no argument. `piped` says whether standard input is a pipe or a file (a terminal is
/// never read). `Err` is a message for the user.
pub fn read_request(
    started: &Started,
    prompt: Option<&str>,
    input: Option<&mut dyn Read>,
) -> Result<String, String> {
    let words = words(started);
    let mut piped = String::new();
    if let Some(input) = input {
        let mut bytes = Vec::new();
        input
            .take(INPUT_LIMIT as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|e| e.to_string())?;
        if bytes.len() > INPUT_LIMIT {
            return Err(words
                .get(
                    "headless.input_too_large",
                    &[("limit", &INPUT_LIMIT.to_string())],
                )
                .unwrap_or_default());
        }
        piped = String::from_utf8(bytes).map_err(|_| {
            words
                .get("headless.input_not_text", &[])
                .unwrap_or_default()
        })?;
    }
    let prompt = prompt.map(str::trim).filter(|p| !p.is_empty());
    let piped = piped.trim();
    let request = match (prompt, piped.is_empty()) {
        (Some(p), true) => p.to_owned(),
        (Some(p), false) => format!("{p}\n\n{piped}"),
        (None, false) => piped.to_owned(),
        (None, true) => {
            return Err(words.get("headless.no_prompt", &[]).unwrap_or_default());
        }
    };
    Ok(request)
}

/// The permission engine of this run: the settings' permissions plus the rules of the flags (a deny always wins),
/// and the mode of `--permission-mode`. `bypass` stays refused until the installation's policy allows it.
pub fn engine(started: &Started, options: &Options, scope: Scope) -> Result<Engine, String> {
    let words = words(started);
    for rule in options.allowed.iter().chain(&options.disallowed) {
        if parse_rule(rule).is_none() {
            return Err(format!(
                "{rule:?} is not a rule; write a tool name, or Tool(pattern)"
            ));
        }
    }
    let mut permissions = started.settings.permissions.clone();
    permissions.allow.extend(options.allowed.iter().cloned());
    permissions.deny.extend(options.disallowed.iter().cloned());
    let engine = Engine::new(
        permissions,
        scope,
        ProjectState::new(started.home.root(), &started.project),
        Some(started.home.settings_path()),
        false,
    );
    if let Some(mode) = options.mode {
        engine.set_mode(mode).map_err(|e| {
            words
                .get(
                    "headless.bad_mode",
                    &[("mode", mode_name(mode)), ("detail", &e.0)],
                )
                .unwrap_or_default()
        })?;
    }
    Ok(engine)
}

fn max_turns(started: &Started, options: &Options) -> Result<u32, String> {
    let Some(text) = &options.max_turns else {
        return Ok(started.settings.agent.max_steps);
    };
    match text.trim().parse::<u32>() {
        Ok(n) if (1..=MAX_TURNS).contains(&n) => Ok(n),
        _ => Err(words(started)
            .get(
                "headless.bad_max_turns",
                &[("limit", &MAX_TURNS.to_string()), ("value", text)],
            )
            .unwrap_or_default()),
    }
}

/// What the model was asked and what it cost, kept while the loop owns the model.
#[derive(Default)]
struct Tally {
    calls: u32,
    usage: Usage,
}

struct Counting<M> {
    inner: M,
    tally: Rc<RefCell<Tally>>,
}

impl<M: Model> Model for Counting<M> {
    fn answer(&mut self, request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        let answer = self.inner.answer(request)?;
        let mut tally = self.tally.borrow_mut();
        tally.calls += 1;
        if let Some(usage) = &answer.usage {
            tally.usage.prompt_tokens += usage.prompt_tokens;
            tally.usage.completion_tokens += usage.completion_tokens;
            tally.usage.total_tokens += usage.total_tokens;
        }
        Ok(answer)
    }
}

fn session_id(now: f64) -> String {
    format!("headless-{:.0}-{}", now * 1000.0, std::process::id())
}

fn clock() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0.0, |d| d.as_secs_f64())
}

fn write_event(out: &Rc<RefCell<Box<dyn Write>>>, event: &Event) {
    let mut out = out.borrow_mut();
    let _ = out.write_all(jsonl::encode(event).as_bytes());
    let _ = out.flush();
}

/// Ends a run before the turn started, in the format asked for. `json` gets a result object, `stream-json` an
/// `error` event, `text` only the message on standard error.
pub(super) fn refuse(
    console: &mut Console,
    format: Format,
    code: &str,
    message: &str,
    exit_code: u8,
) -> u8 {
    say(console, message);
    match format {
        Format::Text => {}
        Format::Json => {
            let value = json!({
                "type": "result", "status": code, "isError": true, "result": message,
                "exitCode": exit_code,
            });
            let _ = writeln!(console.out, "{value}");
        }
        Format::StreamJson => {
            let event = Event::Error {
                code: code.to_owned(),
                message: message.to_owned(),
            };
            let _ = console.out.write_all(jsonl::encode(&event).as_bytes());
        }
    }
    exit_code
}

/// A session of the project's store, found or created.
pub struct Opened {
    store: Store,
    /// The session id.
    pub id: String,
    now: f64,
}

/// Opens the project's store and picks the session the request goes into: a new one, the latest (`--continue`) or
/// the named one (`--resume`). `Err` is the exit code, after the reason was written to `console`.
pub fn open_session(
    started: &Started,
    options: &Options,
    console: &mut Console,
) -> Result<Opened, u8> {
    let words = words(started);
    let format = options.format;
    let store = match Store::open_space(
        started.home.root(),
        &started.project,
        None,
        DEFAULT_BUSY_TIMEOUT,
    ) {
        Ok(store) => store,
        Err(e) => {
            return Err(refuse(
                console,
                format,
                "store_failed",
                &format!("cannot open the session store: {e}"),
                exit::FAILED,
            ));
        }
    };
    let now = clock();
    let existing = store.sessions().unwrap_or_default();
    let id = match &options.resume {
        Resume::New => session_id(now),
        Resume::Continue => match existing.last() {
            Some(id) => id.clone(),
            None => {
                let message = words.get("headless.no_session", &[]).unwrap_or_default();
                return Err(refuse(
                    console,
                    format,
                    "no_session",
                    &message,
                    exit::NO_SESSION,
                ));
            }
        },
        Resume::Session(id) => {
            if !existing.contains(id) {
                let message = words
                    .get("headless.unknown_session", &[("id", id)])
                    .unwrap_or_default();
                return Err(refuse(
                    console,
                    format,
                    "no_session",
                    &message,
                    exit::NO_SESSION,
                ));
            }
            id.clone()
        }
    };
    Ok(Opened { store, id, now })
}

/// Runs `request` as one turn and writes the outcome. Returns the exit code.
///
/// `tools` run only after `gate` lets a call through; `schemas` are the tools offered to the model.
#[allow(clippy::too_many_arguments)]
pub fn execute<M, R>(
    setup: &Setup<'_>,
    options: &Options,
    request: &str,
    model: M,
    tools: R,
    schemas: Vec<ToolSchema>,
    gate: PolicyGate,
    mode: &str,
    session: Opened,
    mut console: Console,
) -> u8
where
    M: Model + 'static,
    R: ToolRunner,
{
    let started = setup.started;
    let words = words(started);
    let format = options.format;
    let steps = match max_turns(started, options) {
        Ok(steps) => steps,
        Err(message) => return refuse(&mut console, format, "usage", &message, exit::USAGE),
    };
    let Opened { store, id, now } = session;
    let recorder = match Recorder::open(store, &id, "headless", now) {
        Ok((recorder, _)) => recorder,
        Err(e) => {
            return refuse(
                &mut console,
                format,
                "store_failed",
                &format!("cannot open session {id}: {e}"),
                exit::FAILED,
            );
        }
    };

    let Console { out, mut err } = console;
    let out: Rc<RefCell<Box<dyn Write>>> = Rc::new(RefCell::new(out));
    if format == Format::StreamJson {
        write_event(
            &out,
            &Event::Ready {
                version: laris_protocol::CORE_VERSION.to_owned(),
                engine: env!("CARGO_PKG_VERSION").to_owned(),
                session: id.clone(),
                cwd: started.project.display().to_string(),
                mode: mode.to_owned(),
                server: setup.server.clone(),
            },
        );
    }

    let mut agent = started.settings.agent.clone();
    agent.max_steps = steps;
    let tally = Rc::new(RefCell::new(Tally::default()));
    let counting = Counting {
        inner: model,
        tally: Rc::clone(&tally),
    };
    let decider = FollowModel::new(agent, words).with_gate(gate);
    let mut driver = Driver::new(recorder, counting, tools, decider, schemas, clock);
    if format == Format::StreamJson {
        let sink = Rc::clone(&out);
        driver = driver.with_sink(move |event| write_event(&sink, event));
    }

    // a session killed in the middle of a turn finishes that turn before it takes the new request
    let mut events = Vec::new();
    let outcome = (|| {
        if *driver.session().pending() != Pending::Idle {
            events.extend(driver.run()?);
        }
        events.extend(driver.send(request)?);
        Ok::<(), laris_core::CoreError>(())
    })();
    if let Err(e) = outcome {
        let message = words
            .get("headless.cannot_continue", &[("detail", &e.to_string())])
            .unwrap_or_default();
        let _ = writeln!(err, "laris: {message}");
        match format {
            Format::Text => {}
            Format::Json => {
                let value = json!({
                    "type": "result", "status": "failed", "isError": true, "result": message,
                    "session": id, "exitCode": exit::FAILED,
                });
                let _ = writeln!(out.borrow_mut(), "{value}");
            }
            Format::StreamJson => write_event(
                &out,
                &Event::Error {
                    code: "core_error".to_owned(),
                    message,
                },
            ),
        }
        return exit::FAILED;
    }

    let last_done = events.iter().rev().find_map(|e| match e {
        Event::Done { status, answer } => Some((status.clone(), answer.clone())),
        _ => None,
    });
    let Some((status, answer)) = last_done else {
        let message = events
            .iter()
            .rev()
            .find_map(|e| match e {
                Event::Error { message, .. } => Some(message.clone()),
                _ => None,
            })
            .unwrap_or_else(|| "the turn produced no answer".to_owned());
        let _ = writeln!(err, "laris: {message}");
        return exit::FAILED;
    };
    let code = exit_code_of(&status);
    let goal = events.iter().rev().find_map(|e| match e {
        Event::Goal { complete, .. } => Some(*complete),
        _ => None,
    });
    let errors: Vec<serde_json::Value> = events
        .iter()
        .filter_map(|e| match e {
            Event::Error { code, message } => Some(json!({"code": code, "message": message})),
            _ => None,
        })
        .collect();
    match format {
        Format::Text => {
            if code == exit::OK {
                let _ = writeln!(out.borrow_mut(), "{answer}");
            } else {
                let _ = writeln!(err, "laris: {status}: {answer}");
            }
        }
        Format::Json => {
            let tally = tally.borrow();
            let value = json!({
                "type": "result",
                "status": status,
                "isError": code != exit::OK,
                "result": answer,
                "session": id,
                "modelCalls": tally.calls,
                "goalComplete": goal,
                "usage": {
                    "promptTokens": tally.usage.prompt_tokens,
                    "completionTokens": tally.usage.completion_tokens,
                    "totalTokens": tally.usage.total_tokens,
                },
                "errors": errors,
                "exitCode": code,
            });
            let _ = writeln!(out.borrow_mut(), "{value}");
        }
        Format::StreamJson => {}
    }
    let _ = out.borrow_mut().flush();
    code
}

/// Ends a run that has nobody to sign in as: `json` gets a result object, `stream-json` the `login_required` event.
pub(super) fn refuse_login(
    console: &mut Console,
    format: Format,
    reason: laris_protocol::events::LoginReason,
    server: &str,
    message: &str,
) -> u8 {
    say(console, message);
    match format {
        Format::Text => {}
        Format::Json => {
            let value = json!({
                "type": "result", "status": "login_required", "isError": true, "result": message,
                "server": server, "exitCode": exit::NOT_SIGNED_IN,
            });
            let _ = writeln!(console.out, "{value}");
        }
        Format::StreamJson => {
            let event = Event::LoginRequired {
                reason,
                server: server.to_owned(),
                fingerprint: String::new(),
                message: message.to_owned(),
            };
            let _ = console.out.write_all(jsonl::encode(&event).as_bytes());
        }
    }
    exit::NOT_SIGNED_IN
}
