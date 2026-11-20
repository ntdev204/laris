//! The decision dataset (T168, ADR-024 9.1): examples from logs and scenarios with provenance, a sealed held-out split,
//! and the exclusion of anything a model wrote or judged. A scripted advisor name stands for ResearchLLM.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};

use laris_brain::dataset::{
    EVIDENCE, Example, Excluded, Origin, Split, SplitSettings, decision_line, from_log,
    outcome_line, scenario_examples, split_of, training_text, verify, write,
};
use laris_brain::decide::{Act, RuleDecider, RuleSettings, Signals, legal};
use laris_brain::{ClaimProposal, Gate, GateSettings, MetadataCheck, Proposer, SourceProposal};
use laris_vault::VaultIndex;
use laris_vault::brain::Level;
use serde_json::Value;

struct Temp(PathBuf);

impl Temp {
    fn new() -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-dataset-{}-{}",
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

const RULES: RuleSettings = RuleSettings {
    required_level: Level::Sourced,
    min_coverage: 0.6,
    max_retrievals: 2,
    max_acquisitions: 2,
    max_advisor_asks: 3,
    max_repeats: 3,
};
const SPLIT: SplitSettings = SplitSettings {
    validation_pct: 10,
    heldout_pct: 20,
    withheld_advisor: None,
};

fn state(coverage: f64) -> Signals {
    let mut s = Signals::empty(6, 100.0);
    s.accepted = usize::from(coverage > 0.0);
    s.best_level = (coverage > 0.0).then_some(Level::Sourced);
    s.coverage = coverage;
    s.acquisition_allowed = true;
    s
}

/// A log of `n` decisions with outcomes, by two advisors.
fn log(n: u64) -> String {
    let decider = RuleDecider::new(RULES);
    let mut out = String::new();
    for seq in 0..n {
        let choice = decider.decide(&state(if seq % 3 == 0 { 1.0 } else { 0.0 }));
        let advisor = if seq % 2 == 0 {
            "advisor-a"
        } else {
            "advisor-b"
        };
        out += &decision_line(&format!("s{}", seq / 4), seq, Some(advisor), &choice);
        out.push('\n');
        // the outcome is measured, not copied from the choice: some right choices turn out badly
        let (good, evidence) = if seq % 5 == 0 {
            (false, "check_failed")
        } else {
            (true, "check_passed")
        };
        out += &outcome_line(&format!("s{}", seq / 4), seq, good, evidence);
        out.push('\n');
    }
    out
}

#[test]
fn log_examples_are_labelled_by_the_outcome_not_by_the_rule_decider() {
    let (examples, left_out) = from_log(&log(20), "decisions.jsonl");
    assert_eq!(examples.len(), 20);
    assert!(left_out.is_empty(), "{left_out:?}");
    assert!(examples.iter().all(|e| e.origin == Origin::Log));
    // the decider chose the same way for sequence 0 and 1, the labels differ with the outcomes
    let bad = examples.iter().filter(|e| !e.outcome.good).count();
    assert_eq!(bad, 4);
    for e in &examples {
        assert!(e.candidates.contains(&e.action));
        assert!(EVIDENCE.contains(&e.outcome.evidence.as_str()));
        assert_eq!(e.provenance["log"], "decisions.jsonl");
        assert_eq!(e.provenance["log_sha256"].as_str().map(str::len), Some(64));
        assert_eq!(e.id().len(), 64);
    }
    // ids are checksums of the content: same log, same ids
    let again = from_log(&log(20), "decisions.jsonl").0;
    assert_eq!(
        examples.iter().map(Example::id).collect::<Vec<_>>(),
        again.iter().map(Example::id).collect::<Vec<_>>()
    );
}

#[test]
fn a_seeded_model_generated_example_is_excluded() {
    let good = log(2);
    let choice = RuleDecider::new(RULES).decide(&state(1.0));
    let seeded = decision_line("sx", 0, Some("claude"), &choice)
        .replace("\"origin\":\"log\"", "\"origin\":\"model_generated\"");
    assert!(seeded.contains("model_generated"));
    let judged = outcome_line("sy", 0, true, "check_passed").replace("system", "model");
    let by_opinion = outcome_line("sz", 0, true, "advisor_says_good");
    let mut text = good.clone();
    text += &seeded;
    text += "\n";
    text += &outcome_line("sx", 0, true, "check_passed");
    text.push('\n');
    text += &decision_line("sy", 0, None, &choice);
    text.push('\n');
    text += &judged;
    text.push('\n');
    text += &decision_line("sz", 0, None, &choice);
    text.push('\n');
    text += &by_opinion;
    text.push('\n');
    text += &decision_line("sw", 0, None, &choice); // no outcome yet
    text.push('\n');
    text += "not json\n";
    let (examples, left_out) = from_log(&text, "mixed.jsonl");
    assert_eq!(examples.len(), 2, "only the two recorded decisions remain");
    assert!(
        examples
            .iter()
            .all(|e| !e.group.starts_with("log:sx") && !e.group.starts_with("log:sy"))
    );
    assert_eq!(left_out[&Excluded::ModelGenerated], 1);
    assert_eq!(left_out[&Excluded::UnmeasuredOutcome], 2);
    assert_eq!(left_out[&Excluded::NoOutcome], 1);
    assert_eq!(left_out[&Excluded::Malformed], 1);
}

#[test]
fn a_choice_outside_the_candidates_is_excluded() {
    let choice = RuleDecider::new(RULES).decide(&state(0.0));
    assert!(!choice.candidates.contains(&Act::Answer));
    let line = decision_line("s", 0, None, &choice).replace(
        &format!("\"action\":\"{}\"", choice.act.as_str()),
        "\"action\":\"answer\"",
    );
    let text = format!("{line}\n{}\n", outcome_line("s", 0, true, "check_passed"));
    let (examples, left_out) = from_log(&text, "l.jsonl");
    assert!(examples.is_empty());
    assert_eq!(left_out[&Excluded::IllegalChoice], 1);
}

#[test]
fn scenario_examples_are_counterfactual_complete_and_deterministic() {
    let a = scenario_examples(&RULES);
    assert!(a.len() > 5_000, "{}", a.len());
    assert_eq!(a, scenario_examples(&RULES));
    let mut groups: BTreeMap<&str, Vec<&Example>> = BTreeMap::new();
    for e in &a {
        assert_eq!(e.origin, Origin::Scenario);
        assert_eq!(e.outcome.evidence, "scenario_oracle");
        groups.entry(e.group.as_str()).or_default().push(e);
    }
    for (group, list) in &groups {
        // one example per legal candidate: the same state tried with each one
        let state = &list[0].signals;
        let mut acts: Vec<Act> = list.iter().map(|e| e.action).collect();
        acts.sort();
        let mut expected = legal(state, &RULES);
        expected.sort();
        assert_eq!(acts, expected, "{group}");
    }
    // the labels are not all one value, and the rule decider's choice is not always the only good one
    let good = a.iter().filter(|e| e.outcome.good).count();
    assert!(good > 0 && good < a.len());
    assert!(
        groups
            .values()
            .any(|l| l.iter().filter(|e| e.outcome.good).count() > 1)
    );
}

fn all_examples() -> Vec<Example> {
    let mut all = from_log(&log(120), "decisions.jsonl").0;
    all.extend(scenario_examples(&RULES));
    all
}

#[test]
fn groups_never_straddle_splits_and_the_heldout_set_is_sealed() {
    let t = Temp::new();
    let all = all_examples();
    let inputs = vec![("decisions.jsonl".to_owned(), "0".repeat(64))];
    let manifest =
        write(&t.0, &all, &SPLIT, &inputs, &BTreeMap::new(), "2026-11-20").expect("write");
    assert_eq!(verify(&t.0, &SPLIT).expect("verify"), Vec::<String>::new());
    // the manifest carries counts, checksums and the scenario share
    let m = &manifest.0;
    for split in ["train", "validation", "heldout"] {
        let s = &m["splits"][split];
        assert!(s["examples"].as_u64().unwrap_or(0) > 0, "{split}");
        let share = s["scenario_share"].as_f64().expect("share");
        assert!((0.0..=1.0).contains(&share));
        assert_eq!(
            m["files"][format!("{split}.jsonl")]["sha256"]
                .as_str()
                .map(str::len),
            Some(64)
        );
    }
    assert_eq!(m["inputs"][0]["name"], "decisions.jsonl");
    // no group is in two splits; the held-out groups are absent from train and validation
    let mut seen: BTreeMap<String, String> = BTreeMap::new();
    for split in ["train", "validation", "heldout"] {
        let body = fs::read_to_string(t.0.join(format!("{split}.jsonl"))).expect("file");
        for line in body.lines() {
            let v: Value = serde_json::from_str(line).expect("json");
            let group = v["group"].as_str().expect("group").to_owned();
            assert_eq!(v["split"], split);
            if let Some(prev) = seen.insert(group.clone(), split.to_owned()) {
                assert_eq!(prev, split, "{group}");
            }
        }
    }
    let total: usize = ["train", "validation", "heldout"]
        .iter()
        .map(|s| {
            fs::read_to_string(t.0.join(format!("{s}.jsonl")))
                .expect("file")
                .lines()
                .count()
        })
        .sum();
    assert_eq!(total, all.len());
}

#[test]
fn a_changed_or_moved_example_breaks_the_seal() {
    let all = all_examples();
    // an edit of the sealed file
    let t = Temp::new();
    write(&t.0, &all, &SPLIT, &[], &BTreeMap::new(), "2026-11-20").expect("write");
    let path = t.0.join("heldout.jsonl");
    let body = fs::read_to_string(&path).expect("file");
    fs::write(&path, body.replacen("\"good\":true", "\"good\":false", 1)).expect("tamper");
    let problems = verify(&t.0, &SPLIT).expect("verify");
    assert!(
        problems.iter().any(|p| p.contains("checksum differs")),
        "{problems:?}"
    );
    assert!(
        problems
            .iter()
            .any(|p| p.contains("not the hash of its content")),
        "{problems:?}"
    );
    // a sealed example moved into train, with the manifest rewritten to match: the split rule and the seal catch it
    let t = Temp::new();
    write(&t.0, &all, &SPLIT, &[], &BTreeMap::new(), "2026-11-20").expect("write");
    let held = fs::read_to_string(t.0.join("heldout.jsonl")).expect("file");
    let moved = held
        .lines()
        .next()
        .expect("line")
        .replace("\"split\":\"heldout\"", "\"split\":\"train\"");
    let train_path = t.0.join("train.jsonl");
    let train = fs::read_to_string(&train_path).expect("file");
    fs::write(&train_path, format!("{train}{moved}\n")).expect("move");
    let problems = verify(&t.0, &SPLIT).expect("verify");
    assert!(!problems.is_empty(), "a leak into train must be found");
}

#[test]
fn a_withheld_advisor_never_reaches_training_or_validation() {
    let settings = SplitSettings {
        withheld_advisor: Some("advisor-b".to_owned()),
        ..SPLIT
    };
    let all = all_examples();
    let t = Temp::new();
    write(&t.0, &all, &settings, &[], &BTreeMap::new(), "2026-11-20").expect("write");
    assert_eq!(
        verify(&t.0, &settings).expect("verify"),
        Vec::<String>::new()
    );
    for e in all
        .iter()
        .filter(|e| e.advisor.as_deref() == Some("advisor-b"))
    {
        assert_eq!(split_of(e, &settings), Split::UnseenAdvisor);
    }
    for name in ["train.jsonl", "validation.jsonl", "heldout.jsonl"] {
        let body = fs::read_to_string(t.0.join(name)).expect("file");
        assert!(!body.contains("\"advisor\":\"advisor-b\""), "{name}");
    }
    let unseen = fs::read_to_string(t.0.join("heldout-unseen-advisor.jsonl")).expect("file");
    assert!(unseen.lines().count() > 0 && unseen.lines().all(|l| l.contains("advisor-b")));
}

// -- text for ResearchLLM -------------------------------------------------------------------------------------

const GATE: GateSettings = GateSettings {
    min_support: 0.9,
    min_equivalence: 0.6,
    subject_overlap: 0.5,
    search_depth: 10,
    max_bytes: 100_000,
};
const C1: &str = "Aspirin reduces fever in adults.";

fn source(gate: &Gate, title: &str, id: &str, text: &str) {
    gate.submit_source(SourceProposal {
        title: title.into(),
        kind: "document".into(),
        identifier: id.into(),
        text: text.into(),
        command: None,
        inputs_sha256: None,
        cites: vec![],
        dataset: None,
        metadata: MetadataCheck::Verified("registry-fixture".into()),
        proposer: Proposer("advisor".into()),
    })
    .expect("io");
}

#[test]
fn training_text_comes_only_from_sources_and_verified_quotes() {
    let t = Temp::new();
    let gate = Gate::new(&t.0, GATE, Box::new(|| "2026-11-20".into()));
    source(&gate, "Paper", "doi:10.1/p", C1);
    source(
        &gate,
        "Gone",
        "doi:10.1/g",
        "A retracted finding about statins.",
    );
    assert!(
        gate.submit_claim(ClaimProposal {
            statement: C1.into(),
            source: Some("Paper".into()),
            quote: C1.into(),
            requested: Level::Sourced,
            evidence: vec![],
            proposer: Proposer("advisor".into()),
        })
        .expect("io")
        .is_accepted()
    );
    gate.retract_source("Gone", "retracted", Proposer("advisor".into()))
        .expect("retract");
    // a model-written Claim that bypassed the gate: no Source, an invented span
    fs::write(
        t.0.join("Claims").join("Invented claim.md"),
        "---\ntype: claim\nlevel: sourced\nsource_ref: \"[[Nothing]]\"\nspan_start: 0\nspan_end: 10\nspan_sha256: abc\ncreated: 2026-11-20\n---\nIbuprofen cures influenza.\n",
    )
    .expect("seed");
    let index = VaultIndex::build(&t.0, None).expect("index");
    let corpus = training_text(&index);
    let texts: Vec<&str> = corpus.items.iter().map(|i| i.text.trim()).collect();
    assert!(texts.contains(&C1));
    assert!(
        !texts
            .iter()
            .any(|x| x.contains("Ibuprofen") || x.contains("statins")),
        "{texts:?}"
    );
    let kinds: BTreeSet<&str> = corpus.items.iter().map(|i| i.kind).collect();
    assert_eq!(kinds, BTreeSet::from(["claim_quote", "source"]));
    // every claim quote is a span of an exported source: nothing the advisor wrote
    let sources: Vec<&str> = corpus
        .items
        .iter()
        .filter(|i| i.kind == "source")
        .map(|i| i.text.as_str())
        .collect();
    for q in corpus.items.iter().filter(|i| i.kind == "claim_quote") {
        assert!(sources.iter().any(|s| s.contains(&q.text)));
    }
    let reasons: BTreeMap<&str, &str> = corpus
        .left_out
        .iter()
        .map(|(t, r)| (t.as_str(), r.as_str()))
        .collect();
    assert!(reasons["Gone"].contains("retracted"));
    assert!(
        reasons["Invented claim"].contains("no usable source"),
        "{reasons:?}"
    );
}
