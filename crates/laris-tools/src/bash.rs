//! `Bash`: one shell command in the project folder, with a time limit and a cap on the output.
//!
//! The command runs with a clean environment (`PATH`, `HOME`, the settings' `env`; the whole environment only when
//! the settings say so) in its own process group, which is killed when the time runs out. The OS sandbox (T135)
//! and the permission rules (T133) are what confine it; this tool does not judge a command.

use crate::args::{object_schema, opt_string, opt_u64, string};
use crate::context::Context;
use crate::error::ToolError;
use crate::registry::LocalTool;
use serde_json::{Map, Value, json};
use std::io::Read;
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::sync::mpsc;
use std::time::{Duration, Instant};

type Args = Map<String, Value>;

/// How often a running command is checked.
const POLL: Duration = Duration::from_millis(10);
/// How long the output of an ended command is awaited when something it started still holds the pipe.
const DRAIN_GRACE: Duration = Duration::from_secs(2);

pub(crate) fn tool(ctx: &Arc<Context>) -> LocalTool {
    let ctx = Arc::clone(ctx);
    let schema = object_schema(
        json!({"command": {"type": "string"}, "timeout_s": {"type": "integer", "minimum": 1},
               "cwd": {"type": "string", "description": "Path relative to the project folder"}}),
        &["command"],
    );
    LocalTool::new(
        "Bash",
        "Run a shell command (needs approval unless a rule allows it). timeout_s and cwd (inside the project) are optional.",
        schema,
        true,
        true,
        move |args: &Args| run(&ctx, args),
    )
}

fn run(ctx: &Context, args: &Args) -> Result<Value, ToolError> {
    let command = string(args, "command")?;
    let cwd = match opt_string(args, "cwd") {
        Some(raw) => ctx.scope.resolve(raw, false)?,
        None => ctx.scope.root().to_path_buf(),
    };
    if !cwd.is_dir() {
        return Err(ToolError::new("not_a_directory", "cwd is not a folder"));
    }
    let max = ctx.limits.bash_max_timeout_seconds;
    let asked =
        opt_u64(args, "timeout_s").map_or(ctx.limits.bash_default_timeout_seconds, |s| s as f64);
    let limit = Duration::from_secs_f64(asked.min(max));

    let shell = shell();
    // standard error joins standard output, as a terminal shows them
    let script = format!("exec 2>&1\n{command}");
    let mut process = match &ctx.sandbox {
        Some(sandbox) => sandbox
            .command(&[shell.clone().into(), "-c".into(), script.into()], &cwd)
            .map_err(|e| ToolError::new("sandbox_unavailable", e.to_string()))?,
        None => {
            if let Some(what) = install_command(command) {
                return Err(ToolError::new(
                    "install_outside_sandbox",
                    format!(
                        "{what} is refused: commands are not confined here, and installs belong inside the sandbox"
                    ),
                ));
            }
            let mut plain = Command::new(&shell);
            plain.arg("-c").arg(script);
            plain
        }
    };
    process
        .current_dir(&cwd)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    if !ctx.inherit_env {
        process.env_clear();
        process.env(
            "PATH",
            std::env::var_os("PATH").unwrap_or_else(|| "/usr/bin:/bin".into()),
        );
        if let Some(home) = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")) {
            process.env("HOME", home);
        }
    }
    process.envs(&ctx.env);
    if let Some(python) = &ctx.python_env {
        let old = process
            .get_envs()
            .find(|(k, _)| *k == "PATH")
            .and_then(|(_, v)| v.map(std::ffi::OsStr::to_owned))
            .or_else(|| std::env::var_os("PATH"))
            .unwrap_or_default();
        let mut paths = vec![python.bin_dir()];
        paths.extend(std::env::split_paths(&old));
        if let Ok(joined) = std::env::join_paths(paths) {
            process.env("PATH", joined);
        }
        process.env("VIRTUAL_ENV", &python.dir);
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        process.process_group(0);
    }
    let mut child = process
        .spawn()
        .map_err(|e| ToolError::io("spawn_failed", &format!("cannot start {shell}"), &e))?;
    let mut pipe = child
        .stdout
        .take()
        .ok_or_else(|| ToolError::new("spawn_failed", "no output pipe"))?;

    // The output is read on another thread, so a full pipe never stops the command, and only what can be shown
    // (with room for multi-byte characters) is kept.
    let keep = usize::try_from(ctx.limits.bash_output_max_chars)
        .unwrap_or(usize::MAX)
        .saturating_mul(4);
    let (sender, receiver) = mpsc::channel();
    std::thread::spawn(move || {
        let mut kept = Vec::new();
        let mut total = 0usize;
        let mut buffer = [0u8; 8192];
        while let Ok(n) = pipe.read(&mut buffer) {
            if n == 0 {
                break;
            }
            total += n;
            if kept.len() < keep {
                kept.extend_from_slice(&buffer[..n.min(keep - kept.len())]);
            }
        }
        sender.send((kept, total)).ok();
    });

    let started = Instant::now();
    let mut timed_out = false;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if started.elapsed() >= limit => {
                timed_out = true;
                kill_tree(&mut child);
                break child.wait().ok();
            }
            Ok(None) => std::thread::sleep(POLL),
            Err(e) => {
                return Err(ToolError::io(
                    "wait_failed",
                    "cannot wait for the command",
                    &e,
                ));
            }
        }
    };
    let (bytes, total) = receiver.recv_timeout(DRAIN_GRACE).unwrap_or_default();

    let cap = usize::try_from(ctx.limits.bash_output_max_chars).unwrap_or(usize::MAX);
    let text = String::from_utf8_lossy(&bytes);
    let clipped = total > bytes.len() || text.chars().count() > cap;
    let mut output: String = text.chars().take(cap).collect();
    if clipped {
        output.push_str("\n… (output truncated)");
    }
    Ok(json!({
        "exit_code": if timed_out { None } else { status.and_then(|s| s.code()) },
        "timed_out": timed_out,
        "output": output,
        "cwd": match ctx.scope.display(&cwd) { d if d.is_empty() => ".".to_owned(), d => d },
    }))
}

