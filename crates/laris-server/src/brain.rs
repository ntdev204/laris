//! The system brain service (SR-S5): the curated hub tree in `.laris/brain/`, read by the server for the model, one
//! step at a time.
//!
//! The brain is a folder of Obsidian-format notes (`docs/specifications/OBSIDIAN_VAULT_FORMAT.md`): a root note
//! (`Brain Index`), domain hubs, playbooks and leaves joined by `children`. The model never gets the whole tree. It
//! gets a *brief* in the prompt (the hub a workflow routes to, its children and its playbook, summaries only) and one
//! tool, `use_system_brain`, with three operations that disclose a little more each time:
//!
//! * `index`: the root's summary, the domain hubs with their summaries, and the routing table;
//! * `open <id>`: one note's summary, its parent and its links with their summaries (no body);
//! * `read <id>`: the note's text, cut to the budget.
//!
//! A note deeper than `max_depth` steps from the root is refused, so every direction reaches its playbook in at most
//! that many steps and without search. Each answer has budgets (calls and characters); every result says how much of
//! them is used. The service has no write path: it holds a [`VaultIndex`] and only reads it, and its notes are outside
//! the model's reach except through these operations. What an answer consulted is a list of note titles
//! ([`Consulted`]): it goes to the client as the evidence list of `LarisMeta` and to the audit row as ids, never
//! as text. The notes are confidential: their text is part of what the guard stops from leaving the server.
//! Their text is low authority: it says how to work, never what is allowed.

use crate::policy::LoadError;
use laris_vault::{Note, VaultIndex};
use serde_json::{Value, json};
use std::collections::{BTreeMap, VecDeque};
use std::path::Path;

const DIR: &str = ".laris/brain";

/// The name of the tool through which the model consults the system brain.
pub const BRAIN_TOOL: &str = "use_system_brain";

/// Settings of the brain, from `LARIS_SERVER__BRAIN_*` variables.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BrainSettings {
    /// Offer the brain at all.
    pub enabled: bool,
    /// Title of the root note.
    pub root_note: String,
    /// Deepest note, in steps from the root, that may be opened.
    pub max_depth: usize,
    /// Longest summary shown in a list, in characters.
    pub summary_chars: usize,
    /// Most characters of the index.
    pub index_chars: usize,
    /// Most characters of one `open` or `read` result.
    pub open_chars: usize,
    /// Most characters of all results of one answer.
    pub turn_chars: usize,
    /// Most characters of the brief in the prompt.
    pub brief_chars: usize,
    /// Most calls of the tool in one answer.
    pub max_calls: usize,
}

impl Default for BrainSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            root_note: "Brain Index".to_owned(),
            max_depth: 3,
            summary_chars: 260,
            index_chars: 2_500,
            open_chars: 3_500,
            turn_chars: 6_000,
            brief_chars: 2_200,
            max_calls: 6,
        }
    }
}

/// What one answer has consulted so far: note titles in the order they were opened, and the budget used.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Consulted {
    titles: Vec<String>,
    calls: usize,
    chars: usize,
}

impl Consulted {
    /// A list that starts with the notes of a brief.
    pub fn seeded(titles: &[String]) -> Self {
        let mut c = Self::default();
        for t in titles {
            c.note(t);
        }
        c
    }

    /// The titles, in the order they were opened, each once.
    pub fn titles(&self) -> &[String] {
        &self.titles
    }

    /// Calls made.
    pub fn calls(&self) -> usize {
        self.calls
    }

    /// Characters handed out.
    pub fn chars(&self) -> usize {
        self.chars
    }

    fn note(&mut self, title: &str) {
        if !self.titles.iter().any(|t| t == title) {
            self.titles.push(title.to_owned());
        }
    }
}

/// The hub a workflow routes to, as the prompt shows it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Brief {
    /// The route name.
    pub route: String,
    /// The notes the brief draws on, hub first.
    pub titles: Vec<String>,
    /// The text.
    pub text: String,
}

