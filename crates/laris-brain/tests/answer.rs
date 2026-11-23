//! Answer assembly on a brain the tests build through the gate: answers cite accepted Claims, abstain without them,
//! present Conflicts, and reject sentences that the notes do not support. The outside-set check's miss rate is measured.

use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};

use laris_brain::answer::{
    ABSTENTION, Answer, AnswerSettings, Judge, Rephraser, Sentence, SentenceKind, assemble,
    check_sentence, compose, verify_answer,
};
use laris_brain::{
    ClaimProposal, Decision, Gate, GateSettings, MetadataCheck, Proposer, SourceProposal,
};
use laris_vault::VaultIndex;
use laris_vault::brain::Level;
use serde_json::json;

struct Temp(PathBuf);

impl Temp {
    fn new() -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-answer-{}-{}",
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
const ANSWER: AnswerSettings = AnswerSettings {
    min_cover: 0.8,
    min_level: Level::Sourced,
    max_notes: 8,
    admissible: None,
};

const C1: &str = "Aspirin reduces fever in adults.";
const C2: &str = "A dose of 500 mg was used in 2020.";
const C3: &str = "Vitamin D may raise serum calcium in adults.";
const C4: &str = "The vaccine was not tested in children.";
const C5: &str = "Dr Lee reported 12 adverse events at Mercy Hospital.";

struct Brain {
    t: Temp,
    gate: Gate,
    titles: BTreeMap<String, String>,
}

fn who() -> Proposer {
    Proposer("advisor-test".into())
}

fn brain() -> Brain {
    let t = Temp::new();
    let gate = Gate::new(&t.0, GATE, Box::new(|| "2026-11-20".into()));
    let text = [C1, C2, C3, C4, C5].join("\n\n");
    let doc = SourceProposal {
        title: "Paper".into(),
        kind: "document".into(),
        identifier: "doi:10.1/p".into(),
        text,
        command: None,
        inputs_sha256: None,
        cites: vec![],
        dataset: None,
        metadata: MetadataCheck::Verified("registry-fixture".into()),
        admission: None,
        proposer: who(),
    };
    assert!(gate.submit_source(doc).expect("io").is_accepted());
    let mut b = Brain {
        t,
        gate,
        titles: BTreeMap::new(),
    };
    for c in [C1, C2, C3, C4, C5] {
        let title = b.claim("Paper", c);
        b.titles.insert(c.to_string(), title);
    }
    b
}

impl Brain {
    fn claim(&self, source: &str, statement: &str) -> String {
        let d = self
            .gate
            .submit_claim(ClaimProposal {
                statement: statement.into(),
                source: Some(source.into()),
                quote: statement.into(),
                requested: Level::Sourced,
                evidence: vec![],
                solver: None,
                proposer: who(),
            })
            .expect("io");
        match d {
            Decision::Accepted { path, .. } => path
                .trim_start_matches("Claims/")
                .trim_end_matches(".md")
                .to_string(),
            other => panic!("{other:?}"),
        }
    }

    fn index(&self) -> VaultIndex {
        VaultIndex::build(&self.t.0, None).expect("index")
    }

