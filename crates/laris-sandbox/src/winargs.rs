//! The parts of the Windows backend that are plain text and so build and test on every platform: the helper's
//! command line, the quoting of a Windows command line, and the per-user capability SID.

use crate::policy::SandboxError;
use sha2::{Digest, Sha256};
use std::ffi::OsString;
use std::path::PathBuf;

/// What the Windows helper must apply before it starts the command.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct WindowsRestrictions {
    /// Folders the command may write (their contents too).
    pub write_roots: Vec<PathBuf>,
    /// Paths inside a write root that stay read-only (`.git`, `.laris`).
    pub protected: Vec<PathBuf>,
}

/// Command-line form of the restrictions, ending with `--` before the command.
#[must_use]
pub fn helper_args(r: &WindowsRestrictions) -> Vec<OsString> {
    let mut args = Vec::new();
    for root in &r.write_roots {
        args.push("--write-root".into());
        args.push(root.clone().into_os_string());
    }
    for path in &r.protected {
        args.push("--protect".into());
        args.push(path.clone().into_os_string());
    }
    args.push("--".into());
    args
}

/// Reads the Windows helper's arguments: the restrictions and the command.
///
/// # Errors
/// An unknown flag, a missing value or an empty command.
pub fn parse_args(
    args: impl IntoIterator<Item = OsString>,
) -> Result<(WindowsRestrictions, Vec<OsString>), SandboxError> {
    let mut r = WindowsRestrictions::default();
    let mut iter = args.into_iter();
    while let Some(arg) = iter.next() {
        let target = match arg.to_str() {
            Some("--write-root") => &mut r.write_roots,
            Some("--protect") => &mut r.protected,
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
        };
        let value = iter
            .next()
            .ok_or_else(|| SandboxError::Unsupported(format!("{arg:?} needs a path")))?;
        target.push(value.into());
    }
    Err(SandboxError::Unsupported("no -- before the command".into()))
}

/// Quotes one argument for a Windows command line (the rules of `CommandLineToArgvW` / the MSVC runtime), as UTF-16.
#[must_use]
pub fn quote_arg(arg: &[u16]) -> Vec<u16> {
    let plain = !arg.is_empty()
        && !arg
            .iter()
            .any(|&c| c == u16::from(b' ') || c == u16::from(b'\t') || c == u16::from(b'"'));
    if plain {
        return arg.to_vec();
    }
    let (quote, backslash) = (u16::from(b'"'), u16::from(b'\\'));
    let mut out = vec![quote];
    let mut slashes = 0usize;
    for &c in arg {
        if c == backslash {
            slashes += 1;
            continue;
        }
        if c == quote {
            // backslashes before a quote are doubled, and the quote itself is escaped
            out.extend(std::iter::repeat_n(backslash, slashes * 2 + 1));
        } else {
            out.extend(std::iter::repeat_n(backslash, slashes));
        }
        slashes = 0;
        out.push(c);
    }
    // backslashes before the closing quote are doubled
    out.extend(std::iter::repeat_n(backslash, slashes * 2));
    out.push(quote);
    out
}

/// The whole command line for `CreateProcess`: the arguments quoted and joined by spaces, without a trailing NUL.
#[must_use]
pub fn command_line(args: &[Vec<u16>]) -> Vec<u16> {
    let mut line = Vec::new();
    for (i, arg) in args.iter().enumerate() {
        if i > 0 {
            line.push(u16::from(b' '));
        }
        line.extend(quote_arg(arg));
    }
    line
}

/// The capability SID of `user_sid` as a string: a stable identity (derived from the user, not stored) that is
/// granted write on the writable roots and is the restricting SID of the command's token.
#[must_use]
pub fn capability_sid(user_sid: &str) -> String {
    let digest = Sha256::digest(format!("laris-sandbox-capability-v1:{user_sid}").as_bytes());
    let part =
        |i: usize| u32::from_le_bytes([digest[i], digest[i + 1], digest[i + 2], digest[i + 3]]);
    format!("S-1-5-21-{}-{}-{}-1500", part(0), part(4), part(8))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn w(s: &str) -> Vec<u16> {
        s.encode_utf16().collect()
    }
    fn q(s: &str) -> String {
        String::from_utf16(&quote_arg(&w(s))).expect("utf16")
    }

    #[test]
    fn quoting_follows_the_msvc_rules() {
        assert_eq!(q("abc"), "abc");
        assert_eq!(q(""), "\"\"");
        assert_eq!(q("a b"), "\"a b\"");
        assert_eq!(q(r#"a"b"#), r#""a\"b""#);
        assert_eq!(q(r"C:\dir\"), r"C:\dir\"); // no space: left alone
        assert_eq!(q(r"C:\my dir\"), r#""C:\my dir\\""#); // trailing backslashes doubled before the closing quote
        assert_eq!(q(r#"a\"b"#), r#""a\\\"b""#);
    }

    #[test]
    fn command_line_joins_quoted_arguments() {
        let line = command_line(&[w("cmd"), w("/c"), w("echo hi there")]);
        assert_eq!(
            String::from_utf16(&line).unwrap(),
            "cmd /c \"echo hi there\""
        );
    }

    #[test]
    fn helper_arguments_round_trip() {
        let r = WindowsRestrictions {
            write_roots: vec![PathBuf::from(r"C:\work")],
            protected: vec![PathBuf::from(r"C:\work\.git")],
        };
        let mut args = helper_args(&r);
        args.extend(["cmd".into(), "/c".into(), "dir".into()]);
        let (back, command) = parse_args(args).expect("parse");
        assert_eq!(back, r);
        assert_eq!(command, vec!["cmd", "/c", "dir"]);
        assert!(parse_args(["--bogus".into()]).is_err());
        assert!(parse_args(["--".into()]).is_err());
        assert!(parse_args(["--write-root".into()]).is_err());
    }

    #[test]
    fn capability_sid_is_stable_per_user_and_differs_between_users() {
        let a = capability_sid("S-1-5-21-1-2-3-1001");
        assert_eq!(a, capability_sid("S-1-5-21-1-2-3-1001"));
        assert_ne!(a, capability_sid("S-1-5-21-1-2-3-1002"));
        assert!(a.starts_with("S-1-5-21-") && a.ends_with("-1500"));
    }
}
