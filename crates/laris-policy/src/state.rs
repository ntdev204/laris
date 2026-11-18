//! What the user decided about one folder: `<home>/projects/<slug>/state.json`.
//!
//! It holds whether the folder is trusted (its own commands and skills may then be used) and the approvals the user
//! saved for it. The file is in the user's home, never in the project, so a cloned repository cannot write it. A
//! missing or damaged file reads as empty.

use laris_store::slug_of;
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};

/// The decisions kept for one project folder.
#[derive(Clone, Debug)]
pub struct ProjectState {
    path: PathBuf,
}

impl ProjectState {
    /// The state of `project_root` under `home`.
    pub fn new(home: &Path, project_root: &Path) -> Self {
        Self {
            path: home
                .join("projects")
                .join(slug_of(project_root))
                .join("state.json"),
        }
    }

    /// The file.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// The content; empty when the file is missing or damaged.
    pub fn read(&self) -> Map<String, Value> {
        std::fs::read_to_string(&self.path)
            .ok()
            .and_then(|text| serde_json::from_str::<Value>(&text).ok())
            .and_then(|value| match value {
                Value::Object(map) => Some(map),
                _ => None,
            })
            .unwrap_or_default()
    }

    fn write(&self, data: &Map<String, Value>) -> std::io::Result<()> {
        if let Some(dir) = self.path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let mut text = serde_json::to_string_pretty(&Value::Object(data.clone()))?;
        text.push('\n');
        let temporary = self.path.with_extension("json.tmp");
        std::fs::write(&temporary, text)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&temporary, std::fs::Permissions::from_mode(0o600))?;
        }
        std::fs::rename(&temporary, &self.path)
    }

    /// Whether the user trusted this folder.
    pub fn trusted(&self) -> bool {
        self.read().get("trusted") == Some(&Value::Bool(true))
    }

    /// Trusts the folder, or stops trusting it.
    pub fn set_trusted(&self, value: bool) -> std::io::Result<()> {
        let mut data = self.read();
        data.insert("trusted".to_owned(), Value::Bool(value));
        self.write(&data)
    }

    /// The saved rules of `kind` (`allow` or `deny`); anything that is not a string is dropped.
    pub fn rules(&self, kind: &str) -> Vec<String> {
        self.read()
            .get("permissions")
            .and_then(|p| p.get(kind))
            .and_then(Value::as_array)
            .map(|rules| {
                rules
                    .iter()
                    .filter_map(|r| r.as_str().map(str::to_owned))
                    .collect()
            })
            .unwrap_or_default()
    }

    /// Saves an `allow` rule for this folder; saving it twice keeps one.
    pub fn add_allow(&self, rule: &str) -> std::io::Result<()> {
        let mut data = self.read();
        let mut permissions = match data.remove("permissions") {
            Some(Value::Object(map)) => map,
            _ => Map::new(),
        };
        let mut allow: Vec<Value> = match permissions.remove("allow") {
            Some(Value::Array(items)) => items,
            _ => Vec::new(),
        };
        if !allow.iter().any(|r| r.as_str() == Some(rule)) {
            allow.push(json!(rule));
        }
        permissions.insert("allow".to_owned(), Value::Array(allow));
        data.insert("permissions".to_owned(), Value::Object(permissions));
        self.write(&data)
    }
}

/// Where the user's skills are looked for: the global folder always, the project's own `.laris/skills` only in a
/// trusted folder.
pub fn skill_dirs(home: &Path, project_root: &Path, state: &ProjectState) -> Vec<PathBuf> {
    let mut dirs = vec![home.join("skills")];
    if state.trusted() {
        dirs.push(project_root.join(".laris").join("skills"));
    }
    dirs
}

/// Where custom commands are looked for, by the same rule as [`skill_dirs`].
pub fn command_dirs(home: &Path, project_root: &Path, state: &ProjectState) -> Vec<PathBuf> {
    let mut dirs = vec![home.join("commands")];
    if state.trusted() {
        dirs.push(project_root.join(".laris").join("commands"));
    }
    dirs
}
