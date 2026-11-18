//! The in-process restrictions of the helper binary (Linux): `no_new_privs`, a seccomp filter, and the Landlock
//! fallback for machines where bubblewrap cannot run.
//!
//! Approach forked from codex (`codex-rs/linux-sandbox/src/seccomp.rs` and `codex-rs/sandboxing/src/landlock.rs`,
//! Apache-2.0, commit `aa5f492031f7edb75a40973d19eda8efb9512c61`). Modified by LARIS: only the filters LARIS needs, the
//! `libc::prctl` call replaced by `rustix` (the workspace forbids `unsafe`), no managed proxy and no WSL special case.
//!
//! The helper is started inside bubblewrap (or alone, for the fallback). It restricts itself and then replaces itself
//! with the command, so the command inherits the restrictions and nothing else runs in between.

use crate::policy::SandboxError;
use std::path::PathBuf;

/// What the helper must apply before it runs the command.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Restrictions {
    /// Refuse sockets other than local ones.
    pub deny_network: bool,
    /// Apply a Landlock ruleset (bubblewrap does the filesystem when this is off).
    pub landlock: bool,
    /// The Landlock write roots; reads are allowed everywhere. Empty with `landlock` on means nothing is writable.
    pub landlock_writable: Vec<PathBuf>,
}

/// Command-line form of `Restrictions`, ending with `--` before the command.
#[must_use]
pub fn helper_args(r: &Restrictions) -> Vec<std::ffi::OsString> {
    let mut args = Vec::new();
    if r.deny_network {
        args.push("--deny-network".into());
    }
    if r.landlock {
        args.push("--landlock".into());
    }
    for root in &r.landlock_writable {
        args.push("--landlock-writable".into());
        args.push(root.clone().into_os_string());
    }
    args.push("--".into());
    args
}

/// Reads the helper's arguments: the restrictions and the command.
///
/// # Errors
/// An unknown flag, a missing value or an empty command.
pub fn parse_args(
    args: impl IntoIterator<Item = std::ffi::OsString>,
) -> Result<(Restrictions, Vec<std::ffi::OsString>), SandboxError> {
    let mut r = Restrictions::default();
    let mut iter = args.into_iter();
    while let Some(arg) = iter.next() {
        match arg.to_str() {
            Some("--deny-network") => r.deny_network = true,
            Some("--landlock") => r.landlock = true,
            Some("--landlock-writable") => r.landlock_writable.push(
                iter.next()
                    .ok_or_else(|| {
                        SandboxError::Unsupported("--landlock-writable needs a path".into())
                    })?
                    .into(),
            ),
            Some("--") => {
                let command: Vec<_> = iter.collect();
                if command.is_empty() {
                    return Err(SandboxError::Unsupported("no command after --".into()));
                }
                return Ok((r, command));
            }
            _ => {
                return Err(SandboxError::Unsupported(format!(
                    "unknown helper flag {arg:?}"
                )));
            }
        }
    }
    Err(SandboxError::Unsupported("no -- before the command".into()))
}