/// The system brain: a read-only view of `.laris/brain/`.
pub struct Brain {
    settings: BrainSettings,
    index: Option<VaultIndex>,
    root: String,
    depth: BTreeMap<String, usize>,
    routes: BTreeMap<String, String>,
    /// Why the brain is not served, or what was skipped (never content).
    pub problems: Vec<String>,
}

fn cut(text: &str, limit: usize) -> String {
    if text.chars().count() <= limit {
        return text.to_owned();
    }
    let keep = limit.saturating_sub(1);
    let mut out: String = text.chars().take(keep).collect();
    out.push('…');
    out
}

fn one_line(text: &str, limit: usize) -> String {
    cut(
        &text.split_whitespace().collect::<Vec<_>>().join(" "),
        limit,
    )
}

impl Brain {
    /// A brain that serves nothing.
    pub fn none(settings: BrainSettings) -> Self {
        Self {
            root: settings.root_note.clone(),
            settings,
            index: None,
            depth: BTreeMap::new(),
            routes: BTreeMap::new(),
            problems: Vec::new(),
        }
    }

    /// Reads `<root>/.laris/brain/`. A missing folder or root note is a problem, not an error: the server runs
    /// without a brain.
    pub fn load(root: &Path, settings: BrainSettings) -> Self {
        let mut brain = Self::none(settings);
        if !brain.settings.enabled {
            return brain;
        }
        let dir = root.join(DIR);
        if !dir.is_dir() {
            brain
                .problems
                .push("the brain folder is missing".to_owned());
            return brain;
        }
        let index = match VaultIndex::build(&dir, None) {
            Ok(index) => index,
            Err(_) => {
                brain
                    .problems
                    .push("the brain folder is unreadable".to_owned());
                return brain;
            }
        };
        let Some(root_note) = index.find(&brain.settings.root_note) else {
            brain.problems.push(format!(
                "root note '{}' is missing",
                brain.settings.root_note
            ));
            return brain;
        };
        brain.root = root_note.title.clone();
        let root_path = root_note.path.clone();
        for line in root_note.body.lines() {
            if let Some(rest) = line.trim().strip_prefix("route:")
                && let Some((name, target)) = rest.split_once("->")
            {
                let hub = laris_vault::note::link_name(target.trim());
                if index.find(&hub).is_some() && !name.trim().is_empty() {
                    brain.routes.insert(name.trim().to_owned(), hub);
                } else {
                    brain
                        .problems
                        .push(format!("route '{}' points at nothing", name.trim()));
                }
            }
        }
        let mut queue = VecDeque::from([(root_path, 0usize)]);
        let mut seen: BTreeMap<String, usize> = BTreeMap::new();
        while let Some((path, d)) = queue.pop_front() {
            if seen.contains_key(&path) {
                continue;
            }
            for child in index.targets(&path, "children") {
                queue.push_back((child, d + 1));
            }
            seen.insert(path, d);
        }
        brain.depth = seen
            .into_iter()
            .filter_map(|(path, d)| index.notes.get(&path).map(|n| (n.title.clone(), d)))
            .collect();
        brain.index = Some(index);
        brain
    }

    /// Whether the brain is served.
    pub fn offered(&self) -> bool {
        self.settings.enabled && self.index.is_some()
    }

    /// The settings in force.
    pub fn settings(&self) -> &BrainSettings {
        &self.settings
    }

    /// Most calls one answer may make; zero when no brain is served.
    pub fn max_calls(&self) -> usize {
        if self.offered() {
            self.settings.max_calls
        } else {
            0
        }
    }

    /// The text of every note, for the guard: none of it may leave the server.
    pub fn texts(&self) -> Vec<String> {
        self.index
            .as_ref()
            .map(|i| i.notes.values().map(|n| n.body.clone()).collect())
            .unwrap_or_default()
    }

