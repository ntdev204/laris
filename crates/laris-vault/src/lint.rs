//! Vault lint: format problems, the hub-tree rules of the system brain and content limits (SR-L2, SR-B6).
//!
//! Every function reads an index and returns the problems in a fixed order (path order, then rule order), so two runs
//! on the same vault give the same list. The limits are arguments: the caller reads them from configuration.

use std::collections::{BTreeMap, VecDeque};
use std::fmt;
use std::sync::LazyLock;

use regex::Regex;

use crate::index::VaultIndex;
use crate::note::{FORBIDDEN_NAME_CHARS, LinkSource, link_name};
use crate::writer::MAX_TITLE_CHARS;
use crate::yaml::Value;

static PROP_NAME: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[A-Za-z][\w-]*$").expect("static pattern"));

/// One finding.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Problem {
    /// The note the finding is about (or the root title when the root is missing).
    pub path: String,
    /// The rule that found it, as a short code.
    pub code: String,
    /// A sentence for people.
    pub message: String,
}

impl Problem {
    /// A finding.
    pub fn new(path: &str, code: &str, message: impl Into<String>) -> Problem {
        Problem {
            path: path.to_string(),
            code: code.to_string(),
            message: message.into(),
        }
    }
}

impl fmt::Display for Problem {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: [{}] {}", self.path, self.code, self.message)
    }
}

/// Python's name for the type of a property value, as generation 1 compared them.
fn type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Int(_) => "int",
        Value::Float(_) => "float",
        Value::Str(_) => "str",
        Value::Date(_) => "date",
        Value::DateTime(_) => "datetime",
        Value::List(_) => "list",
        Value::Map(_) => "dict",
    }
}

/// Rules that apply to every vault: names, properties, links.
pub fn lint_format(index: &VaultIndex) -> Vec<Problem> {
    let mut problems = Vec::new();
    let mut types: BTreeMap<&str, &'static str> = BTreeMap::new();
    for (path, note) in &index.notes {
        for err in &note.errors {
            problems.push(Problem::new(path, "properties", err.clone()));
        }
        if note.title.chars().any(|c| FORBIDDEN_NAME_CHARS.contains(c))
            || note.title.chars().count() > MAX_TITLE_CHARS
        {
            problems.push(Problem::new(
                path,
                "name",
                "note name has characters that break links",
            ));
        }
        for (name, value) in &note.props {
            if !PROP_NAME.is_match(name) {
                problems.push(Problem::new(
                    path,
                    "property-name",
                    format!("unsafe property name: {name}"),
                ));
            }
            let kind = type_name(value);
            if !matches!(value, Value::Null) {
                let first = *types.entry(name.as_str()).or_insert(kind);
                if first != kind {
                    problems.push(Problem::new(
                        path,
                        "property-type",
                        format!("{name} is {kind} here, {first} elsewhere"),
                    ));
                }
            }
            if matches!(value, Value::Map(_)) {
                problems.push(Problem::new(
                    path,
                    "property-nested",
                    format!("{name} must not be nested"),
                ));
            }
        }
    }
    for (path, target) in &index.unresolved {
        problems.push(Problem::new(
            path,
            "link",
            format!("unresolved link: [[{target}]]"),
        ));
    }
    for (path, target) in &index.ambiguous {
        problems.push(Problem::new(
            path,
            "link",
            format!("ambiguous link: [[{target}]]"),
        ));
    }
    problems
}

/// The limits of the hub tree (spec SR-B6); the caller reads them from configuration.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HierarchyRules<'a> {
    /// Title of the root note.
    pub root_title: &'a str,
    /// Deepest level allowed (the root is level 0).
    pub max_depth: usize,
    /// Most children a hub may list.
    pub max_children: usize,
    /// Properties every note must carry.
    pub required: &'a [&'a str],
    /// Longest `summary`, in characters.
    pub summary_max_chars: usize,
    /// Relation properties whose targets must exist.
    pub relations: &'a [&'a str],
}

