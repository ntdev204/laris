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
    /// Windows: a write-restricted token, ACLs on the writable roots and a job object, set up by the helper.
    /// Option A of T134: no read hiding and no OS network block.
    RestrictedToken,
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
    /// `Unavailable` when nothing can confine the command (a command must then not run) and `Unsupported` when the
    /// only working backend cannot enforce the policy.
    pub fn detect(policy: Policy, helper: Option<PathBuf>) -> Result<Self, SandboxError> {
        if cfg!(windows) {
            return Self::with_backend(policy, Backend::RestrictedToken, helper);
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
            Backend::RestrictedToken => {
                let helper = helper.ok_or_else(|| {
                    SandboxError::Unavailable(format!(
                        "laris-sandbox-helper not found (set {HELPER_ENV})"
                    ))
                })?;
                windows_policy_check(&policy)?;
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
            Backend::RestrictedToken => vec![
                "no read hiding and no read limit: the whole disk is readable",
                "no network block: the network is on",
                "a folder that grants write to Everyone stays writable",
                "the capability ACE stays on the writable roots after the command",
                "no private desktop",
                "never run on Windows in this build's tests",
            ],
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
            Backend::RestrictedToken => {
                let mut cmd = Command::new(&self.helper);
                cmd.args(crate::winargs::helper_args(
                    &crate::winargs::WindowsRestrictions {
                        write_roots: self.policy.writable.clone(),
                        protected: self.policy.protected_paths(),
                    },
                ));
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

/// What the Windows backend cannot enforce: refused rather than silently weakened (T134 decision 2).
///
/// # Errors
/// `Unsupported` for hidden paths, limited reads, or a network that is off.
pub fn windows_policy_check(policy: &Policy) -> Result<(), SandboxError> {
    if !policy.deny_read.is_empty()
        || !matches!(policy.readable, crate::policy::Readable::Everything)
    {
        return Err(SandboxError::Unsupported(
            "the Windows backend cannot hide paths from reads".into(),
        ));
    }
    if !policy.network {
        return Err(SandboxError::Unsupported(
            "the Windows backend cannot block the network; the policy must allow it explicitly"
                .into(),
        ));
    }
    Ok(())
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn windows_refuses_what_it_cannot_enforce() {
        let on = Policy::workspace([PathBuf::from("w")]).with_network(true);
        assert!(windows_policy_check(&on).is_ok());
        assert!(windows_policy_check(&Policy::workspace([PathBuf::from("w")])).is_err());
        assert!(windows_policy_check(&on.clone().with_deny_read([PathBuf::from("s")])).is_err());
        assert!(windows_policy_check(&on.with_readable_only([PathBuf::from("r")])).is_err());
    }

    #[test]
    fn windows_command_passes_roots_and_protected_names_to_the_helper() {
        let sandbox = Sandbox::with_backend(
            Policy::workspace([PathBuf::from("w")]).with_network(true),
            Backend::RestrictedToken,
            Some(PathBuf::from("helper")),
        )
        .expect("sandbox");
        let cmd = sandbox
            .command(&[os("cmd"), os("/c"), os("dir")], Path::new("w"))
            .expect("command");
        let args: Vec<_> = cmd
            .get_args()
            .map(|a| a.to_string_lossy().into_owned())
            .collect();
        assert_eq!(args, ["--write-root", "w", "--", "cmd", "/c", "dir"]);
        assert_eq!(cmd.get_program(), "helper");
        assert!(sandbox.limits().iter().any(|l| l.contains("network")));
    }
}