/// The kind of install a command line tries (package managers), when it does; such a command may not run outside the
/// sandbox. This is the generation-1 rule; inside the sandbox the same command simply fails to write.
fn install_command(line: &str) -> Option<&'static str> {
    use std::sync::OnceLock;
    static RULES: OnceLock<Vec<(regex::Regex, &'static str)>> = OnceLock::new();
    let rules = RULES.get_or_init(|| {
        [
            (r"(?:^|[\s;&|(`])(?:uv\s+)?pip3?\s+(?:--?\S+\s+)*install\b", "pip install"),
            (r"(?:^|[\s;&|(`])uv\s+(?:add|sync|tool\s+install)\b", "uv install"),
            (r"python[0-9.]*\s+-m\s+(?:uv\s+)?pip\s+install\b", "pip install"),
            (r"(?:^|[\s;&|(`])(?:conda|mamba|apt|apt-get|dnf|yum|brew|pacman)\s+(?:-\S+\s+)*(?:install|add|-S)\b", "package install"),
            (r"(?:^|[\s;&|(`])(?:npm|pnpm|yarn)\s+(?:install|i|add)\b", "package install"),
        ]
        .into_iter()
        .filter_map(|(pattern, what)| regex::Regex::new(pattern).ok().map(|re| (re, what)))
        .collect()
    });
    rules
        .iter()
        .find(|(re, _)| re.is_match(line))
        .map(|(_, what)| *what)
}

/// The shell commands and hooks run in: `bash` where there is one, else `sh`.
pub fn shell() -> String {
    if cfg!(windows) {
        return "bash".to_owned();
    }
    for candidate in ["/bin/bash", "/usr/bin/bash"] {
        if std::path::Path::new(candidate).is_file() {
            return candidate.to_owned();
        }
    }
    "/bin/sh".to_owned()
}

/// Ends the command and everything it started.
pub fn kill_tree(child: &mut std::process::Child) {
    let pid = child.id().to_string();
    #[cfg(unix)]
    let group = Command::new("kill")
        .args(["-KILL", "--", &format!("-{pid}")])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    #[cfg(windows)]
    let group = Command::new("taskkill")
        .args(["/PID", &pid, "/T", "/F"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    if !group.is_ok_and(|s| s.success()) {
        child.kill().ok();
    }
}
