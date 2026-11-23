//! The single write gate of the main brain (SR-K3, ADR-024 section 4).
//!
//! ```text
//! proposal -> 1 shape -> 2 span -> 3 metadata -> 4 support -> 5 evidence -> 6 contradiction search -> 7 write | refuse
//! ```
//!
//! [`Gate`] is the only code that writes the vault: it creates Sources, Claims, Theories and Conflicts, raises a Claim's
//! level on evidence and lowers it when evidence goes away. A refusal changes nothing in the vault and is recorded in the
//! audit. Model-only text has no Source, so it is refused at step 1; text a model wrote *about* a Source is checked
//! against the Source's own words at steps 2 and 4.
//!
//! The checks read vocabulary, not meaning ([`crate::text`]): they refuse what is plainly unsupported and keep what is
//! supported in words. Their misses are measured, not assumed zero.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use laris_retrieval::NoteSearch;
use laris_vault::brain::{Level, resolve_span, sha256_hex};
use laris_vault::index::VaultIndex;
use laris_vault::note::{Note, link_name, parse_note};
use laris_vault::writer::{atomic_write, render_note, resolve_inside, safe_title};
use laris_vault::{Value, lint_brain};
use serde_json::json;

use crate::audit;
use crate::text::{self, Facts};

/// Folder of retired notes below `.laris/`, outside the vault index.
const RETIRED: &str = ".laris/retired";

/// Thresholds of the rule checks, filled by whoever owns the configuration. There is no default.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct GateSettings {
    /// Share of a statement's content words that must occur in its quote (0 to 1).
    pub min_support: f64,
    /// Content overlap (Jaccard) at which two statements count as the same (0 to 1).
    pub min_equivalence: f64,
    /// Content overlap at which two statements count as being on the same subject (0 to 1).
    pub subject_overlap: f64,
    /// How many notes the contradiction search reads per proposal.
    pub search_depth: usize,
    /// Longest statement, quote or Source text, in bytes.
    pub max_bytes: usize,
}

/// Who proposed something: an advisor id, a tool name or a person. It is recorded, never trusted.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Proposer(pub String);

/// The result of the identifier and metadata check of T165 for a document Source.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MetadataCheck {
    /// The identifier resolved and the authors and date match; the registry that said so.
    Verified(String),
    /// The registry gave other metadata.
    Mismatch(String),
    /// The identifier could not be resolved.
    Unresolved,
    /// No check ran (a tool run has no registry entry).
    NotApplicable,
}

/// A Source to store: the verbatim text of a document or the output of a tool run.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceProposal {
    /// Note name.
    pub title: String,
    /// `document` or `tool_run`.
    pub kind: String,
    /// DOI, URL or tool name that identifies it.
    pub identifier: String,
    /// The text, kept byte for byte.
    pub text: String,
    /// The command, for a tool run.
    pub command: Option<String>,
    /// Hash of the inputs, for a tool run.
    pub inputs_sha256: Option<String>,
    /// Identifiers of the documents this one cites (kept for the independence check of corroboration).
    pub cites: Vec<String>,
    /// The dataset release it reports on, when it names one.
    pub dataset: Option<String>,
    /// The metadata check.
    pub metadata: MetadataCheck,
    /// The admission record (T285), stored with the Source; `None` for a Source that is never certain.
    pub admission: Option<Admission>,
    /// Who proposed it.
    pub proposer: Proposer,
}

/// What the importer found about a document Source at import (T285): its class, the registry that resolved it with
/// the hash of that registry's response, its licence, its venue and the retraction check. The gate stores it; whether
/// it makes a Claim certain is decided when the Claim is read ([`crate::certain`]), against the configured classes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Admission {
    /// Source class name (configuration).
    pub class: String,
    /// The registry that resolved the identifier.
    pub resolved_by: String,
    /// SHA-256 of the registry's response.
    pub resolution_sha256: String,
    /// The licence, as the class lists it.
    pub licence: String,
    /// The venue (ISSN), when the class has a venue list.
    pub venue: Option<String>,
    /// `REGISTRY:none` or `REGISTRY:retracted`, when the class needs a check.
    pub retraction_check: Option<String>,
}

/// Evidence for a level above `sourced` (ADR-024 3.2).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Evidence {
    /// Another Claim on an independent Source states the same thing.
    Corroborated {
        /// Note name of that Claim.
        with: String,
        /// Why the Sources are independent.
        independence: String,
    },
    /// A tool run reproduces or checks the claim.
    ToolRun {
        /// Note name of the `tool_run` Source.
        source: String,
    },
    /// A person accepted it.
    Reviewed {
        /// Who.
        reviewer: String,
        /// When, `YYYY-MM-DD`.
        on: String,
    },
}

impl Evidence {
    fn level(&self) -> Level {
        match self {
            Evidence::Corroborated { .. } => Level::Corroborated,
            Evidence::ToolRun { .. } => Level::Verified,
            Evidence::Reviewed { .. } => Level::Reviewed,
        }
    }
}

/// A Claim to store.
#[derive(Debug, Clone, PartialEq)]
pub struct ClaimProposal {
    /// The atomic statement.
    pub statement: String,
    /// Note name of the Source; `None` is model-only text and is refused.
    pub source: Option<String>,
    /// The exact words of the Source that the statement rests on.
    pub quote: String,
    /// The level asked for; it cannot be above what the evidence holds, and `candidate` is refused.
    pub requested: Level,
    /// Evidence for levels above `sourced`.
    pub evidence: Vec<Evidence>,
    /// Note name of a `tool_run` Source that holds the solver call computing with this Claim's formula. It links the
    /// Claim to a computation; it is not evidence and does not raise the level.
    pub solver: Option<String>,
    /// Who proposed it.
    pub proposer: Proposer,
}

/// A Theory to store: a position attributed to someone, never asserted as fact.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TheoryProposal {
    /// The position, in the attributing words ("X argues that ...").
    pub statement: String,
    /// Who holds it.
    pub attributed_to: String,
    /// Note name of the Source.
    pub source: Option<String>,
    /// The exact words of the Source.
    pub quote: String,
    /// Who proposed it.
    pub proposer: Proposer,
}

/// Why the gate refused.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Refusal {
    /// The proposal is malformed.
    Shape,
    /// The text has no Source: model-only text never becomes a Claim.
    ModelOnly,
    /// The Source does not exist or is not a Source note.
    UnknownSource,
    /// The Source is retracted or superseded.
    SourceNotActive,
    /// The quote is not in the Source.
    Span,
    /// The identifier or metadata did not check out.
    Metadata,
    /// The quote does not support the statement.
    Unsupported,
    /// The level asked for is above the evidence, or is `candidate`.
    Level,
    /// The evidence does not hold.
    Evidence,
    /// The note exists already (Sources are immutable; Claims are raised through evidence).
    Duplicate,
}