    /// The titles of the notes that can be opened, in path order.
    pub fn titles(&self) -> Vec<&str> {
        self.index
            .as_ref()
            .map(|i| {
                i.notes
                    .values()
                    .filter(|n| self.depth.contains_key(&n.title))
                    .map(|n| n.title.as_str())
                    .collect()
            })
            .unwrap_or_default()
    }

    /// Steps from the root to the note, or `None` when it is not in the tree.
    pub fn depth_of(&self, title: &str) -> Option<usize> {
        self.depth.get(title).copied()
    }

    /// The hub a route (a workflow name or a task type) leads to.
    pub fn route(&self, name: &str) -> Option<&str> {
        self.routes.get(name).map(String::as_str)
    }

    /// Every route and its hub.
    pub fn routes(&self) -> &BTreeMap<String, String> {
        &self.routes
    }

    fn note(&self, id: &str) -> Option<&Note> {
        let id = laris_vault::note::link_name(id.trim());
        self.index.as_ref()?.find(&id)
    }

    fn summary(&self, note: &Note) -> String {
        one_line(
            &note.prop_list("summary").join(" "),
            self.settings.summary_chars,
        )
    }

    fn kind(note: &Note) -> String {
        note.prop_list("type").join(" ")
    }

    fn children(&self, note: &Note) -> Vec<&Note> {
        let Some(index) = &self.index else {
            return Vec::new();
        };
        index
            .targets(&note.path, "children")
            .iter()
            .filter_map(|p| index.notes.get(p))
            .collect()
    }

    fn linked(&self, note: &Note, prop: &str) -> Vec<&Note> {
        let Some(index) = &self.index else {
            return Vec::new();
        };
        index
            .targets(&note.path, prop)
            .iter()
            .filter_map(|p| index.notes.get(p))
            .collect()
    }

    fn list(&self, notes: &[&Note]) -> String {
        notes
            .iter()
            .map(|n| format!("- {} — {}", n.title, self.summary(n)))
            .collect::<Vec<_>>()
            .join("\n")
    }

    /// The brain for a workflow: its hub, the hub's children and its playbook, summaries only.
    pub fn brief(&self, route: &str) -> Option<Brief> {
        if !self.offered() {
            return None;
        }
        let hub = self.note(self.route(route)?)?;
        let children = self.children(hub);
        let playbook = children
            .iter()
            .copied()
            .chain(self.linked(hub, "uses"))
            .find(|n| Self::kind(n) == "playbook");
        let mut titles = vec![hub.title.clone()];
        let mut text = format!(
            "Route {route} leads to the hub {} — {}\nNotes under it:\n{}",
            hub.title,
            self.summary(hub),
            self.list(&children)
        );
        if let Some(p) = playbook {
            titles.push(p.title.clone());
            text.push_str(&format!(
                "\nPlaybook {}: {}\nIts sections: {}.",
                p.title,
                self.summary(p),
                p.headings
                    .iter()
                    .skip(1)
                    .cloned()
                    .collect::<Vec<_>>()
                    .join(", ")
            ));
        }
        text.push_str(&format!(
            "\nOpen any of these with {BRAIN_TOOL} (action open or read, id = the title) when the request needs it."
        ));
        Some(Brief {
            route: route.to_owned(),
            titles,
            text: cut(&text, self.settings.brief_chars),
        })
    }

