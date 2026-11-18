//! Bubblewrap arguments for a `Policy` (Linux).
//!
//! Approach forked from codex (`codex-rs/linux-sandbox/src/bwrap.rs`, Apache-2.0, commit
//! `aa5f492031f7edb75a40973d19eda8efb9512c61`), rewritten against the LARIS `Policy`. Modified by LARIS: no managed
//! proxy, no bundled bubblewrap, no `codex-protocol` types. The function is pure, so it is tested on every platform.

use crate::policy::{Policy, Readable};
use std::ffi::OsString;
use std::path::{Path, PathBuf};

/// System folders a restricted-read policy still shows, when they exist.
const SYSTEM_DIRS: [&str; 7] = ["/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/etc"];

/// The arguments for `bwrap` up to and including `--`, so that the command to run can follow.
///
/// Order matters: a later mount covers an earlier one, so the writable roots come after the read-only base, the
/// protected names after the roots, and the hidden paths last.
#[must_use]
pub fn bwrap_args(policy: &Policy, cwd: &Path) -> Vec<OsString> {
    let mut args: Vec<OsString> = Vec::new();
    let mut push = |items: &[&OsString]| args.extend(items.iter().map(|s| (*s).clone()));
    let flag = |s: &str| OsString::from(s);
    push(&[&flag("--new-session"), &flag("--die-with-parent")]);
    push(&[&flag("--unshare-user"), &flag("--unshare-pid")]);
    push(&[&flag("--unshare-ipc"), &flag("--unshare-uts")]);
    if !policy.network {
        push(&[&flag("--unshare-net")]);
    }
    match &policy.readable {
        Readable::Everything => push(&[&flag("--ro-bind"), &flag("/"), &flag("/")]),
        Readable::Only(roots) => {
            push(&[&flag("--tmpfs"), &flag("/")]);
            for dir in SYSTEM_DIRS.iter().map(Path::new).filter(|d| d.exists()) {
                bind(&mut args, "--ro-bind", dir);
            }
            for root in roots.iter().filter(|r| r.exists()) {
                bind(&mut args, "--ro-bind", root);
            }
        }
    }
    args.extend(["--dev", "/dev", "--proc", "/proc"].map(OsString::from));
    for root in policy.writable.iter().filter(|r| r.exists()) {
        bind(&mut args, "--bind", root);
    }
    for path in policy.protected_paths() {
        bind(&mut args, "--ro-bind", &path);
    }
    for path in policy.deny_read.iter().filter(|p| p.exists()) {
        if path.is_dir() {
            args.extend(["--tmpfs".into(), path.clone().into_os_string()]);
        } else {
            args.extend([
                OsString::from("--ro-bind"),
                OsString::from("/dev/null"),
                path.clone().into_os_string(),
            ]);
        }
    }
    args.extend(["--chdir".into(), PathBuf::from(cwd).into_os_string()]);
    args.push("--".into());
    args
}

fn bind(args: &mut Vec<OsString>, kind: &str, path: &Path) {
    args.extend([
        OsString::from(kind),
        path.as_os_str().to_owned(),
        path.as_os_str().to_owned(),
    ]);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn text(args: &[OsString]) -> String {
        args.iter()
            .map(|a| a.to_string_lossy().into_owned())
            .collect::<Vec<_>>()
            .join(" ")
    }

    #[test]
    fn network_is_cut_unless_allowed() {
        let off = text(&bwrap_args(&Policy::read_only(), Path::new("/")));
        assert!(off.contains("--unshare-net"));
        let on = text(&bwrap_args(
            &Policy::read_only().with_network(true),
            Path::new("/"),
        ));
        assert!(!on.contains("--unshare-net"));
    }

    #[test]
    fn mounts_come_in_covering_order() {
        let dir = std::env::temp_dir().join(format!("laris-bwrap-order-{}", std::process::id()));
        std::fs::create_dir_all(dir.join(".git")).expect("mkdir");
        let secret = dir.join("secret.txt");
        std::fs::write(&secret, "x").expect("write");
        let policy = Policy::workspace([dir.clone()]).with_deny_read([secret.clone()]);
        let args = text(&bwrap_args(&policy, &dir));
        let base = args.find("--ro-bind / /").expect("base");
        let root = args
            .find(&format!("--bind {0} {0}", dir.display()))
            .expect("root");
        let git = args
            .find(&format!("--ro-bind {0}/.git {0}/.git", dir.display()))
            .expect("protected");
        let hidden = args.find("--ro-bind /dev/null").expect("hidden");
        assert!(base < root && root < git && git < hidden, "{args}");
        assert!(args.ends_with("--"));
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn restricted_read_starts_from_an_empty_root() {
        let args = text(&bwrap_args(
            &Policy::read_only().with_readable_only([]),
            Path::new("/"),
        ));
        assert!(args.contains("--tmpfs /"));
        assert!(!args.contains("--ro-bind / /"));
    }
}
