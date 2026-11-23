//! The one rule for a brain-only answer: when a Claim is **certain** (T285, SR-K3, ADR-026 section 5).
//!
//! A Claim is certain when all of these hold, checked again every time it is read:
//!
//! 1. it is a Claim at level `sourced` or higher (and at least the caller's minimum);
//! 2. its Source is an active `document` whose text still hashes to its recorded `sha256`;
//! 3. the Source carries an admission record whose class is one of the configured source classes, resolved by a
//!    registry that class accepts, with the hash of that registry's response, a licence the class accepts, a venue on
//!    the class's list when the class has one, and a retraction check that found nothing when the class needs one;
//! 4. the Claim's quote is found again at its recorded byte span of the Source text with its recorded hash.
//!
//! Anything else may be context for the model, never a brain-only answer. The classes, registries, licences and venues
//! are configuration ([`Admissibility::from_json`]); nothing here lists them. The rule reads only the vault: it never
//! calls a registry (the network is used at import, the gate and evaluation runs stay offline).
//!
//! The admission record is written by the gate from a [`crate::gate::Admission`] at import and is immutable with the
//! Source, as the Source text is.

use std::collections::{BTreeMap, BTreeSet};

use laris_vault::brain::{Level, resolve_span, sha256_hex};
use laris_vault::index::VaultIndex;
use laris_vault::note::{Note, link_name};
use serde_json::Value as Json;

/// What one source class admits.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceClass {
    /// Registries whose resolution of the identifier the class accepts (e.g. `crossref`).
    pub registries: BTreeSet<String>,
    /// Licences the class accepts, as written in the admission record.
    pub licences: BTreeSet<String>,
    /// Venues (ISSN) the class accepts; `None` when the class has no venue list.
    pub venues: Option<BTreeSet<String>>,
    /// Whether a retraction check that found nothing is required.
    pub retraction_check: bool,
}

/// The configured source classes, by name.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Admissibility {
    /// Classes by name.
    pub classes: BTreeMap<String, SourceClass>,
}

fn strings(value: Option<&Json>, what: &str) -> Result<BTreeSet<String>, String> {
    let items = value
        .and_then(Json::as_array)
        .ok_or_else(|| format!("{what}: expected a list of strings"))?;
    items
        .iter()
        .map(|v| {
            v.as_str()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .ok_or_else(|| format!("{what}: expected non-empty strings"))
        })
        .collect()
}

impl Admissibility {
    /// Reads the `classes` object of a configuration document: `{"classes": {NAME: {"registries": [..], "licences":
    /// [..], "venues": [..] | null, "retraction_check": bool}}}`. Other top-level keys are ignored (the acquisition
    /// settings live beside the classes). Every field is required; an empty list of registries or licences is refused,
    /// since it would make the class admit nothing by accident.
    pub fn from_json(doc: &Json) -> Result<Admissibility, String> {
        let classes = doc
            .get("classes")
            .and_then(Json::as_object)
            .ok_or("expected an object `classes`")?;
        if classes.is_empty() {
            return Err("`classes` is empty".into());
        }
        let mut out = BTreeMap::new();
        for (name, spec) in classes {
            let field = |key: &str| format!("classes.{name}.{key}");
            let registries = strings(spec.get("registries"), &field("registries"))?;
            let licences = strings(spec.get("licences"), &field("licences"))?;
            if registries.is_empty() || licences.is_empty() {
                return Err(format!(
                    "classes.{name}: registries and licences may not be empty"
                ));
            }
            let venues = match spec.get("venues") {
                Some(Json::Null) => None,
                Some(v) => Some(
                    strings(Some(v), &field("venues"))?
                        .into_iter()
                        .map(|s| s.to_ascii_uppercase())
                        .collect(),
                ),
                None => return Err(format!("{}: required (null for none)", field("venues"))),
            };
            let retraction_check = spec
                .get("retraction_check")
                .and_then(Json::as_bool)
                .ok_or_else(|| format!("{}: expected true or false", field("retraction_check")))?;
            out.insert(
                name.clone(),
                SourceClass {
                    registries,
                    licences,
                    venues,
                    retraction_check,
                },
            );
        }
        Ok(Admissibility { classes: out })
    }

    /// Reads the configuration file at `path`.
    pub fn load(path: &std::path::Path) -> Result<Admissibility, String> {
        let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
        let doc: Json =
            serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))?;
        Admissibility::from_json(&doc).map_err(|e| format!("{}: {e}", path.display()))
    }
}

