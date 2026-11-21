//! Workflows: declarative procedures that can only narrow what a session may do (rules W-1 to W-4).
//!
//! `.laris/workflows/<name>.toml` lists ordered phases and limits the server enforces: the tools the turn may offer
//! the model, a step cap, a stricter approval mode, required citations and the sections the answer must contain.
//! The phases and instructions stay on the server; the client learns only the limits (`GET /v1/laris/workflows`).

use super::integrity::Snapshot;
use laris_protocol::p1::WorkflowInfo;
use serde_json::{Map, Value};
use std::collections::BTreeMap;

const DIR: &str = ".laris/workflows";

/// A workflow file that cannot be used.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{file}: {reason}")]
pub struct WorkflowError {
    /// File name.
    pub file: String,
    /// What is wrong.
    pub reason: String,
}

/// One phase of a workflow.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Phase {
    /// Identifier.
    pub id: String,
    /// What the phase achieves.
    pub goal: String,
    /// How, in the author's words.
    pub instructions: String,
    /// When it is done.
    pub exit: String,
}

/// A workflow.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Workflow {
    /// Name, equal to the file stem.
    pub name: String,
    /// One-sentence description.
    pub description: String,
    /// Version text.
    pub version: String,
    /// Phrases that suggest it.
    pub triggers: Vec<String>,
    /// The only tools a turn under this workflow may offer.
    pub allowed_tools: Vec<String>,
    /// Step budget (1 to 10).
    pub max_steps: u32,
    /// Whether the answer must cite.
    pub require_citations: bool,
    /// `inherit`, `ask` or `deny`.
    pub approval: String,
    /// Ordered phases.
    pub phases: Vec<Phase>,
    /// Sections the answer must hold.
    pub output_sections: Vec<String>,
    /// When to stop.
    pub stop_conditions: Vec<String>,
}

fn valid_name(name: &str) -> bool {
    let bytes = name.as_bytes();
    (2..=63).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-')
}

fn valid_phase_id(id: &str) -> bool {
    let bytes = id.as_bytes();
    (1..=41).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-' || *b == b'_')
}

fn text(map: &Map<String, Value>, key: &str) -> Result<String, String> {
    match map.get(key) {
        None | Some(Value::Null) => Ok(String::new()),
        Some(Value::String(s)) => Ok(s.clone()),
        Some(_) => Err(format!("{key} must be text")),
    }
}

fn texts(map: &Map<String, Value>, key: &str) -> Result<Vec<String>, String> {
    match map.get(key) {
        None | Some(Value::Null) => Ok(Vec::new()),
        Some(Value::Array(items)) => items
            .iter()
            .map(|v| match v {
                Value::String(s) => Ok(s.clone()),
                _ => Err(format!("{key} must be a list of text")),
            })
            .collect(),
        Some(_) => Err(format!("{key} must be a list")),
    }
}

impl Workflow {
    fn from_value(stem: &str, value: &Value) -> Result<Self, String> {
        let map = value.as_object().ok_or("expected a mapping")?;
        let name = text(map, "name")?;
        if name != stem || !valid_name(&name) {
            return Err("name must equal the file name (lowercase-dash)".into());
        }
        let description = text(map, "description")?;
        if description.chars().count() < 10 {
            return Err("description is too short".into());
        }
        let allowed_tools = texts(map, "allowed_tools")?;
        if allowed_tools.is_empty() {
            return Err("allowed_tools must not be empty".into());
        }
        let max_steps = match map.get("max_steps") {
            None => 6,
            Some(v) => v
                .as_u64()
                .filter(|n| (1..=10).contains(n))
                .ok_or("max_steps must be 1 to 10")? as u32,
        };
        let approval = match text(map, "approval")?.as_str() {
            "" | "inherit" => "inherit".to_owned(),
            a @ ("ask" | "deny") => a.to_owned(),
            _ => return Err("approval must be inherit, ask or deny".into()),
        };
        let require_citations = match map.get("require_citations") {
            None => false,
            Some(Value::Bool(b)) => *b,
            Some(_) => return Err("require_citations must be true or false".into()),
        };
        let Some(Value::Array(raw_phases)) = map.get("phases") else {
            return Err("phases must be a list".into());
        };
        let mut phases = Vec::new();
        for raw in raw_phases {
            let p = raw.as_object().ok_or("a phase must be a mapping")?;
            let id = text(p, "id")?;
            let goal = text(p, "goal")?;
            if !valid_phase_id(&id) || goal.chars().count() < 3 {
                return Err("a phase needs an id and a goal".into());
            }
            phases.push(Phase {
                id,
                goal,
                instructions: text(p, "instructions")?,
                exit: text(p, "exit")?,
            });
        }
        if phases.is_empty() {
            return Err("at least one phase is required".into());
        }
        Ok(Self {
            name,
            description,
            version: match map.get("version") {
                Some(Value::String(s)) => s.clone(),
                _ => "1.0.0".to_owned(),
            },
            triggers: texts(map, "triggers")?,
            allowed_tools,
            max_steps,
            require_citations,
            approval,
            phases,
            output_sections: texts(map, "output_sections")?,
            stop_conditions: texts(map, "stop_conditions")?,
        })
    }

