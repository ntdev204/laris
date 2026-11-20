//! The main-brain profile: note types, certainty ladder and lint (SR-K2, ADR-024 section 3).
//!
//! The main brain is a vault in which knowledge is stored only with provenance. This module defines what the five
//! types (Source, Claim, Theory, Conflict, Open question) must carry and checks it; it never writes. The single
//! writer is the write gate (T164), which uses [`Level`] and the same rules.
//!
//! Spans are **byte offsets** into the text of a Source, which is the body of the Source note exactly as the parser
//! reads it ([`Note::body`]). A span hash is the SHA-256 of those bytes. Whether the quote *means* what a Claim says
//! is the gate's work; lint only proves the span exists and reproduces byte-for-byte.

use std::collections::BTreeSet;

use sha2::{Digest, Sha256};

use crate::index::VaultIndex;
use crate::lint::Problem;
use crate::note::{Note, link_name};
use crate::schema::{Schema, validate_note};
use crate::yaml::Value;

/// The registry of the main-brain profile. Types outside it are reported by lint (`schema-type`).
pub const BRAIN_YAML: &str = r#"
version: 1
types:
  source:
    required: [type, kind, identifier, retrieved, status, sha256, created]
    links: [superseded_by]
    folder: Sources
  claim:
    required: [type, level, source_ref, span_start, span_end, span_sha256, created]
    links: [source_ref, corroborated_by, tool_run_ref]
    folder: Claims
  theory:
    required: [type, attributed_to, source_ref, span_start, span_end, span_sha256, created]
    links: [source_ref]
    folder: Theories
  conflict:
    required: [type, status, sides, created]
    links: [sides, closed_by]
    folder: Conflicts
  open-question:
    required: [type, status, created]
    links: [bears_on, answered_by]
    folder: Questions
"#;

/// The registry of the main-brain profile.
pub fn brain_schema() -> Schema {
    Schema::from_text(BRAIN_YAML).expect("built-in brain schema is valid")
}

/// What an answer may do with a Claim, ordered from weakest to strongest in what has been checked (ADR-024 3.2).
///
/// `Candidate` is a level for proposals in a session; a note at that level is never in the vault, so lint refuses it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Level {
    /// Proposed; no verified span yet. Session only.
    Candidate,
    /// The exact quote is found in the Source and the metadata matches.
    Sourced,
    /// At least two independent Sources state the same atomic claim.
    Corroborated,
    /// A tool or computation reproduces or checks the claim.
    Verified,
    /// A human accepted it.
    Reviewed,
}

impl Level {
    /// Every level, weakest first.
    pub const ALL: [Level; 5] = [
        Level::Candidate,
        Level::Sourced,
        Level::Corroborated,
        Level::Verified,
        Level::Reviewed,
    ];

    /// The name written in the `level` property.
    pub fn as_str(self) -> &'static str {
        match self {
            Level::Candidate => "candidate",
            Level::Sourced => "sourced",
            Level::Corroborated => "corroborated",
            Level::Verified => "verified",
            Level::Reviewed => "reviewed",
        }
    }

    /// The level named `name`, if any.
    pub fn parse(name: &str) -> Option<Level> {
        Level::ALL.into_iter().find(|l| l.as_str() == name)
    }
}

/// The status values of a Source.
pub const SOURCE_STATUSES: [&str; 3] = ["active", "superseded", "retracted"];
/// The kinds of a Source.
pub const SOURCE_KINDS: [&str; 2] = ["document", "tool_run"];
/// The status values of a Conflict.
pub const CONFLICT_STATUSES: [&str; 2] = ["open", "closed"];
/// The status values of an Open question.
pub const QUESTION_STATUSES: [&str; 2] = ["open", "answered"];

/// SHA-256 of `bytes` as lowercase hex.
pub fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// Why a span does not resolve in a Source text.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SpanError {
    /// `start >= end`.
    Empty,
    /// The span ends after the text.
    OutOfRange,
    /// An offset falls inside a UTF-8 character.
    NotOnBoundary,
    /// The bytes at the span hash to something else.
    HashMismatch,
}

impl SpanError {
    fn message(&self) -> &'static str {
        match self {
            SpanError::Empty => "span is empty",
            SpanError::OutOfRange => "span lies outside the source text",
            SpanError::NotOnBoundary => "span does not start and end on character boundaries",
            SpanError::HashMismatch => "span text does not match span_sha256",
        }
    }
}

/// The quote at `start..end` of `text` when it resolves and its hash is `sha256`.
pub fn resolve_span<'a>(
    text: &'a str,
    start: i64,
    end: i64,
    sha256: &str,
) -> Result<&'a str, SpanError> {
    if start < 0 || end <= start {
        return Err(SpanError::Empty);
    }
    let (start, end) = (start as usize, end as usize);
    if end > text.len() {
        return Err(SpanError::OutOfRange);
    }
    if !text.is_char_boundary(start) || !text.is_char_boundary(end) {
        return Err(SpanError::NotOnBoundary);
    }
    let quote = &text[start..end];
    if !sha256_hex(quote.as_bytes()).eq_ignore_ascii_case(sha256) {
        return Err(SpanError::HashMismatch);
    }
    Ok(quote)
}

