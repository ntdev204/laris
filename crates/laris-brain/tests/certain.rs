//! The rule "certain" (T285): a Claim answers alone only when its Source is admissible under the configured classes,
//! was resolved by a registry the class accepts, carries an accepted licence and venue, was checked for retraction,
//! and the Claim's quote is found again at its span with its hash. Each way of failing is named.

use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicU32, Ordering};

use laris_brain::answer::{AnswerSettings, SentenceKind, compose};
use laris_brain::certain::{Admissibility, NotCertain, check};
use laris_brain::{
    Admission, ClaimProposal, Decision, Gate, GateSettings, MetadataCheck, Proposer, Refusal,
    SourceProposal,
};
use laris_vault::VaultIndex;
use laris_vault::brain::Level;
use serde_json::json;

struct Temp(PathBuf);

impl Temp {
    fn new() -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-certain-{}-{}",
            std::process::id(),
            N.fetch_add(1, Ordering::SeqCst)
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("temp dir");
        Temp(dir)
    }
}

impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

const GATE: GateSettings = GateSettings {
    min_support: 0.9,
    min_equivalence: 0.6,
    subject_overlap: 0.5,
    search_depth: 10,
    max_bytes: 100_000,
};
const HASH: &str = "4f1d3b0c9a8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d6c5b4a392817060000";

fn rules() -> Admissibility {
    Admissibility::from_json(&json!({"classes": {
        "journal_paper": {"registries": ["crossref"], "licences": ["cc-by-4.0", "cc0-1.0"],
                          "venues": ["2041-1723"], "retraction_check": true},
        "textbook": {"registries": ["openstax-catalogue"], "licences": ["cc-by-4.0"],
                     "venues": null, "retraction_check": false}
    }}))
    .expect("valid classes")
}

fn paper() -> Admission {
    Admission {
        class: "journal_paper".into(),
        resolved_by: "crossref".into(),
        resolution_sha256: HASH.into(),
        licence: "cc-by-4.0".into(),
        venue: Some("2041-1723".into()),
        retraction_check: Some("crossref:none".into()),
    }
}

struct Brain {
    t: Temp,
    gate: Gate,
}

fn who() -> Proposer {
    Proposer("tool:test".into())
}

impl Brain {
    fn new() -> Brain {
        let t = Temp::new();
        let gate = Gate::new(&t.0, GATE, Box::new(|| "2026-11-23".into()));
        Brain { t, gate }
    }

    /// A Source named `title` stating `fact`, with `admission`, and one Claim quoting the fact. Returns the Claim's
    /// note path.
    fn paper(&self, title: &str, fact: &str, admission: Option<Admission>) -> String {
        let d = self
            .gate
            .submit_source(SourceProposal {
                title: title.into(),
                kind: "document".into(),
                identifier: format!("doi:10.1/{title}"),
                text: format!("Abstract.\n\n{fact}\n"),
                command: None,
                inputs_sha256: None,
                cites: vec![],
                dataset: None,
                metadata: MetadataCheck::Verified("crossref".into()),
                admission,
                proposer: who(),
            })
            .expect("io");
        assert!(d.is_accepted(), "{d:?}");
        self.claim(Some(title), fact)
    }

    fn claim(&self, source: Option<&str>, statement: &str) -> String {
        let d = self
            .gate
            .submit_claim(ClaimProposal {
                statement: statement.into(),
                source: source.map(Into::into),
                quote: statement.into(),
                requested: Level::Sourced,
                evidence: vec![],
                solver: None,
                proposer: who(),
            })
            .expect("io");
        match d {
            Decision::Accepted { path, .. } => path,
            Decision::Refused { reason, detail } => format!("refused:{}:{detail}", reason.as_str()),
        }
    }

    fn verdict(&self, path: &str) -> Result<(), NotCertain> {
        let index = VaultIndex::build(&self.t.0, None).expect("index");
        let note = index.notes.get(path).expect("claim note");
        check(&index, note, &rules(), Level::Sourced)
    }

    fn edit(&self, rel: &str, from: &str, to: &str) {
        let path = self.t.0.join(rel);
        let text = fs::read_to_string(&path).expect("read");
        assert!(text.contains(from), "{rel} has no {from:?}");
        fs::write(&path, text.replacen(from, to, 1)).expect("write");
    }
}

const FACT: &str = "Ribosomes translate messenger RNA into protein in every living cell.";

#[test]
fn an_admitted_paper_with_its_quote_in_place_is_certain() {
    let b = Brain::new();
    let claim = b.paper("Ribosomes", FACT, Some(paper()));
    assert_eq!(b.verdict(&claim), Ok(()));
}

