//! `laris` with no arguments: the terminal loop. It reads the keyboard, hands what happened to the
//! [`Controller`], and draws the interface on the terminal with [`Screen`].

use super::commands::CommandSet;
use super::control::{Controller, Starter};
use super::front::{Front, Wiring};
use super::worker::{Handle, spawn};
use crate::headless::args::{Format, Options, Resume};
use crate::headless::real::build;
use crate::login::HttpVerifier;
use crate::start::Started;
use laris_config::Catalogue;
use laris_config::home::INSTRUCTIONS_FILE;
use laris_core::{Driver, FollowModel, Recorder};
use laris_model_client::ApiKey;
use laris_protocol::Event;
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use laris_tui::Theme;
use laris_tui::term::{RawMode, Screen, Term, next, pending, size};
use std::io::{IsTerminal, Write};
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

/// Starts the real session: the model and tools of a headless run, the person as the approver.
pub fn start_real(
    started: &Arc<Started>,
    key: &ApiKey,
    server: &str,
    events: Sender<Event>,
) -> Handle {
    let started = Arc::clone(started);
    let key = key.clone();
    let server = server.to_owned();
    spawn(events, move |ports| {
        let now = clock();
        let id = format!("chat-{:.0}-{}", now * 1000.0, std::process::id());
        let built = build(&started, &session_options(), &key, &id, ports.approver)
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
        let driver = Driver::new(
            recorder,
            built.model,
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
            },
        ))
    })
}

fn wants_colour(env: &[(String, String)]) -> bool {
    let get = |name: &str| env.iter().find(|(k, _)| k == name).map(|(_, v)| v.as_str());
    get("NO_COLOR").is_none_or(str::is_empty) && get("TERM") != Some("dumb")
}

/// Runs the interface until the person leaves. Returns the exit code.
pub fn run(started: Arc<Started>) -> u8 {
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
    let start: Starter = Box::new(start_real);
    let mut control = Controller::new(
        Arc::clone(&started),
        theme,
        start,
        Box::new(HttpVerifier {
            use_env_proxy: true,
        }),
    );
    let raw = match RawMode::enter() {
        Ok(raw) => raw,
        Err(e) => {
            eprintln!("laris: cannot use the terminal: {e}");
            return 2;
        }
    };
    let mut screen = Screen::new(std::io::stdout(), colour);
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
                    Term::Key(key) => control.key_deferred(key),
                    Term::Paste(text) => control.paste(text),
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
    drop(control);
    match result {
        Ok(()) => 0,
        Err(e) => {
            eprintln!("laris: the terminal failed: {e}");
            1
        }
    }
}