fn text(note: &Note, name: &str) -> String {
    note.prop(name).map_or(String::new(), |v| v.py_str())
}

fn int(note: &Note, name: &str) -> Option<i64> {
    match note.prop(name) {
        Some(Value::Int(n)) => Some(*n),
        _ => None,
    }
}

fn present(note: &Note, name: &str) -> bool {
    match note.prop(name) {
        None | Some(Value::Null) => false,
        Some(Value::Str(s)) => !s.trim().is_empty(),
        Some(Value::List(items)) => !items.is_empty(),
        Some(_) => true,
    }
}

/// The notes a link property points at, as `(written text, note if it resolves)`.
fn targets<'a>(index: &'a VaultIndex, note: &Note, prop: &str) -> Vec<(String, Option<&'a Note>)> {
    note.prop_list(prop)
        .into_iter()
        .map(|value| {
            let found = index.find(&link_name(&value));
            (value, found)
        })
        .collect()
}

fn kind_of(note: &Note) -> String {
    text(note, "type")
}

/// The Source a span property set points at, with the span checked. Pushes problems and returns the Source when it
/// exists, whatever the span result, so the caller can look at its status.
fn check_span<'a>(
    index: &'a VaultIndex,
    note: &Note,
    problems: &mut Vec<Problem>,
) -> Option<&'a Note> {
    let (_, source) = targets(index, note, "source_ref").into_iter().next()?;
    let Some(source) = source else {
        return None; // the schema reports the unresolved link
    };
    if kind_of(source) != "source" {
        problems.push(Problem::new(
            &note.path,
            "brain-source-ref",
            format!(
                "source_ref points at a {} note, not a source",
                kind_of(source)
            ),
        ));
        return None;
    }
    let (Some(start), Some(end)) = (int(note, "span_start"), int(note, "span_end")) else {
        problems.push(Problem::new(
            &note.path,
            "brain-span",
            "span_start and span_end must be integers",
        ));
        return Some(source);
    };
    if let Err(error) = resolve_span(&source.body, start, end, &text(note, "span_sha256")) {
        problems.push(Problem::new(&note.path, "brain-span", error.message()));
    }
    Some(source)
}

fn check_choice(note: &Note, prop: &str, allowed: &[&str], problems: &mut Vec<Problem>) {
    if present(note, prop) && !allowed.contains(&text(note, prop).as_str()) {
        problems.push(Problem::new(
            &note.path,
            "brain-value",
            format!("{prop} must be one of {}", allowed.join(", ")),
        ));
    }
}

fn lint_source(note: &Note, problems: &mut Vec<Problem>) {
    check_choice(note, "kind", &SOURCE_KINDS, problems);
    check_choice(note, "status", &SOURCE_STATUSES, problems);
    if present(note, "sha256")
        && !sha256_hex(note.body.as_bytes()).eq_ignore_ascii_case(&text(note, "sha256"))
    {
        problems.push(Problem::new(
            &note.path,
            "brain-source-hash",
            "source text does not match sha256: a source is immutable",
        ));
    }
    if text(note, "kind") == "tool_run" {
        for prop in ["command", "inputs_sha256"] {
            if !present(note, prop) {
                problems.push(Problem::new(
                    &note.path,
                    "brain-tool-run",
                    format!("a tool_run source needs {prop}"),
                ));
            }
        }
    }
    if text(note, "status") == "superseded" && !present(note, "superseded_by") {
        problems.push(Problem::new(
            &note.path,
            "brain-superseded",
            "a superseded source names its replacement in superseded_by",
        ));
    }
}

