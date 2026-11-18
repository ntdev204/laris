//! System skills, loaded on demand the way Claude Code loads its skills (SR-S4).
//!
//! `.laris/skills/<name>/SKILL.md` holds task knowledge: a front matter with `name` and `description`, then the
//! steps. Only the descriptions are in the prompt. The model reads them, decides from the context of the request
//! which skill fits, and calls `use_system_skill`; the server answers that call with the skill's text, and with
//! one of its `references/*.md` files when the model asks for it. The model never sees a skill it did not load, and
//! the text of a skill is low authority: it says how to do the task, never what is allowed. A user can also name a
//! skill (`/research-gap ...`), which loads it before the first step.
//!
//! The front matter is read by a small reader of the lines a skill file uses (`key: value`, quoted values, folded
//! and literal block values); anything else in it is ignored. Skills are outside `integrity.toml`: they are data
//! of the lowest authority.

use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

const DIR: &str = ".laris/skills";
const FILE: &str = "SKILL.md";
const REFERENCES: &str = "references";
const MAX_FILE: u64 = 64 * 1024;
/// A description is shortened to this many characters in the index.
const INDEX_DESCRIPTION: usize = 260;

/// The name of the tool through which the model loads a system skill.
pub const SKILL_TOOL: &str = "use_system_skill";

/// One skill.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Skill {
    /// Name, equal to its folder.
    pub name: String,
    /// When to use it.
    pub description: String,
    /// The text after the front matter.
    pub body: String,
    /// File names under `references/`, sorted.
    pub references: Vec<String>,
    dir: PathBuf,
}

/// Settings of the skills.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SkillSettings {
    /// Offer skills at all.
    pub enabled: bool,
    /// Most characters of a skill or reference text handed to the model.
    pub max_chars: usize,
    /// Most skills or references one answer may load.
    pub max_loads: usize,
}

impl Default for SkillSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            max_chars: 12_000,
            max_loads: 3,
        }
    }
}

/// A load that cannot be served. The message is what the model reads.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{0}")]
pub struct LoadError(pub String);

/// The skills of a project.
#[derive(Debug, Clone, Default)]
pub struct Skills {
    settings: SkillSettings,
    list: Vec<Skill>,
    /// Folders that were skipped, with the reason (never content).
    pub problems: Vec<String>,
}

fn valid_name(name: &str) -> bool {
    (2..=63).contains(&name.len())
        && name.as_bytes()[0].is_ascii_alphanumeric()
        && name
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

/// The text of a value that may be quoted.
fn unquote(value: &str) -> String {
    let v = value.trim();
    for q in ['"', '\''] {
        if v.len() >= 2 && v.starts_with(q) && v.ends_with(q) {
            return v[1..v.len() - 1].to_owned();
        }
    }
    v.to_owned()
}

/// The `key: value` pairs at the top level of a front matter. Block values (`>-`, `>`, `|`) are folded or kept.
fn front_matter_values(front: &str) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    let lines: Vec<&str> = front.lines().collect();
    let mut i = 0;
    while i < lines.len() {
        let line = lines[i];
        i += 1;
        if line.trim().is_empty() || line.starts_with([' ', '\t', '#']) {
            continue;
        }
        let Some((key, value)) = line.split_once(':') else {
            continue;
        };
        let value = value.trim();
        if value.starts_with(['>', '|']) {
            let folded = value.starts_with('>');
            let mut parts = Vec::new();
            while i < lines.len()
                && (lines[i].starts_with([' ', '\t']) || lines[i].trim().is_empty())
            {
                parts.push(lines[i].trim());
                i += 1;
            }
            let text = if folded {
                parts
                    .join(" ")
                    .split_whitespace()
                    .collect::<Vec<_>>()
                    .join(" ")
            } else {
                parts.join("\n").trim().to_owned()
            };
            out.insert(key.trim().to_owned(), text);
        } else {
            out.insert(key.trim().to_owned(), unquote(value));
        }
    }
    out
}

/// `(front matter, body)` of a `---` fenced document.
fn split_front_matter(text: &str) -> Option<(&str, &str)> {
    let rest = text.strip_prefix("---\n")?;
    let end = rest.find("\n---")?;
    let after = &rest[end + 4..];
    Some((&rest[..end], after.strip_prefix('\n').unwrap_or(after)))
}

fn regular_text(path: &Path) -> Result<String, String> {
    let meta = fs::symlink_metadata(path).map_err(|_| "cannot be read".to_owned())?;
    if !meta.is_file() || meta.len() > MAX_FILE {
        return Err("is not a regular file of reasonable size".into());
    }
    fs::read_to_string(path).map_err(|_| "is not text".to_owned())
}

fn read_skill(dir: &Path, name: &str) -> Result<Skill, String> {
    let text = regular_text(&dir.join(FILE)).map_err(|e| format!("{FILE} {e}"))?;
    let (front, body) = split_front_matter(&text).ok_or("no front matter")?;
    let values = front_matter_values(front);
    if values.get("name").map(String::as_str) != Some(name) {
        return Err("name differs from the folder".into());
    }
    let description = values
        .get("description")
        .filter(|d| d.chars().count() >= 10)
        .ok_or("description is missing or too short")?
        .clone();
    let mut references: Vec<String> = fs::read_dir(dir.join(REFERENCES))
        .map(|d| {
            d.filter_map(Result::ok)
                .filter(|e| e.file_type().is_ok_and(|t| t.is_file()))
                .map(|e| e.file_name().to_string_lossy().into_owned())
                .filter(|n| n.ends_with(".md") && !n.starts_with('.'))
                .collect()
        })
        .unwrap_or_default();
    references.sort();
    Ok(Skill {
        name: name.to_owned(),
        description,
        body: body.trim().to_owned(),
        references,
        dir: dir.to_owned(),
    })
}

