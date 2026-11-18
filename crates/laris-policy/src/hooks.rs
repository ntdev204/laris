//! Hooks: local commands the user runs at five points of a session.
//!
//! Events: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`. Hooks are declared only in the
//! user's own settings: the settings come from the global file and the environment, and a project folder has no
//! layer, so cloning a repository runs nothing. Each hook runs as `bash -c` in the project folder with a clean
//! environment, a JSON description of the event on standard input, and a time limit after which its process group
//! is killed.
//!
//! What a hook answers:
//! * exit code 0 and nothing on standard output: carry on;
//! * exit code 0 and a JSON object: `{"decision": "block", "reason": "..."}` blocks, `{"additionalContext": "..."}`
//!   adds text for the model, anything else in it is ignored;
//! * exit code 2: block, the reason is what the hook wrote on standard error;
//! * any other exit code, a timeout, a failure to start or output that is not a JSON object: a warning, and the
//!   event carries on (a broken hook never stops the session; a hook that must block exits with 2).
//!
//! `PreToolUse` can only make things stricter: a hook cannot grant a permission. Output is cut at [`OUTPUT_CAP`]
//! characters and stripped of control characters, so a hook cannot flood memory or repaint the terminal.

use laris_config::Settings;
use laris_config::settings::{HOOK_EVENTS, HookMatcher};
use laris_tools::{kill_tree, shell};
use regex::Regex;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::sync::mpsc;
use std::time::{Duration, Instant};

/// Most characters kept of a hook's output, and of a block reason.
pub const OUTPUT_CAP: usize = 64_000;
/// The events that name a tool.
const TOOL_EVENTS: [&str; 2] = ["PreToolUse", "PostToolUse"];
const POLL: Duration = Duration::from_millis(10);
/// How long the output of an ended hook is awaited when something it started still holds the pipe.
const DRAIN_GRACE: Duration = Duration::from_secs(2);

/// What the hooks of one event answered.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HookOutcome {
    /// A hook blocked.
    pub blocked: bool,
    /// Why, when blocked.
    pub reason: String,
    /// Text for the model.
    pub context: Vec<String>,
    /// Failures that did not block.
    pub warnings: Vec<String>,
    /// How many hooks ran.
    pub ran: usize,
}

/// A warning or a block, kept for the front end to show.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Notice {
    /// The event.
    pub event: String,
    /// `warning` or `blocked`.
    pub kind: String,
    /// The text.
    pub text: String,
}

/// Strips what could move the cursor, retitle the window, write to the clipboard or hide text: every control
/// character but the tab and the new line.
pub fn clean(text: &str) -> String {
    text.chars()
        .filter(|c| !matches!(*c as u32, 0..=8 | 0x0b..=0x1f | 0x7f..=0x9f))
        .collect()
}

fn cut(text: &str, max: usize) -> String {
    text.chars().take(max).collect()
}

/// Runs the hooks declared in the settings.
pub struct HookRunner {
    hooks: BTreeMap<String, Vec<HookMatcher>>,
    env: BTreeMap<String, String>,
    inherit_env: bool,
    project_root: PathBuf,
    session_id: String,
    notices: Mutex<Vec<Notice>>,
}

impl HookRunner {
    /// A runner for the hooks and the `env` of `settings`, in `project_root`.
    pub fn new(settings: &Settings, project_root: impl Into<PathBuf>, session_id: &str) -> Self {
        Self {
            hooks: settings.hooks.clone(),
            env: settings.env.clone(),
            inherit_env: settings.sandbox.inherit_env,
            project_root: project_root.into(),
            session_id: session_id.to_owned(),
            notices: Mutex::new(Vec::new()),
        }
    }

    /// Whether any hook is declared for `event`.
    pub fn has(&self, event: &str) -> bool {
        self.hooks.get(event).is_some_and(|m| !m.is_empty())
    }

