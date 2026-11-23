//! T277: the gate's batch of Claims decides exactly as one Claim at a time, and a Claim can link the solver call that
//! computes with its formula (a `tool_run` Source), which lint checks.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};

use laris_brain::{
    ClaimProposal, Decision, Gate, GateSettings, MetadataCheck, Proposer, Refusal, SourceProposal,
};
use laris_vault::brain::Level;
use laris_vault::{VaultIndex, lint_brain};

struct Temp(PathBuf);

impl Temp {
    fn new() -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-batch-{}-{}",
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

fn gate(dir: &Path) -> Gate {
    Gate::new(dir, SETTINGS, Box::new(|| "2026-11-23".to_string()))
}

fn who() -> Proposer {
    Proposer("tool:test".into())
}

fn document(title: &str, text: &str) -> SourceProposal {
    SourceProposal {
        title: title.into(),
        kind: "document".into(),
        identifier: format!("https://example.org/{title}"),
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

fn tool_run(title: &str, output: &str) -> SourceProposal {
    SourceProposal {
        title: title.into(),
        kind: "tool_run".into(),
        identifier: "tool:solve_stem".into(),
        text: output.into(),
        command: Some("solve_stem {\"operation\": \"solve\"}".into()),
        inputs_sha256: Some("0".repeat(64)),
        cites: vec![],
        dataset: None,
        metadata: MetadataCheck::NotApplicable,
        admission: None,
        proposer: who(),
    }
}

fn claim(statement: &str, source: &str, solver: Option<&str>) -> ClaimProposal {
    ClaimProposal {
        statement: statement.into(),
        source: Some(source.into()),
        quote: statement.into(),
        requested: Level::Sourced,
        evidence: vec![],
        solver: solver.map(Into::into),
        proposer: who(),
    }
}

const BOOK: &str = "Kinematics\n\nThe velocity of an object increases when it accelerates.\n\n\
The velocity of an object does not increase when it accelerates.\n\n\
Final velocity: v = v_0 + a t.\n\nAverage speed is distance divided by time.";

fn proposals() -> Vec<ClaimProposal> {
    vec![
        claim(
            "The velocity of an object increases when it accelerates.",
            "Book",
            None,
        ),
        claim("Final velocity: v = v_0 + a t.", "Book", None),
        // contradicts the first one: the batch must see it
        claim(
            "The velocity of an object does not increase when it accelerates.",
            "Book",
            None,
        ),
        // the same claim twice: the second is a duplicate
        claim("Average speed is distance divided by time.", "Book", None),
        claim("Average speed is distance divided by time.", "Book", None),
        // not in the source: the span check refuses it
        claim("Speed is a vector.", "Book", None),
    ]
}

fn tree(dir: &Path) -> Vec<(String, String)> {
    fn walk(base: &Path, dir: &Path, out: &mut Vec<(String, String)>) {
        for e in fs::read_dir(dir).expect("dir").flatten() {
            let p = e.path();
            if p.is_dir() {
                walk(base, &p, out);
            } else {
                let rel = p
                    .strip_prefix(base)
                    .expect("prefix")
                    .to_string_lossy()
                    .into_owned();
                out.push((rel, fs::read_to_string(&p).expect("read")));
            }
        }
    }
    let mut out = Vec::new();
    walk(dir, dir, &mut out);
    out.sort();
    out
}

fn kinds(decisions: &[Decision]) -> Vec<String> {
    decisions
        .iter()
        .map(|d| match d {
            Decision::Accepted { conflicts, .. } => format!("accepted/{}", conflicts.len()),
            Decision::Refused { reason, .. } => format!("refused/{}", reason.as_str()),
        })
        .collect()
}

#[test]
fn a_batch_decides_and_writes_exactly_as_one_claim_at_a_time() {
    let one = Temp::new();
    let many = Temp::new();
    for t in [&one, &many] {
        assert!(
            gate(&t.0)
                .submit_source(document("Book", BOOK))
                .expect("io")
                .is_accepted()
        );
    }
    let g = gate(&one.0);
    let single: Vec<Decision> = proposals()
        .into_iter()
        .map(|p| g.submit_claim(p).expect("io"))
        .collect();
    let batch = gate(&many.0).submit_claims(proposals()).expect("io");
    assert_eq!(single, batch);
    assert_eq!(
        kinds(&batch),
        [
            "accepted/0",
            "accepted/0",
            "accepted/1",
            "accepted/0",
            "refused/duplicate",
            "refused/span"
        ]
    );
    assert_eq!(
        tree(&one.0),
        tree(&many.0),
        "the same files with the same bytes"
    );
    let index = VaultIndex::build(&many.0, None).expect("index");
    assert!(lint_brain(&index).is_empty(), "{:?}", lint_brain(&index));
}

#[test]
fn a_claim_links_the_solver_run_of_its_formula() {
    let t = Temp::new();
    let g = gate(&t.0);
    assert!(
        g.submit_source(document("Book", BOOK))
            .expect("io")
            .is_accepted()
    );
    assert!(
        g.submit_source(tool_run(
            "Solver run 1",
            "{\"status\": \"verified\", \"answer\": \"v_0 + a*t\"}"
        ))
        .expect("io")
        .is_accepted()
    );
    let d = g
        .submit_claim(claim(
            "Final velocity: v = v_0 + a t.",
            "Book",
            Some("Solver run 1"),
        ))
        .expect("io");
    let Decision::Accepted { path, level, .. } = d else {
        panic!("expected accepted, got {d:?}");
    };
    assert_eq!(level, Some(Level::Sourced), "a solver link is not evidence");
    let text = fs::read_to_string(t.0.join(&path)).expect("claim");
    assert!(
        text.contains("solver_ref: '[[Solver run 1]]'")
            || text.contains("solver_ref: \"[[Solver run 1]]\""),
        "{text}"
    );
    let index = VaultIndex::build(&t.0, None).expect("index");
    assert!(lint_brain(&index).is_empty(), "{:?}", lint_brain(&index));
}

#[test]
fn a_solver_link_to_anything_but_an_active_tool_run_is_refused() {
    let t = Temp::new();
    let g = gate(&t.0);
    assert!(
        g.submit_source(document("Book", BOOK))
            .expect("io")
            .is_accepted()
    );
    for target in ["Book", "No such run"] {
        let d = g
            .submit_claim(claim(
                "Final velocity: v = v_0 + a t.",
                "Book",
                Some(target),
            ))
            .expect("io");
        assert!(
            matches!(
                d,
                Decision::Refused {
                    reason: Refusal::Evidence,
                    ..
                }
            ),
            "{target}: {d:?}"
        );
    }
    assert!(!t.0.join("Claims").exists(), "a refusal writes nothing");
}

#[test]
fn lint_rejects_a_solver_ref_that_is_not_a_tool_run() {
    let t = Temp::new();
    let g = gate(&t.0);
    assert!(
        g.submit_source(document("Book", BOOK))
            .expect("io")
            .is_accepted()
    );
    let d = g
        .submit_claim(claim(
            "Average speed is distance divided by time.",
            "Book",
            None,
        ))
        .expect("io");
    let Decision::Accepted { path, .. } = d else {
        panic!("expected accepted");
    };
    // a hand edit that points the link at a document
    let file = t.0.join(&path);
    let text = fs::read_to_string(&file).expect("claim");
    fs::write(
        &file,
        text.replacen("---\n", "---\nsolver_ref: '[[Book]]'\n", 1),
    )
    .expect("edit");
    let index = VaultIndex::build(&t.0, None).expect("index");
    let problems = lint_brain(&index);
    assert!(
        problems.iter().any(|p| p.message.contains("solver_ref")),
        "{problems:?}"
    );
}

/// Found in T277: a quote that holds both words of an opposite pair was refused as support for itself. The support
/// check now refuses only a word whose opposite the quote says and which the quote never says itself.
#[test]
fn a_quote_that_says_both_opposites_supports_itself_but_not_a_flip() {
    let t = Temp::new();
    let g = gate(&t.0);
    let text = "Flow\n\nFor N below about 2000, flow is laminar; above about 3000, it is turbulent.\n\n\
                Pressure falls when the speed is higher.";
    assert!(
        g.submit_source(document("Flow", text))
            .expect("io")
            .is_accepted()
    );
    let both = "For N below about 2000, flow is laminar; above about 3000, it is turbulent.";
    assert!(
        g.submit_claim(claim(both, "Flow", None))
            .expect("io")
            .is_accepted()
    );
    let mut flipped = claim("Pressure falls when the speed is lower.", "Flow", None);
    flipped.quote = "Pressure falls when the speed is higher.".into();
    let d = g.submit_claim(flipped).expect("io");
    assert!(
        matches!(d, Decision::Refused { reason: Refusal::Unsupported, ref detail } if detail.contains("opposite")),
        "{d:?}"
    );
}