impl Refusal {
    /// The code written in the audit.
    pub fn as_str(self) -> &'static str {
        match self {
            Refusal::Shape => "shape",
            Refusal::ModelOnly => "model-only",
            Refusal::UnknownSource => "unknown-source",
            Refusal::SourceNotActive => "source-not-active",
            Refusal::Span => "span",
            Refusal::Metadata => "metadata",
            Refusal::Unsupported => "unsupported",
            Refusal::Level => "level",
            Refusal::Evidence => "evidence",
            Refusal::Duplicate => "duplicate",
        }
    }
}

/// What the gate decided.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Decision {
    /// Written (or already there, unchanged).
    Accepted {
        /// Vault-relative path of the note.
        path: String,
        /// The level of a Claim; `None` for other notes.
        level: Option<Level>,
        /// Conflict notes written or joined because of this proposal.
        conflicts: Vec<String>,
    },
    /// Not written.
    Refused {
        /// The kind of refusal.
        reason: Refusal,
        /// What exactly failed.
        detail: String,
    },
}

impl Decision {
    /// True for [`Decision::Accepted`].
    pub fn is_accepted(&self) -> bool {
        matches!(self, Decision::Accepted { .. })
    }
}

/// A failure that is not a refusal: the vault could not be read or written.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GateError(pub String);

impl std::fmt::Display for GateError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for GateError {}

impl From<std::io::Error> for GateError {
    fn from(e: std::io::Error) -> Self {
        GateError(e.to_string())
    }
}

/// What consolidation changed.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ConsolidationReport {
    /// Notes moved out of the brain, with the reason.
    pub retired: Vec<(String, String)>,
    /// Claims whose level fell: path, from, to.
    pub downgraded: Vec<(String, Level, Level)>,
    /// Claims pointed at the replacing Source.
    pub repointed: Vec<String>,
    /// Notes whose dead links were removed.
    pub pruned: Vec<String>,
}

impl ConsolidationReport {
    /// True when nothing changed.
    pub fn is_empty(&self) -> bool {
        self.retired.is_empty()
            && self.downgraded.is_empty()
            && self.repointed.is_empty()
            && self.pruned.is_empty()
    }
}

type Refused = (Refusal, String);
type Props = Vec<(String, Value)>;
type Edit<'a> = &'a mut dyn FnMut(&mut Props);

fn refuse<T>(reason: Refusal, detail: impl Into<String>) -> Result<T, Refused> {
    Err((reason, detail.into()))
}

fn prop_text(note: &Note, name: &str) -> String {
    note.prop(name).map_or(String::new(), Value::py_str)
}

fn kind_of(note: &Note) -> String {
    prop_text(note, "type")
}

fn link(title: &str) -> Value {
    Value::Str(format!("[[{title}]]"))
}

fn title_of(path: &str) -> String {
    let name = path.rsplit('/').next().unwrap_or(path);
    name.strip_suffix(".md").unwrap_or(name).to_string()
}

fn get<'a>(props: &'a [(String, Value)], name: &str) -> Option<&'a Value> {
    props.iter().find(|(k, _)| k == name).map(|(_, v)| v)
}

fn set(props: &mut Vec<(String, Value)>, name: &str, value: Value) {
    match props.iter_mut().find(|(k, _)| k == name) {
        Some(slot) => slot.1 = value,
        None => props.push((name.to_string(), value)),
    }
}

fn unset(props: &mut Vec<(String, Value)>, name: &str) {
    props.retain(|(k, _)| k != name);
}

fn list_of(props: &[(String, Value)], name: &str) -> Vec<String> {
    match get(props, name) {
        Some(Value::List(items)) => items.iter().map(Value::py_str).collect(),
        Some(Value::Null) | None => Vec::new(),
        Some(other) => vec![other.py_str()],
    }
}

fn set_list(props: &mut Vec<(String, Value)>, name: &str, items: Vec<String>) {
    if items.is_empty() {
        unset(props, name);
    } else {
        set(
            props,
            name,
            Value::List(items.into_iter().map(Value::Str).collect()),
        );
    }
}

/// What a note's front matter looks like once edited, with the text after it untouched.
fn splice_front(text: &str, edit: Edit) -> Result<String, GateError> {
    let rest = text
        .strip_prefix("---\n")
        .ok_or_else(|| GateError("note has no front matter".into()))?;
    let close = rest
        .find("\n---\n")
        .ok_or_else(|| GateError("note front matter is not closed".into()))?;
    let after = &rest[close + 5..];
    let mut props = parse_note(text, "x.md").props;
    edit(&mut props);
    let front = laris_vault::emit::dump_properties(&props).map_err(|e| GateError(e.to_string()))?;
    Ok(format!("---\n{front}\n---\n{after}"))
}

/// The body of a note exactly as the parser reads it once written by [`render_note`].
fn canonical_body(text: &str) -> String {
    let probe = format!("---\ntype: probe\n---\n\n{}\n", text.trim());
    parse_note(&probe, "probe.md").body
}

/// The search the contradiction check reads: Claims and Theories.
fn claim_search(index: &VaultIndex) -> NoteSearch {
    let folders = ["Claims".to_string(), "Theories".to_string()];
    NoteSearch::new(index, &folders)
}

/// The only writer of the main brain.
pub struct Gate {
    root: PathBuf,
    settings: GateSettings,
    today: Box<dyn Fn() -> String + Send + Sync>,
}

impl Gate {
    /// A gate for the vault at `root`. `today` gives the date as `YYYY-MM-DD`.
    pub fn new(
        root: &Path,
        settings: GateSettings,
        today: Box<dyn Fn() -> String + Send + Sync>,
    ) -> Gate {
        Gate {
            root: root.to_path_buf(),
            settings,
            today,
        }
    }

    /// The vault root.
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// The thresholds this gate was built with.
    pub fn settings(&self) -> GateSettings {
        self.settings
    }

    /// The brain as an index, read fresh from disk.
    pub fn index(&self) -> Result<VaultIndex, GateError> {
        VaultIndex::build(&self.root, None)
            .map_err(|e| GateError(format!("cannot read the brain: {e:?}")))
    }

    fn date(&self) -> Value {
        Value::Date((self.today)())
    }

