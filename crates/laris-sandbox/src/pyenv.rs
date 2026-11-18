//! The Python environment `~/.laris/.venv`, built with `uv` on first use.
//!
//! One build at a time: an exclusive lock on `<home>/.venv.lock` makes a second session wait and then find the
//! finished environment. An environment counts as healthy only when its marker holds the fingerprint of the wanted
//! settings and its interpreter runs; anything else (half built, interpreter deleted, settings changed) is removed and
//! rebuilt in place. The marker is written last, so an interrupted build is never taken for a good one.

use crate::policy::SandboxError;
use laris_config::settings::Sandbox as SandboxSettings;
use sha2::{Digest, Sha256};
use std::ffi::{OsStr, OsString};
use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// Environment variable naming the `uv` program; otherwise `uv` is looked up on `PATH`.
pub const UV_ENV: &str = "LARIS_UV";

const MARKER: &str = ".laris-env";

/// A ready environment.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PythonEnv {
    /// The environment folder (`<home>/.venv`).
    pub dir: PathBuf,
    /// Whether this call built it (false: it was already healthy, or another session built it meanwhile).
    pub built: bool,
}

impl PythonEnv {
    /// The folder holding the interpreter and the installed commands; put it first on `PATH`.
    #[must_use]
    pub fn bin_dir(&self) -> PathBuf {
        self.dir.join(if cfg!(windows) { "Scripts" } else { "bin" })
    }

    /// The interpreter.
    #[must_use]
    pub fn python(&self) -> PathBuf {
        self.bin_dir().join(if cfg!(windows) {
            "python.exe"
        } else {
            "python"
        })
    }
}

/// Makes sure `<home>/.venv` exists and matches `settings`, building or repairing it when not.
///
/// # Errors
/// `Python` when `uv` is missing or a build step fails (the half-built folder is removed), `Io` for the lock or the
/// folder.
pub fn ensure(home: &Path, settings: &SandboxSettings) -> Result<PythonEnv, SandboxError> {
    let program = std::env::var_os(UV_ENV)
        .filter(|p| !p.is_empty())
        .unwrap_or_else(|| OsString::from("uv"));
    ensure_with(&program, home, settings)
}

/// As `ensure`, with the `uv` program named by the caller.
///
/// # Errors
/// As `ensure`.
pub fn ensure_with(
    uv: &OsStr,
    home: &Path,
    settings: &SandboxSettings,
) -> Result<PythonEnv, SandboxError> {
    fs::create_dir_all(home).map_err(|e| SandboxError::io("create the LARIS home", e))?;
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(home.join(".venv.lock"))
        .map_err(|e| SandboxError::io("open the build lock", e))?;
    lock.lock()
        .map_err(|e| SandboxError::io("take the build lock", e))?;
    let result = build_locked(uv, home, settings);
    drop(lock); // releases the lock
    result
}

fn build_locked(
    uv: &OsStr,
    home: &Path,
    settings: &SandboxSettings,
) -> Result<PythonEnv, SandboxError> {
    let env = PythonEnv {
        dir: home.join(".venv"),
        built: false,
    };
    let print = fingerprint(settings);
    if healthy(&env, &print) {
        return Ok(env);
    }
    if env.dir.exists() {
        fs::remove_dir_all(&env.dir)
            .map_err(|e| SandboxError::io("remove the broken environment", e))?;
    }
    let attempt = create(uv, &env, settings).and_then(|()| {
        fs::write(env.dir.join(MARKER), &print)
            .map_err(|e| SandboxError::io("write the environment marker", e))
    });
    if let Err(e) = attempt {
        fs::remove_dir_all(&env.dir).ok();
        return Err(e);
    }
    Ok(PythonEnv { built: true, ..env })
}

fn create(program: &OsStr, env: &PythonEnv, s: &SandboxSettings) -> Result<(), SandboxError> {
    let mut venv = uv(program);
    venv.arg("venv")
        .arg("--python")
        .arg(&s.python)
        .arg(&env.dir);
    if !s.python_source.is_empty() {
        venv.env("UV_PYTHON_INSTALL_MIRROR", &s.python_source);
    }
    run(venv, "uv venv")?;
    if !s.packages.is_empty() {
        let mut install = uv(program);
        install
            .args(["pip", "install", "--python"])
            .arg(env.python());
        if !s.index_url.is_empty() {
            install.arg("--index-url").arg(&s.index_url);
        }
        install.args(&s.packages);
        run(install, "uv pip install")?;
    }
    Ok(())
}

fn uv(program: &OsStr) -> Command {
    let mut cmd = Command::new(program);
    cmd.stdin(Stdio::null()).env("UV_NO_PROGRESS", "1");
    cmd
}

fn run(mut cmd: Command, what: &str) -> Result<(), SandboxError> {
    let out = cmd.output().map_err(|e| {
        SandboxError::Python(format!("cannot start {what} ({e}); is uv installed?"))
    })?;
    if out.status.success() {
        return Ok(());
    }
    let err = String::from_utf8_lossy(&out.stderr);
    let tail: String = err
        .chars()
        .rev()
        .take(1000)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    Err(SandboxError::Python(format!(
        "{what} failed ({}): {}",
        out.status,
        tail.trim()
    )))
}

fn healthy(env: &PythonEnv, print: &str) -> bool {
    fs::read_to_string(env.dir.join(MARKER)).is_ok_and(|m| m == print)
        && Command::new(env.python())
            .args(["-c", "import sys"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok_and(|s| s.success())
}

/// A hash of what the environment must contain, so a change of settings forces a rebuild.
fn fingerprint(s: &SandboxSettings) -> String {
    let mut packages = s.packages.clone();
    packages.sort();
    let text = serde_json::json!({"python": s.python, "packages": packages, "index": s.index_url, "source": s.python_source});
    let digest = Sha256::digest(text.to_string().as_bytes());
    digest.iter().map(|b| format!("{b:02x}")).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fingerprint_ignores_package_order_but_not_content() {
        let a = SandboxSettings {
            packages: vec!["b".into(), "a".into()],
            ..SandboxSettings::default()
        };
        let mut b = a.clone();
        b.packages = vec!["a".into(), "b".into()];
        assert_eq!(fingerprint(&a), fingerprint(&b));
        b.python = "3.11".into();
        assert_ne!(fingerprint(&a), fingerprint(&b));
    }
}
