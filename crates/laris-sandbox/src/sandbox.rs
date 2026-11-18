//! Choosing a backend and wrapping a command in it.

use crate::policy::{Policy, SandboxError};
use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};
use std::process::Command;

/// Environment variable naming the helper binary; otherwise it is looked up next to the running program.
pub const HELPER_ENV: &str = "LARIS_SANDBOX_HELPER";

/// How a command is confined.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Backend {
    /// Linux: bubblewrap mounts plus a seccomp filter in the helper.
    Bubblewrap,
    /// Linux without a usable bubblewrap: Landlock write roots plus the seccomp filter. Weaker: see `limits`.
    Landlock,
    /// macOS: `sandbox-exec` with a generated profile.
    Seatbelt,
}

/// A policy bound to a backend.
#[derive(Debug, Clone)]
pub struct Sandbox {
    backend: Backend,
    policy: Policy,
    helper: PathBuf,
}

impl Sandbox {
    /// Picks the strongest backend that works on this machine.
    ///
    /// # Errors
    /// `Unavailable` when nothing can confine the command (a command must then not run), `Unsupported` when the
    /// only working backend cannot enforce the policy, and always on Windows (no backend in this build).
    pub fn detect(policy: Policy, helper: Option<PathBuf>) -> Result<Self, SandboxError> {
        if cfg!(windows) {
            return Err(SandboxError::Unavailable(
                "there is no Windows backend in this build; commands cannot be confined".into(),
            ));
        }
        if cfg!(target_os = "macos") {
            return Self::with_backend(policy, Backend::Seatbelt, helper);
        }
        let backend = if bwrap_works() {
            Backend::Bubblewrap
        } else {
            Backend::Landlock
        };
        Self::with_backend(policy, backend, helper)
    }

    /// Uses `backend` as asked.
    ///
    /// # Errors
    /// `Unsupported` when the backend cannot enforce the policy, `Unavailable` when its helper is missing.
    pub fn with_backend(
        policy: Policy,
        backend: Backend,
        helper: Option<PathBuf>,
    ) -> Result<Self, SandboxError> {
        let helper = helper.or_else(find_helper);
        match backend {
            Backend::Bubblewrap | Backend::Landlock => {
                let helper = helper.ok_or_else(|| {
                    SandboxError::Unavailable(format!(
                        "laris-sandbox-helper not found (set {HELPER_ENV})"
                    ))
                })?;
                if backend == Backend::Landlock
                    && (!policy.deny_read.is_empty()
                        || !matches!(policy.readable, crate::policy::Readable::Everything))
                {
                    return Err(SandboxError::Unsupported(
                        "the Landlock fallback cannot hide paths from reads".into(),
                    ));
                }
                Ok(Self {
                    backend,
                    policy,
                    helper,
                })
            }
            Backend::Seatbelt => Ok(Self {
                backend,
                policy,
                helper: helper.unwrap_or_default(),
            }),
        }
    }

    /// The backend in use.
    #[must_use]
    pub fn backend(&self) -> Backend {
        self.backend
    }

    /// The policy.
    #[must_use]
    pub fn policy(&self) -> &Policy {
        &self.policy
    }

    /// What this backend does not enforce, to be shown to the user; empty for a full backend.
    #[must_use]
    pub fn limits(&self) -> Vec<&'static str> {
        match self.backend {
            Backend::Bubblewrap => vec![],
            Backend::Landlock => vec![
                "protected names (.git, .laris) are writable inside a writable root",
                "no private /proc or process namespace",
                "no read hiding",
            ],
            Backend::Seatbelt => vec!["not run on macOS in this build's tests"],
        }
    }

    /// A command that runs `argv` in `cwd` confined by the policy. The caller sets the environment and the pipes.
    ///
    /// # Errors
    /// `Unsupported` for an empty `argv`.
    pub fn command(&self, argv: &[OsString], cwd: &Path) -> Result<Command, SandboxError> {
        let Some(program) = argv.first() else {
            return Err(SandboxError::Unsupported("empty command".into()));
        };
        let _ = program;
        match self.backend {
            Backend::Bubblewrap => {
                let mut cmd = Command::new("bwrap");
                let mut policy = self.policy.clone();
                if let (crate::policy::Readable::Only(roots), Some(dir)) =
                    (&mut policy.readable, self.helper.parent())
                {
                    roots.push(dir.to_path_buf()); // the helper must be runnable inside
                }
                cmd.args(crate::bwrap::bwrap_args(&policy, cwd));
                cmd.arg(&self.helper);
                cmd.args(self.helper_flags(false));
                cmd.args(argv);
                Ok(cmd)
            }
            Backend::Landlock => {
                let mut cmd = Command::new(&self.helper);
                cmd.args(self.helper_flags(true));
                cmd.args(argv);
                cmd.current_dir(cwd);
                Ok(cmd)
            }
            Backend::Seatbelt => {
                let mut cmd = Command::new(crate::macos::SANDBOX_EXEC);
                cmd.args(crate::macos::sandbox_exec_args(&self.policy, argv));
                cmd.current_dir(cwd);
                Ok(cmd)
            }
        }
    }

    fn helper_flags(&self, landlock: bool) -> Vec<OsString> {
        crate::helper::helper_args(&crate::helper::Restrictions {
            deny_network: !self.policy.network,
            landlock,
            landlock_writable: if landlock {
                self.policy.writable.clone()
            } else {
                Vec::new()
            },
        })
    }
}

/// Whether `bwrap` exists and can build a sandbox here (user namespaces can be switched off by the system).
#[must_use]
pub fn bwrap_works() -> bool {
    Command::new("bwrap")
        .args([
            "--ro-bind",
            "/",
            "/",
            "--unshare-user",
            "--unshare-pid",
            "--",
            "true",
        ])
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .is_ok_and(|s| s.success())
}

fn find_helper() -> Option<PathBuf> {
    if let Some(path) = std::env::var_os(HELPER_ENV).filter(|p| !p.is_empty()) {
        return Some(path.into());
    }
    let exe = std::env::current_exe().ok()?;
    let name = format!("laris-sandbox-helper{}", std::env::consts::EXE_SUFFIX);
    // beside the program, or in a parent folder (`cargo test` runs from below `target/<profile>`)
    exe.ancestors()
        .skip(1)
        .take(4)
        .map(|dir| dir.join(&name))
        .find(|path| path.is_file())
}

/// Used by tests and callers that hold a program name.
#[must_use]
pub fn os(s: &str) -> OsString {
    OsStr::new(s).to_owned()
}