#[test]
fn every_way_of_failing_is_named() {
    let b = Brain::new();
    let cases: Vec<(&str, Option<Admission>, NotCertain)> = vec![
        ("NoRecord", None, NotCertain::NotAdmitted),
        (
            "UnknownClass",
            Some(Admission {
                class: "blog".into(),
                ..paper()
            }),
            NotCertain::NotAdmitted,
        ),
        (
            // the DOI did not resolve at Crossref: the importer had only another registry's word for it
            "Unresolvable",
            Some(Admission {
                resolved_by: "openalex".into(),
                ..paper()
            }),
            NotCertain::Unresolved,
        ),
        (
            "NoResponseHash",
            Some(Admission {
                resolution_sha256: "abc".into(),
                ..paper()
            }),
            NotCertain::Unresolved,
        ),
        (
            "Retracted",
            Some(Admission {
                retraction_check: Some("crossref:retracted".into()),
                ..paper()
            }),
            NotCertain::Retracted,
        ),
        (
            "Unchecked",
            Some(Admission {
                retraction_check: None,
                ..paper()
            }),
            NotCertain::RetractionUnchecked,
        ),
        (
            "OffList",
            Some(Admission {
                venue: Some("1234-5678".into()),
                ..paper()
            }),
            NotCertain::Venue,
        ),
        (
            "NoVenue",
            Some(Admission {
                venue: None,
                ..paper()
            }),
            NotCertain::Venue,
        ),
        (
            "Closed",
            Some(Admission {
                licence: "cc-by-nc-4.0".into(),
                ..paper()
            }),
            NotCertain::Licence,
        ),
    ];
    for (i, (title, admission, want)) in cases.into_iter().enumerate() {
        // a different fact per Source, so no Claim is a duplicate of another
        let fact = format!("{FACT} Case {title} has number {i}.");
        let claim = b.paper(title, &fact, admission);
        assert_eq!(b.verdict(&claim), Err(want), "{title}");
        assert!(!want.as_str().is_empty());
    }
}

#[test]
fn a_quote_moved_or_a_source_edited_is_not_certain() {
    let b = Brain::new();
    let claim = b.paper("Moved", FACT, Some(paper()));
    assert_eq!(b.verdict(&claim), Ok(()));
    b.edit(&claim, "span_start: ", "span_start: 1");
    assert_eq!(b.verdict(&claim), Err(NotCertain::QuoteMoved));

    let other = b.paper(
        "Edited",
        "Mitochondria make most of the ATP of a cell.",
        Some(paper()),
    );
    b.edit("Sources/Edited.md", "Mitochondria", "Chloroplasts");
    assert_eq!(b.verdict(&other), Err(NotCertain::SourceChanged));
}

#[test]
fn a_retracted_source_is_not_certain() {
    let b = Brain::new();
    let claim = b.paper("Later", FACT, Some(paper()));
    b.gate
        .retract_source("Later", "retraction notice", who())
        .expect("retract");
    // the gate moves the dependants out of the brain; read the Claim as it stands
    let index = VaultIndex::build(&b.t.0, None).expect("index");
    let source = index.find("Later").expect("source note kept");
    assert_eq!(
        laris_brain::certain::admissible(source, &rules()),
        Err(NotCertain::Retracted)
    );
    if let Some(note) = index.notes.get(&claim) {
        assert!(check(&index, note, &rules(), Level::Sourced).is_err());
    }
}

#[test]
fn a_model_only_claim_stays_refused() {
    let b = Brain::new();
    let refused = b.claim(None, "Ribosomes are made of lipids only.");
    assert!(
        refused.starts_with(&format!("refused:{}", Refusal::ModelOnly.as_str())),
        "{refused}"
    );
}

#[test]
fn the_answer_uses_only_certain_claims_when_classes_are_set() {
    let b = Brain::new();
    b.paper("Good", FACT, Some(paper()));
    b.paper(
        "Bad",
        "Ribosomes translate messenger RNA quickly in yeast cells under stress.",
        Some(Admission {
            licence: "cc-by-nc-4.0".into(),
            ..paper()
        }),
    );
    let index = VaultIndex::build(&b.t.0, None).expect("index");
    let mut settings = AnswerSettings {
        min_cover: 0.8,
        min_level: Level::Sourced,
        max_notes: 8,
        admissible: None,
    };
    let question = "Do ribosomes translate messenger RNA in cells?";
    let plain = compose(&index, question, &settings);
    let cited = |a: &laris_brain::answer::Answer| {
        a.sentences
            .iter()
            .filter(|s| s.kind == SentenceKind::Claim)
            .count()
    };
    assert_eq!(cited(&plain), 2, "without classes both Claims are used");
    settings.admissible = Some(Arc::new(rules()));
    let strict = compose(&index, question, &settings);
    assert_eq!(cited(&strict), 1, "only the admissible paper's Claim");
}

#[test]
fn the_classes_are_configuration_and_refuse_an_empty_or_partial_entry() {
    let bad = [
        json!({}),
        json!({"classes": {}}),
        json!({"classes": {"x": {"registries": [], "licences": ["a"], "venues": null, "retraction_check": false}}}),
        json!({"classes": {"x": {"registries": ["r"], "licences": ["a"], "retraction_check": false}}}),
        json!({"classes": {"x": {"registries": ["r"], "licences": ["a"], "venues": null}}}),
    ];
    for doc in bad {
        assert!(Admissibility::from_json(&doc).is_err(), "{doc}");
    }
    let repo =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../configs/admissible-sources.json");
    let shipped = Admissibility::load(&repo).expect("the shipped classes load");
    assert!(shipped.classes.contains_key("journal_paper"));
}

#[test]
fn an_admission_record_needs_its_fields() {
    let b = Brain::new();
    let d = b
        .gate
        .submit_source(SourceProposal {
            title: "Half".into(),
            kind: "document".into(),
            identifier: "doi:10.1/half".into(),
            text: "Abstract.\n".into(),
            command: None,
            inputs_sha256: None,
            cites: vec![],
            dataset: None,
            metadata: MetadataCheck::Verified("crossref".into()),
            admission: Some(Admission {
                licence: " ".into(),
                ..paper()
            }),
            proposer: who(),
        })
        .expect("io");
    assert!(
        matches!(
            d,
            Decision::Refused {
                reason: Refusal::Shape,
                ..
            }
        ),
        "{d:?}"
    );
}
