//! Note schema registry: which properties each note type must carry, and where it lives (SR-L2).
//!
//! The registry is read from `.laris/vault/schema.yaml` (under the integrity lock). A project without that file (a thin
//! client, an adopted vault) uses the same table built into [`BUILTIN_YAML`]; a test keeps the two identical. A note
//! without a `type` belongs to the user and is never checked.

use std::collections::BTreeMap;
use std::path::Path;

use serde_json::{Map, Value as Json, json};

use crate::index::VaultIndex;
use crate::lint::Problem;
use crate::note::{Note, link_name};
use crate::yaml::{self, Value};

/// The registry built into the library.
pub const BUILTIN_YAML: &str = r#"
version: 1
types:
  index: {required: [type], folder: ""}
  source: {required: [type, trust, source, created], links: [concepts], folder: Sources}
  concept: {required: [type, created], folder: Concepts}
  claim: {required: [type, created, source_ref], links: [source_ref], folder: Claims}
  method: {required: [type, created], folder: Concepts}
  dataset: {required: [type, created], folder: Concepts}
  metric: {required: [type, created], folder: Concepts}
  limitation: {required: [type, created, source_ref], links: [source_ref], folder: Claims}
  answer:
    required: [type, trust, session, created]
    links: [session, sources, notes_used]
    folder: Questions
  session: {required: [type, created], folder: Sessions}
  memory: {required: [type, created], folder: Memory}
  decision: {required: [type, created], folder: Decisions}
  analysis: {required: [type, created, scope], folder: Analyses}
  proposal: {required: [type, status, origin, created], folder: _inbox}
  knowledge: {required: [type], folder: Knowledge}
  knowledge-hub: {required: [type, domain], folder: Knowledge}
"#;

/// What one note type asks for.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TypeRule {
    /// Properties that must be present and not empty.
    pub required: Vec<String>,
    /// Properties whose values must be wikilinks that resolve.
    pub links: Vec<String>,
    /// The folder the type lives in; empty for anywhere.
    pub folder: String,
}

/// The registry.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Schema {
    /// Rules by type name.
    pub types: BTreeMap<String, TypeRule>,
}

fn names(rule: &[(String, Value)], key: &str) -> Vec<String> {
    match rule.iter().find(|(k, _)| k == key).map(|(_, v)| v) {
        Some(Value::List(items)) => items.iter().map(Value::py_str).collect(),
        _ => Vec::new(),
    }
}

impl Schema {
    /// Read a registry from YAML text. A document that is not a mapping, or has no `types`, gives an empty registry.
    pub fn from_text(text: &str) -> Result<Schema, String> {
        let doc =
            yaml::parse(text).map_err(|e| format!("schema is not valid YAML: {}", e.message))?;
        let mut types = BTreeMap::new();
        if let Value::Map(top) = doc
            && let Some((_, Value::Map(raw))) = top.iter().find(|(k, _)| k == "types")
        {
            for (name, rule) in raw {
                let Value::Map(rule) = rule else { continue };
                let folder = rule
                    .iter()
                    .find(|(k, _)| k == "folder")
                    .map_or(String::new(), |(_, v)| v.py_str());
                types.insert(
                    name.clone(),
                    TypeRule {
                        required: names(rule, "required"),
                        links: names(rule, "links"),
                        folder,
                    },
                );
            }
        }
        Ok(Schema { types })
    }

    /// The registry built into the library.
    pub fn builtin() -> Schema {
        Schema::from_text(BUILTIN_YAML).expect("built-in schema is valid")
    }

    /// The registry in `path` when the file exists, else the built-in one.
    pub fn load(path: Option<&Path>) -> Result<Schema, String> {
        match path {
            Some(p) if p.is_file() => {
                let text = std::fs::read_to_string(p)
                    .map_err(|e| format!("cannot read {}: {e}", p.display()))?;
                Schema::from_text(&text)
            }
            _ => Ok(Schema::builtin()),
        }
    }

    /// The folder a type lives in; empty for an unknown type or anywhere.
    pub fn folder_of(&self, kind: &str) -> &str {
        self.types.get(kind).map_or("", |r| r.folder.as_str())
    }

    /// The registry as JSON, types sorted.
    pub fn to_json(&self) -> Json {
        let mut out = Map::new();
        for (name, rule) in &self.types {
            out.insert(
                name.clone(),
                json!({"required": rule.required, "links": rule.links, "folder": rule.folder}),
            );
        }
        Json::Object(out)
    }
}

fn folder_ok(path: &str, folder: &str) -> bool {
    folder.is_empty() || path.starts_with(&format!("{folder}/"))
}

fn empty(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => true,
        Some(Value::Str(s)) => s.is_empty(),
        Some(Value::List(l)) => l.is_empty(),
        _ => false,
    }
}

/// The problems of one note against the registry.
pub fn validate_note(note: &Note, index: &VaultIndex, schema: &Schema) -> Vec<Problem> {
    let kind = match note.prop("type") {
        None | Some(Value::Null) => return Vec::new(), // the user's own note
        Some(v) => v.py_str(),
    };
    let Some(rule) = schema.types.get(&kind) else {
        return vec![Problem::new(
            &note.path,
            "schema-type",
            format!("unknown note type: {kind}"),
        )];
    };
    let mut problems = Vec::new();
    for prop in &rule.required {
        if empty(note.prop(prop)) {
            problems.push(Problem::new(
                &note.path,
                "schema-required",
                format!("{kind} needs property {prop}"),
            ));
        }
    }
    for prop in &rule.links {
        for value in note.prop_list(prop) {
            if index.find(&link_name(&value)).is_none() {
                problems.push(Problem::new(
                    &note.path,
                    "schema-link",
                    format!("{prop} does not resolve: {value}"),
                ));
            }
        }
    }
    if kind != "proposal" && !folder_ok(&note.path, &rule.folder) {
        problems.push(Problem::new(
            &note.path,
            "schema-folder",
            format!("{kind} notes live in {}/", rule.folder),
        ));
    }
    problems
}

/// The schema problems of a whole vault, in path order.
pub fn lint_schema(index: &VaultIndex, schema: &Schema) -> Vec<Problem> {
    index
        .notes
        .values()
        .flat_map(|note| validate_note(note, index, schema))
        .collect()
}
