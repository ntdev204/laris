//! `save_memory` and `use_skill`.

use crate::args::{object_schema, opt_bool, opt_string, string};
use crate::context::Context;
use crate::error::ToolError;
use crate::files::{read_text, write_atomic};
use crate::registry::LocalTool;
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};
use std::sync::Arc;

type Args = Map<String, Value>;

/// A memory or skill name: lowercase letters, digits, `-` and `_` (`_` only for memory), starting with a letter or
/// digit, at most 64 characters.
fn valid_name(name: &str, underscore: bool) -> bool {
    let mut chars = name.chars();
    chars
        .next()
        .is_some_and(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
        && name.len() <= 64
        && chars.all(|c| {
            c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-' || (underscore && c == '_')
        })
}

pub(crate) fn tools(ctx: &Arc<Context>) -> Vec<LocalTool> {
    vec![save_memory(ctx), use_skill(ctx)]
}

fn save_memory(ctx: &Arc<Context>) -> LocalTool {
    let ctx = Arc::clone(ctx);
    LocalTool::new(
        "save_memory",
        "Save a short note to the project memory folder (needs approval).",
        object_schema(
            json!({"name": {"type": "string"}, "content": {"type": "string"}, "append": {"type": "boolean"}}),
            &["name", "content"],
        ),
        true,
        false,
        move |args: &Args| {
            let Some(folder) = &ctx.memory_dir else {
                return Err(ToolError::new(
                    "no_memory",
                    "there is no memory folder for this project",
                ));
            };
            let raw = string(args, "name")?.trim();
            let name = raw.strip_suffix(".md").unwrap_or(raw);
            if !valid_name(name, true) {
                return Err(ToolError::new(
                    "invalid_arguments",
                    "name: lowercase letters, digits, - or _ (at most 64)",
                ));
            }
            let content = (ctx.redact)(string(args, "content")?.trim());
            if content.is_empty() {
                return Err(ToolError::new(
                    "invalid_arguments",
                    "content must not be empty",
                ));
            }
            let path = folder.join(format!("{name}.md"));
            let existing = path
                .is_file()
                .then(|| read_text(&path, ctx.limits.edit_max_bytes))
                .transpose()?;
            let append = opt_bool(args, "append").unwrap_or(true);
            let (text, mode) = match existing {
                Some(old) if append => (format!("{}\n\n{content}\n", old.trim_end()), "appended"),
                Some(_) => (format!("{content}\n"), "replaced"),
                None => (format!("{content}\n"), "created"),
            };
            if text.len() as u64 > ctx.limits.edit_max_bytes {
                return Err(ToolError::new(
                    "too_large",
                    "the memory note would be too large",
                ));
            }
            let saved = ctx
                .checkpoints
                .as_ref()
                .map(|c| c.record(&path, "save_memory"))
                .transpose()?;
            if let Err(error) = write_atomic(&path, &text) {
                if let (Some(c), Some(seq)) = (&ctx.checkpoints, saved) {
                    c.discard(seq);
                }
                return Err(error);
            }
            Ok(json!({"path": format!("memory/{name}.md"), "mode": mode}))
        },
    )
}

/// A skill: `<folder>/<name>/SKILL.md` with `name` and `description` in the front matter.
struct Skill {
    description: String,
    body: String,
    folder: PathBuf,
}

/// The value of `key` in a front matter: one line, or a block (`>`, `|`, or indented lines) joined by spaces.
fn front_value(front: &str, key: &str) -> Option<String> {
    let lines: Vec<&str> = front.lines().collect();
    let prefix = format!("{key}:");
    let at = lines.iter().position(|l| l.starts_with(&prefix))?;
    let mut parts = vec![lines[at][prefix.len()..].trim().to_owned()];
    for line in &lines[at + 1..] {
        if line.starts_with(' ') || line.starts_with('\t') {
            parts.push(line.trim().to_owned());
        } else {
            break;
        }
    }
    let joined = parts
        .iter()
        .filter(|p| !matches!(p.as_str(), ">" | "|" | ">-" | "|-" | ""))
        .cloned()
        .collect::<Vec<_>>()
        .join(" ");
    Some(joined.trim_matches(|c| c == '"' || c == '\'').to_owned())
}

fn load_skill(folder: &Path, name: &str) -> Result<Skill, ToolError> {
    let file = folder.join("SKILL.md");
    let bad = |why: &str| ToolError::new("invalid_skill", format!("skill `{name}`: {why}"));
    let text = read_text(&file, 1 << 20)?;
    let rest = text
        .strip_prefix("---")
        .ok_or_else(|| bad("missing front matter"))?;
    let (front, body) = rest
        .split_once("\n---")
        .ok_or_else(|| bad("front matter is not closed"))?;
    if front_value(front, "name").as_deref() != Some(name) {
        return Err(bad("the name in the front matter must match the folder"));
    }
    let description = front_value(front, "description")
        .filter(|d| !d.is_empty())
        .ok_or_else(|| bad("no description"))?;
    let body = body.trim().to_owned();
    if body.is_empty() {
        return Err(bad("empty instructions"));
    }
    Ok(Skill {
        description,
        body,
        folder: folder.to_path_buf(),
    })
}

fn references(folder: &Path) -> Vec<Value> {
    let mut found = Vec::new();
    let mut stack = vec![folder.join("references")];
    while let Some(dir) = stack.pop() {
        let Ok(read) = std::fs::read_dir(&dir) else {
            continue;
        };
        for entry in read.filter_map(Result::ok) {
            let path = entry.path();
            match entry.file_type() {
                Ok(kind) if kind.is_dir() => stack.push(path),
                Ok(kind) if kind.is_file() => {
                    if let (Ok(relative), Ok(meta)) = (path.strip_prefix(folder), entry.metadata())
                    {
                        let shown = relative
                            .components()
                            .map(|c| c.as_os_str().to_string_lossy())
                            .collect::<Vec<_>>()
                            .join("/");
                        found.push(json!({"path": shown, "bytes": meta.len()}));
                    }
                }
                _ => {}
            }
        }
    }
    found.sort_by_key(|v| v["path"].as_str().map(str::to_owned));
    found
}

fn use_skill(ctx: &Arc<Context>) -> LocalTool {
    let ctx = Arc::clone(ctx);
    LocalTool::new(
        "use_skill",
        "Load a skill's instructions (see the Skills list in the system prompt).",
        object_schema(
            json!({"name": {"type": "string"}, "arguments": {"type": "string"}}),
            &["name"],
        ),
        false,
        false,
        move |args: &Args| {
            let wanted = string(args, "name")?
                .trim()
                .trim_start_matches('/')
                .to_lowercase();
            let mut known = Vec::new();
            for dir in &ctx.skill_dirs {
                let Ok(read) = std::fs::read_dir(dir) else {
                    continue;
                };
                let mut names: Vec<String> = read
                    .filter_map(Result::ok)
                    .filter(|e| e.path().join("SKILL.md").is_file())
                    .filter_map(|e| e.file_name().into_string().ok())
                    .filter(|n| valid_name(n, false))
                    .collect();
                names.sort();
                if names.contains(&wanted) {
                    let skill = load_skill(&dir.join(&wanted), &wanted)?;
                    let limit = usize::try_from(ctx.limits.skill_max_chars).unwrap_or(usize::MAX);
                    let truncated = skill.body.chars().count() > limit;
                    return Ok(json!({
                        "name": wanted,
                        "description": skill.description,
                        "instructions": skill.body.chars().take(limit).collect::<String>(),
                        "truncated": truncated,
                        "arguments": opt_string(args, "arguments").unwrap_or(""),
                        "references": references(&skill.folder),
                    }));
                }
                known.extend(names);
            }
            known.sort();
            known.dedup();
            let list = if known.is_empty() {
                "none".to_owned()
            } else {
                known.join(", ")
            };
            Err(ToolError::new(
                "unknown_skill",
                format!("unknown skill '{wanted}' (available: {list})"),
            ))
        },
    )
}
