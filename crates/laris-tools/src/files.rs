//! `Read`, `Write` and `Edit`.

use crate::args::{object_schema, opt_bool, opt_u64, string};
use crate::context::Context;
use crate::error::ToolError;
use crate::registry::LocalTool;
use serde_json::{Map, Value, json};
use std::path::Path;
use std::sync::Arc;

type Args = Map<String, Value>;

/// Reads a text file as UTF-8 (invalid bytes replaced); refuses files over `limit` bytes and binary files.
pub(crate) fn read_text(path: &Path, limit: u64) -> Result<String, ToolError> {
    let size = std::fs::metadata(path)
        .map_err(|e| ToolError::io("unreadable", "cannot read the file", &e))?
        .len();
    if size > limit {
        return Err(ToolError::new(
            "too_large",
            format!("the file is larger than {limit} bytes"),
        ));
    }
    let data =
        std::fs::read(path).map_err(|e| ToolError::io("unreadable", "cannot read the file", &e))?;
    if data.iter().take(8192).any(|b| *b == 0) {
        return Err(ToolError::new("binary", "this looks like a binary file"));
    }
    Ok(String::from_utf8_lossy(&data).into_owned())
}

/// Replaces `path` with `text` in one step (a temporary file, then a rename), keeping its permissions.
pub(crate) fn write_atomic(path: &Path, text: &str) -> Result<(), ToolError> {
    let io = |e: std::io::Error| ToolError::io("write_failed", "cannot write the file", &e);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(io)?;
    }
    let mut temp = path.as_os_str().to_owned();
    temp.push(".laris-tmp");
    let temp = std::path::PathBuf::from(temp);
    std::fs::write(&temp, text).map_err(io)?;
    if let Ok(meta) = std::fs::metadata(path) {
        std::fs::set_permissions(&temp, meta.permissions()).ok();
    }
    std::fs::rename(&temp, path).map_err(|e| {
        std::fs::remove_file(&temp).ok();
        io(e)
    })
}

fn path_property() -> Value {
    json!({"type": "string", "description": "Path relative to the project folder"})
}

pub(crate) fn tools(ctx: &Arc<Context>) -> Vec<LocalTool> {
    vec![read(ctx), write(ctx), edit(ctx)]
}

fn read(ctx: &Arc<Context>) -> LocalTool {
    let ctx = Arc::clone(ctx);
    LocalTool::new(
        "Read",
        "Read a text file with line numbers; offset (first line, 1-based) and limit (lines).",
        object_schema(
            json!({"path": path_property(), "offset": {"type": "integer", "minimum": 1},
                   "limit": {"type": "integer", "minimum": 1}}),
            &["path"],
        ),
        false,
        true,
        move |args: &Args| {
            let path = ctx.scope.resolve(string(args, "path")?, false)?;
            if path.is_dir() {
                return Err(ToolError::new("is_directory", "the path is a folder"));
            }
            if !path.is_file() {
                return Err(ToolError::new("not_found", "no such file"));
            }
            let text = read_text(&path, ctx.limits.edit_max_bytes)?;
            let lines: Vec<&str> = text.lines().collect();
            let max = u64::from(ctx.limits.read_max_lines);
            let start = opt_u64(args, "offset").unwrap_or(1).max(1);
            let count = opt_u64(args, "limit").unwrap_or(max).min(max);
            let from = usize::try_from(start - 1)
                .unwrap_or(usize::MAX)
                .min(lines.len());
            let to = usize::try_from(start - 1 + count)
                .unwrap_or(usize::MAX)
                .min(lines.len());
            let numbered: Vec<String> = lines[from..to]
                .iter()
                .enumerate()
                .map(|(i, line)| format!("{:>6}\t{line}", from + i + 1))
                .collect();
            Ok(json!({
                "path": ctx.scope.display(&path),
                "total_lines": lines.len(),
                "start": start,
                "end": from + numbered.len(),
                "text": numbered.join("\n"),
                "truncated": to < lines.len(),
            }))
        },
    )
}