    /// The workflow as the prompt shows it, cut to `limit` characters.
    pub fn render(&self, request: &str, limit: usize) -> String {
        let mut lines = vec![
            format!(
                "Workflow: {} (v{}) — {}",
                self.name, self.version, self.description
            ),
            format!(
                "Allowed tools: {}. Step limit: {}.",
                self.allowed_tools.join(", "),
                self.max_steps
            ),
            "Follow the phases in order; do not call a tool outside the allowed list.".to_owned(),
        ];
        for (number, phase) in self.phases.iter().enumerate() {
            lines.push(format!("{}. [{}] {}", number + 1, phase.id, phase.goal));
            if !phase.instructions.is_empty() {
                lines.push(format!(
                    "   {}",
                    phase
                        .instructions
                        .split_whitespace()
                        .collect::<Vec<_>>()
                        .join(" ")
                ));
            }
            if !phase.exit.is_empty() {
                lines.push(format!("   Done when: {}", phase.exit));
            }
        }
        if !self.stop_conditions.is_empty() {
            lines.push(format!("Stop when: {}", self.stop_conditions.join("; ")));
        }
        if !self.output_sections.is_empty() {
            lines.push(format!(
                "The final answer MUST contain these sections: {}",
                self.output_sections.join(", ")
            ));
        }
        if !request.is_empty() {
            lines.push(format!("Task: {request}"));
        }
        lines.join("\n").chars().take(limit).collect()
    }

    /// What the client may know: the limits, not the phases.
    pub fn info(&self) -> WorkflowInfo {
        WorkflowInfo {
            name: self.name.clone(),
            description: self.description.clone(),
            triggers: self.triggers.clone(),
            allowed_tools: self.allowed_tools.clone(),
            max_steps: self.max_steps,
            require_citations: self.require_citations,
            approval: self.approval.clone(),
            output_sections: self.output_sections.clone(),
            extra: Map::new(),
        }
    }
}

/// Every workflow of the policy.
#[derive(Debug, Clone, Default)]
pub struct Workflows {
    by_name: BTreeMap<String, Workflow>,
}

impl Workflows {
    /// Reads `.laris/workflows/*.toml`. A file that does not load stops the server: a workflow that silently
    /// vanished would widen what a turn may do.
    pub fn load(snapshot: &Snapshot) -> Result<Self, WorkflowError> {
        let mut by_name = BTreeMap::new();
        for label in snapshot.labels_in(DIR, ".toml") {
            let file = label.rsplit('/').next().unwrap_or(label).to_owned();
            let fail = |reason: String| WorkflowError {
                file: file.clone(),
                reason,
            };
            let source = snapshot
                .text(label)
                .and_then(Result::ok)
                .ok_or_else(|| fail("not readable text".into()))?;
            let value: Value = toml::from_str(source).map_err(|e| fail(e.message().to_owned()))?;
            let stem = file.trim_end_matches(".toml");
            let workflow = Workflow::from_value(stem, &value).map_err(fail)?;
            by_name.insert(workflow.name.clone(), workflow);
        }
        Ok(Self { by_name })
    }

    /// A workflow by name; a leading slash and capitals are forgiven.
    pub fn get(&self, name: &str) -> Option<&Workflow> {
        self.by_name
            .get(name.trim().trim_start_matches('/').to_lowercase().as_str())
    }

    /// The workflow one of whose trigger phrases the request contains, compared without case. When several match, the
    /// longest phrase wins, then the first name. A client that names no workflow still gets the one its user asked
    /// for in words.
    pub fn triggered_by(&self, request: &str) -> Option<&Workflow> {
        let text = request.to_lowercase();
        let mut best: Option<(usize, &Workflow)> = None;
        for workflow in self.by_name.values() {
            let longest = workflow
                .triggers
                .iter()
                .map(|t| t.trim().to_lowercase())
                .filter(|t| !t.is_empty() && text.contains(t.as_str()))
                .map(|t| t.chars().count())
                .max();
            if let Some(length) = longest
                && best.is_none_or(|(b, _)| length > b)
            {
                best = Some((length, workflow));
            }
        }
        best.map(|(_, w)| w)
    }

    /// All workflows, by name.
    pub fn all(&self) -> impl Iterator<Item = &Workflow> {
        self.by_name.values()
    }

    /// Number of workflows.
    pub fn len(&self) -> usize {
        self.by_name.len()
    }

    /// Whether there are none.
    pub fn is_empty(&self) -> bool {
        self.by_name.is_empty()
    }
}