/// The hub-tree rules of the system brain.
pub fn lint_hierarchy(index: &VaultIndex, rules: &HierarchyRules<'_>) -> Vec<Problem> {
    let Some(root) = index.find(rules.root_title) else {
        return vec![Problem::new(
            rules.root_title,
            "root",
            "root note is missing",
        )];
    };
    let root_path = root.path.clone();
    let mut problems = Vec::new();
    for (path, note) in &index.notes {
        for prop in rules.required {
            let missing = match note.prop(prop) {
                None | Some(Value::Null) => true,
                Some(Value::Str(s)) => s.is_empty(),
                Some(Value::List(l)) => l.is_empty(),
                _ => false,
            };
            if missing {
                problems.push(Problem::new(
                    path,
                    "property",
                    format!("missing property: {prop}"),
                ));
            }
        }
        let summary = note.prop("summary").map_or(String::new(), Value::py_str);
        if summary.chars().count() > rules.summary_max_chars {
            problems.push(Problem::new(path, "summary", "summary is too long"));
        }
    }
    let mut parent_of: BTreeMap<String, String> = BTreeMap::new();
    for (path, note) in &index.notes {
        let children = index.targets(path, "children");
        if children.len() > rules.max_children {
            problems.push(Problem::new(
                path,
                "wide-hub",
                format!("{} children (max {})", children.len(), rules.max_children),
            ));
        }
        for child in &children {
            if parent_of.get(child).is_some_and(|p| p != path) {
                problems.push(Problem::new(
                    child,
                    "parents",
                    "more than one parent lists this note",
                ));
            }
            parent_of.insert(child.clone(), path.clone());
        }
        let declared: std::collections::BTreeSet<String> = note
            .prop_list("children")
            .iter()
            .map(|c| link_name(c))
            .collect();
        let body_links: std::collections::BTreeSet<&str> = note
            .links
            .iter()
            .filter(|l| l.source == LinkSource::Body)
            .map(|l| l.target.as_str())
            .collect();
        for name in declared.iter().filter(|n| !body_links.contains(n.as_str())) {
            problems.push(Problem::new(
                path,
                "hub-body",
                format!("child [[{name}]] is not described in the body"),
            ));
        }
        for relation in rules.relations {
            for target in note.prop_list(relation) {
                if index.find(&link_name(&target)).is_none() {
                    problems.push(Problem::new(
                        path,
                        "relation",
                        format!("{relation} target missing: {target}"),
                    ));
                }
            }
        }
    }
    let mut depth: BTreeMap<String, usize> = BTreeMap::new();
    let mut queue = VecDeque::from([(root_path.clone(), 0usize)]);
    while let Some((path, d)) = queue.pop_front() {
        if depth.contains_key(&path) {
            continue;
        }
        queue.extend(
            index
                .targets(&path, "children")
                .into_iter()
                .map(|c| (c, d + 1)),
        );
        depth.insert(path, d);
    }
    for (path, note) in &index.notes {
        let Some(&d) = depth.get(path) else {
            problems.push(Problem::new(
                path,
                "orphan",
                "not reachable from the root through children",
            ));
            continue;
        };
        if d > rules.max_depth {
            problems.push(Problem::new(
                path,
                "depth",
                format!("depth {d} exceeds {}", rules.max_depth),
            ));
        }
        if *path != root_path {
            let declared = index.targets(path, "parent");
            if declared.first() != parent_of.get(path) {
                problems.push(Problem::new(
                    path,
                    "parent",
                    "parent does not match the listing hub",
                ));
            }
        }
        let level = note.prop("level").map_or("".to_string(), Value::py_str);
        if level != d.to_string() {
            problems.push(Problem::new(path, "level", format!("level should be {d}")));
        }
    }
    problems
}

/// Rules about what a note contains: oversize, duplicate aliases, stored secrets. `redact` returns the text with
/// secrets replaced; a note whose text changes under it holds a secret.
pub fn lint_content(
    index: &VaultIndex,
    max_note_chars: usize,
    max_property_chars: usize,
    redact: Option<&dyn Fn(&str) -> String>,
) -> Vec<Problem> {
    let mut problems = Vec::new();
    let mut aliases: BTreeMap<String, String> = BTreeMap::new();
    for (path, note) in &index.notes {
        if note.body.chars().count() > max_note_chars {
            problems.push(Problem::new(
                path,
                "oversize",
                format!("note is longer than {max_note_chars} chars"),
            ));
        }
        for (name, value) in &note.props {
            if value.py_str().chars().count() > max_property_chars {
                problems.push(Problem::new(
                    path,
                    "oversize",
                    format!("property {name} is very long"),
                ));
            }
        }
        for alias in note.prop_list("aliases") {
            let key = alias.trim().to_lowercase();
            match aliases.get(&key) {
                Some(owner) if owner != path => problems.push(Problem::new(
                    path,
                    "alias",
                    format!("alias '{alias}' is also used by {owner}"),
                )),
                Some(_) => {}
                None => {
                    aliases.insert(key, path.clone());
                }
            }
        }
        if let Some(redact) = redact {
            let props: Vec<String> = note.props.iter().map(|(_, v)| v.py_str()).collect();
            let text = format!("{}\n{}", note.body, props.join("\n"));
            if redact(&text) != text {
                problems.push(Problem::new(
                    path,
                    "secret",
                    "the note appears to contain a secret",
                ));
            }
        }
    }
    problems
}