fn lint_claim(index: &VaultIndex, note: &Note, problems: &mut Vec<Problem>) {
    let source = check_span(index, note, problems);
    let level = text(note, "level");
    match Level::parse(&level) {
        None => problems.push(Problem::new(
            &note.path,
            "brain-level",
            format!(
                "level must be one of {}",
                Level::ALL[1..]
                    .iter()
                    .map(|l| l.as_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
        )),
        Some(Level::Candidate) => problems.push(Problem::new(
            &note.path,
            "brain-level",
            "a candidate never enters the main brain",
        )),
        Some(Level::Sourced) => {}
        Some(Level::Corroborated) => {
            let own = source.map(|s| s.path.clone());
            let independent =
                targets(index, note, "corroborated_by")
                    .into_iter()
                    .any(|(_, other)| {
                        other.is_some_and(|c| {
                            kind_of(c) == "claim"
                                && targets(index, c, "source_ref")
                                    .first()
                                    .and_then(|(_, s)| s.map(|s| s.path.clone()))
                                    != own
                        })
                    });
            if !independent || !present(note, "independence") {
                problems.push(Problem::new(
                    &note.path,
                    "brain-evidence",
                    "corroborated needs corroborated_by (a Claim on a different Source) and independence",
                ));
            }
        }
        Some(Level::Verified) => {
            let run = targets(index, note, "tool_run_ref").into_iter().next();
            let ok = run
                .and_then(|(_, n)| n)
                .is_some_and(|n| kind_of(n) == "source" && text(n, "kind") == "tool_run");
            if !ok {
                problems.push(Problem::new(
                    &note.path,
                    "brain-evidence",
                    "verified needs tool_run_ref pointing at a tool_run source",
                ));
            }
        }
        Some(Level::Reviewed) => {
            if !present(note, "reviewer") || !present(note, "reviewed_on") {
                problems.push(Problem::new(
                    &note.path,
                    "brain-evidence",
                    "reviewed needs reviewer and reviewed_on",
                ));
            }
        }
    }
    if source.is_some_and(|s| text(s, "status") == "retracted") {
        problems.push(Problem::new(
            &note.path,
            "brain-retracted",
            "the source is retracted: the claim must be downgraded and leave the brain",
        ));
    }
}

fn lint_theory(index: &VaultIndex, note: &Note, problems: &mut Vec<Problem>) {
    let source = check_span(index, note, problems);
    if source.is_some_and(|s| text(s, "status") == "retracted") {
        problems.push(Problem::new(
            &note.path,
            "brain-retracted",
            "the source is retracted: the theory must be removed or re-attributed",
        ));
    }
}

fn lint_conflict(index: &VaultIndex, note: &Note, problems: &mut Vec<Problem>) {
    check_choice(note, "status", &CONFLICT_STATUSES, problems);
    let sides: BTreeSet<String> = targets(index, note, "sides")
        .into_iter()
        .map(|(value, found)| found.map_or(link_name(&value), |n| n.path.clone()))
        .collect();
    if sides.len() < 2 {
        problems.push(Problem::new(
            &note.path,
            "brain-conflict",
            "a conflict keeps at least two different sides",
        ));
    }
    for (value, found) in targets(index, note, "sides") {
        if let Some(side) = found
            && !matches!(kind_of(side).as_str(), "claim" | "theory")
        {
            problems.push(Problem::new(
                &note.path,
                "brain-conflict",
                format!("side {value} is a {}, not a claim or theory", kind_of(side)),
            ));
        }
    }
    if text(note, "status") == "closed" && !present(note, "closed_by") {
        problems.push(Problem::new(
            &note.path,
            "brain-conflict",
            "a closed conflict names who or what closed it in closed_by",
        ));
    }
}

fn lint_question(index: &VaultIndex, note: &Note, problems: &mut Vec<Problem>) {
    check_choice(note, "status", &QUESTION_STATUSES, problems);
    for (value, found) in targets(index, note, "bears_on") {
        if let Some(n) = found
            && !matches!(kind_of(n).as_str(), "claim" | "conflict")
        {
            problems.push(Problem::new(
                &note.path,
                "brain-question",
                format!(
                    "bears_on {value} is a {}, not a claim or conflict",
                    kind_of(n)
                ),
            ));
        }
    }
    for (value, found) in targets(index, note, "answered_by") {
        if let Some(n) = found
            && kind_of(n) != "claim"
        {
            problems.push(Problem::new(
                &note.path,
                "brain-question",
                format!("answered_by {value} is a {}, not a claim", kind_of(n)),
            ));
        }
    }
    if text(note, "status") == "answered" && !present(note, "answered_by") {
        problems.push(Problem::new(
            &note.path,
            "brain-question",
            "an answered question links the Claims that answer it in answered_by",
        ));
    }
}

/// The problems of a main-brain vault in path order: the schema of [`brain_schema`] (required properties, links,
/// folders, unknown types) and the rules of ADR-024 3.3. Notes without a `type` belong to the user and are skipped.
pub fn lint_brain(index: &VaultIndex) -> Vec<Problem> {
    let schema = brain_schema();
    let mut problems = Vec::new();
    for note in index.notes.values() {
        let schema_problems = validate_note(note, index, &schema);
        let known = schema.types.contains_key(&kind_of(note));
        problems.extend(schema_problems);
        if !known {
            continue;
        }
        match kind_of(note).as_str() {
            "source" => lint_source(note, &mut problems),
            "claim" => lint_claim(index, note, &mut problems),
            "theory" => lint_theory(index, note, &mut problems),
            "conflict" => lint_conflict(index, note, &mut problems),
            "open-question" => lint_question(index, note, &mut problems),
            _ => {}
        }
    }
    problems
}