    fn cite(&self, statements: &[&str]) -> Vec<String> {
        statements.iter().map(|s| self.titles[*s].clone()).collect()
    }
}

fn sentence(cites: Vec<String>, body: &str) -> Sentence {
    Sentence {
        kind: SentenceKind::Claim,
        body: body.into(),
        cites,
    }
}

#[test]
fn an_answer_is_built_from_accepted_claims_with_note_ids_and_levels() {
    let b = brain();
    let index = b.index();
    let answer = compose(&index, "does aspirin reduce fever", &ANSWER);
    assert_eq!(answer.sentences.len(), 1);
    assert_eq!(answer.sentences[0].body, C1);
    assert_eq!(answer.sentences[0].cites, b.cite(&[C1]));
    let text = answer.render(&index);
    assert!(
        text.contains(&format!("[[{}]]", b.titles[C1])) && text.contains("(level: sourced)"),
        "{text}"
    );
    assert!(verify_answer(&index, &answer, &ANSWER).is_empty());
}

#[test]
fn nothing_accepted_gives_the_abstention() {
    let b = brain();
    let index = b.index();
    let answer = compose(&index, "how tall is the moon landing", &ANSWER);
    assert!(answer.abstained());
    assert_eq!(answer.render(&index), ABSTENTION);
    assert!(verify_answer(&index, &answer, &ANSWER).is_empty());
    // a retracted source takes its claims out of every answer
    b.gate
        .retract_source("Paper", "retracted", who())
        .expect("retract");
    assert!(compose(&b.index(), "does aspirin reduce fever", &ANSWER).abstained());
    // a level above what the claim holds leaves it out
    let b = brain();
    let strict = AnswerSettings {
        min_level: Level::Corroborated,
        ..ANSWER
    };
    assert!(compose(&b.index(), "does aspirin reduce fever", &strict).abstained());
}

#[test]
fn a_conflict_is_presented_with_both_sides() {
    let b = brain();
    let other = SourceProposal {
        title: "Paper C".into(),
        kind: "document".into(),
        identifier: "doi:10.1/c".into(),
        text: "Aspirin does not reduce fever in adults.".into(),
        command: None,
        inputs_sha256: None,
        cites: vec![],
        dataset: None,
        metadata: MetadataCheck::Verified("registry-fixture".into()),
        admission: None,
        proposer: who(),
    };
    b.gate.submit_source(other).expect("io");
    let rival = b.claim("Paper C", "Aspirin does not reduce fever in adults.");
    let index = b.index();
    let answer = compose(&index, "does aspirin reduce fever", &ANSWER);
    let conflict = answer
        .sentences
        .iter()
        .find(|s| s.kind == SentenceKind::Conflict)
        .expect("conflict sentence");
    assert!(
        conflict.body.starts_with("The sources disagree:")
            && conflict.body.contains("does not reduce")
            && conflict.body.contains("reduces fever")
    );
    assert!(
        conflict.cites.contains(&rival)
            && conflict.cites.contains(&b.titles[C1])
            && conflict.cites.iter().any(|c| c.starts_with("Conflict"))
    );
    assert!(
        verify_answer(&index, &answer, &ANSWER).is_empty(),
        "{:?}",
        verify_answer(&index, &answer, &ANSWER)
    );
    // dropping a side from the sentence is found
    let mut cut = answer.clone();
    let at = cut
        .sentences
        .iter()
        .position(|s| s.kind == SentenceKind::Conflict)
        .expect("at");
    cut.sentences[at].cites.remove(0);
    assert!(!verify_answer(&index, &cut, &ANSWER).is_empty());
}

struct Fixed(&'static str);

impl Rephraser for Fixed {
    fn rephrase(&self, _body: &str, _cited: &[String]) -> Result<String, String> {
        Ok(self.0.to_string())
    }
}

struct Down;

impl Rephraser for Down {
    fn rephrase(&self, _body: &str, _cited: &[String]) -> Result<String, String> {
        Err("model unavailable".into())
    }
}

struct Veto;

impl Judge for Veto {
    fn veto(&self, _rephrased: &str, _cited: &[String]) -> bool {
        true
    }
}

struct Yes;

impl Judge for Yes {
    fn veto(&self, _rephrased: &str, _cited: &[String]) -> bool {
        false
    }
}

#[test]
fn the_advisor_may_only_rephrase() {
    let b = brain();
    let index = b.index();
    let q = "does aspirin reduce fever";
    // a faithful rewording is used
    let ok = assemble(
        &index,
        q,
        &ANSWER,
        &Fixed("In adults, aspirin reduces fever."),
        None,
    );
    assert_eq!(
        ok.answer.sentences[0].body,
        "In adults, aspirin reduces fever."
    );
    assert!(ok.replaced.is_empty());
    // an unsupported rewording is replaced by the Claim's own words, with the reason
    for bad in [
        "Aspirin cures fever and prevents strokes in adults.",
        "Aspirin reduces fever in adults at 900 mg.",
        "Aspirin does not reduce fever in adults.",
    ] {
        let got = assemble(&index, q, &ANSWER, &Fixed(bad), None);
        assert_eq!(got.answer.sentences[0].body, C1, "{bad}");
        assert_eq!(got.replaced.len(), 1, "{bad}");
        assert!(verify_answer(&index, &got.answer, &ANSWER).is_empty());
    }
    // an advisor that fails changes nothing but is reported
    let down = assemble(&index, q, &ANSWER, &Down, None);
    assert_eq!(down.answer.sentences[0].body, C1);
    assert!(down.replaced[0].reason.contains("model unavailable"));
    // a judge can only veto: a yes does not rescue a failing sentence, a no refuses a good one
    let still = assemble(
        &index,
        q,
        &ANSWER,
        &Fixed("Aspirin cures fever and prevents strokes in adults."),
        Some(&Yes),
    );
    assert_eq!(still.answer.sentences[0].body, C1);
    let vetoed = assemble(
        &index,
        q,
        &ANSWER,
        &Fixed("In adults, aspirin reduces fever."),
        Some(&Veto),
    );
    assert_eq!(vetoed.answer.sentences[0].body, C1);
}

#[test]
fn inserted_unsupported_sentences_are_rejected() {
    let b = brain();
    let index = b.index();
    let mut answer = compose(&index, "does aspirin reduce fever", &ANSWER);
    assert!(verify_answer(&index, &answer, &ANSWER).is_empty());
    answer.sentences.push(Sentence {
        kind: SentenceKind::Claim,
        body: "Aspirin prevents heart attacks.".into(),
        cites: vec![],
    });
    answer.sentences.push(sentence(
        vec!["Claim that does not exist".into()],
        "Aspirin prevents heart attacks.",
    ));
    answer
        .sentences
        .push(sentence(b.cite(&[C1]), "Aspirin prevents heart attacks."));
    answer.sentences.push(Sentence {
        kind: SentenceKind::System,
        body: "Everything is certain.".into(),
        cites: vec![],
    });
    let found: Vec<usize> = verify_answer(&index, &answer, &ANSWER)
        .into_iter()
        .map(|(i, _)| i)
        .collect();
    assert_eq!(found, vec![1, 2, 3, 4]);
    // a candidate-level note cannot be cited: a Source is not a claim
    let source_cited = sentence(vec!["Paper".into()], C1);
    assert!(check_sentence(&index, &source_cited, &ANSWER).is_err());
}

/// The miss rate of the outside-set check on inserted unsupported sentences, and its false-reject rate on faithful
/// rewordings. The figures are pinned and, with `LARIS_BRAIN_REPORT=<file>`, written as a measured report.
#[test]
fn the_outside_set_miss_rate_is_measured() {
    let b = brain();
    let index = b.index();
    // (label, cited claims, sentence, expected to be caught)
    let unsupported: Vec<(&str, Vec<&str>, &str, bool)> = vec![
        (
            "number changed",
            vec![C1],
            "Aspirin reduces fever in adults at 900 mg.",
            true,
        ),
        (
            "number changed in a dose",
            vec![C2],
            "A dose of 800 mg was used in 2020.",
            true,
        ),
        (
            "polarity flipped to positive",
            vec![C4],
            "The vaccine was tested in children.",
            true,
        ),
        (
            "polarity flipped to negative",
            vec![C1],
            "Aspirin does not reduce fever in adults.",
            true,
        ),
        (
            "hedge dropped",
            vec![C3],
            "Vitamin D raises serum calcium in adults.",
            true,
        ),
        (
            "hedge added",
            vec![C1],
            "Aspirin always reduces fever in adults.",
            true,
        ),
        (
            "quantifier added",
            vec![C1],
            "Aspirin reduces fever in all adults.",
            true,
        ),
        (
            "new name",
            vec![C5],
            "Dr Smith reported 12 adverse events at Mercy Hospital.",
            true,
        ),
        (
            "new content",
            vec![C1],
            "Aspirin cures fever and prevents strokes in adults.",
            true,
        ),
        (
            "opposite verb",
            vec![C1],
            "Aspirin increases fever in adults.",
            true,
        ),
        (
            "stronger verb",
            vec![C1],
            "Aspirin lowers fever in adults.",
            true,
        ),
        (
            "no citation",
            vec![],
            "Aspirin prevents heart attacks.",
            true,
        ),
        (
            "made-up citation",
            vec![],
            "Aspirin prevents heart attacks.",
            true,
        ),
        (
            "words kept, roles swapped",
            vec![C1],
            "Fever reduces aspirin in adults.",
            false,
        ),
        (
            "words kept, names swapped",
            vec![C5],
            "Mercy Hospital reported 12 adverse events at Dr Lee.",
            false,
        ),
        (
            "two claims spliced",
            vec![C1, C2],
            "A dose of 500 mg reduces fever in adults.",
            false,
        ),
    ];
    let mut caught = 0;
    let mut misses = Vec::new();
    let mut cases = Vec::new();
    for (label, cites, body, expect_caught) in &unsupported {
        let cites = if *label == "made-up citation" {
            vec!["No such claim".to_string()]
        } else {
            b.cite(cites)
        };
        let rejected = check_sentence(&index, &sentence(cites, body), &ANSWER).is_err();
        assert_eq!(rejected, *expect_caught, "{label}: {body}");
        if rejected {
            caught += 1;
        } else {
            misses.push(*label);
        }
        cases.push(json!({"label": label, "sentence": body, "caught": rejected}));
    }
    let total = unsupported.len();
    assert_eq!((caught, total), (13, 16));
    // faithful rewordings: how many survive (a rejected one only costs the Claim's own wording)
    let faithful: Vec<(Vec<&str>, &str)> = vec![
        (vec![C1], "In adults, aspirin reduces fever."),
        (vec![C1], "Aspirin reduces fever in adults."),
        (vec![C2], "In 2020 a dose of 500 mg was used."),
        (vec![C3], "In adults, vitamin D may raise serum calcium."),
        (vec![C4], "The vaccine was not tested in children."),
        (
            vec![C5],
            "At Mercy Hospital, Dr Lee reported 12 adverse events.",
        ),
        (vec![C1], "Adults taking aspirin see less fever."),
        (vec![C2], "The trial gave 500 mg in 2020."),
    ];
    let kept = faithful
        .iter()
        .filter(|(cites, body)| {
            check_sentence(&index, &sentence(b.cite(cites), body), &ANSWER).is_ok()
        })
        .count();
    assert_eq!(
        (kept, faithful.len()),
        (6, 8),
        "free paraphrase is the cost of the filter"
    );
    if let Ok(path) = std::env::var("LARIS_BRAIN_REPORT") {
        let report = json!({
            "report": "outside-set check (ADR-024 6.3, T166)",
            "date": "2026-11-20",
            "settings": {"min_cover": ANSWER.min_cover},
            "fixture": "tests/answer.rs: 5 claims, 16 inserted unsupported sentences, 8 faithful rewordings",
            "unsupported_sentences": total, "caught": caught, "missed": misses.len(),
            "miss_rate": misses.len() as f64 / total as f64, "missed_cases": misses,
            "faithful_rewordings": faithful.len(), "faithful_kept": kept,
            "false_reject_rate": 1.0 - kept as f64 / faithful.len() as f64,
            "cases": cases,
            "reading": "A filter on vocabulary, not a proof. It misses rearrangements that keep every word, and it rejects free paraphrase; the system is faithful to accepted Claims up to the measured miss rate on this fixture.",
        });
        fs::write(path, serde_json::to_string_pretty(&report).expect("json")).expect("report");
    }
    let _ = Answer::default();
}