    fn write_new(&self, rel: &str, text: &str) -> Result<(), GateError> {
        let path = resolve_inside(&self.root, rel).map_err(|e| GateError(e.message))?;
        if path.exists() {
            return Err(GateError(format!("{rel} exists")));
        }
        atomic_write(&path, text)?;
        Ok(())
    }

    fn rewrite(&self, rel: &str, edit: Edit) -> Result<(), GateError> {
        let path = resolve_inside(&self.root, rel).map_err(|e| GateError(e.message))?;
        let text = fs::read_to_string(&path)?;
        atomic_write(&path, &splice_front(&text, edit)?)?;
        Ok(())
    }

    fn record(
        &self,
        action: &str,
        who: &str,
        target: &str,
        checks: &[&str],
        decision: &Decision,
    ) -> Result<(), GateError> {
        let (verdict, reason, detail) = match decision {
            Decision::Accepted {
                path,
                level,
                conflicts,
            } => (
                "accepted",
                String::new(),
                json!({"path": path, "level": level.map(Level::as_str), "conflicts": conflicts}),
            ),
            Decision::Refused { reason, detail } => (
                "refused",
                reason.as_str().to_string(),
                json!({"detail": detail}),
            ),
        };
        audit::append(
            &self.root,
            json!({"date": (self.today)(), "action": action, "proposer": who, "target": target,
                   "checks": checks, "decision": verdict, "reason": reason, "detail": detail}),
        )?;
        Ok(())
    }

    fn decide(
        &self,
        action: &str,
        who: &Proposer,
        target: &str,
        checks: &[&str],
        outcome: Result<Decision, Refused>,
    ) -> Result<Decision, GateError> {
        let decision =
            outcome.unwrap_or_else(|(reason, detail)| Decision::Refused { reason, detail });
        self.record(action, &who.0, target, checks, &decision)?;
        Ok(decision)
    }

    // ---- Sources -------------------------------------------------------------------------------------------

    /// Store a Source. Sources are immutable: the same text under the same name is accepted unchanged, other text under
    /// a used name is refused.
    pub fn submit_source(&self, p: SourceProposal) -> Result<Decision, GateError> {
        let outcome = self.source_outcome(&p);
        self.decide(
            "source",
            &p.proposer,
            &p.title,
            &["shape", "metadata", "write"],
            outcome,
        )
    }

    fn source_outcome(&self, p: &SourceProposal) -> Result<Decision, Refused> {
        if !["document", "tool_run"].contains(&p.kind.as_str()) {
            return refuse(Refusal::Shape, "kind must be document or tool_run");
        }
        if p.title.trim().is_empty() || p.identifier.trim().is_empty() || p.text.trim().is_empty() {
            return refuse(
                Refusal::Shape,
                "a source needs a title, an identifier and text",
            );
        }
        if p.text.len() > self.settings.max_bytes {
            return refuse(Refusal::Shape, "the source text is longer than the limit");
        }
        if p.kind == "tool_run"
            && (p.command.as_deref().unwrap_or("").is_empty()
                || p.inputs_sha256.as_deref().unwrap_or("").is_empty())
        {
            return refuse(
                Refusal::Shape,
                "a tool_run source needs command and inputs_sha256",
            );
        }
        let check = match (&p.kind[..], &p.metadata) {
            ("document", MetadataCheck::Verified(registry)) => format!("verified:{registry}"),
            ("document", MetadataCheck::Mismatch(why)) => {
                return refuse(Refusal::Metadata, format!("metadata mismatch: {why}"));
            }
            ("document", MetadataCheck::Unresolved) => {
                return refuse(Refusal::Metadata, "the identifier does not resolve");
            }
            ("document", MetadataCheck::NotApplicable) => {
                return refuse(Refusal::Metadata, "a document needs a metadata check");
            }
            (_, _) => "tool-run".to_string(),
        };
        let body = canonical_body(&p.text);
        let title = safe_title(&p.title, "Source");
        let rel = format!("Sources/{title}.md");
        let existing = resolve_inside(&self.root, &rel).map_err(|e| (Refusal::Shape, e.message))?;
        if existing.exists() {
            let old = fs::read_to_string(&existing).map_err(|e| (Refusal::Shape, e.to_string()))?;
            return if parse_note(&old, &rel).body == body {
                Ok(Decision::Accepted {
                    path: rel,
                    level: None,
                    conflicts: vec![],
                })
            } else {
                refuse(
                    Refusal::Duplicate,
                    "a source is immutable: supersede it instead",
                )
            };
        }
        let mut props = vec![
            ("type".to_string(), Value::Str("source".into())),
            ("kind".to_string(), Value::Str(p.kind.clone())),
            ("identifier".to_string(), Value::Str(p.identifier.clone())),
            ("retrieved".to_string(), self.date()),
            ("status".to_string(), Value::Str("active".into())),
            (
                "sha256".to_string(),
                Value::Str(sha256_hex(body.as_bytes())),
            ),
            ("metadata_check".to_string(), Value::Str(check)),
            ("created".to_string(), self.date()),
        ];
        if let Some(command) = &p.command {
            props.push(("command".to_string(), Value::Str(command.clone())));
        }
        if let Some(hash) = &p.inputs_sha256 {
            props.push(("inputs_sha256".to_string(), Value::Str(hash.clone())));
        }
        if !p.cites.is_empty() {
            props.push((
                "cites".to_string(),
                Value::List(p.cites.iter().cloned().map(Value::Str).collect()),
            ));
        }
        if let Some(dataset) = &p.dataset {
            props.push(("dataset".to_string(), Value::Str(dataset.clone())));
        }
        if let Some(a) = &p.admission {
            let filled = |v: &str| !v.trim().is_empty();
            if p.kind != "document"
                || ![&a.class, &a.resolved_by, &a.resolution_sha256, &a.licence]
                    .iter()
                    .all(|v| filled(v))
                || a.venue.as_deref().is_some_and(|v| !filled(v))
                || a.retraction_check
                    .as_deref()
                    .is_some_and(|v| !v.contains(':'))
            {
                return refuse(
                    Refusal::Shape,
                    "an admission record belongs to a document and needs class, registry, response hash and licence",
                );
            }
            let mut add = |k: &str, v: &str| props.push((k.to_string(), Value::Str(v.to_string())));
            add("source_class", &a.class);
            add("resolved_by", &a.resolved_by);
            add("resolution_sha256", &a.resolution_sha256);
            add("licence", &a.licence);
            if let Some(v) = &a.venue {
                add("venue", v);
            }
            if let Some(v) = &a.retraction_check {
                add("retraction_check", v);
            }
        }
        let text = render_note(&props, &body).map_err(|e| (Refusal::Shape, e.message))?;
        self.write_new(&rel, &text)
            .map_err(|e| (Refusal::Shape, e.0))?;
        Ok(Decision::Accepted {
            path: rel,
            level: None,
            conflicts: vec![],
        })
    }

