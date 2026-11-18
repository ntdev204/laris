//! `Glob` and `Grep`.

use crate::args::{object_schema, opt_bool, opt_string, opt_u64, string};
use crate::context::Context;
use crate::error::ToolError;
use crate::files::read_text;
use crate::glob::glob_to_regex;
use crate::registry::LocalTool;
use regex::RegexBuilder;
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};
use std::sync::Arc;

type Args = Map<String, Value>;

/// Folders the searches do not enter.
const SKIPPED_DIRS: [&str; 6] = [
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    ".mypy_cache",
    ".ruff_cache",
];
/// Characters of a matching line shown.
const LINE_CHARS: usize = 300;
/// Compiled size a `Grep` expression may reach, in bytes.
const REGEX_SIZE_LIMIT: usize = 1 << 20;

fn path_property() -> Value {
    json!({"type": "string", "description": "Path relative to the project folder"})
}

pub(crate) fn tools(ctx: &Arc<Context>) -> Vec<LocalTool> {
    vec![glob(ctx), grep(ctx)]
}

/// The files under `base` the tools may see, in name order. A symbolic link is followed only for a file, and only
/// when its target is inside the allowed folders and not a secret; a folder behind a link is not entered.
fn files(ctx: &Context, base: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    if base.is_file() {
        out.push(base.to_path_buf());
        return out;
    }
    let mut stack = vec![base.to_path_buf()];
    while let Some(folder) = stack.pop() {
        let Ok(read) = std::fs::read_dir(&folder) else {
            continue;
        };
        let mut entries: Vec<_> = read.filter_map(Result::ok).collect();
        entries.sort_by_key(std::fs::DirEntry::file_name);
        let mut subfolders = Vec::new();
        for entry in entries {
            let path = entry.path();
            let Ok(kind) = entry.file_type() else {
                continue;
            };
            let name = entry.file_name();
            if kind.is_dir() {
                if !SKIPPED_DIRS.iter().any(|s| name == *s) {
                    subfolders.push(path);
                }
            } else if kind.is_file() {
                if !ctx.scope.is_secret(&path) {
                    out.push(path);
                }
            } else if kind.is_symlink()
                && let Ok(target) = path.canonicalize()
                && target.is_file()
                && ctx.scope.inside(&target)
                && !ctx.scope.is_secret(&target)
                && !ctx.scope.is_secret(&path)
            {
                out.push(target);
            }
        }
        stack.extend(subfolders.into_iter().rev());
    }
    out.sort();
    out
}

fn glob(ctx: &Arc<Context>) -> LocalTool {
    let ctx = Arc::clone(ctx);
    LocalTool::new(
        "Glob",
        "List files matching a glob pattern such as `src/**/*.py`.",
        object_schema(
            json!({"pattern": {"type": "string"}, "path": path_property()}),
            &["pattern"],
        ),
        false,
        false,
        move |args: &Args| {
            let base = ctx
                .scope
                .resolve(opt_string(args, "path").unwrap_or("."), false)?;
            if !base.is_dir() {
                return Err(ToolError::new("not_a_directory", "not a directory"));
            }
            let pattern = string(args, "pattern")?;
            let regex = glob_to_regex(pattern).ok_or_else(|| {
                ToolError::new("invalid_pattern", format!("bad glob pattern `{pattern}`"))
            })?;
            let mut found = Vec::new();
            for path in files(&ctx, &base) {
                let relative = path
                    .strip_prefix(&base)
                    .map(|r| {
                        r.components()
                            .map(|c| c.as_os_str().to_string_lossy())
                            .collect::<Vec<_>>()
                            .join("/")
                    })
                    .unwrap_or_else(|_| ctx.scope.display(&path));
                if regex.is_match(&relative) {
                    found.push(ctx.scope.display(&path));
                }
            }
            let limit = usize::try_from(ctx.limits.glob_max_results).unwrap_or(usize::MAX);
            let truncated = found.len() > limit;
            found.truncate(limit);
            Ok(json!({"files": found, "truncated": truncated}))
        },
    )
}

fn grep(ctx: &Arc<Context>) -> LocalTool {
    let ctx = Arc::clone(ctx);
    LocalTool::new(
        "Grep",
        "Search file contents with a regular expression; optional path, glob filter, ignore_case and max_results.",
        object_schema(
            json!({"pattern": {"type": "string"}, "path": path_property(), "glob": {"type": "string"},
                   "ignore_case": {"type": "boolean"}, "max_results": {"type": "integer", "minimum": 1}}),
            &["pattern"],
        ),
        false,
        true,
        move |args: &Args| {
            let regex = RegexBuilder::new(string(args, "pattern")?)
                .case_insensitive(opt_bool(args, "ignore_case").unwrap_or(false))
                .size_limit(REGEX_SIZE_LIMIT)
                .build()
                .map_err(|e| {
                    ToolError::new("invalid_pattern", format!("bad regular expression: {e}"))
                })?;
            let base = ctx
                .scope
                .resolve(opt_string(args, "path").unwrap_or("."), false)?;
            let wanted = opt_string(args, "glob")
                .map(|g| {
                    glob_to_regex(g).ok_or_else(|| {
                        ToolError::new("invalid_pattern", format!("bad glob pattern `{g}`"))
                    })
                })
                .transpose()?;
            let cap = u64::from(ctx.limits.grep_max_results);
            let limit = usize::try_from(opt_u64(args, "max_results").unwrap_or(cap).min(cap))
                .unwrap_or(usize::MAX);
            let mut matches = Vec::new();
            for path in files(&ctx, &base) {
                let shown = ctx.scope.display(&path);
                let name = path
                    .file_name()
                    .map(|n| n.to_string_lossy().into_owned())
                    .unwrap_or_default();
                if wanted
                    .as_ref()
                    .is_some_and(|w| !w.is_match(&shown) && !w.is_match(&name))
                {
                    continue;
                }
                if std::fs::metadata(&path).is_ok_and(|m| m.len() > ctx.limits.grep_max_file_bytes)
                {
                    continue;
                }
                let Ok(text) = read_text(&path, ctx.limits.grep_max_file_bytes) else {
                    continue;
                };
                for (number, line) in text.lines().enumerate() {
                    if regex.is_match(line) {
                        if matches.len() == limit {
                            return Ok(json!({"matches": matches, "truncated": true}));
                        }
                        let shown_line: String = line.chars().take(LINE_CHARS).collect();
                        matches
                            .push(json!({"path": shown, "line": number + 1, "text": shown_line}));
                    }
                }
            }
            Ok(json!({"matches": matches, "truncated": false}))
        },
    )
}