/// Why a note is not certain. Each has a stable name for counts and reports.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum NotCertain {
    /// The note is not a Claim.
    NotAClaim,
    /// The Claim's level is below `sourced` or below the caller's minimum.
    Level,
    /// The Claim names no Source, or the Source is missing or is not a document.
    NoSource,
    /// The Source is retracted, or its retraction check found a retraction.
    Retracted,
    /// The Source is superseded or otherwise not active.
    SourceInactive,
    /// The Source text no longer hashes to its recorded `sha256`.
    SourceChanged,
    /// The Source has no admission record, or names a class that is not configured.
    NotAdmitted,
    /// The resolution is missing, by a registry the class does not accept, or without the response hash.
    Unresolved,
    /// The licence is not one the class accepts.
    Licence,
    /// The venue is not on the class's list.
    Venue,
    /// The class needs a retraction check and none is recorded.
    RetractionUnchecked,
    /// The quote is not found at its recorded span with its recorded hash.
    QuoteMoved,
}

impl NotCertain {
    /// The stable name.
    pub fn as_str(self) -> &'static str {
        match self {
            NotCertain::NotAClaim => "not-a-claim",
            NotCertain::Level => "level",
            NotCertain::NoSource => "no-source",
            NotCertain::Retracted => "retracted",
            NotCertain::SourceInactive => "source-inactive",
            NotCertain::SourceChanged => "source-changed",
            NotCertain::NotAdmitted => "not-admitted",
            NotCertain::Unresolved => "unresolved",
            NotCertain::Licence => "licence",
            NotCertain::Venue => "venue",
            NotCertain::RetractionUnchecked => "retraction-unchecked",
            NotCertain::QuoteMoved => "quote-moved",
        }
    }
}

fn prop(note: &Note, name: &str) -> String {
    note.prop(name)
        .map_or(String::new(), |v| v.py_str().trim().to_string())
}

fn int(note: &Note, name: &str) -> Option<i64> {
    match note.prop(name) {
        Some(laris_vault::yaml::Value::Int(n)) => Some(*n),
        _ => None,
    }
}

fn is_sha256(text: &str) -> bool {
    text.len() == 64 && text.bytes().all(|b| b.is_ascii_hexdigit())
}

/// Whether the Source note `source` is admissible under `rules`; `Ok` names its class.
pub fn admissible<'a>(source: &Note, rules: &'a Admissibility) -> Result<&'a str, NotCertain> {
    if prop(source, "type") != "source" || prop(source, "kind") != "document" {
        return Err(NotCertain::NoSource);
    }
    match prop(source, "status").as_str() {
        "active" => {}
        "retracted" => return Err(NotCertain::Retracted),
        _ => return Err(NotCertain::SourceInactive),
    }
    if !sha256_hex(source.body.as_bytes()).eq_ignore_ascii_case(&prop(source, "sha256")) {
        return Err(NotCertain::SourceChanged);
    }
    let (name, class) = rules
        .classes
        .get_key_value(prop(source, "source_class").as_str())
        .ok_or(NotCertain::NotAdmitted)?;
    if !class.registries.contains(&prop(source, "resolved_by"))
        || !is_sha256(&prop(source, "resolution_sha256"))
    {
        return Err(NotCertain::Unresolved);
    }
    if !class.licences.contains(&prop(source, "licence")) {
        return Err(NotCertain::Licence);
    }
    if let Some(venues) = &class.venues
        && !venues.contains(&prop(source, "venue").to_ascii_uppercase())
    {
        return Err(NotCertain::Venue);
    }
    if class.retraction_check {
        // written as `REGISTRY:none` or `REGISTRY:retracted`
        let check = prop(source, "retraction_check");
        match check.split_once(':') {
            Some((registry, "none")) if class.registries.contains(registry) => {}
            Some((_, "retracted")) => return Err(NotCertain::Retracted),
            _ => return Err(NotCertain::RetractionUnchecked),
        }
    }
    Ok(name.as_str())
}

/// Whether `note` is a certain Claim under `rules` with level at least `min_level` (never below `sourced`).
pub fn check(
    index: &VaultIndex,
    note: &Note,
    rules: &Admissibility,
    min_level: Level,
) -> Result<(), NotCertain> {
    if prop(note, "type") != "claim" {
        return Err(NotCertain::NotAClaim);
    }
    let level = Level::parse(&prop(note, "level")).ok_or(NotCertain::Level)?;
    if level < min_level.max(Level::Sourced) {
        return Err(NotCertain::Level);
    }
    let source = index
        .find(&link_name(&prop(note, "source_ref")))
        .ok_or(NotCertain::NoSource)?;
    admissible(source, rules)?;
    let (Some(start), Some(end)) = (int(note, "span_start"), int(note, "span_end")) else {
        return Err(NotCertain::QuoteMoved);
    };
    resolve_span(&source.body, start, end, &prop(note, "span_sha256"))
        .map_err(|_| NotCertain::QuoteMoved)?;
    Ok(())
}
