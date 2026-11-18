//! Permission rules: `Tool` or `Tool(pattern)`, and whether one fits a call.
//!
//! The tool name is compared without regard to case (`Edit(src/**)` fits the `Edit` tool). The pattern is matched
//! against what the call acts on: the command of a shell tool, else the resolved path, else the first text argument.
//!
//! * A path is matched resolved (`..` and symbolic links followed), never as written: `src/../secret` is not inside
//!   `src/`.
//! * A command line holding several commands (`&&`, `;`, `|`, a substitution, a redirection) is not let through by
//!   a rule written for one: an `allow` rule must fit every command of it, while a `deny` or `ask` rule fits when
//!   any command of it does, so chaining cannot dodge them.

use laris_tools::{Scope, glob_to_regex};
use regex::Regex;
use serde_json::{Map, Value};
use std::sync::OnceLock;

/// A parsed rule.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Rule {
    /// Lower-cased tool name, or `*`.
    pub tool: String,
    /// The pattern in the parentheses, if any.
    pub pattern: Option<String>,
}

fn rule_shape() -> &'static Regex {
    static SHAPE: OnceLock<Regex> = OnceLock::new();
    SHAPE.get_or_init(|| {
        Regex::new(r"(?s)^\s*([A-Za-z_*][\w*]*)\s*(?:\((.*)\))?\s*$").expect("a fixed pattern")
    })
}

fn parts_pattern() -> &'static Regex {
    static PARTS: OnceLock<Regex> = OnceLock::new();
    PARTS.get_or_init(|| {
        Regex::new(r"&&|\|\||[;|&\n\r]|\$\(|`|<\(|>\(|[(){}]").expect("a fixed pattern")
    })
}

fn redirect_pattern() -> &'static Regex {
    static REDIRECT: OnceLock<Regex> = OnceLock::new();
    REDIRECT.get_or_init(|| Regex::new(r"\$\(|`|<\(|>\(|[<>]|\n|\r").expect("a fixed pattern"))
}

/// `Edit(src/**)` is (`edit`, `src/**`); `Bash` is (`bash`, none); anything else is `None`.
pub fn parse_rule(text: &str) -> Option<Rule> {
    let found = rule_shape().captures(text)?;
    Some(Rule {
        tool: found[1].to_lowercase(),
        pattern: found.get(2).map(|p| p.as_str().trim().to_owned()),
    })
}

/// What a call acts on.
enum Subject {
    Command(String),
    Path(String),
    Text(String),
}

fn subject(arguments: &Map<String, Value>) -> Subject {
    if let Some(command) = arguments.get("command").and_then(Value::as_str) {
        return Subject::Command(command.trim().to_owned());
    }
    for key in ["path", "file_path"] {
        if let Some(path) = arguments.get(key).and_then(Value::as_str) {
            return Subject::Path(path.to_owned());
        }
    }
    let first = arguments.values().find_map(Value::as_str);
    Subject::Text(first.unwrap_or_default().to_owned())
}

/// Shell-style matching: `*` any run, `?` one character, `[abc]` a set.
fn fnmatch(pattern: &str, value: &str) -> bool {
    let mut out = String::from("(?s)^");
    let chars: Vec<char> = pattern.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        match chars[i] {
            '*' => out.push_str(".*"),
            '?' => out.push('.'),
            '[' => match chars[i + 1..].iter().position(|&c| c == ']') {
                Some(offset) if offset > 0 => {
                    let close = i + 1 + offset;
                    out.push('[');
                    let mut j = i + 1;
                    if matches!(chars[j], '!' | '^') {
                        out.push('^');
                        j += 1;
                    }
                    for &c in &chars[j..close] {
                        if matches!(c, '\\' | '[' | ']' | '&' | '~') {
                            out.push('\\');
                        }
                        out.push(c);
                    }
                    out.push(']');
                    i = close;
                }
                _ => out.push_str("\\["),
            },
            c => out.push_str(&regex::escape(&c.to_string())),
        }
        i += 1;
    }
    out.push('$');
    Regex::new(&out).is_ok_and(|re| re.is_match(value))
}

fn command_matches(pattern: &str, value: &str) -> bool {
    match pattern.strip_suffix(":*") {
        // a command prefix on a word boundary: `git status:*`
        Some(prefix) => value == prefix || value.starts_with(&format!("{prefix} ")),
        None => fnmatch(pattern, value),
    }
}

/// The commands of a command line, split at the shell's separators.
pub(crate) fn command_parts(value: &str) -> Vec<String> {
    parts_pattern()
        .split(value)
        .map(str::trim)
        .filter(|p| !p.is_empty())
        .map(str::to_owned)
        .collect()
}

/// Whether the command line holds a redirection or a substitution.
pub(crate) fn has_redirect_or_substitution(value: &str) -> bool {
    redirect_pattern().is_match(value)
}

fn command_pattern_matches(pattern: &str, value: &str, any_part: bool) -> bool {
    if !parts_pattern().is_match(value) && !redirect_pattern().is_match(value) {
        return command_matches(pattern, value);
    }
    if any_part {
        return command_matches(pattern, value)
            || command_parts(value)
                .iter()
                .any(|part| command_matches(pattern, part));
    }
    if pattern == "*" {
        return true;
    }
    if redirect_pattern().is_match(value) {
        // only a rule that spells the whole line out
        return value == pattern;
    }
    command_parts(value)
        .iter()
        .all(|part| command_matches(pattern, part))
}

fn pattern_matches(
    pattern: &str,
    arguments: &Map<String, Value>,
    scope: &Scope,
    any_part: bool,
) -> bool {
    match subject(arguments) {
        Subject::Command(value) => command_pattern_matches(pattern, &value, any_part),
        Subject::Path(value) => {
            let Some(resolved) = scope.locate(&value) else {
                return false;
            };
            let mut candidates = vec![resolved.to_string_lossy().replace('\\', "/")];
            candidates.extend(scope.relative_to_root(&resolved));
            let wanted = pattern.strip_prefix("./").unwrap_or(pattern);
            glob_to_regex(wanted).is_some_and(|re| candidates.iter().any(|c| re.is_match(c)))
        }
        Subject::Text(value) => fnmatch(pattern, &value),
    }
}

/// Whether `rule` fits the call of `tool` with `arguments`. With `any_part` (`deny` and `ask` rules) a rule fits a
/// command line when it fits any command in it.
pub fn rule_matches(
    rule: &str,
    tool: &str,
    arguments: &Map<String, Value>,
    scope: &Scope,
    any_part: bool,
) -> bool {
    let Some(parsed) = parse_rule(rule) else {
        return false;
    };
    if parsed.tool != "*" && parsed.tool != tool.trim().to_lowercase() {
        return false;
    }
    parsed
        .pattern
        .is_none_or(|pattern| pattern_matches(&pattern, arguments, scope, any_part))
}

/// The rule an "always allow" answer would save for this call: `bash(git status:*)`, `write(src/a.rs)`, `search`.
pub fn suggest_rule(tool: &str, arguments: &Map<String, Value>) -> String {
    let name = tool.trim().to_lowercase();
    match subject(arguments) {
        Subject::Command(value) if !value.is_empty() => {
            let words: Vec<&str> = value.split_whitespace().collect();
            match words.as_slice() {
                [] => name,
                [first, second, ..] if !second.starts_with('-') => {
                    format!("{name}({first} {second}:*)")
                }
                [first, ..] => format!("{name}({first}:*)"),
            }
        }
        Subject::Path(value) if !value.is_empty() => format!("{name}({value})"),
        _ => name,
    }
}