    // ---- Claims and Theories -----------------------------------------------------------------------------

    /// Check and store a Claim.
    pub fn submit_claim(&self, p: ClaimProposal) -> Result<Decision, GateError> {
        let index = self.index()?;
        let search = claim_search(&index);
        let outcome = self.claim_outcome(&index, &search, &p);
        self.decide_claim(&p, outcome)
    }

    /// Check and store many Claims, one after the other, exactly as [`Gate::submit_claim`] would one by one: each
    /// proposal sees the notes the earlier ones wrote (the duplicate check and the contradiction search included). The
    /// brain is read once and the notes written are added to that reading, so a large ingestion does not read the
    /// vault again for every proposal.
    pub fn submit_claims(&self, proposals: Vec<ClaimProposal>) -> Result<Vec<Decision>, GateError> {
        let mut index = self.index()?;
        let mut search = claim_search(&index);
        let mut out = Vec::with_capacity(proposals.len());
        for p in proposals {
            let outcome = self.claim_outcome(&index, &search, &p);
            let decision = self.decide_claim(&p, outcome)?;
            if let Decision::Accepted {
                path, conflicts, ..
            } = &decision
            {
                let note = self.read_note(path)?;
                search.add(path, &note);
                index.insert(note);
                for conflict in conflicts {
                    let note = self.read_note(conflict)?;
                    // the sides stored earlier carry the new conflict now: read them again
                    let sides = list_of(&note.props, "sides");
                    index.insert(note);
                    for side in sides {
                        if let Some(rel) = index.find(&link_name(&side)).map(|n| n.path.clone()) {
                            let fresh = self.read_note(&rel)?;
                            index.insert(fresh);
                        }
                    }
                }
            }
            out.push(decision);
        }
        Ok(out)
    }

    fn read_note(&self, rel: &str) -> Result<Note, GateError> {
        let path = resolve_inside(&self.root, rel).map_err(|e| GateError(e.message))?;
        Ok(parse_note(&fs::read_to_string(path)?, rel))
    }

    fn decide_claim(
        &self,
        p: &ClaimProposal,
        outcome: Result<Decision, Refused>,
    ) -> Result<Decision, GateError> {
        let target: String = p.statement.chars().take(60).collect();
        self.decide(
            "claim",
            &p.proposer,
            &target,
            &[
                "shape",
                "span",
                "metadata",
                "support",
                "evidence",
                "solver",
                "contradiction",
                "write",
            ],
            outcome,
        )
    }

