//! What an approval shows: for a file, a diff of what the call would change.

use laris_tools::Scope;
use serde_json::{Map, Value};

/// Lines of a preview kept.
const MAX_LINES: usize = 80;
/// Most lines compared; a longer file gets a summary instead of a diff.
const MAX_COMPARED: usize = 2_000;

/// The preview of a `Write` or `Edit` call; `None` for any other tool.
pub fn preview(tool: &str, arguments: &Map<String, Value>, scope: &Scope) -> Option<String> {
    let path = arguments.get("path").and_then(Value::as_str)?;
    let shown = scope
        .relative_to_root(&scope.locate(path)?)
        .unwrap_or_else(|| path.to_owned());
    match tool.to_lowercase().as_str() {
        "write" => {
            let new = arguments.get("content").and_then(Value::as_str)?;
            let old = scope
                .locate(path)
                .and_then(|p| std::fs::read_to_string(p).ok());
            Some(match old {
                Some(old) => diff(&shown, &old, new),
                None => diff(&shown, "", new),
            })
        }
        "edit" => {
            let old = arguments.get("old_string").and_then(Value::as_str)?;
            let new = arguments.get("new_string").and_then(Value::as_str)?;
            Some(diff(&shown, old, new))
        }
        _ => None,
    }
}

/// A line diff: `-` removed, `+` added, no context; the common head and tail are left out.
pub fn diff(name: &str, old: &str, new: &str) -> String {
    let before: Vec<&str> = old.lines().collect();
    let after: Vec<&str> = new.lines().collect();
    let head = before
        .iter()
        .zip(&after)
        .take_while(|(a, b)| a == b)
        .count();
    let tail = before[head..]
        .iter()
        .rev()
        .zip(after[head..].iter().rev())
        .take_while(|(a, b)| a == b)
        .count();
    let removed = &before[head..before.len() - tail];
    let added = &after[head..after.len() - tail];
    let mut out = vec![format!("--- {name}"), format!("+++ {name}")];
    if removed.len() > MAX_COMPARED || added.len() > MAX_COMPARED {
        out.push(format!(
            "{} lines replaced by {} lines",
            removed.len(),
            added.len()
        ));
    } else {
        out.push(format!("@@ line {} @@", head + 1));
        out.extend(removed.iter().map(|l| format!("-{l}")));
        out.extend(added.iter().map(|l| format!("+{l}")));
    }
    if out.len() > MAX_LINES {
        let more = out.len() - MAX_LINES;
        out.truncate(MAX_LINES);
        out.push(format!("… ({more} more lines)"));
    }
    out.join("\n")
}
