//! `laris` with no arguments: the terminal loop. It reads the keyboard, hands what happened to the
//! [`Controller`], and draws the interface on the terminal with [`Screen`].

use super::commands::CommandSet;
use super::control::{Controller, Starter};
use super::front::{Front, Remote, Wiring};
use super::meter::{Meter, Metered};
use super::worker::{Handle, spawn};
use crate::headless::args::{Format, Options, Resume};
use crate::headless::real::build;
use crate::login::HttpVerifier;
use crate::start::Started;
use laris_config::Catalogue;
use laris_config::home::INSTRUCTIONS_FILE;
use laris_core::{Driver, FollowModel, Record, Recorder, decode_record};
use laris_model_client::ApiKey;
use laris_protocol::{Command, Event};
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use laris_tui::term::{FullScreen, RawMode, Term, next, pending, size};
use laris_tui::{History, Theme};
use std::io::{IsTerminal, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::mpsc::Sender;
use std::time::{Duration, Instant};

/// How long the loop waits for a key before it looks at the session again.
const POLL: Duration = Duration::from_millis(40);

fn clock() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0.0, |d| d.as_secs_f64())
}

/// The options of an interactive session: the settings' permissions, no flags.
pub fn session_options() -> Options {
    Options {
        prompt: None,
        format: Format::Text,
        resume: Resume::New,
        max_turns: None,
        mode: None,
        allowed: Vec::new(),
        disallowed: Vec::new(),
    }
}

/// The session a resumed run goes on with and what was said in it, read back from the event log: what the user sent
/// and what the core answered. `Ok((None, []))` for a new session; `Err` is the reason, for the person.
pub fn history(
    started: &Started,
    resume: &Resume,
) -> Result<(Option<String>, Vec<History>), String> {
    if matches!(resume, Resume::New) {
        return Ok((None, Vec::new()));
    }
    let store = Store::open_space(
        started.home.root(),
        &started.project,
        None,
        DEFAULT_BUSY_TIMEOUT,
    )
    .map_err(|e| format!("cannot open the session store: {e}"))?;
    let words = Catalogue::new(started.settings.ui.language);
    let existing = store.sessions().unwrap_or_default();
    let id = match resume {
        Resume::Continue => existing
            .last()
            .cloned()
            .ok_or_else(|| words.get("headless.no_session", &[]).unwrap_or_default())?,
        Resume::Session(id) if existing.contains(id) => id.clone(),
        Resume::Session(id) => {
            return Err(words
                .get("headless.unknown_session", &[("id", id)])
                .unwrap_or_default());
        }
        Resume::New => return Ok((None, Vec::new())),
    };
    let stored = store
        .events(&id, 0)
        .map_err(|e| format!("cannot read the session {id}: {e}"))?;
    let entries = stored
        .iter()
        .filter_map(|e| decode_record(&e.data).ok())
        .filter_map(|record| match record {
            Record::Command {
                command: Command::UserMessage { text, .. },
            } => Some(History::User(text)),
            Record::Emitted { event } => Some(History::Event(event)),
            _ => None,
        })
        .collect();
    Ok((Some(id), entries))
}

/// Starts the real session: the model and tools of a headless run, the person as the approver. `resume` is the
/// session to go on with (from [`history`]); without it a new one is made.
pub fn start_real(
    started: &Arc<Started>,
    key: &ApiKey,
    server: &str,
    events: Sender<Event>,
    resume: Option<&str>,
) -> Handle {
    let started = Arc::clone(started);
    let key = key.clone();
    let server = server.to_owned();
    let resume = resume.map(str::to_owned);
    spawn(events, move |ports| {
        let now = clock();
        let id =
            resume.unwrap_or_else(|| format!("chat-{:.0}-{}", now * 1000.0, std::process::id()));
        let progress = Some(std::rc::Rc::clone(&ports.emit));
        let built = build(
            &started,
            &session_options(),
            &key,
            &id,
            ports.approver,
            progress,
        )
        .map_err(|e| e.message)?;
        let store = Store::open_space(
            started.home.root(),
            &started.project,
            None,
            DEFAULT_BUSY_TIMEOUT,
        )
        .map_err(|e| format!("cannot open the session store: {e}"))?;
        let (recorder, _) = Recorder::open(store, &id, "interactive", now)
            .map_err(|e| format!("cannot open the session {id}: {e}"))?;
        let words = Catalogue::new(started.settings.ui.language);
        let decider = FollowModel::new(started.settings.agent.clone(), words).with_gate(built.gate);
        let meter = Meter::new(
            started.settings.context.window_tokens,
            started.settings.context.compact_threshold,
        );
        let remote: Remote = {
            let settings = started.settings.server.clone();
            let key = key.clone();
            std::rc::Rc::new(move |path: &str| remote_get(&settings, &key, path))
        };
        let driver = Driver::new(
            recorder,
            Metered::new(built.model, meter.clone(), std::rc::Rc::clone(&ports.emit)),
            built.tools,
            decider,
            built.schemas,
            clock,
        )
        .with_interrupt_flag(ports.interrupt);
        let commands = CommandSet::load(
            &started.home.commands_dir(),
            &started.project_folder().path().join("commands"),
            words,
        );
        let sandbox = !built.warnings.iter().any(|w| w.contains("sandbox"));
        Ok(Front::new(
            driver,
            Wiring {
                registry: built.registry,
                engine: built.engine,
                commands,
                words,
                project: started.project.clone(),
                note_file: started.project_folder().path().join(INSTRUCTIONS_FILE),
                session: id,
                server,
                waiting: ports.waiting,
                sandbox,
                emit: ports.emit,
                meter,
                remote,
                mcp: built.mcp,
            },
        ))
    })
}