    /// The warnings and blocks since the last call.
    pub fn drain(&self) -> Vec<Notice> {
        let mut notices = self
            .notices
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        std::mem::take(&mut *notices)
    }

    fn matches(matcher: &str, tool: &str) -> bool {
        if matcher.is_empty() || matcher == "*" {
            return true;
        }
        Regex::new(&format!("(?i)^(?:{matcher})$")).is_ok_and(|re| re.is_match(tool))
    }

    /// Runs every hook of `event` (for a tool event, those whose matcher fits `tool`) in order; the first block
    /// ends the run. `payload` is added to the JSON on standard input.
    pub fn run(&self, event: &str, payload: &Map<String, Value>, tool: &str) -> HookOutcome {
        let mut total = HookOutcome::default();
        if !HOOK_EVENTS.contains(&event) {
            return total;
        }
        let mut body = Map::new();
        body.insert("hook_event_name".to_owned(), json!(event));
        body.insert("session_id".to_owned(), json!(self.session_id));
        body.insert(
            "cwd".to_owned(),
            json!(self.project_root.display().to_string()),
        );
        for (key, value) in payload {
            body.insert(key.clone(), value.clone());
        }
        let body = Value::Object(body).to_string();
        'matchers: for matcher in self.hooks.get(event).into_iter().flatten() {
            if TOOL_EVENTS.contains(&event) && !Self::matches(&matcher.matcher, tool) {
                continue;
            }
            for hook in &matcher.hooks {
                let one = self.run_one(&hook.command, hook.timeout, &body, event);
                total.ran += one.ran;
                total.context.extend(one.context);
                total.warnings.extend(one.warnings);
                if one.blocked {
                    total.blocked = true;
                    total.reason = one.reason;
                    break 'matchers;
                }
            }
        }
        let mut notices = Vec::new();
        for warning in &total.warnings {
            notices.push(Notice {
                event: event.to_owned(),
                kind: "warning".to_owned(),
                text: warning.clone(),
            });
        }
        if total.blocked {
            notices.push(Notice {
                event: event.to_owned(),
                kind: "blocked".to_owned(),
                text: total.reason.clone(),
            });
        }
        self.notices
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .extend(notices);
        total
    }

    fn command(&self, command: &str, event: &str) -> Command {
        let mut process = Command::new(shell());
        process.arg("-c").arg(command);
        process
            .current_dir(&self.project_root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        if !self.inherit_env {
            process.env_clear();
            process.env(
                "PATH",
                std::env::var_os("PATH").unwrap_or_else(|| "/usr/bin:/bin".into()),
            );
            if let Some(home) = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE"))
            {
                process.env("HOME", home);
            }
        }
        process.envs(&self.env);
        process
            .env("LARIS_HOOK_EVENT", event)
            .env("LARIS_PROJECT_DIR", &self.project_root)
            .env("LARIS_SESSION_ID", &self.session_id);
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            process.process_group(0);
        }
        process
    }

    fn run_one(&self, command: &str, timeout: f64, payload: &str, event: &str) -> HookOutcome {
        let mut outcome = HookOutcome {
            ran: 1,
            ..HookOutcome::default()
        };
        let mut child = match self.command(command, event).spawn() {
            Ok(child) => child,
            Err(error) => {
                outcome
                    .warnings
                    .push(format!("hook could not start: {error}"));
                return outcome;
            }
        };
        let keep = OUTPUT_CAP * 4;
        let stdout = spawn_drain(child.stdout.take(), keep);
        let stderr = spawn_drain(child.stderr.take(), keep);
        if let Some(mut stdin) = child.stdin.take() {
            let body = payload.as_bytes().to_vec();
            // the hook may never read its input: a failed write is fine, and must not stall the session
            std::thread::spawn(move || {
                stdin.write_all(&body).ok();
            });
        }
        let limit = Duration::from_secs_f64(timeout);
        let started = Instant::now();
        let status = loop {
            match child.try_wait() {
                Ok(Some(status)) => break Some(status),
                Ok(None) if started.elapsed() >= limit => {
                    kill_tree(&mut child);
                    child.wait().ok();
                    outcome.warnings.push(format!(
                        "hook timed out after {timeout}s: {}",
                        cut(&clean(command), 80)
                    ));
                    return outcome;
                }
                Ok(None) => std::thread::sleep(POLL),
                Err(error) => {
                    outcome
                        .warnings
                        .push(format!("cannot wait for the hook: {error}"));
                    return outcome;
                }
            }
        };
        let mut lingering = false;
        let deadline = Instant::now() + DRAIN_GRACE;
        let mut take = |receiver: mpsc::Receiver<Vec<u8>>| {
            let wait = deadline.saturating_duration_since(Instant::now());
            receiver.recv_timeout(wait).unwrap_or_else(|_| {
                lingering = true;
                Vec::new()
            })
        };
        let out_bytes = take(stdout);
        let err_bytes = take(stderr);
        if lingering {
            // something the hook started holds a pipe: end it with the rest of the group
            kill_tree(&mut child);
        }
        let out = cut(
            clean(&String::from_utf8_lossy(&out_bytes)).trim(),
            OUTPUT_CAP,
        );
        let err = cut(
            clean(&String::from_utf8_lossy(&err_bytes)).trim(),
            OUTPUT_CAP,
        );
        let code = status.and_then(|s| s.code());
        if code == Some(2) {
            outcome.blocked = true;
            outcome.reason = [err, out]
                .into_iter()
                .find(|t| !t.is_empty())
                .unwrap_or_else(|| "blocked by a hook".to_owned());
            return outcome;
        }
        if code != Some(0) {
            let shown = if err.is_empty() { &out } else { &err };
            outcome.warnings.push(format!(
                "hook exited with code {}: {}",
                code.map_or_else(|| "none".to_owned(), |c| c.to_string()),
                cut(shown, 200)
            ));
            return outcome;
        }
        if out.is_empty() {
            return outcome;
        }
        let Ok(Value::Object(data)) = serde_json::from_str::<Value>(&out) else {
            outcome.warnings.push(format!(
                "hook output is not a JSON object and was ignored: {}",
                cut(&out, 80)
            ));
            return outcome;
        };
        let context = data
            .get("additionalContext")
            .or_else(|| {
                data.get("hookSpecificOutput")
                    .and_then(|s| s.get("additionalContext"))
            })
            .and_then(Value::as_str)
            .map(|c| clean(c).trim().to_owned())
            .filter(|c| !c.is_empty());
        outcome.context.extend(context);
        if data.get("decision").and_then(Value::as_str) == Some("block") {
            outcome.blocked = true;
            outcome.reason = data
                .get("reason")
                .and_then(Value::as_str)
                .filter(|r| !r.is_empty())
                .map_or_else(
                    || "blocked by a hook".to_owned(),
                    |r| cut(&clean(r), OUTPUT_CAP),
                );
        }
        outcome
    }
}

/// Reads a pipe to its end on another thread, keeping the first `limit` bytes: a hook that floods its output
/// cannot fill memory, and never blocks on a full pipe.
fn spawn_drain<R: Read + Send + 'static>(pipe: Option<R>, limit: usize) -> mpsc::Receiver<Vec<u8>> {
    let (sender, receiver) = mpsc::channel();
    std::thread::spawn(move || {
        let mut kept = Vec::new();
        if let Some(mut pipe) = pipe {
            let mut buffer = [0u8; 65_536];
            while let Ok(n) = pipe.read(&mut buffer) {
                if n == 0 {
                    break;
                }
                if kept.len() < limit {
                    kept.extend_from_slice(&buffer[..n.min(limit - kept.len())]);
                }
            }
        }
        sender.send(kept).ok();
    });
    receiver
}