fn write(ctx: &Arc<Context>) -> LocalTool {
    let ctx = Arc::clone(ctx);
    LocalTool::new(
        "Write",
        "Create or overwrite a file with the given content (needs approval; the previous content is checkpointed).",
        object_schema(
            json!({"path": path_property(), "content": {"type": "string"}}),
            &["path", "content"],
        ),
        true,
        false,
        move |args: &Args| {
            let path = ctx.scope.resolve(string(args, "path")?, true)?;
            if path.is_dir() {
                return Err(ToolError::new("is_directory", "the path is a folder"));
            }
            let content = (ctx.redact)(string(args, "content")?); // never persist a credential
            if content.len() as u64 > ctx.limits.edit_max_bytes {
                return Err(ToolError::new("too_large", "the content is too large"));
            }
            let created = !path.exists();
            let saved = ctx
                .checkpoints
                .as_ref()
                .map(|c| c.record(&path, "Write"))
                .transpose()?;
            if let Err(error) = write_atomic(&path, &content) {
                if let (Some(c), Some(seq)) = (&ctx.checkpoints, saved) {
                    c.discard(seq);
                }
                return Err(error);
            }
            Ok(
                json!({"path": ctx.scope.display(&path), "bytes": content.len(), "created": created}),
            )
        },
    )
}

fn edit(ctx: &Arc<Context>) -> LocalTool {
    let ctx = Arc::clone(ctx);
    LocalTool::new(
        "Edit",
        "Replace one exact piece of text in a file. old_string must appear exactly once (add surrounding context) \
         unless replace_all is true (needs approval).",
        object_schema(
            json!({"path": path_property(), "old_string": {"type": "string"},
                   "new_string": {"type": "string"}, "replace_all": {"type": "boolean"}}),
            &["path", "old_string", "new_string"],
        ),
        true,
        false,
        move |args: &Args| {
            let path = ctx.scope.resolve(string(args, "path")?, true)?;
            if !path.is_file() {
                return Err(ToolError::new("not_found", "no such file"));
            }
            let (old, new) = (
                string(args, "old_string")?,
                (ctx.redact)(string(args, "new_string")?),
            );
            let all = opt_bool(args, "replace_all").unwrap_or(false);
            let before = read_text(&path, ctx.limits.edit_max_bytes)?;
            let after = replace(&before, old, &new, all)?;
            if after.len() as u64 > ctx.limits.edit_max_bytes {
                return Err(ToolError::new(
                    "too_large",
                    "the edited file would be too large",
                ));
            }
            let saved = ctx
                .checkpoints
                .as_ref()
                .map(|c| c.record(&path, "Edit"))
                .transpose()?;
            if let Err(error) = write_atomic(&path, &after) {
                if let (Some(c), Some(seq)) = (&ctx.checkpoints, saved) {
                    c.discard(seq);
                }
                return Err(error);
            }
            let count = if all { before.matches(old).count() } else { 1 };
            Ok(json!({"path": ctx.scope.display(&path), "replacements": count}))
        },
    )
}

/// The text with `old` replaced by `new`: once, which needs exactly one match, or everywhere.
pub(crate) fn replace(text: &str, old: &str, new: &str, all: bool) -> Result<String, ToolError> {
    if old.is_empty() {
        return Err(ToolError::new(
            "invalid_arguments",
            "old_string must not be empty",
        ));
    }
    if old == new {
        return Err(ToolError::new(
            "no_change",
            "old_string and new_string are the same",
        ));
    }
    let count = text.matches(old).count();
    if count == 0 {
        return Err(ToolError::new(
            "not_found",
            "old_string was not found in the file",
        ));
    }
    if count > 1 && !all {
        return Err(ToolError::new(
            "not_unique",
            format!(
                "old_string appears {count} times; add context to make it unique or set replace_all"
            ),
        )
        .with("matches", count));
    }
    Ok(if all {
        text.replace(old, new)
    } else {
        text.replacen(old, new, 1)
    })
}
