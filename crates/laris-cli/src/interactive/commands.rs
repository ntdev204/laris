//! The commands of the interface: the built-in ones, the custom ones read from `commands/` folders, and the
//! completion of both (SR-C2).
//!
//! A custom command is a Markdown file `commands/<name>.md` (a folder makes a prefix: `review/pr.md` is
//! `/review:pr`) in the home folder or in the project's `.laris/`; the project's wins. An optional header between
//! `---` lines may say `description:`. The body is sent as the user's message with `$ARGUMENTS` replaced by what was
//! typed after the name, and `$1` to `$9` by its words; a body with no placeholder gets the arguments added at the
//! end. A custom command never replaces a built-in one.

use laris_config::Catalogue;
use laris_protocol::events::CompletionItem;
use std::fs;
use std::path::Path;

/// The built-in commands: name and the catalogue key of its description.
pub const BUILTIN: [(&str, &str); 13] = [
    ("help", "commands.help"),
    ("clear", "commands.clear"),
    ("exit", "commands.exit"),
    ("mode", "commands.mode"),
    ("status", "commands.status"),
    ("usage", "commands.usage"),
    ("context", "commands.context"),
    ("model", "commands.model"),
    ("config", "commands.config"),
    ("export", "commands.export"),
    ("rewind", "commands.rewind"),
    ("login", "commands.login"),
    ("logout", "commands.logout"),
];

/// Largest custom command file read, in bytes.
const MAX_FILE: u64 = 64 * 1024;
/// Most custom commands loaded.
const MAX_COMMANDS: usize = 200;

/// A command read from a file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Custom {
    /// The name, without the slash.
    pub name: String,
    /// What it does (the header's `description`, else the first line of the body).
    pub description: String,
    /// What is sent.
    pub body: String,
    /// `user` or `project`.
    pub source: &'static str,
}

/// Whether `name` is a usable command name: letters, digits, `-`, `_` and `:`.
pub fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | ':'))
}

/// Reads one command file: the header and the body.
pub fn parse(name: &str, text: &str, source: &'static str) -> Custom {
    let text = text.strip_prefix('\u{feff}').unwrap_or(text);
    let mut description = String::new();
    let mut body = text;
    if let Some(rest) = text
        .strip_prefix("---\n")
        .or_else(|| text.strip_prefix("---\r\n"))
        && let Some(end) = rest.find("\n---")
    {
        for line in rest[..end].lines() {
            if let Some(value) = line.strip_prefix("description:") {
                description = value.trim().trim_matches(['"', '\'']).to_owned();
            }
        }
        let after = &rest[end + 4..];
        body = after.trim_start_matches(['\r', '\n']);
    }
    let body = body.trim().to_owned();
    if description.is_empty() {
        description = body
            .lines()
            .find(|l| !l.trim().is_empty())
            .unwrap_or("")
            .trim_start_matches('#')
            .trim()
            .chars()
            .take(80)
            .collect();
    }
    Custom {
        name: name.to_owned(),
        description,
        body,
        source,
    }
}

/// The body with the arguments put in.
pub fn expand(body: &str, args: &str) -> String {
    let words: Vec<&str> = args.split_whitespace().collect();
    let mut used = body.contains("$ARGUMENTS");
    let mut out = body.replace("$ARGUMENTS", args);
    for n in (1..=9).rev() {
        let mark = format!("${n}");
        if out.contains(&mark) {
            used = true;
            out = out.replace(&mark, words.get(n - 1).copied().unwrap_or(""));
        }
    }
    if !used && !args.is_empty() {
        out.push_str("\n\n");
        out.push_str(args);
    }
    out
}

