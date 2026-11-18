//! `Bash` inside the OS sandbox (T135): a write outside the project fails, the time limit still ends everything the
//! command started, the Python environment leads `PATH`, and without a sandbox installs are refused.
#![cfg(target_os = "linux")]
#![allow(missing_docs)]

mod common;

use common::{args, exists, temp_dir};
use laris_config::Settings;
use laris_sandbox::{Backend, Policy, PythonEnv, Sandbox};
use laris_tools::{Context, Registry};
use serde_json::{Value, json};
use std::path::PathBuf;
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant};

/// The helper binary of `laris-sandbox`, built on demand (a dependency's binary is not built by `cargo test` here).
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

fn backend() -> Backend {
    if laris_sandbox::sandbox::bwrap_works() {
        Backend::Bubblewrap
    } else {
        Backend::Landlock
    }
}

struct Rig {
    project: PathBuf,
    registry: Registry,
}

fn rig(name: &str, sandboxed: bool, python: Option<PythonEnv>) -> Rig {
    let base = temp_dir(name);
    let project = base.join("project");
    std::fs::create_dir_all(&project).expect("project");
    let mut ctx = Context::new(&project, &Settings::default()).expect("context");
    if sandboxed {
        let policy = Policy::workspace([project.clone()]);
        let sandbox = Sandbox::with_backend(policy, backend(), Some(helper())).expect("sandbox");
        ctx = ctx.with_sandbox(Arc::new(sandbox));
    }
    if let Some(env) = python {
        ctx = ctx.with_python_env(env);
    }
    Rig {
        project,
        registry: Registry::with_local_tools(ctx),
    }
}

impl Rig {
    fn bash(&mut self, command: &str) -> Value {
        self.registry
            .call("Bash", &args(json!({"command": command})))
    }
}

#[test]
fn a_sandboxed_command_writes_in_the_project_and_not_outside() {
    let mut r = rig("sb-write", true, None);
    let outside = temp_dir("sb-outside").join("x.txt");
    let ok = r.bash("echo in > in.txt; cat in.txt");
    assert_eq!(ok["exit_code"], 0, "{ok}");
    assert!(exists(&r.project.join("in.txt")));
    let bad = r.bash(&format!("echo no > {}", outside.display()));
    assert_ne!(bad["exit_code"], 0, "{bad}");
    assert!(!exists(&outside));
}

#[test]
fn the_time_limit_ends_a_sandboxed_command_and_everything_it_started() {
    let mut r = rig("sb-timeout", true, None);
    let started = Instant::now();
    let out = r.registry.call(
        "Bash",
        &args(json!({"command": "echo start; (sleep 30; echo late > late.txt) & sleep 30", "timeout_s": 1})),
    );
    assert!(started.elapsed() < Duration::from_secs(20), "{out}");
    assert_eq!(out["timed_out"], true, "{out}");
    std::thread::sleep(Duration::from_millis(500));
    assert!(
        !exists(&r.project.join("late.txt")),
        "the child outlived the limit"
    );
}

#[test]
fn the_python_environment_leads_the_path() {
    let home = temp_dir("sb-py-home");
    let settings = laris_config::settings::Sandbox {
        python: "3.12".into(),
        ..Default::default()
    };
    let env = laris_sandbox::pyenv::ensure(&home, &settings).expect("python environment");
    let mut r = rig("sb-py", true, Some(env.clone()));
    let out =
        r.bash("command -v python; python -c 'import sys; print(sys.prefix)'; echo $VIRTUAL_ENV");
    let text = out["output"].as_str().expect("output");
    assert!(text.contains(&env.dir.display().to_string()), "{out}");
    assert!(
        text.starts_with(&env.bin_dir().display().to_string()),
        "{out}"
    );
}

#[test]
fn installs_are_refused_without_a_sandbox_and_run_inside_one() {
    let mut open = rig("install-open", false, None);
    for line in [
        "pip install requests",
        "pip3 install -U requests",
        "python3 -m pip install requests",
        "uv pip install requests",
        "echo a && pip install x",
        "apt-get install -y curl",
        "npm install left-pad",
    ] {
        let out = open.bash(line);
        assert_eq!(
            out["error"]["code"], "install_outside_sandbox",
            "{line}: {out}"
        );
    }
    // commands that do not install are left alone
    assert_eq!(open.bash("grep -r install .; true")["exit_code"], 0);
    // inside the sandbox the command is not refused by name; the sandbox is what stops it writing outside
    let mut closed = rig("install-closed", true, None);
    let out = closed.bash("pip install --target /usr/lib/laris-nope requests");
    assert!(out.get("error").is_none(), "{out}");
    assert_ne!(out["exit_code"], 0);
}

#[test]
fn a_sandbox_that_cannot_start_stops_the_command() {
    let base = temp_dir("sb-missing");
    let project = base.join("project");
    std::fs::create_dir_all(&project).expect("project");
    let sandbox = Sandbox::with_backend(
        Policy::workspace([project.clone()]),
        Backend::Bubblewrap,
        Some(PathBuf::from("/nonexistent/laris-sandbox-helper")),
    )
    .expect("sandbox");
    let ctx = Context::new(&project, &Settings::default())
        .expect("context")
        .with_sandbox(Arc::new(sandbox));
    let mut registry = Registry::with_local_tools(ctx);
    let out = registry.call("Bash", &args(json!({"command": "echo ran > ran.txt"})));
    assert_ne!(out["exit_code"], 0, "{out}");
    assert!(!exists(&project.join("ran.txt")));
}
