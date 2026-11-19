//! `@path`: completing a path as it is typed, and putting the files a message names into the message (SR-C2).
//!
//! Only what the tools themselves may read is offered or attached: [`Scope::resolve`] refuses a path outside the
//! project folders and the files that hold secrets, so `@.env` and `@../x` attach nothing.

use laris_protocol::events::CompletionItem;
use laris_tools::Scope;
use std::fs;

/// Most candidates offered.
pub const MAX_ITEMS: usize = 60;
/// Largest file put into a message, in bytes.
pub const MAX_FILE: u64 = 64 * 1024;
/// Most files put into one message.
pub const MAX_FILES: usize = 8;
/// Most entries listed for a folder.
const MAX_LISTED: usize = 50;
/// Folders nobody wants to complete into.
const NOISE: [&str; 3] = ["target", "node_modules", ".git"];

/// Candidates for the path typed after `@`: the entries of the folder named so far that start with the rest.
/// Folders end in `/` and come first.
pub fn complete(scope: &Scope, typed: &str) -> Vec<CompletionItem> {
    let (dir, prefix) = match typed.rfind('/') {
        Some(at) => (&typed[..=at], &typed[at + 1..]),
        None => ("", typed),
    };
    let Ok(folder) = scope.resolve(if dir.is_empty() { "." } else { dir }, false) else {
        return Vec::new();
    };
    let Ok(entries) = fs::read_dir(&folder) else {
        return Vec::new();
    };
    let mut found: Vec<(bool, String)> = Vec::new();
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        if !name.starts_with(prefix) || NOISE.contains(&name.as_str()) {
            continue;
        }
        if name.starts_with('.') && !prefix.starts_with('.') {
            continue;
        }
        let Ok(kind) = entry.file_type() else {
            continue;
        };
        let shown = format!("{dir}{name}");
        // a link, a socket or a secret is not offered
        if (!kind.is_dir() && !kind.is_file()) || scope.resolve(&shown, false).is_err() {
            continue;
        }
        found.push((kind.is_dir(), shown));
    }
    found.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
    found
        .into_iter()
        .take(MAX_ITEMS)
        .map(|(is_dir, name)| CompletionItem {
            value: if is_dir { format!("{name}/") } else { name },
            description: String::new(),
        })
        .collect()
}

/// The `@path` words of `text`: a word that starts with `@` at the start or after white space.
pub fn references(text: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for word in text.split_whitespace() {
        if let Some(path) = word.strip_prefix('@') {
            let path = path.trim_end_matches([',', ';', ':', '!', '?', ')', '.']);
            if !path.is_empty() && !out.iter().any(|p| p == path) {
                out.push(path.to_owned());
            }
        }
    }
    out
}

/// `text` with the files it names added at the end, each in a `<file path="…">` block, and what was attached or
/// left out. A folder is listed, a file larger than [`MAX_FILE`] or not text is left out, a path the tools may not
/// read is left as written.
pub fn attach(scope: &Scope, text: &str) -> (String, Vec<String>) {
    let mut out = text.to_owned();
    let mut notes = Vec::new();
    let mut count = 0;
    for raw in references(text) {
        if count >= MAX_FILES {
            break;
        }
        let Ok(path) = scope.resolve(&raw, false) else {
            continue;
        };
        let Ok(meta) = fs::metadata(&path) else {
            continue;
        };
        let shown = scope.display(&path);
        if meta.is_dir() {
            let Ok(entries) = fs::read_dir(&path) else {
                continue;
            };
            let mut names: Vec<String> = entries
                .flatten()
                .filter(|e| {
                    let name = e.file_name().to_string_lossy().into_owned();
                    !name.starts_with('.') && scope.resolve(&format!("{raw}/{name}"), false).is_ok()
                })
                .map(|e| {
                    let name = e.file_name().to_string_lossy().into_owned();
                    if e.file_type().is_ok_and(|t| t.is_dir()) {
                        format!("{name}/")
                    } else {
                        name
                    }
                })
                .collect();
            names.sort();
            names.truncate(MAX_LISTED);
            out.push_str(&format!(
                "\n\n<folder path=\"{shown}\">\n{}\n</folder>",
                names.join("\n")
            ));
            notes.push(format!("@{shown}/"));
            count += 1;
        } else if meta.is_file() && meta.len() <= MAX_FILE {
            let Ok(content) = fs::read_to_string(&path) else {
                continue;
            };
            out.push_str(&format!("\n\n<file path=\"{shown}\">\n{content}\n</file>"));
            notes.push(format!("@{shown}"));
            count += 1;
        }
    }
    (out, notes)
}