    /// The checks of steps 1 to 4 shared by Claims and Theories: the Source note and the span in it.
    fn locate_quote<'a>(
        &self,
        index: &'a VaultIndex,
        source: &Option<String>,
        statement: &str,
        quote: &str,
        holder: Option<&str>,
    ) -> Result<(&'a Note, usize, usize, Facts), Refused> {
        if statement.trim().is_empty() || quote.trim().is_empty() {
            return refuse(Refusal::Shape, "a statement and its quote are required");
        }
        if statement.len() > self.settings.max_bytes || quote.len() > self.settings.max_bytes {
            return refuse(
                Refusal::Shape,
                "the statement or quote is longer than the limit",
            );
        }
        let Some(name) = source.as_deref().filter(|s| !s.trim().is_empty()) else {
            return refuse(
                Refusal::ModelOnly,
                "a statement without a Source is model-only text",
            );
        };
        let Some(note) = index.find(&link_name(name)) else {
            return refuse(Refusal::UnknownSource, format!("no note named {name}"));
        };
        if kind_of(note) != "source" {
            return refuse(
                Refusal::UnknownSource,
                format!("{name} is a {}, not a source", kind_of(note)),
            );
        }
        if prop_text(note, "status") != "active" {
            return refuse(
                Refusal::SourceNotActive,
                format!("{name} is {}", prop_text(note, "status")),
            );
        }
        let Some((start, end)) = text::locate(&note.body, quote) else {
            return refuse(Refusal::Span, "the quote is not in the source");
        };
        if prop_text(note, "kind") == "document"
            && !prop_text(note, "metadata_check").starts_with("verified")
        {
            return refuse(Refusal::Metadata, "the source's metadata was not verified");
        }
        let words = text::facts(&note.body[start..end]);
        let said = match holder {
            Some(h) => text::attributed_facts(statement, h),
            None => text::facts(statement),
        };
        if let Some(why) = text::unsupported(&said, &words, self.settings.min_support) {
            return refuse(Refusal::Unsupported, why);
        }
        Ok((note, start, end, words))
    }

    fn claim_outcome(
        &self,
        index: &VaultIndex,
        search: &NoteSearch,
        p: &ClaimProposal,
    ) -> Result<Decision, Refused> {
        if p.requested == Level::Candidate {
            return refuse(Refusal::Level, "a candidate never enters the main brain");
        }
        let (source, start, end, _) =
            self.locate_quote(index, &p.source, &p.statement, &p.quote, None)?;
        let facts = text::facts(&p.statement);
        let mut level = Level::Sourced;
        let mut extra: Vec<(String, Value)> = Vec::new();
        for evidence in &p.evidence {
            let found = self.check_evidence(index, &facts, source, evidence)?;
            level = level.max(evidence.level());
            extra.extend(found);
        }
        if p.requested > level {
            return refuse(
                Refusal::Level,
                format!(
                    "{} was asked for but the evidence holds {}",
                    p.requested.as_str(),
                    level.as_str()
                ),
            );
        }
        let solver = match p.solver.as_deref().filter(|s| !s.trim().is_empty()) {
            None => None,
            Some(name) => {
                let Some(run) = index.find(&link_name(name)) else {
                    return refuse(Refusal::Evidence, format!("no note named {name}"));
                };
                if kind_of(run) != "source"
                    || prop_text(run, "kind") != "tool_run"
                    || prop_text(run, "status") != "active"
                {
                    return refuse(
                        Refusal::Evidence,
                        format!("the solver link {name} is not an active tool_run source"),
                    );
                }
                Some(run.title.clone())
            }
        };
        let span = &source.body[start..end];
        let hash = sha256_hex(span.as_bytes());
        let name = format!(
            "{} {}",
            safe_title(&p.statement.chars().take(60).collect::<String>(), "Claim"),
            &sha256_hex(format!("{}\0{start}\0{end}\0{}", source.path, p.statement).as_bytes())
                [..8]
        );
        let rel = format!("Claims/{name}.md");
        if index.notes.contains_key(&rel) {
            return refuse(
                Refusal::Duplicate,
                "this claim is stored already; raise it through evidence",
            );
        }
        let conflicts = self.contradictions(index, search, &p.statement, &facts, &rel);
        let mut props = vec![
            ("type".to_string(), Value::Str("claim".into())),
            ("level".to_string(), Value::Str(level.as_str().into())),
            ("source_ref".to_string(), link(&source.title)),
            ("span_start".to_string(), Value::Int(start as i64)),
            ("span_end".to_string(), Value::Int(end as i64)),
            ("span_sha256".to_string(), Value::Str(hash)),
            ("proposed_by".to_string(), Value::Str(p.proposer.0.clone())),
            ("created".to_string(), self.date()),
        ];
        for (k, v) in extra {
            merge_prop(&mut props, &k, v);
        }
        if let Some(run) = &solver {
            props.push(("solver_ref".to_string(), link(run)));
        }
        let conflict_name = (!conflicts.is_empty()).then(|| conflict_title(&name, &conflicts));
        if let Some(c) = &conflict_name {
            set(&mut props, "conflict_refs", Value::List(vec![link(c)]));
        }
        let text =
            render_note(&props, p.statement.trim()).map_err(|e| (Refusal::Shape, e.message))?;
        self.write_new(&rel, &text)
            .map_err(|e| (Refusal::Shape, e.0))?;
        let mut written = Vec::new();
        if let Some(c) = &conflict_name {
            let sides: Vec<String> = std::iter::once(name.clone())
                .chain(conflicts.iter().map(|path| title_of(path)))
                .collect();
            match self.write_conflict(c, &sides, "new claim contradicts stored notes") {
                Ok(path) => written.push(path),
                Err(e) => {
                    let _ = fs::remove_file(self.root.join(&rel));
                    return refuse(
                        Refusal::Shape,
                        format!("could not write the conflict: {}", e.0),
                    );
                }
            }
            // the stored notes know of the conflict too
            for path in &conflicts {
                let _ = self.rewrite(path, &mut |props| {
                    let mut refs = list_of(props, "conflict_refs");
                    let l = format!("[[{c}]]");
                    if !refs.contains(&l) {
                        refs.push(l);
                    }
                    set_list(props, "conflict_refs", refs);
                });
            }
        }
        Ok(Decision::Accepted {
            path: rel,
            level: Some(level),
            conflicts: written,
        })
    }

    /// Store a Theory: an attributed position.
    pub fn submit_theory(&self, p: TheoryProposal) -> Result<Decision, GateError> {
        let index = self.index()?;
        let target: String = p.statement.chars().take(60).collect();
        let outcome = self.theory_outcome(&index, &p);
        self.decide(
            "theory",
            &p.proposer,
            &target,
            &[
                "shape",
                "span",
                "metadata",
                "support",
                "contradiction",
                "write",
            ],
            outcome,
        )
    }

    fn theory_outcome(&self, index: &VaultIndex, p: &TheoryProposal) -> Result<Decision, Refused> {
        if p.attributed_to.trim().is_empty() {
            return refuse(Refusal::Shape, "a theory names who holds it");
        }
        let (source, start, end, _) = self.locate_quote(
            index,
            &p.source,
            &p.statement,
            &p.quote,
            Some(&p.attributed_to),
        )?;
        let hash = sha256_hex(&source.body.as_bytes()[start..end]);
        let name = format!(
            "{} {}",
            safe_title(&p.statement.chars().take(60).collect::<String>(), "Theory"),
            &sha256_hex(format!("{}\0{start}\0{end}\0{}", source.path, p.statement).as_bytes())
                [..8]
        );
        let rel = format!("Theories/{name}.md");
        if index.notes.contains_key(&rel) {
            return refuse(Refusal::Duplicate, "this theory is stored already");
        }
        let facts = text::facts(&p.statement);
        let search = claim_search(index);
        let conflicts = self.contradictions(index, &search, &p.statement, &facts, &rel);
        let mut props = vec![
            ("type".to_string(), Value::Str("theory".into())),
            (
                "attributed_to".to_string(),
                Value::Str(p.attributed_to.clone()),
            ),
            ("source_ref".to_string(), link(&source.title)),
            ("span_start".to_string(), Value::Int(start as i64)),
            ("span_end".to_string(), Value::Int(end as i64)),
            ("span_sha256".to_string(), Value::Str(hash)),
            ("proposed_by".to_string(), Value::Str(p.proposer.0.clone())),
            ("created".to_string(), self.date()),
        ];
        let conflict_name = (!conflicts.is_empty()).then(|| conflict_title(&name, &conflicts));
        if let Some(c) = &conflict_name {
            set(&mut props, "conflict_refs", Value::List(vec![link(c)]));
        }
        let text =
            render_note(&props, p.statement.trim()).map_err(|e| (Refusal::Shape, e.message))?;
        self.write_new(&rel, &text)
            .map_err(|e| (Refusal::Shape, e.0))?;
        let mut written = Vec::new();
        if let Some(c) = &conflict_name {
            let sides: Vec<String> = std::iter::once(name.clone())
                .chain(conflicts.iter().map(|path| title_of(path)))
                .collect();
            match self.write_conflict(c, &sides, "new theory contradicts stored notes") {
                Ok(path) => written.push(path),
                Err(e) => {
                    let _ = fs::remove_file(self.root.join(&rel));
                    return refuse(
                        Refusal::Shape,
                        format!("could not write the conflict: {}", e.0),
                    );
                }
            }
            for path in &conflicts {
                let _ = self.rewrite(path, &mut |props| {
                    let mut refs = list_of(props, "conflict_refs");
                    let l = format!("[[{c}]]");
                    if !refs.contains(&l) {
                        refs.push(l);
                    }
                    set_list(props, "conflict_refs", refs);
                });
            }
        }
        Ok(Decision::Accepted {
            path: rel,
            level: None,
            conflicts: written,
        })
    }

    fn write_conflict(&self, name: &str, sides: &[String], why: &str) -> Result<String, GateError> {
        let rel = format!("Conflicts/{name}.md");
        let props = vec![
            ("type".to_string(), Value::Str("conflict".into())),
            ("status".to_string(), Value::Str("open".into())),
            (
                "sides".to_string(),
                Value::List(sides.iter().map(|s| link(s)).collect()),
            ),
            ("created".to_string(), self.date()),
        ];
        let body = format!("Both sides are kept; neither is settled. {why}.");
        let text = render_note(&props, &body).map_err(|e| GateError(e.message))?;
        self.write_new(&rel, &text)?;
        Ok(rel)
    }

    /// Stored Claims and Theories on the same subject that the statement contradicts (paths, sorted).
    fn contradictions(
        &self,
        index: &VaultIndex,
        search: &NoteSearch,
        statement: &str,
        facts: &Facts,
        own: &str,
    ) -> Vec<String> {
        let mut found: BTreeSet<String> = BTreeSet::new();
        for hit in search.search(statement, self.settings.search_depth) {
            if hit.path == own {
                continue;
            }
            if let Some(note) = index.notes.get(&hit.path)
                && text::contradicts(
                    facts,
                    &text::facts(&note.body),
                    self.settings.subject_overlap,
                )
            {
                found.insert(hit.path);
            }
        }
        found.into_iter().collect()
    }

    // ---- Evidence ---------------------------------------------------------------------------------------------

    /// Check one piece of evidence for a statement whose own Source is `own`. Returns the properties it adds.
    fn check_evidence(
        &self,
        index: &VaultIndex,
        statement: &Facts,
        own: &Note,
        evidence: &Evidence,
    ) -> Result<Vec<(String, Value)>, Refused> {
        match evidence {
            Evidence::Corroborated { with, independence } => {
                if independence.trim().is_empty() {
                    return refuse(
                        Refusal::Evidence,
                        "corroboration states why the sources are independent",
                    );
                }
                let Some(other) = index
                    .find(&link_name(with))
                    .filter(|n| kind_of(n) == "claim")
                else {
                    return refuse(Refusal::Evidence, format!("{with} is not a stored claim"));
                };
                let other_source = index.find(&link_name(&prop_text(other, "source_ref")));
                let Some(other_source) =
                    other_source.filter(|s| prop_text(s, "status") == "active")
                else {
                    return refuse(Refusal::Evidence, "the other claim has no active source");
                };
                if other_source.path == own.path
                    || prop_text(other_source, "identifier") == prop_text(own, "identifier")
                {
                    return refuse(Refusal::Evidence, "the two claims rest on the same source");
                }
                if !text::equivalent(
                    statement,
                    &text::facts(&other.body),
                    self.settings.min_equivalence,
                ) {
                    return refuse(
                        Refusal::Evidence,
                        "the two statements are not equivalent by the rule check",
                    );
                }
                Ok(vec![
                    (
                        "corroborated_by".to_string(),
                        Value::List(vec![link(&other.title)]),
                    ),
                    ("independence".to_string(), Value::Str(independence.clone())),
                ])
            }
            Evidence::ToolRun { source } => {
                let Some(run) = index.find(&link_name(source)) else {
                    return refuse(Refusal::Evidence, format!("no note named {source}"));
                };
                if kind_of(run) != "source"
                    || prop_text(run, "kind") != "tool_run"
                    || prop_text(run, "status") != "active"
                {
                    return refuse(
                        Refusal::Evidence,
                        format!("{source} is not an active tool_run source"),
                    );
                }
                if let Some(why) = text::unsupported(
                    statement,
                    &text::facts(&run.body),
                    self.settings.min_support,
                ) {
                    return refuse(
                        Refusal::Evidence,
                        format!("the tool output does not support the statement: {why}"),
                    );
                }
                Ok(vec![("tool_run_ref".to_string(), link(&run.title))])
            }
            Evidence::Reviewed { reviewer, on } => {
                if reviewer.trim().is_empty() || on.trim().is_empty() {
                    return refuse(
                        Refusal::Evidence,
                        "a review names the reviewer and the date",
                    );
                }
                Ok(vec![
                    ("reviewer".to_string(), Value::Str(reviewer.clone())),
                    ("reviewed_on".to_string(), Value::Date(on.clone())),
                ])
            }
        }
    }

    /// Raise a stored Claim on new evidence. A Claim only goes up here; it comes down by consolidation.
    pub fn promote(
        &self,
        claim: &str,
        evidence: Evidence,
        who: Proposer,
    ) -> Result<Decision, GateError> {
        let index = self.index()?;
        let outcome = self.promote_outcome(&index, claim, &evidence);
        self.decide("promote", &who, claim, &["evidence", "write"], outcome)
    }

    fn promote_outcome(
        &self,
        index: &VaultIndex,
        claim: &str,
        evidence: &Evidence,
    ) -> Result<Decision, Refused> {
        let Some(note) = index
            .find(&link_name(claim))
            .filter(|n| kind_of(n) == "claim")
        else {
            return refuse(Refusal::Shape, format!("{claim} is not a stored claim"));
        };
        let Some(source) = index.find(&link_name(&prop_text(note, "source_ref"))) else {
            return refuse(Refusal::UnknownSource, "the claim's source is missing");
        };
        let found = self.check_evidence(index, &text::facts(&note.body), source, evidence)?;
        let current = Level::parse(&prop_text(note, "level")).unwrap_or(Level::Sourced);
        let level = current.max(evidence.level());
        let path = note.path.clone();
        self.rewrite(&path, &mut |props| {
            set(props, "level", Value::Str(level.as_str().into()));
            for (k, v) in &found {
                merge_prop(props, k, v.clone());
            }
        })
        .map_err(|e| (Refusal::Shape, e.0))?;
        // corroboration is mutual: the other claim learns of it as well
        if let Evidence::Corroborated { with, independence } = evidence
            && let Some(other) = index.find(&link_name(with))
        {
            let back = link(&note.title);
            let other_level = Level::parse(&prop_text(other, "level"))
                .unwrap_or(Level::Sourced)
                .max(Level::Corroborated);
            let _ = self.rewrite(&other.path.clone(), &mut |props| {
                set(props, "level", Value::Str(other_level.as_str().into()));
                merge_prop(props, "corroborated_by", Value::List(vec![back.clone()]));
                set(props, "independence", Value::Str(independence.clone()));
            });
        }
        Ok(Decision::Accepted {
            path,
            level: Some(level),
            conflicts: vec![],
        })
    }

    // ---- Retraction, replacement and consolidation -------------------------------------------------------

    /// Mark a Source retracted and consolidate: dependants are downgraded or leave the brain.
    pub fn retract_source(
        &self,
        title: &str,
        reason: &str,
        who: Proposer,
    ) -> Result<ConsolidationReport, GateError> {
        let index = self.index()?;
        let note = index
            .find(&link_name(title))
            .filter(|n| kind_of(n) == "source")
            .ok_or_else(|| GateError(format!("{title} is not a stored source")))?;
        let path = note.path.clone();
        let date = (self.today)();
        let why = reason.to_string();
        self.rewrite(&path, &mut |props| {
            set(props, "status", Value::Str("retracted".into()));
            set(props, "retracted_reason", Value::Str(why.clone()));
            set(props, "retracted_on", Value::Date(date.clone()));
        })?;
        audit::append(
            &self.root,
            json!({"date": (self.today)(), "action": "retract", "proposer": who.0, "target": path, "checks": [],
                   "decision": "accepted", "reason": "", "detail": {"reason": reason}}),
        )?;
        self.consolidate()
    }

    /// Replace a Source: store `new`, mark `old` superseded, point the Claims whose quote is still in the new text at it
    /// and retire the others, then consolidate.
    pub fn supersede_source(
        &self,
        old: &str,
        new: SourceProposal,
    ) -> Result<(Decision, ConsolidationReport), GateError> {
        let decision = self.submit_source(new.clone())?;
        let Decision::Accepted { path: new_path, .. } = &decision else {
            return Ok((decision, ConsolidationReport::default()));
        };
        let index = self.index()?;
        let old_note = index
            .find(&link_name(old))
            .filter(|n| kind_of(n) == "source")
            .ok_or_else(|| GateError(format!("{old} is not a stored source")))?;
        let new_note = index
            .notes
            .get(new_path)
            .ok_or_else(|| GateError("the new source is not in the vault".into()))?;
        if new_note.path == old_note.path {
            return Err(GateError("a source cannot replace itself".into()));
        }
        let mut report = ConsolidationReport::default();
        let new_title = new_note.title.clone();
        for note in index.notes.values() {
            if !matches!(kind_of(note).as_str(), "claim" | "theory")
                || index
                    .find(&link_name(&prop_text(note, "source_ref")))
                    .map(|s| s.path.clone())
                    != Some(old_note.path.clone())
            {
                continue;
            }
            let start = note
                .prop("span_start")
                .map_or(0, |v| v.py_str().parse::<usize>().unwrap_or(0));
            let end = note
                .prop("span_end")
                .map_or(0, |v| v.py_str().parse::<usize>().unwrap_or(0));
            let quote = old_note.body.get(start..end).unwrap_or("");
            match text::locate(&new_note.body, quote) {
                Some((s, e)) => {
                    let hash = sha256_hex(&new_note.body.as_bytes()[s..e]);
                    self.rewrite(&note.path, &mut |props| {
                        set(props, "source_ref", link(&new_title));
                        set(props, "span_start", Value::Int(s as i64));
                        set(props, "span_end", Value::Int(e as i64));
                        set(props, "span_sha256", Value::Str(hash.clone()));
                    })?;
                    report.repointed.push(note.path.clone());
                }
                None => {
                    self.retire(
                        &note.path,
                        "the replacing source no longer holds the quote",
                        &mut report,
                    )?;
                }
            }
        }
        let new_link = format!("[[{new_title}]]");
        self.rewrite(&old_note.path, &mut |props| {
            set(props, "status", Value::Str("superseded".into()));
            set(props, "superseded_by", Value::Str(new_link.clone()));
        })?;
        audit::append(
            &self.root,
            json!({"date": (self.today)(), "action": "supersede", "proposer": new.proposer.0, "target": old_note.path,
                   "checks": [], "decision": "accepted", "reason": "", "detail": {"by": new_path}}),
        )?;
        let rest = self.consolidate()?;
        report.retired.extend(rest.retired);
        report.downgraded.extend(rest.downgraded);
        report.pruned.extend(rest.pruned);
        Ok((decision, report))
    }

    fn retire(
        &self,
        path: &str,
        reason: &str,
        report: &mut ConsolidationReport,
    ) -> Result<(), GateError> {
        let from = resolve_inside(&self.root, path).map_err(|e| GateError(e.message))?;
        let mut to = self.root.join(RETIRED).join(path);
        let mut n = 1;
        while to.exists() {
            to = self.root.join(RETIRED).join(format!("{path}.{n}"));
            n += 1;
        }
        if let Some(dir) = to.parent() {
            fs::create_dir_all(dir)?;
        }
        let text = fs::read_to_string(&from)?;
        fs::rename(&from, &to)?;
        audit::append(
            &self.root,
            json!({"date": (self.today)(), "action": "retire", "proposer": "gate", "target": path, "checks": [],
                   "decision": "accepted", "reason": reason, "detail": {"sha256": sha256_hex(text.as_bytes())}}),
        )?;
        report.retired.push((path.to_string(), reason.to_string()));
        Ok(())
    }

    /// Bring the brain back to what its Sources support (ADR-024 section 4). Deterministic and idempotent: a second run
    /// finds nothing to do.
    ///
    /// * a Claim or Theory whose Source is retracted or missing leaves the brain (it falls to `candidate`);
    /// * a Claim whose corroborating Claims are gone falls to `sourced`; one whose tool run is gone falls to the level
    ///   its remaining evidence holds; a `reviewed` Claim stays reviewed;
    /// * dead links are removed; a Conflict with fewer than two sides leaves the brain; an Open question that lost its
    ///   answer opens again.
    pub fn consolidate(&self) -> Result<ConsolidationReport, GateError> {
        let mut report = ConsolidationReport::default();
        loop {
            let index = self.index()?;
            let before = report.retired.len();
            // 1. notes without an active Source leave
            let mut gone: Vec<(String, String)> = Vec::new();
            for note in index.notes.values() {
                match kind_of(note).as_str() {
                    "claim" | "theory" => {
                        let source = index.find(&link_name(&prop_text(note, "source_ref")));
                        match source {
                            None => gone.push((note.path.clone(), "its source is missing".into())),
                            Some(s) if prop_text(s, "status") == "retracted" => {
                                gone.push((
                                    note.path.clone(),
                                    format!("its source {} is retracted", s.title),
                                ));
                            }
                            _ => {}
                        }
                    }
                    "conflict" => {
                        let sides: BTreeSet<String> = note
                            .prop_list("sides")
                            .iter()
                            .filter_map(|v| index.find(&link_name(v)))
                            .filter(|n| matches!(kind_of(n).as_str(), "claim" | "theory"))
                            .filter(|n| !gone_contains(&gone, &n.path))
                            .map(|n| n.path.clone())
                            .collect();
                        if sides.len() < 2 {
                            gone.push((note.path.clone(), "fewer than two sides remain".into()));
                        }
                    }
                    _ => {}
                }
            }
            // a Conflict loses a side only after the pass that retires the side, so retire in rounds
            for (path, reason) in &gone {
                self.retire(path, reason, &mut report)?;
            }
            if report.retired.len() > before {
                continue;
            }
            // 2. levels and dead links
            let mut changed = false;
            for note in index.notes.values() {
                let kind = kind_of(note);
                if !matches!(
                    kind.as_str(),
                    "claim" | "theory" | "conflict" | "open-question"
                ) {
                    continue;
                }
                if let Some(change) = self.repair(&index, note)? {
                    changed = true;
                    if let Some(down) = change.downgrade {
                        report.downgraded.push((note.path.clone(), down.0, down.1));
                    }
                    report.pruned.push(note.path.clone());
                }
            }
            if !changed {
                break;
            }
        }
        report.pruned.sort();
        report.pruned.dedup();
        Ok(report)
    }

    fn repair(&self, index: &VaultIndex, note: &Note) -> Result<Option<Repair>, GateError> {
        let alive = |value: &str| index.find(&link_name(value)).is_some();
        let kind = kind_of(note);
        let mut props = note.props.clone();
        let mut downgrade = None;
        match kind.as_str() {
            "claim" => {
                let own_source = index
                    .find(&link_name(&prop_text(note, "source_ref")))
                    .map(|s| s.path.clone());
                let valid_corroborators: Vec<String> = note
                    .prop_list("corroborated_by")
                    .into_iter()
                    .filter(|v| {
                        index.find(&link_name(v)).is_some_and(|c| {
                            kind_of(c) == "claim"
                                && index
                                    .find(&link_name(&prop_text(c, "source_ref")))
                                    .map(|s| s.path.clone())
                                    != own_source
                        })
                    })
                    .collect();
                let run_ok = index
                    .find(&link_name(&prop_text(note, "tool_run_ref")))
                    .is_some_and(|r| prop_text(r, "status") != "retracted");
                let level = Level::parse(&prop_text(note, "level")).unwrap_or(Level::Sourced);
                let held = if level == Level::Reviewed {
                    Level::Reviewed
                } else if run_ok && level >= Level::Verified {
                    Level::Verified
                } else if !valid_corroborators.is_empty() && level >= Level::Corroborated {
                    Level::Corroborated
                } else {
                    Level::Sourced
                };
                set_list(&mut props, "corroborated_by", valid_corroborators.clone());
                if valid_corroborators.is_empty() {
                    unset(&mut props, "independence");
                }
                if !run_ok {
                    unset(&mut props, "tool_run_ref");
                }
                if held < level {
                    set(&mut props, "level", Value::Str(held.as_str().into()));
                    downgrade = Some((level, held));
                }
                let refs: Vec<String> = list_of(&props, "conflict_refs")
                    .into_iter()
                    .filter(|v| alive(v))
                    .collect();
                set_list(&mut props, "conflict_refs", refs);
            }
            "theory" => {
                let refs: Vec<String> = list_of(&props, "conflict_refs")
                    .into_iter()
                    .filter(|v| alive(v))
                    .collect();
                set_list(&mut props, "conflict_refs", refs);
            }
            "conflict" => {
                let sides: Vec<String> = list_of(&props, "sides")
                    .into_iter()
                    .filter(|v| alive(v))
                    .collect();
                set_list(&mut props, "sides", sides);
            }
            _ => {
                let bears: Vec<String> = list_of(&props, "bears_on")
                    .into_iter()
                    .filter(|v| alive(v))
                    .collect();
                set_list(&mut props, "bears_on", bears);
                let answers: Vec<String> = list_of(&props, "answered_by")
                    .into_iter()
                    .filter(|v| alive(v))
                    .collect();
                if answers.is_empty() && prop_text(note, "status") == "answered" {
                    set(&mut props, "status", Value::Str("open".into()));
                }
                set_list(&mut props, "answered_by", answers);
            }
        }
        if props == note.props {
            return Ok(None);
        }
        let path = resolve_inside(&self.root, &note.path).map_err(|e| GateError(e.message))?;
        let text = fs::read_to_string(&path)?;
        let new = props;
        atomic_write(&path, &splice_front(&text, &mut |p| *p = new.clone())?)?;
        Ok(Some(Repair { downgrade }))
    }

    /// The problems lint finds in the brain after the gate's work (the gate's own check on itself).
    pub fn lint(&self) -> Result<Vec<(String, String)>, GateError> {
        Ok(lint_brain(&self.index()?)
            .into_iter()
            .map(|p| (p.path, p.code))
            .collect())
    }

    /// Spans of all stored Claims resolve (a quick self-check used by tests and the owner).
    pub fn spans_resolve(&self) -> Result<bool, GateError> {
        let index = self.index()?;
        let mut ok = true;
        let by_title: BTreeMap<&str, &Note> = index
            .notes
            .values()
            .map(|n| (n.title.as_str(), n))
            .collect();
        for note in index.notes.values().filter(|n| kind_of(n) == "claim") {
            let Some(source) = by_title.get(link_name(&prop_text(note, "source_ref")).as_str())
            else {
                ok = false;
                continue;
            };
            let int = |n: &str| {
                note.prop(n)
                    .map_or(-1, |v| v.py_str().parse::<i64>().unwrap_or(-1))
            };
            ok &= resolve_span(
                &source.body,
                int("span_start"),
                int("span_end"),
                &prop_text(note, "span_sha256"),
            )
            .is_ok();
        }
        Ok(ok)
    }
}

struct Repair {
    downgrade: Option<(Level, Level)>,
}

fn gone_contains(gone: &[(String, String)], path: &str) -> bool {
    gone.iter().any(|(p, _)| p == path)
}

fn merge_prop(props: &mut Vec<(String, Value)>, name: &str, value: Value) {
    match (get(props, name).cloned(), value) {
        (Some(Value::List(mut old)), Value::List(new)) => {
            for item in new {
                if !old.contains(&item) {
                    old.push(item);
                }
            }
            set(props, name, Value::List(old));
        }
        (_, value) => set(props, name, value),
    }
}

fn conflict_title(own: &str, others: &[String]) -> String {
    let mut all: Vec<String> = others.to_vec();
    all.push(own.to_string());
    all.sort();
    format!("Conflict {}", &sha256_hex(all.join("\0").as_bytes())[..8])
}
