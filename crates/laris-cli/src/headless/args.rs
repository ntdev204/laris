//! The command line of `laris -p` (SR-C5): what is asked, in which format, with which permissions.

use laris_config::settings::PermissionMode;

/// What is written to standard output.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Format {
    /// The final answer only.
    Text,
    /// One JSON object when the turn ends.
    Json,
    /// One core event per line (JSON lines), as they happen.
    StreamJson,
}

/// Which session the request goes into.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Resume {
    /// A new session.
    New,
    /// The latest session of this project.
    Continue,
    /// This session.
    Session(String),
}

/// A parsed `laris -p` command line.
#[derive(Debug, Clone, PartialEq)]
pub struct Options {
    /// The request given as an argument; standard input is added to it or stands in for it.
    pub prompt: Option<String>,
    /// The output format.
    pub format: Format,
    /// The session.
    pub resume: Resume,
    /// Model calls allowed in the turn (`agent.maxSteps` when absent).
    pub max_turns: Option<String>,
    /// The permission mode of this run.
    pub mode: Option<PermissionMode>,
    /// Rules that allow, added to the settings'.
    pub allowed: Vec<String>,
    /// Rules that deny, added to the settings'.
    pub disallowed: Vec<String>,
}

/// The usage text.
pub const USAGE: &str = "usage: laris -p [REQUEST] [--output-format text|json|stream-json] [--continue | --resume ID] \
[--max-turns N] [--permission-mode default|acceptEdits|plan|bypass] [--allowedTools RULES] [--disallowedTools RULES]\n\
the request may also be piped in; exit codes: 0 done, 1 failed, 2 usage, 3 not signed in, 4 turn limit reached, 5 no such session";

/// Splits a list of rules on commas and white space that are not inside parentheses, so `Bash(git log --oneline)`
/// stays one rule.
pub fn split_rules(list: &str) -> Vec<String> {
    let mut rules = Vec::new();
    let mut current = String::new();
    let mut depth = 0usize;
    for c in list.chars() {
        match c {
            '(' => {
                depth += 1;
                current.push(c);
            }
            ')' => {
                depth = depth.saturating_sub(1);
                current.push(c);
            }
            ',' | ' ' | '\t' | '\n' if depth == 0 => {
                if !current.is_empty() {
                    rules.push(std::mem::take(&mut current));
                }
            }
            _ => current.push(c),
        }
    }
    if !current.is_empty() {
        rules.push(current);
    }
    rules
}

fn mode_of(text: &str) -> Result<PermissionMode, String> {
    match text {
        "default" => Ok(PermissionMode::Default),
        "acceptEdits" => Ok(PermissionMode::AcceptEdits),
        "plan" => Ok(PermissionMode::Plan),
        "bypass" => Ok(PermissionMode::Bypass),
        other => Err(format!(
            "unknown permission mode {other:?}; use default, acceptEdits, plan or bypass"
        )),
    }
}

fn format_of(text: &str) -> Result<Format, String> {
    match text {
        "text" => Ok(Format::Text),
        "json" => Ok(Format::Json),
        "stream-json" => Ok(Format::StreamJson),
        other => Err(format!(
            "unknown output format {other:?}; use text, json or stream-json"
        )),
    }
}

/// Parses the arguments after the program name. `Ok(None)` when there is no `-p` / `--print`: this is not a
/// headless run.
pub fn parse(args: &[String]) -> Result<Option<Options>, String> {
    if !args.iter().any(|a| a == "-p" || a == "--print") {
        return Ok(None);
    }
    let mut options = Options {
        prompt: None,
        format: Format::Text,
        resume: Resume::New,
        max_turns: None,
        mode: None,
        allowed: Vec::new(),
        disallowed: Vec::new(),
    };
    let mut words: Vec<String> = Vec::new();
    let mut continued = false;
    let mut resumed = false;
    let mut iter = args.iter();
    while let Some(arg) = iter.next() {
        let (name, inline) = match arg.split_once('=') {
            Some((n, v)) if n.starts_with("--") => (n, Some(v.to_owned())),
            _ => (arg.as_str(), None),
        };
        let mut value = |flag: &str| -> Result<String, String> {
            match inline.clone().or_else(|| iter.next().cloned()) {
                Some(v) => Ok(v),
                None => Err(format!("{flag} needs a value")),
            }
        };
        match name {
            "-p" | "--print" => {}
            "-c" | "--continue" => continued = true,
            "-r" | "--resume" => {
                resumed = true;
                options.resume = Resume::Session(value(name)?);
            }
            "--output-format" => options.format = format_of(&value(name)?)?,
            "--max-turns" => options.max_turns = Some(value(name)?),
            "--permission-mode" => options.mode = Some(mode_of(&value(name)?)?),
            "--allowedTools" | "--allowed-tools" => {
                options.allowed.extend(split_rules(&value(name)?));
            }
            "--disallowedTools" | "--disallowed-tools" => {
                options.disallowed.extend(split_rules(&value(name)?));
            }
            "--" => {
                words.extend(iter.by_ref().cloned());
            }
            flag if flag.starts_with('-') && flag.len() > 1 => {
                return Err(format!("unknown option {flag}"));
            }
            _ => words.push(arg.clone()),
        }
    }
    if continued && resumed {
        return Err("--continue and --resume cannot be used together".to_owned());
    }
    if continued {
        options.resume = Resume::Continue;
    }
    if !words.is_empty() {
        options.prompt = Some(words.join(" "));
    }
    Ok(Some(options))
}