/// `GET /v1<path>` as JSON, for `/usage` and `/model`.
fn remote_get(
    server: &laris_config::settings::Server,
    key: &ApiKey,
    path: &str,
) -> Result<serde_json::Value, String> {
    let client = crate::login::connect(server, key, true).map_err(|e| e.to_string())?;
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| e.to_string())?
        .block_on(client.get_json::<serde_json::Value>(path, &laris_model_client::Interrupt::new()))
        .map_err(|e| e.to_string())
}

/// `/restart`: starts the program again, resuming the session when it has one on record. On Unix the process is
/// replaced; elsewhere the new one runs to its end and its exit code is ours.
fn restart(started: &Started, exe: &Path, session: Option<&str>) -> u8 {
    let mut command = std::process::Command::new(exe);
    if let Some(id) = session
        && history(started, &Resume::Session(id.to_owned())).is_ok()
    {
        command.arg("--resume").arg(id);
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        let failure = command.exec();
        eprintln!("laris: cannot restart: {failure}");
        1
    }
    #[cfg(not(unix))]
    match command.status() {
        Ok(status) => u8::try_from(status.code().unwrap_or(1)).unwrap_or(1),
        Err(e) => {
            eprintln!("laris: cannot restart: {e}");
            1
        }
    }
}

fn wants_colour(env: &[(String, String)]) -> bool {
    let get = |name: &str| env.iter().find(|(k, _)| k == name).map(|(_, v)| v.as_str());
    get("NO_COLOR").is_none_or(str::is_empty) && get("TERM") != Some("dumb")
}

/// Runs the interface until the person leaves. Returns the exit code.
pub fn run(started: Arc<Started>, resume: &Resume) -> u8 {
    let words = Catalogue::new(started.settings.ui.language);
    if !std::io::stdin().is_terminal() || !std::io::stdout().is_terminal() {
        eprintln!(
            "laris: {}",
            words.get("ui.needs_terminal", &[]).unwrap_or_default()
        );
        return 2;
    }
    let colour = wants_colour(&started.env);
    let theme = (!colour).then(Theme::mono);
    let (session, past) = match history(&started, resume) {
        Ok(found) => found,
        Err(message) => {
            eprintln!("laris: {message}");
            return 2;
        }
    };
    let start: Starter = Box::new(move |started, key, server, events| {
        start_real(started, key, server, events, session.as_deref())
    });
    let mut control = Controller::new(
        Arc::clone(&started),
        theme,
        start,
        Box::new(HttpVerifier {
            use_env_proxy: true,
        }),
    );
    control.app.show_history(past);
    let raw = match RawMode::enter_full() {
        Ok(raw) => raw,
        Err(e) => {
            eprintln!("laris: cannot use the terminal: {e}");
            return 2;
        }
    };
    // taken now: once an update replaces the file, the system may no longer name the running program
    let exe = std::env::current_exe().ok().map(|p| {
        let text = p.to_string_lossy();
        PathBuf::from(text.strip_suffix(" (deleted)").unwrap_or(&text))
    });
    if let Some(exe) = exe.clone() {
        let events = control.sender();
        let scratch = started.home.root().to_path_buf();
        crate::update::spawn_watch(
            started.settings.update.clone(),
            exe,
            scratch,
            Box::new(move |version| {
                let mut data = serde_json::Map::new();
                data.insert("version".to_owned(), version.into());
                let _ = events.send(Event::Status {
                    kind: "update".to_owned(),
                    data,
                });
            }),
        );
    }
    let mut screen = FullScreen::new(std::io::stdout(), colour);
    let (mut columns, mut rows) = size();
    let mut last = Instant::now();
    let result = (|| -> std::io::Result<()> {
        loop {
            control.pump();
            let now = Instant::now();
            let ms = u64::try_from(now.duration_since(last).as_millis()).unwrap_or(u64::MAX);
            last = now;
            control.tick(ms);
            if control.app.take_clear() {
                screen.clear()?;
            }
            screen.draw(&control.app, usize::from(columns), usize::from(rows))?;
            if control.should_quit() {
                break;
            }
            let mut waited = POLL;
            // read what is there without drawing in between, so a paste or a held key is one frame
            while let Some(term) = next(waited)? {
                waited = Duration::ZERO;
                match term {
                    Term::Key(key) => {
                        screen.to_end();
                        control.key_deferred(key);
                    }
                    Term::Paste(text) => {
                        screen.to_end();
                        control.paste(text);
                    }
                    Term::Scroll(lines) => screen.scroll_by(lines),
                    Term::Page(pages) => screen.page_by(pages, usize::from(rows)),
                    Term::Resize(c, r) => {
                        columns = c.max(1);
                        rows = r.max(1);
                    }
                }
                if control.should_quit() || control.has_deferred() || !pending()? {
                    break;
                }
            }
            if control.has_deferred() {
                // show "checking the key" before the wait for the server
                screen.draw(&control.app, usize::from(columns), usize::from(rows))?;
                control.settle();
            }
        }
        screen.finish()
    })();
    drop(raw);
    let _ = std::io::stdout().flush();
    let again = control.app.restart_requested().then(|| control.session());
    drop(control);
    if let (Ok(()), Some(session), Some(exe)) = (&result, again, &exe) {
        return restart(&started, exe, session.as_deref());
    }
    match result {
        Ok(()) => 0,
        Err(e) => {
            eprintln!("laris: the terminal failed: {e}");
            1
        }
    }
}
