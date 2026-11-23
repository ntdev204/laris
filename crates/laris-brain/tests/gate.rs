//! The write gate on vaults the tests write: refusals change nothing, accepted notes lint clean, a contradiction writes
//! a Conflict and a retracted Source downgrades what rests on it.

use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};

use laris_brain::audit;
use laris_brain::{
    ClaimProposal, Decision, Evidence, Gate, GateSettings, MetadataCheck, Proposer, Refusal,
    SourceProposal, TheoryProposal,
};
use laris_vault::brain::Level;

struct Temp(PathBuf);

impl Temp {
    fn new() -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-gate-{}-{}",
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

const SETTINGS: GateSettings = GateSettings {
    min_support: 0.9,
    min_equivalence: 0.6,
    subject_overlap: 0.5,
    search_depth: 10,
    max_bytes: 100_000,
};

fn gate(t: &Temp) -> Gate {
    Gate::new(&t.0, SETTINGS, Box::new(|| "2026-11-20".to_string()))
}

fn who() -> Proposer {
    Proposer("advisor-test".into())
}

fn source(title: &str, id: &str, text: &str) -> SourceProposal {
    SourceProposal {
        title: title.into(),
        kind: "document".into(),
        identifier: id.into(),
        text: text.into(),
        command: None,
        inputs_sha256: None,
        cites: vec![],
        dataset: None,
        metadata: MetadataCheck::Verified("registry-fixture".into()),
        admission: None,
        proposer: who(),
    }
}

fn claim(statement: &str, src: Option<&str>, quote: &str) -> ClaimProposal {
    ClaimProposal {
        statement: statement.into(),
        source: src.map(Into::into),
        quote: quote.into(),
        requested: Level::Sourced,
        evidence: vec![],
        solver: None,
        proposer: who(),
    }
}

const A: &str = "Aspirin reduces fever in adults. A dose of 500 mg was used in 2020.\n\nIt did not reduce blood pressure.";
const B: &str = "In a second trial, aspirin reduces fever in adults at 500 mg.";

fn accepted(d: &Decision) -> (String, Option<Level>, Vec<String>) {
    match d {
        Decision::Accepted {
            path,
            level,
            conflicts,
        } => (path.clone(), *level, conflicts.clone()),
        other => panic!("expected accepted, got {other:?}"),
    }
}

fn refused(d: &Decision) -> (Refusal, String) {
    match d {
        Decision::Refused { reason, detail } => (*reason, detail.clone()),
        other => panic!("expected refused, got {other:?}"),
    }
}

fn files(t: &Temp) -> Vec<String> {
    fn walk(dir: &std::path::Path, base: &std::path::Path, out: &mut Vec<String>) {
        for e in fs::read_dir(dir).expect("dir").flatten() {
            let p = e.path();
            if p.is_dir() {
                walk(&p, base, out);
            } else {
                out.push(
                    p.strip_prefix(base)
                        .expect("prefix")
                        .to_string_lossy()
                        .into_owned(),
                );
            }
        }
    }
    let mut out = Vec::new();
    walk(&t.0, &t.0, &mut out);
    out.retain(|f| !f.starts_with(".laris/"));
    out.sort();
    out
}

fn with_source(t: &Temp) -> Gate {
    let g = gate(t);
    assert!(
        g.submit_source(source("Paper A", "doi:10.1/a", A))
            .expect("io")
            .is_accepted()
    );
    g
}

#[test]
fn an_accepted_claim_lints_clean_and_is_audited() {
    let t = Temp::new();
    let g = with_source(&t);
    let d = g
        .submit_claim(claim(
            "Aspirin reduces fever in adults.",
            Some("Paper A"),
            "Aspirin reduces fever in adults.",
        ))
        .expect("io");
    let (path, level, conflicts) = accepted(&d);
    assert!(path.starts_with("Claims/"));
    assert_eq!(level, Some(Level::Sourced));
    assert!(conflicts.is_empty());
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
    assert!(g.spans_resolve().expect("spans"));
    let log = audit::read(&t.0);
    assert_eq!(log.len(), 2);
    assert_eq!(log[1]["decision"], "accepted");
    assert_eq!(log[1]["proposer"], "advisor-test");
}

#[test]
fn model_only_claims_are_refused_and_change_nothing() {
    let t = Temp::new();
    let g = with_source(&t);
    let before = files(&t);
    let cases = [
        // no source at all
        (
            claim("Aspirin cures cancer.", None, "Aspirin cures cancer."),
            Refusal::ModelOnly,
        ),
        // a source that is not in the brain
        (
            claim(
                "Aspirin reduces fever in adults.",
                Some("Nowhere"),
                "Aspirin reduces fever",
            ),
            Refusal::UnknownSource,
        ),
        // a quote the source does not hold
        (
            claim(
                "Aspirin cures cancer.",
                Some("Paper A"),
                "Aspirin cures cancer.",
            ),
            Refusal::Span,
        ),
        // a quote that is there but does not support the statement
        (
            claim(
                "Aspirin reduces fever in children.",
                Some("Paper A"),
                "Aspirin reduces fever in adults.",
            ),
            Refusal::Unsupported,
        ),
        (
            claim(
                "Aspirin reduces fever in adults at 900 mg.",
                Some("Paper A"),
                "A dose of 500 mg was used in 2020.",
            ),
            Refusal::Unsupported,
        ),
        (
            claim(
                "Aspirin reduces blood pressure.",
                Some("Paper A"),
                "It did not reduce blood pressure.",
            ),
            Refusal::Unsupported,
        ),
    ];
    for (proposal, expected) in cases {
        let (reason, _) = refused(&g.submit_claim(proposal.clone()).expect("io"));
        assert_eq!(reason, expected, "{proposal:?}");
    }
    let mut candidate = claim(
        "Aspirin reduces fever in adults.",
        Some("Paper A"),
        "Aspirin reduces fever in adults.",
    );
    candidate.requested = Level::Candidate;
    assert_eq!(
        refused(&g.submit_claim(candidate).expect("io")).0,
        Refusal::Level
    );
    assert_eq!(files(&t), before, "a refusal writes no note");
    // every refusal is in the audit
    let log = audit::read(&t.0);
    assert_eq!(log.iter().filter(|r| r["decision"] == "refused").count(), 7);
}

#[test]
fn a_source_without_verified_metadata_is_refused() {
    let t = Temp::new();
    let g = gate(&t);
    for metadata in [
        MetadataCheck::Unresolved,
        MetadataCheck::Mismatch("authors differ".into()),
        MetadataCheck::NotApplicable,
    ] {
        let mut s = source("Paper A", "doi:10.1/a", A);
        s.metadata = metadata;
        assert_eq!(
            refused(&g.submit_source(s).expect("io")).0,
            Refusal::Metadata
        );
    }
    assert_eq!(files(&t), Vec::<String>::new());
    // a changed text under a used name is refused: sources are immutable
    assert!(
        g.submit_source(source("Paper A", "doi:10.1/a", A))
            .expect("io")
            .is_accepted()
    );
    assert!(
        g.submit_source(source("Paper A", "doi:10.1/a", A))
            .expect("io")
            .is_accepted(),
        "the same text is unchanged"
    );
    assert_eq!(
        refused(
            &g.submit_source(source("Paper A", "doi:10.1/a", "other"))
                .expect("io")
        )
        .0,
        Refusal::Duplicate
    );
}

#[test]
fn whitespace_in_the_quote_is_folded_but_the_span_is_exact() {
    let t = Temp::new();
    let g = with_source(&t);
    let d = g
        .submit_claim(claim(
            "Aspirin reduces fever in adults.",
            Some("Paper A"),
            "Aspirin   reduces\nfever in adults.",
        ))
        .expect("io");
    accepted(&d);
    assert!(g.spans_resolve().expect("spans"));
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
}

#[test]
fn a_contradiction_writes_a_conflict_and_keeps_both_sides() {
    let t = Temp::new();
    let g = with_source(&t);
    let first = accepted(
        &g.submit_claim(claim(
            "Aspirin reduces fever in adults.",
            Some("Paper A"),
            "Aspirin reduces fever in adults.",
        ))
        .expect("io"),
    )
    .0;
    assert!(
        g.submit_source(source(
            "Paper C",
            "doi:10.1/c",
            "Aspirin does not reduce fever in adults."
        ))
        .expect("io")
        .is_accepted()
    );
    let d = g
        .submit_claim(claim(
            "Aspirin does not reduce fever in adults.",
            Some("Paper C"),
            "Aspirin does not reduce fever in adults.",
        ))
        .expect("io");
    let (second, level, conflicts) = accepted(&d);
    assert_eq!(
        level,
        Some(Level::Sourced),
        "the new claim is stored at its own level"
    );
    assert_eq!(conflicts.len(), 1);
    assert!(conflicts[0].starts_with("Conflicts/"));
    let conflict = fs::read_to_string(t.0.join(&conflicts[0])).expect("conflict");
    let title = |p: &str| {
        p.trim_start_matches("Claims/")
            .trim_end_matches(".md")
            .to_string()
    };
    assert!(
        conflict.contains(&title(&first)) && conflict.contains(&title(&second)),
        "{conflict}"
    );
    assert!(conflict.contains("status: open"));
    assert!(
        fs::read_to_string(t.0.join(&first))
            .expect("first")
            .contains("conflict_refs"),
        "the stored claim links the conflict"
    );
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
}

#[test]
fn numbers_and_opposite_words_conflict_too() {
    let t = Temp::new();
    let g = gate(&t);
    g.submit_source(source(
        "P1",
        "doi:10.1/p1",
        "The trial enrolled 120 patients in 2019.",
    ))
    .expect("io");
    g.submit_source(source(
        "P2",
        "doi:10.1/p2",
        "The trial enrolled 80 patients in 2019.",
    ))
    .expect("io");
    g.submit_source(source(
        "P3",
        "doi:10.1/p3",
        "The drug increases appetite in patients.",
    ))
    .expect("io");
    g.submit_source(source(
        "P4",
        "doi:10.1/p4",
        "The drug decreases appetite in patients.",
    ))
    .expect("io");
    let one = |s: &str, q: &str| accepted(&g.submit_claim(claim(q, Some(s), q)).expect("io"));
    one("P1", "The trial enrolled 120 patients in 2019.");
    assert_eq!(
        one("P2", "The trial enrolled 80 patients in 2019.").2.len(),
        1
    );
    one("P3", "The drug increases appetite in patients.");
    assert_eq!(
        one("P4", "The drug decreases appetite in patients.")
            .2
            .len(),
        1
    );
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
}

#[test]
fn a_theory_needs_attribution_and_a_source() {
    let t = Temp::new();
    let g = with_source(&t);
    let theory = |attr: &str, src: Option<&str>| TheoryProposal {
        statement: "Dr X argues that aspirin reduces fever in adults.".into(),
        attributed_to: attr.into(),
        source: src.map(Into::into),
        quote: "Aspirin reduces fever in adults.".into(),
        proposer: who(),
    };
    assert_eq!(
        refused(&g.submit_theory(theory("", Some("Paper A"))).expect("io")).0,
        Refusal::Shape
    );
    assert_eq!(
        refused(&g.submit_theory(theory("Dr X", None)).expect("io")).0,
        Refusal::ModelOnly
    );
    accepted(
        &g.submit_theory(theory("Dr X", Some("Paper A")))
            .expect("io"),
    );
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
}

#[test]
fn levels_follow_evidence_and_cannot_be_overclaimed() {
    let t = Temp::new();
    let g = with_source(&t);
    g.submit_source(source("Paper B", "doi:10.1/b", B))
        .expect("io");
    let statement = "Aspirin reduces fever in adults.";
    let a = accepted(
        &g.submit_claim(claim(statement, Some("Paper A"), statement))
            .expect("io"),
    )
    .0;
    // overclaim: asked for corroborated with no evidence
    let mut over = claim(
        "Aspirin reduces fever in adults at 500 mg.",
        Some("Paper B"),
        "aspirin reduces fever in adults at 500 mg.",
    );
    over.requested = Level::Corroborated;
    assert_eq!(
        refused(&g.submit_claim(over).expect("io")).0,
        Refusal::Level
    );
    // the same source cannot corroborate
    let name = |p: &str| {
        p.trim_start_matches("Claims/")
            .trim_end_matches(".md")
            .to_string()
    };
    let same = g
        .promote(
            &name(&a),
            Evidence::Corroborated {
                with: name(&a),
                independence: "x".into(),
            },
            who(),
        )
        .expect("io");
    assert_eq!(refused(&same).0, Refusal::Evidence);
    // an independent claim that says the same raises both
    let b = accepted(
        &g.submit_claim(claim(
            "Aspirin reduces fever in adults.",
            Some("Paper B"),
            "aspirin reduces fever in adults at 500 mg.",
        ))
        .expect("io"),
    )
    .0;
    let up = g
        .promote(
            &name(&a),
            Evidence::Corroborated {
                with: name(&b),
                independence: "different trials, different groups".into(),
            },
            who(),
        )
        .expect("io");
    assert_eq!(accepted(&up).1, Some(Level::Corroborated));
    assert!(
        fs::read_to_string(t.0.join(&b))
            .expect("b")
            .contains("level: corroborated")
    );
    // a review needs a reviewer
    assert_eq!(
        refused(
            &g.promote(
                &name(&a),
                Evidence::Reviewed {
                    reviewer: String::new(),
                    on: "2026-11-20".into()
                },
                who()
            )
            .expect("io")
        )
        .0,
        Refusal::Evidence
    );
    assert_eq!(
        accepted(
            &g.promote(
                &name(&a),
                Evidence::Reviewed {
                    reviewer: "owner".into(),
                    on: "2026-11-20".into()
                },
                who()
            )
            .expect("io")
        )
        .1,
        Some(Level::Reviewed)
    );
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
}

#[test]
fn a_tool_run_verifies_only_what_its_output_supports() {
    let t = Temp::new();
    let g = with_source(&t);
    let run = |title: &str, out: &str| SourceProposal {
        title: title.into(),
        kind: "tool_run".into(),
        identifier: format!("tool:{title}"),
        text: out.into(),
        command: Some("python check.py".into()),
        inputs_sha256: Some("0".repeat(64)),
        cites: vec![],
        dataset: None,
        metadata: MetadataCheck::NotApplicable,
        admission: None,
        proposer: who(),
    };
    g.submit_source(run(
        "Run 1",
        "A dose of 500 mg was used in 2020 as recomputed.",
    ))
    .expect("io");
    g.submit_source(run(
        "Run 2",
        "A dose of 900 mg was used in 2020 as recomputed.",
    ))
    .expect("io");
    let c = accepted(
        &g.submit_claim(claim(
            "A dose of 500 mg was used in 2020.",
            Some("Paper A"),
            "A dose of 500 mg was used in 2020.",
        ))
        .expect("io"),
    )
    .0;
    let name = c
        .trim_start_matches("Claims/")
        .trim_end_matches(".md")
        .to_string();
    assert_eq!(
        refused(
            &g.promote(
                &name,
                Evidence::ToolRun {
                    source: "Run 2".into()
                },
                who()
            )
            .expect("io")
        )
        .0,
        Refusal::Evidence
    );
    let up = g
        .promote(
            &name,
            Evidence::ToolRun {
                source: "Run 1".into(),
            },
            who(),
        )
        .expect("io");
    assert_eq!(accepted(&up).1, Some(Level::Verified));
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
}

/// Builds: A (sourced claim only on Paper A), a corroborated pair on Paper A and Paper B, a Conflict between the
/// Paper A claim and a Paper C claim. Retracting Paper A must retire the Paper A claims, downgrade the Paper B claim
/// and retire the Conflict, leaving a clean vault; a second run changes nothing.
#[test]
fn a_retracted_source_downgrades_its_dependants() {
    let t = Temp::new();
    let g = with_source(&t);
    g.submit_source(source("Paper B", "doi:10.1/b", B))
        .expect("io");
    g.submit_source(source(
        "Paper C",
        "doi:10.1/c",
        "Aspirin does not reduce fever in adults.",
    ))
    .expect("io");
    let name = |p: &str| {
        p.trim_start_matches("Claims/")
            .trim_end_matches(".md")
            .to_string()
    };
    let on_a = accepted(
        &g.submit_claim(claim(
            "Aspirin reduces fever in adults.",
            Some("Paper A"),
            "Aspirin reduces fever in adults.",
        ))
        .expect("io"),
    )
    .0;
    let dose = accepted(
        &g.submit_claim(claim(
            "A dose of 500 mg was used in 2020.",
            Some("Paper A"),
            "A dose of 500 mg was used in 2020.",
        ))
        .expect("io"),
    )
    .0;
    let on_b = accepted(
        &g.submit_claim(claim(
            "Aspirin reduces fever in adults.",
            Some("Paper B"),
            "aspirin reduces fever in adults at 500 mg.",
        ))
        .expect("io"),
    )
    .0;
    g.promote(
        &name(&on_a),
        Evidence::Corroborated {
            with: name(&on_b),
            independence: "separate trials".into(),
        },
        who(),
    )
    .expect("io");
    let on_c = accepted(
        &g.submit_claim(claim(
            "Aspirin does not reduce fever in adults.",
            Some("Paper C"),
            "Aspirin does not reduce fever in adults.",
        ))
        .expect("io"),
    )
    .0;
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
    assert!(files(&t).iter().any(|f| f.starts_with("Conflicts/")));

    let report = g
        .retract_source("Paper A", "retracted by the journal", who())
        .expect("retract");
    assert!(report.retired.iter().any(|(p, _)| *p == on_a));
    assert!(report.retired.iter().any(|(p, _)| *p == dose));
    assert!(
        report.downgraded.iter().any(|(p, from, to)| *p == on_b
            && *from == Level::Corroborated
            && *to == Level::Sourced)
    );
    // the conflict had three sides (the claims on Paper A and Paper B against Paper C): it keeps the two that remain
    let conflict = files(&t)
        .into_iter()
        .find(|f| f.starts_with("Conflicts/"))
        .expect("conflict stays");
    let conflict_text = fs::read_to_string(t.0.join(&conflict)).expect("conflict");
    assert!(
        !conflict_text.contains(&name(&on_a))
            && conflict_text.contains(&name(&on_b))
            && conflict_text.contains(&name(&on_c))
    );
    let b_text = fs::read_to_string(t.0.join(&on_b)).expect("b");
    assert!(
        b_text.contains("level: sourced") && !b_text.contains("corroborated_by"),
        "{b_text}"
    );
    let c_text = fs::read_to_string(t.0.join(&on_c)).expect("c");
    assert!(c_text.contains("conflict_refs"), "{c_text}");
    assert!(!t.0.join(&on_a).exists());
    assert!(
        t.0.join(".laris/retired").join(&on_a).exists(),
        "retired notes are kept outside the brain"
    );
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
    // with Paper B gone as well the conflict has one side left: it leaves the brain and the claim forgets it
    let more = g
        .retract_source("Paper B", "retracted too", who())
        .expect("retract B");
    assert!(
        more.retired
            .iter()
            .any(|(p, _)| p.starts_with("Conflicts/"))
    );
    assert!(
        !fs::read_to_string(t.0.join(&on_c))
            .expect("c")
            .contains("conflict_refs")
    );
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
    // a new claim on the retracted source is refused
    assert_eq!(
        refused(
            &g.submit_claim(claim(
                "Aspirin reduces fever in adults.",
                Some("Paper A"),
                "Aspirin reduces fever in adults."
            ))
            .expect("io")
        )
        .0,
        Refusal::SourceNotActive
    );
    // idempotent
    let again = g.consolidate().expect("again");
    assert!(again.is_empty(), "{again:?}");
    assert!(audit::read(&t.0).iter().any(|r| r["action"] == "retract"));
}

#[test]
fn a_reviewed_claim_survives_the_loss_of_other_evidence_but_not_of_its_source() {
    let t = Temp::new();
    let g = with_source(&t);
    let statement = "Aspirin reduces fever in adults.";
    let c = accepted(
        &g.submit_claim(claim(statement, Some("Paper A"), statement))
            .expect("io"),
    )
    .0;
    let name = c
        .trim_start_matches("Claims/")
        .trim_end_matches(".md")
        .to_string();
    g.promote(
        &name,
        Evidence::Reviewed {
            reviewer: "owner".into(),
            on: "2026-11-20".into(),
        },
        who(),
    )
    .expect("io");
    assert!(g.consolidate().expect("consolidate").is_empty());
    let report = g
        .retract_source("Paper A", "retracted", who())
        .expect("retract");
    assert!(
        report.retired.iter().any(|(p, _)| *p == c),
        "no review keeps a claim whose source is retracted"
    );
}

#[test]
fn a_replacing_source_keeps_claims_whose_quote_survives() {
    let t = Temp::new();
    let g = with_source(&t);
    let keep = accepted(
        &g.submit_claim(claim(
            "Aspirin reduces fever in adults.",
            Some("Paper A"),
            "Aspirin reduces fever in adults.",
        ))
        .expect("io"),
    )
    .0;
    let lose = accepted(
        &g.submit_claim(claim(
            "A dose of 500 mg was used in 2020.",
            Some("Paper A"),
            "A dose of 500 mg was used in 2020.",
        ))
        .expect("io"),
    )
    .0;
    let new = source(
        "Paper A v2",
        "doi:10.1/a-v2",
        "Corrigendum. Aspirin reduces fever in adults. The dose is withdrawn.",
    );
    let (decision, report) = g.supersede_source("Paper A", new).expect("supersede");
    accepted(&decision);
    assert_eq!(report.repointed, vec![keep.clone()]);
    assert!(report.retired.iter().any(|(p, _)| *p == lose));
    assert!(
        fs::read_to_string(t.0.join(&keep))
            .expect("keep")
            .contains("Paper A v2")
    );
    assert!(g.spans_resolve().expect("spans"));
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
}

#[test]
fn an_open_question_that_lost_its_answer_opens_again() {
    let t = Temp::new();
    let g = with_source(&t);
    let c = accepted(
        &g.submit_claim(claim(
            "Aspirin reduces fever in adults.",
            Some("Paper A"),
            "Aspirin reduces fever in adults.",
        ))
        .expect("io"),
    )
    .0;
    let name = c
        .trim_start_matches("Claims/")
        .trim_end_matches(".md")
        .to_string();
    fs::create_dir_all(t.0.join("Questions")).expect("dir");
    fs::write(
        t.0.join("Questions/Does it work.md"),
        format!("---\ntype: open-question\nstatus: answered\nanswered_by:\n- \"[[{name}]]\"\ncreated: 2026-11-20\n---\n\nDoes it work?"),
    )
    .expect("write");
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
    g.retract_source("Paper A", "retracted", who())
        .expect("retract");
    let q = fs::read_to_string(t.0.join("Questions/Does it work.md")).expect("q");
    assert!(
        q.contains("status: open") && !q.contains("answered_by"),
        "{q}"
    );
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
}

/// Measures the miss rate of the contradiction search on seeded pairs and states it. The pairs that use other
/// vocabulary are expected to be missed (ADR-024 4, honest limit); the test pins the figures so a change of the rule
/// check shows as a failure and the report stays true.
#[test]
fn the_contradiction_search_miss_rate_is_measured() {
    // (stored statement, opposing statement, detectable by vocabulary)
    let pairs = [
        (
            "Vitamin D raises serum calcium in adults.",
            "Vitamin D does not raise serum calcium in adults.",
            true,
        ),
        (
            "The vaccine is safe in children.",
            "The vaccine is unsafe in children.",
            true,
        ),
        (
            "The study enrolled 300 participants in 2018.",
            "The study enrolled 450 participants in 2018.",
            true,
        ),
        (
            "Exercise increases bone density in adults.",
            "Exercise decreases bone density in adults.",
            true,
        ),
        (
            "The drug lowers blood pressure in patients.",
            "The drug never lowers blood pressure in patients.",
            true,
        ),
        (
            "The compound is effective against the virus.",
            "The compound is ineffective against the virus.",
            true,
        ),
        (
            "The treatment lasted 12 weeks.",
            "The treatment lasted 8 weeks.",
            true,
        ),
        // different vocabulary: not found, and said so
        (
            "Coffee lowers the risk of heart disease.",
            "Heavy coffee intake is harmful for the heart.",
            false,
        ),
        (
            "The river floods every spring.",
            "Spring brings drought along the river.",
            false,
        ),
        (
            "The enzyme speeds up the reaction.",
            "The reaction proceeds slower once the enzyme is present.",
            false,
        ),
    ];
    let mut found = 0;
    let mut expected = 0;
    for (i, (stored, opposing, detectable)) in pairs.iter().enumerate() {
        let t = Temp::new();
        let g = gate(&t);
        g.submit_source(source("S1", &format!("doi:10.1/s{i}a"), stored))
            .expect("io");
        g.submit_source(source("S2", &format!("doi:10.1/s{i}b"), opposing))
            .expect("io");
        accepted(
            &g.submit_claim(claim(stored, Some("S1"), stored))
                .expect("io"),
        );
        let (_, _, conflicts) = accepted(
            &g.submit_claim(claim(opposing, Some("S2"), opposing))
                .expect("io"),
        );
        expected += 1;
        if !conflicts.is_empty() {
            found += 1;
        }
        assert_eq!(
            !conflicts.is_empty(),
            *detectable,
            "pair {i}: {stored} / {opposing}"
        );
    }
    // 7 of 10 seeded contradictions found: a miss rate of 30 % on this fixture, all misses in the different-vocabulary group
    assert_eq!((found, expected), (7, 10));
}