/// Applies the restrictions to the current process. Linux only.
///
/// # Errors
/// The kernel refused a filter, or Landlock is not enforced here.
#[cfg(target_os = "linux")]
pub fn apply(r: &Restrictions) -> Result<(), SandboxError> {
    use landlock::{
        ABI, Access, AccessFs, CompatLevel, Compatible, Ruleset, RulesetAttr, RulesetCreatedAttr,
    };

    rustix::thread::set_no_new_privs(true)
        .map_err(|e| SandboxError::io("no_new_privs", e.into()))?;
    install_seccomp(r.deny_network)?;
    if r.landlock {
        let abi = ABI::V5;
        let all = AccessFs::from_all(abi);
        let read = AccessFs::from_read(abi);
        let fail = |e: &dyn std::fmt::Display| SandboxError::Unavailable(format!("landlock: {e}"));
        let mut set = Ruleset::default()
            .set_compatibility(CompatLevel::BestEffort)
            .handle_access(all)
            .map_err(|e| fail(&e))?
            .create()
            .map_err(|e| fail(&e))?
            .add_rules(landlock::path_beneath_rules(["/"], read))
            .map_err(|e| fail(&e))?
            .add_rules(landlock::path_beneath_rules(["/dev"], all))
            .map_err(|e| fail(&e))?;
        let roots: Vec<&PathBuf> = r.landlock_writable.iter().filter(|p| p.exists()).collect();
        set = set
            .add_rules(landlock::path_beneath_rules(roots, all))
            .map_err(|e| fail(&e))?;
        let status = set.restrict_self().map_err(|e| fail(&e))?;
        if status.ruleset == landlock::RulesetStatus::NotEnforced {
            return Err(SandboxError::Unavailable(
                "landlock is not enforced by this kernel".into(),
            ));
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn install_seccomp(deny_network: bool) -> Result<(), SandboxError> {
    use seccompiler::{
        BpfProgram, SeccompAction, SeccompCmpArgLen, SeccompCmpOp, SeccompCondition, SeccompFilter,
        SeccompRule, TargetArch,
    };
    use std::collections::BTreeMap;

    let arch = if cfg!(target_arch = "x86_64") {
        TargetArch::x86_64
    } else if cfg!(target_arch = "aarch64") {
        TargetArch::aarch64
    } else {
        return Err(SandboxError::Unsupported(
            "seccomp is wired for x86_64 and aarch64 only".into(),
        ));
    };
    let eperm = SeccompAction::Errno(libc::EPERM as u32);
    let mut rules: BTreeMap<i64, Vec<SeccompRule>> = BTreeMap::new();
    // Syscalls that reach outside the sandbox or other processes. An empty rule list matches every call.
    for nr in [
        libc::SYS_ptrace,
        libc::SYS_process_vm_readv,
        libc::SYS_process_vm_writev,
        libc::SYS_perf_event_open,
        libc::SYS_bpf,
        libc::SYS_userfaultfd,
        libc::SYS_kexec_load,
        libc::SYS_add_key,
        libc::SYS_request_key,
        libc::SYS_keyctl,
        libc::SYS_io_uring_setup,
        libc::SYS_io_uring_enter,
        libc::SYS_io_uring_register,
    ] {
        rules.insert(nr, vec![]);
    }
    if deny_network {
        // Local sockets stay (many tools need them); every other family is refused.
        let not_local = SeccompCondition::new(
            0,
            SeccompCmpArgLen::Dword,
            SeccompCmpOp::Ne,
            libc::AF_UNIX as u64,
        )
        .map_err(|e| SandboxError::Unavailable(format!("seccomp: {e}")))?;
        rules.insert(
            libc::SYS_socket,
            vec![
                SeccompRule::new(vec![not_local])
                    .map_err(|e| SandboxError::Unavailable(format!("seccomp: {e}")))?,
            ],
        );
    }
    let filter = SeccompFilter::new(rules, SeccompAction::Allow, eperm, arch)
        .map_err(|e| SandboxError::Unavailable(format!("seccomp: {e}")))?;
    let program: BpfProgram = filter.try_into().map_err(|e: seccompiler::BackendError| {
        SandboxError::Unavailable(format!("seccomp: {e}"))
    })?;
    seccompiler::apply_filter_all_threads(&program)
        .map_err(|e| SandboxError::Unavailable(format!("seccomp: {e}")))
}

/// Applies the restrictions on a platform that has no helper stage.
///
/// # Errors
/// Always: only Linux has this stage.
#[cfg(not(target_os = "linux"))]
pub fn apply(_: &Restrictions) -> Result<(), SandboxError> {
    Err(SandboxError::Unsupported(
        "the helper stage exists on Linux only".into(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn arguments_round_trip() {
        let r = Restrictions {
            deny_network: true,
            landlock: true,
            landlock_writable: vec![PathBuf::from("/work")],
        };
        let mut args = helper_args(&r);
        args.extend(["echo".into(), "hi".into()]);
        let (back, command) = parse_args(args).expect("parse");
        assert_eq!(back, r);
        assert_eq!(command, vec!["echo", "hi"]);
    }

    #[test]
    fn bad_arguments_are_refused() {
        assert!(parse_args(["--bogus".into()]).is_err());
        assert!(parse_args(["--".into()]).is_err());
        assert!(parse_args(["--landlock-writable".into()]).is_err());
    }
}