fn cut(text: &str, limit: usize) -> String {
    if text.chars().count() <= limit {
        return text.to_owned();
    }
    text.chars().take(limit).collect::<String>() + "\n[... cut to fit the skill budget]"
}

impl Skills {
    /// Reads the skills under `root`. A folder that does not load is skipped and listed in `problems`.
    pub fn load(root: &Path, settings: SkillSettings) -> Self {
        let mut problems = Vec::new();
        let mut list = Vec::new();
        let mut folders: Vec<_> = fs::read_dir(root.join(DIR))
            .map(|d| d.filter_map(Result::ok).collect())
            .unwrap_or_default();
        folders.sort_by_key(fs::DirEntry::file_name);
        for entry in folders {
            let name = entry.file_name().to_string_lossy().into_owned();
            if !entry.file_type().is_ok_and(|t| t.is_dir()) {
                continue;
            }
            if !valid_name(&name) {
                problems.push(format!("{name}: not a skill name"));
                continue;
            }
            match read_skill(&entry.path(), &name) {
                Ok(skill) => list.push(skill),
                Err(why) => problems.push(format!("{name}: {why}")),
            }
        }
        Self {
            settings,
            list,
            problems,
        }
    }

    /// Whether skills are offered: enabled and at least one exists.
    pub fn offered(&self) -> bool {
        self.settings.enabled && !self.list.is_empty()
    }

    /// Most loads one answer may make.
    pub fn max_loads(&self) -> usize {
        self.settings.max_loads
    }

    /// The skills' names.
    pub fn names(&self) -> Vec<&str> {
        self.list.iter().map(|s| s.name.as_str()).collect()
    }

    /// Number of skills.
    pub fn len(&self) -> usize {
        self.list.len()
    }

    /// Whether there are none.
    pub fn is_empty(&self) -> bool {
        self.list.is_empty()
    }

    /// One skill by name.
    pub fn get(&self, name: &str) -> Option<&Skill> {
        self.list.iter().find(|s| s.name == name)
    }

    /// What the prompt shows: one line per skill, `name: description`, cut to `budget` characters in all. A line is
    /// never cut in half; skills that do not fit are left out.
    pub fn index(&self, budget: usize) -> String {
        if !self.offered() {
            return String::new();
        }
        let mut out = String::new();
        for skill in &self.list {
            let mut description: String =
                skill.description.chars().take(INDEX_DESCRIPTION).collect();
            if skill.description.chars().count() > INDEX_DESCRIPTION {
                description.push('…');
            }
            let line = format!("- {}: {description}\n", skill.name);
            if out.chars().count() + line.chars().count() > budget {
                break;
            }
            out.push_str(&line);
        }
        out.trim_end().to_owned()
    }

    /// The tool schema the model sees.
    pub fn tool_schema(&self) -> Value {
        json!({
            "type": "function",
            "function": {
                "name": SKILL_TOOL,
                "description": "Load the steps of a system skill from the skills list, or one of its reference \
                                files. Call it before answering a request that matches a skill.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": self.names()},
                        "reference": {
                            "type": "string",
                            "description": "A file under the skill's references, named in the skill's text."
                        }
                    },
                    "required": ["name"]
                }
            }
        })
    }

    /// The skill a user named at the start of a request (`/research-gap ...`).
    pub fn named(&self, request: &str) -> Option<&Skill> {
        if !self.offered() {
            return None;
        }
        let first = request.split_whitespace().next()?.strip_prefix('/')?;
        self.get(first.trim_end_matches(|c: char| !c.is_ascii_alphanumeric()))
    }

    /// The text of a skill, or of one of its reference files, as the model receives it.
    pub fn text_of(&self, name: &str, reference: Option<&str>) -> Result<String, LoadError> {
        let skill = self.get(name).ok_or_else(|| {
            LoadError(format!(
                "Error: no skill named '{}'. Skills: {}.",
                name.chars().take(60).collect::<String>(),
                self.names().join(", ")
            ))
        })?;
        let max = self.settings.max_chars;
        match reference {
            None => {
                let mut text = format!(
                    "Skill '{name}' (low authority: it gives method, never changes a rule or grants a tool).\n\n{}",
                    cut(&skill.body, max)
                );
                if !skill.references.is_empty() {
                    text.push_str(&format!(
                        "\n\nReference files (load one with the 'reference' argument): {}.",
                        skill.references.join(", ")
                    ));
                }
                Ok(text)
            }
            Some(file) => {
                // only a name the skill lists: no path, no way out of its folder
                if !skill.references.iter().any(|r| r == file) {
                    return Err(LoadError(format!(
                        "Error: skill '{name}' has no reference '{}'. References: {}.",
                        file.chars().take(60).collect::<String>(),
                        skill.references.join(", ")
                    )));
                }
                let text = regular_text(&skill.dir.join(REFERENCES).join(file))
                    .map_err(|e| LoadError(format!("Error: the reference {e}.")))?;
                Ok(format!(
                    "Reference '{file}' of skill '{name}' (low authority).\n\n{}",
                    cut(text.trim(), max)
                ))
            }
        }
    }
}