    /// The tool the model uses.
    pub fn tool_schema(&self) -> Value {
        let hubs = self
            .index
            .as_ref()
            .and_then(|i| i.find(&self.root))
            .map(|root| {
                self.children(root)
                    .iter()
                    .map(|n| n.title.clone())
                    .collect::<Vec<_>>()
                    .join(", ")
            })
            .unwrap_or_default();
        json!({
            "type": "function",
            "function": {
                "name": BRAIN_TOOL,
                "description": format!(
                    "Read the system brain: curated guidance on how to do research tasks (never the user's data). \
                     Start with action index, then open a hub, then read the playbook or the note you need. \
                     Domain hubs: {hubs}. Cite a note you used as [brain: Title]."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["index", "open", "read"],
                            "description": "index: the hubs; open: a note's summary and links; read: a note's text."
                        },
                        "id": {"type": "string", "description": "A note title from the index or from a list."}
                    },
                    "required": ["action"]
                }
            }
        })
    }

    fn index_text(&self) -> String {
        let Some(root) = self.index.as_ref().and_then(|i| i.find(&self.root)) else {
            return String::new();
        };
        let mut text = format!(
            "{} — {}\nDomain hubs:\n{}\nRoutes:",
            root.title,
            self.summary(root),
            self.list(&self.children(root))
        );
        for (route, hub) in &self.routes {
            text.push_str(&format!("\n{route} -> {hub}"));
        }
        cut(&text, self.settings.index_chars)
    }

    fn open_text(&self, note: &Note) -> String {
        let mut text = format!(
            "{} ({}, {} step(s) from the root)\n{}",
            note.title,
            Self::kind(note),
            self.depth_of(&note.title).unwrap_or(0),
            self.summary(note)
        );
        for (label, prop) in [
            ("Parent", "parent"),
            ("Notes under it", "children"),
            ("Uses", "uses"),
            ("Feeds", "feeds"),
        ] {
            let linked = self.linked(note, prop);
            if !linked.is_empty() {
                text.push_str(&format!("\n{label}:\n{}", self.list(&linked)));
            }
        }
        if note.headings.len() > 1 {
            text.push_str(&format!("\nSections: {}.", note.headings[1..].join(", ")));
        }
        text.push_str("\nUse action read with the title to get the text.");
        text
    }

    /// Answers one call of the tool. The error text is what the model reads.
    ///
    /// Every call counts against the answer's budgets; the result ends with how much is used.
    pub fn consult(&self, args: &Value, used: &mut Consulted) -> Result<String, LoadError> {
        let s = &self.settings;
        used.calls += 1;
        if used.calls > s.max_calls {
            return Err(LoadError(
                "Error: the limit of brain calls for this answer is reached; answer with what you have.".into(),
            ));
        }
        let left = s.turn_chars.saturating_sub(used.chars);
        if left == 0 {
            return Err(LoadError(
                "Error: the brain budget for this answer is used; answer with what you have."
                    .into(),
            ));
        }
        let action = args
            .get("action")
            .and_then(Value::as_str)
            .unwrap_or("index");
        let id = args.get("id").and_then(Value::as_str).unwrap_or_default();
        let (title, text, cap) = match action {
            "index" => (None, self.index_text(), s.index_chars),
            "open" | "read" => {
                let note = self.note(id).ok_or_else(|| {
                    LoadError(format!(
                        "Error: no note named '{}'. Call action index to see the hubs.",
                        id.chars().take(60).collect::<String>()
                    ))
                })?;
                let Some(depth) = self.depth_of(&note.title) else {
                    return Err(LoadError(format!(
                        "Error: '{}' is not part of the brain tree.",
                        note.title
                    )));
                };
                if depth > s.max_depth {
                    return Err(LoadError(format!(
                        "Error: '{}' is {depth} steps from the root; the limit is {}.",
                        note.title, s.max_depth
                    )));
                }
                let text = if action == "open" {
                    self.open_text(note)
                } else {
                    format!(
                        "{}\n{}\n\n{}",
                        note.title,
                        self.summary(note),
                        note.body.trim()
                    )
                };
                (Some(note.title.clone()), text, s.open_chars)
            }
            other => {
                return Err(LoadError(format!(
                    "Error: unknown action '{}'. Use index, open or read.",
                    other.chars().take(20).collect::<String>()
                )));
            }
        };
        let mut text = cut(&text, cap.min(left));
        used.chars += text.chars().count();
        if let Some(t) = title {
            used.note(&t);
        }
        text.push_str(&format!(
            "\n[brain budget: {} of {} calls, {} of {} characters]",
            used.calls, s.max_calls, used.chars, s.turn_chars
        ));
        Ok(text)
    }
}