fn collect(dir: &Path, prefix: &str, source: &'static str, depth: usize, out: &mut Vec<Custom>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    let mut entries: Vec<_> = entries.flatten().collect();
    entries.sort_by_key(|e| e.file_name());
    for entry in entries {
        if out.len() >= MAX_COMMANDS {
            return;
        }
        let path = entry.path();
        let file = entry.file_name().to_string_lossy().into_owned();
        // a link could point anywhere; only plain files and folders are read
        let Ok(kind) = entry.file_type() else {
            continue;
        };
        if kind.is_dir() && depth < 3 && valid_name(&file) {
            collect(&path, &format!("{prefix}{file}:"), source, depth + 1, out);
        } else if kind.is_file()
            && let Some(stem) = file.strip_suffix(".md")
        {
            let name = format!("{prefix}{stem}");
            if !valid_name(&name) {
                continue;
            }
            let small = fs::metadata(&path).is_ok_and(|m| m.len() <= MAX_FILE);
            if !small {
                continue;
            }
            if let Ok(text) = fs::read_to_string(&path) {
                out.push(parse(&name, &text, source));
            }
        }
    }
}

/// The commands the interface answers.
#[derive(Debug, Clone)]
pub struct CommandSet {
    custom: Vec<Custom>,
    words: Catalogue,
}

impl CommandSet {
    /// The built-in commands and those found in `user` and `project` folders (the project's win).
    pub fn load(user: &Path, project: &Path, words: Catalogue) -> Self {
        let mut found: Vec<Custom> = Vec::new();
        collect(user, "", "user", 0, &mut found);
        let mut from_project = Vec::new();
        collect(project, "", "project", 0, &mut from_project);
        found.retain(|c| !from_project.iter().any(|p| p.name == c.name));
        found.extend(from_project);
        found.retain(|c| !BUILTIN.iter().any(|(name, _)| *name == c.name));
        found.sort_by(|a, b| a.name.cmp(&b.name));
        Self {
            custom: found,
            words,
        }
    }

    /// Only the built-in commands.
    pub fn builtin_only(words: Catalogue) -> Self {
        Self {
            custom: Vec::new(),
            words,
        }
    }

    /// The custom commands.
    pub fn custom(&self) -> &[Custom] {
        &self.custom
    }

    /// The custom command called `name`.
    pub fn find(&self, name: &str) -> Option<&Custom> {
        self.custom.iter().find(|c| c.name == name)
    }

    /// The words of a built-in command's description.
    fn describe(&self, key: &str) -> String {
        self.words.get(key, &[]).unwrap_or_default()
    }

    /// Candidates for `/prefix`: names that start with it, then names that contain it; built-in first within each.
    pub fn complete(&self, prefix: &str) -> Vec<CompletionItem> {
        let mut all: Vec<CompletionItem> = BUILTIN
            .iter()
            .map(|(name, key)| CompletionItem {
                value: (*name).to_owned(),
                description: self.describe(key),
            })
            .collect();
        all.extend(self.custom.iter().map(|c| CompletionItem {
            value: c.name.clone(),
            description: c.description.clone(),
        }));
        let (mut starts, contains): (Vec<_>, Vec<_>) = all
            .into_iter()
            .filter(|item| item.value.contains(prefix))
            .partition(|item| item.value.starts_with(prefix));
        starts.extend(contains);
        starts
    }

    /// The text `/help` answers: every command with its description, then the ways of typing.
    pub fn help(&self) -> String {
        let word = |key: &str| self.words.get(key, &[]).unwrap_or_default();
        let mut out = format!("{}:\n", word("ui.help_head"));
        for (name, key) in BUILTIN {
            out.push_str(&format!("  /{name} — {}\n", self.describe(key)));
        }
        if !self.custom.is_empty() {
            out.push_str(&format!("\n{}:\n", word("ui.help_custom")));
            for c in &self.custom {
                let from = self
                    .words
                    .get("commands.custom", &[("source", c.source)])
                    .unwrap_or_default();
                out.push_str(&format!("  /{} — {} ({from})\n", c.name, c.description));
            }
        }
        out.push('\n');
        out.push_str(&word("ui.help_input"));
        out.push('\n');
        out
    }
}
