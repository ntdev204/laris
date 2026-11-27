//! The miss-rate fixture of the gate's checks (T283, ADR-024 6.3): measured false Conflicts of the T277 snapshot, real
//! contradictions the search must still find, and the two check misses of T172 (a strengthened quantifier accepted by
//! the gate, a rewording with an appended clause kept by the answer check). Every case runs through the real gate and
//! the real answer check; the figures are pinned, so a change of a rule shows here. With
//! `LARIS_PRECISION_REPORT=<file>` the measurement is written as JSON.

use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};

use laris_brain::answer::{AnswerSettings, Sentence, SentenceKind, check_sentence};
use laris_brain::{
    ClaimProposal, Decision, Gate, GateSettings, MetadataCheck, Proposer, SourceProposal,
};
use laris_vault::VaultIndex;
use laris_vault::brain::Level;
use serde_json::{Value, json};

struct Temp(PathBuf);

impl Temp {
    fn new() -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-precision-{}-{}",
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

/// The deployed thresholds (T277 build, `docker/compose.yaml`), untuned.
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

fn fixture() -> Value {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/fixtures/check-precision.json"
    );
    serde_json::from_str(&fs::read_to_string(path).expect("fixture")).expect("json")
}

fn cases<'a>(f: &'a Value, group: &str) -> &'a Vec<Value> {
    f[group].as_array().expect("group")
}

fn s<'a>(v: &'a Value, key: &str) -> &'a str {
    v[key].as_str().expect("string")
}

fn who() -> Proposer {
    Proposer("advisor-test".into())
}

fn source(g: &Gate, title: &str, text: &str) {
    let d = g
        .submit_source(SourceProposal {
            title: title.into(),
            kind: "document".into(),
            identifier: format!("doi:10.1/{}", title.to_lowercase()),
            text: text.into(),
            command: None,
            inputs_sha256: None,
            cites: vec![],
            dataset: None,
            metadata: MetadataCheck::Verified("registry-fixture".into()),
            admission: None,
            proposer: who(),
        })
        .expect("io");
    assert!(d.is_accepted(), "{d:?}");
}

fn claim(g: &Gate, src: &str, statement: &str, quote: &str) -> Decision {
    g.submit_claim(ClaimProposal {
        statement: statement.into(),
        source: Some(src.into()),
        quote: quote.into(),
        requested: Level::Sourced,
        evidence: vec![],
        solver: None,
        proposer: who(),
    })
    .expect("io")
}

/// Whether the gate writes a Conflict when the second statement arrives after the first (each from its own Source).
fn conflict_raised(a: &str, b: &str) -> bool {
    let t = Temp::new();
    let g = Gate::new(&t.0, GATE, Box::new(|| "2026-11-27".into()));
    source(&g, "S1", a);
    source(&g, "S2", b);
    assert!(claim(&g, "S1", a, a).is_accepted());
    match claim(&g, "S2", b, b) {
        Decision::Accepted { conflicts, .. } => !conflicts.is_empty(),
        other => panic!("{b}: {other:?}"),
    }
}

fn gate_accepts(quote: &str, statement: &str) -> bool {
    let t = Temp::new();
    let g = Gate::new(&t.0, GATE, Box::new(|| "2026-11-27".into()));
    source(&g, "Paper", quote);
    claim(&g, "Paper", statement, quote).is_accepted()
}

fn answer_keeps(claimed: &str, sentence: &str) -> bool {
    let t = Temp::new();
    let g = Gate::new(&t.0, GATE, Box::new(|| "2026-11-27".into()));
    source(&g, "Paper", claimed);
    let Decision::Accepted { path, .. } = claim(&g, "Paper", claimed, claimed) else {
        panic!("claim refused");
    };
    let title = path
        .trim_start_matches("Claims/")
        .trim_end_matches(".md")
        .to_string();
    let index = VaultIndex::build(&t.0, None).expect("index");
    let s = Sentence {
        kind: SentenceKind::Claim,
        body: sentence.into(),
        cites: vec![title],
    };
    check_sentence(&index, &s, &ANSWER).is_ok()
}

#[test]
fn the_check_precision_fixture_is_measured() {
    let f = fixture();
    let mut report = Vec::new();

    let (mut real, mut found, mut false_total, mut false_raised) = (0, 0, 0, 0);
    let mut lost = Vec::new();
    let mut remaining = Vec::new();
    for c in cases(&f, "contradiction_pairs") {
        let raised = conflict_raised(s(c, "a"), s(c, "b"));
        if c["contradiction"] == true {
            real += 1;
            if raised {
                found += 1;
            } else {
                lost.push(s(c, "label").to_string());
            }
        } else {
            false_total += 1;
            if raised {
                false_raised += 1;
                remaining.push(s(c, "label").to_string());
            }
        }
        report.push(json!({"group": "contradiction", "label": c["label"], "expected": c["contradiction"], "raised": raised}));
    }

    let (mut unsup, mut unsup_accepted, mut sup, mut sup_refused) = (0, 0, 0, 0);
    for c in cases(&f, "gate_support") {
        let accepted = gate_accepts(s(c, "quote"), s(c, "statement"));
        if c["supported"] == true {
            sup += 1;
            sup_refused += usize::from(!accepted);
        } else {
            unsup += 1;
            unsup_accepted += usize::from(accepted);
        }
        report.push(json!({"group": "gate", "label": c["label"], "expected": c["supported"], "accepted": accepted}));
    }

    let (mut unf, mut unf_kept, mut fai, mut fai_kept) = (0, 0, 0, 0);
    for c in cases(&f, "answer_check") {
        let kept = answer_keeps(s(c, "claim"), s(c, "sentence"));
        if c["faithful"] == true {
            fai += 1;
            fai_kept += usize::from(kept);
        } else {
            unf += 1;
            unf_kept += usize::from(kept);
        }
        report.push(json!({"group": "answer", "label": c["label"], "expected": c["faithful"], "kept": kept}));
    }

    if let Ok(path) = std::env::var("LARIS_PRECISION_REPORT") {
        let out = json!({
            "contradiction": {"real": real, "found": found, "false_pairs": false_total, "false_raised": false_raised},
            "gate": {"unsupported": unsup, "unsupported_accepted": unsup_accepted, "supported": sup, "supported_refused": sup_refused},
            "answer": {"unfaithful": unf, "unfaithful_kept": unf_kept, "faithful": fai, "faithful_kept": fai_kept},
            "cases": report,
        });
        fs::write(path, serde_json::to_string_pretty(&out).expect("json")).expect("report");
    }

    // no real contradiction is lost
    assert_eq!(lost, Vec::<String>::new());
    assert_eq!((found, real), (19, 19));
    // 4 of the 22 measured false Conflicts remain, each a stated limit (labelled `known remaining` in the fixture)
    assert_eq!((false_raised, false_total), (4, 22), "{remaining:?}");
    assert_eq!((unsup_accepted, unsup), (0, 5));
    // the one false refusal: a hedge in another sentence of a wider quote
    assert_eq!((sup_refused, sup), (1, 6));
    assert_eq!((unf_kept, unf), (0, 9));
    assert_eq!((fai_kept, fai), (3, 8), "free paraphrase stays the cost");
}
