//! The rule decider v0 (T167, ADR-024 section 7): the scenario suite, legality and traceability. A placeholder advisor
//! stands for ResearchLLM; nothing here says anything about a model's quality (the foundation model is NOT QUALIFIED).

use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};

use laris_brain::answer::{AnswerSettings, compose};
use laris_brain::decide::{
    Act, CallState, Choice, Chooser, Limit, RULES, RuleDecider, RuleSettings, Signals, hard_limit,
    legal,
};
use laris_brain::{
    ClaimProposal, Decision, Gate, GateSettings, MetadataCheck, Proposer, SourceProposal,
};
use laris_vault::VaultIndex;
use laris_vault::brain::Level;

struct Temp(PathBuf);

impl Temp {
    fn new() -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-decide-{}-{}",
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
};
const RULES_CFG: RuleSettings = RuleSettings {
    required_level: Level::Sourced,
    min_coverage: 0.6,
    max_retrievals: 2,
    max_acquisitions: 2,
    max_advisor_asks: 3,
    max_repeats: 3,
};

const C1: &str = "Aspirin reduces fever in adults.";
const Q1: &str = "does aspirin reduce fever in adults";

fn who() -> Proposer {
    Proposer("placeholder-advisor".into())
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
        proposer: who(),
    }
}

fn claim(gate: &Gate, source: Option<&str>, statement: &str, quote: &str) -> Decision {
    gate.submit_claim(ClaimProposal {
        statement: statement.into(),
        source: source.map(str::to_owned),
        quote: quote.into(),
        requested: Level::Sourced,
        evidence: vec![],
        solver: None,
        proposer: who(),
    })
    .expect("io")
}

fn brain_with(statements: &[&str]) -> (Temp, Gate) {
    let t = Temp::new();
    let gate = Gate::new(&t.0, GATE, Box::new(|| "2026-11-20".into()));
    let text = statements.join("\n\n");
    assert!(
        gate.submit_source(source("Paper", "doi:10.1/p", &text))
            .expect("io")
            .is_accepted()
    );
    for s in statements {
        assert!(claim(&gate, Some("Paper"), s, s).is_accepted());
    }
    (t, gate)
}

fn index(t: &Temp) -> VaultIndex {
    VaultIndex::build(&t.0, None).expect("index")
}

fn base() -> Signals {
    let mut s = Signals::empty(8, 120.0);
    s.acquisition_allowed = true;
    s
}

fn decide(s: &Signals) -> Choice {
    RuleDecider::new(RULES_CFG).decide(s)
}

fn assert_traceable(d: &Choice) {
    assert!(RULES.contains(&d.rule.as_str()), "unknown rule {}", d.rule);
    assert!(!d.reason.is_empty());
    assert!(d.candidates.contains(&d.act), "{:?} not legal", d.act);
    let json = d.to_json();
    assert_eq!(json["action"], d.act.as_str());
    assert_eq!(json["rule"], d.rule.as_str());
    assert_eq!(json["signals"], d.signals.to_json());
}

#[test]
fn stop_when_a_hard_limit_holds() {
    for (name, change, limit) in [
        (
            "budget",
            (|s: &mut Signals| s.budget_left = 0.0) as fn(&mut Signals),
            Limit::Budget,
        ),
        ("time", |s| s.time_left_seconds = 0.0, Limit::Time),
        ("steps", |s| s.steps_left = 0, Limit::Steps),
        ("cycle", |s| s.repeats = 3, Limit::Cycle),
    ] {
        let mut s = base();
        // even a fully covered question stops: the limit is the first rule
        s.accepted = 3;
        s.coverage = 1.0;
        s.best_level = Some(Level::Verified);
        change(&mut s);
        let d = decide(&s);
        assert_eq!((d.act, d.limit), (Act::Stop, Some(limit)), "{name}");
        assert_eq!(d.rule, "R1-limit");
        assert_traceable(&d);
    }
}

#[test]
fn ask_the_user_when_a_required_slot_is_missing() {
    let mut s = base();
    s.missing_slot = Some("drug".into());
    let d = decide(&s);
    assert_eq!((d.act, d.rule.as_str()), (Act::AskUser, "R2-missing-slot"));
    assert!(d.reason.contains("drug"));
    assert_traceable(&d);
}

#[test]
fn abstain_when_nothing_supports_an_answer_and_nothing_more_can_be_done() {
    let (t, _gate) = brain_with(&[C1]);
    let s = Signals {
        acquisition_allowed: false,
        advisor_asks: 3,
        ..base()
    }
    .measure(
        &index(&t),
        "how tall is the moon landing",
        &ANSWER,
        Level::Sourced,
    );
    assert_eq!(s.accepted, 0);
    let d = decide(&s);
    assert_eq!((d.act, d.rule.as_str()), (Act::Abstain, "R6-abstain"));
    assert!(!d.candidates.contains(&Act::Answer));
    assert_traceable(&d);
    // the composer abstains on the same question: the two agree
    assert!(compose(&index(&t), "how tall is the moon landing", &ANSWER).abstained());
}

#[test]
fn answer_when_accepted_claims_cover_the_question() {
    let (t, _gate) = brain_with(&[C1]);
    let s = base().measure(&index(&t), Q1, &ANSWER, Level::Sourced);
    assert!(s.coverage >= RULES_CFG.min_coverage, "{}", s.coverage);
    let d = decide(&s);
    assert_eq!((d.act, d.rule.as_str()), (Act::Answer, "R3-covered"));
    assert_traceable(&d);
    // a required level the claim does not hold is not covered
    let s = base().measure(&index(&t), Q1, &ANSWER, Level::Corroborated);
    assert_eq!(s.below_required, 1);
    let strict = RuleDecider::new(RuleSettings {
        required_level: Level::Corroborated,
        ..RULES_CFG
    });
    let d = strict.decide(&s);
    assert_eq!((d.act, d.rule.as_str()), (Act::Verify, "R4-verify"));
}

#[test]
fn verify_before_answer_when_a_candidate_is_pending() {
    let mut s = base();
    s.pending_candidates = 1;
    let d = decide(&s);
    assert_eq!((d.act, d.rule.as_str()), (Act::Verify, "R4-verify"));
    assert_traceable(&d);
    // once the candidate is verified and accepted, the answer follows
    let (t, _gate) = brain_with(&[C1]);
    let s = base().measure(&index(&t), Q1, &ANSWER, Level::Sourced);
    assert_eq!(decide(&s).act, Act::Answer);
}

#[test]
fn an_open_conflict_is_presented_not_hidden() {
    let (t, gate) = brain_with(&[C1]);
    gate.submit_source(source(
        "Paper C",
        "doi:10.1/c",
        "Aspirin does not reduce fever in adults.",
    ))
    .expect("io");
    assert!(
        claim(
            &gate,
            Some("Paper C"),
            "Aspirin does not reduce fever in adults.",
            "Aspirin does not reduce fever in adults."
        )
        .is_accepted()
    );
    let s = base().measure(&index(&t), Q1, &ANSWER, Level::Sourced);
    assert_eq!(s.open_conflicts, 1);
    let d = decide(&s);
    assert_eq!(
        (d.act, d.rule.as_str()),
        (Act::Answer, "R3-covered-conflict")
    );
    assert!(d.reason.contains("presented"));
    // and the answer it leads to states the conflict
    let answer = compose(&index(&t), Q1, &ANSWER);
    assert!(
        answer
            .sentences
            .iter()
            .any(|x| x.body.starts_with("The sources disagree:"))
    );
}

#[test]
fn a_model_only_claim_is_refused_and_never_supports_an_answer() {
    let (t, gate) = brain_with(&[C1]);
    // the advisor proposes a statement with no Source: the gate refuses and nothing is written
    let refused = claim(
        &gate,
        None,
        "Ibuprofen cures influenza.",
        "Ibuprofen cures influenza.",
    );
    assert!(!refused.is_accepted());
    let s = base().measure(
        &index(&t),
        "does ibuprofen cure influenza",
        &ANSWER,
        Level::Sourced,
    );
    assert_eq!((s.accepted, s.coverage), (0, 0.0));
    let d = decide(&s);
    assert_ne!(d.act, Act::Answer);
    assert!(!d.candidates.contains(&Act::Answer));
    assert_traceable(&d);
}

#[test]
fn acquire_then_retrieve_then_ask_the_advisor_when_coverage_is_missing() {
    let mut s = base();
    let d = decide(&s);
    assert_eq!((d.act, d.rule.as_str()), (Act::Acquire, "R5-acquire"));
    // a source was stored: read it before anything else
    s.acquisitions = 1;
    s.fresh_since_retrieve = true;
    let d = decide(&s);
    assert_eq!((d.act, d.rule.as_str()), (Act::Retrieve, "R5-retrieve-new"));
    // acquisition spent: the advisor proposes, its call runs only if legal
    s.fresh_since_retrieve = false;
    s.acquisitions = 2;
    assert_eq!(decide(&s).act, Act::AskAdvisor);
    s.call = CallState::Legal;
    assert_eq!(decide(&s).act, Act::RunTool);
    // a call the policy refuses is never run
    s.call = CallState::Refused;
    let d = decide(&s);
    assert_eq!(d.act, Act::AskAdvisor);
    assert!(!d.candidates.contains(&Act::RunTool));
}

#[test]
fn every_decision_over_a_grid_of_signals_is_legal_deterministic_and_traceable() {
    let decider = RuleDecider::new(RULES_CFG);
    let mut seen = std::collections::BTreeSet::new();
    let mut count = 0;
    for missing in [None, Some("x".to_string())] {
        for coverage in [0.0, 0.5, 0.6, 1.0] {
            for (accepted, best) in [
                (0, None),
                (1, Some(Level::Sourced)),
                (2, Some(Level::Verified)),
            ] {
                for below in [0, 1] {
                    for pending in [0, 1] {
                        for conflicts in [0, 2] {
                            for acq in [false, true] {
                                for asks in [0, 3] {
                                    for call in
                                        [CallState::None, CallState::Legal, CallState::Refused]
                                    {
                                        for (steps, repeats) in [(5, 0), (0, 0), (5, 3)] {
                                            for fresh in [false, true] {
                                                let mut s = base();
                                                s.missing_slot = missing.clone();
                                                s.coverage = coverage;
                                                s.accepted = accepted;
                                                s.best_level = best;
                                                s.below_required = below;
                                                s.pending_candidates = pending;
                                                s.open_conflicts = conflicts;
                                                s.acquisition_allowed = acq;
                                                s.advisor_asks = asks;
                                                s.call = call;
                                                s.steps_left = steps;
                                                s.repeats = repeats;
                                                s.fresh_since_retrieve = fresh;
                                                let d = decider.decide(&s);
                                                assert_eq!(d, decider.decide(&s));
                                                assert_traceable(&d);
                                                assert_eq!(d.candidates, legal(&s, &RULES_CFG));
                                                if d.act == Act::Stop {
                                                    assert!(hard_limit(&s, &RULES_CFG).is_some());
                                                }
                                                seen.insert(d.rule.clone());
                                                count += 1;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    assert!(count > 10_000);
    // every rule fires somewhere on the grid
    for rule in RULES {
        assert!(seen.contains(rule), "rule {rule} never fired");
    }
}

#[test]
fn the_decider_is_a_chooser_and_keeps_no_state() {
    let mut a = RuleDecider::new(RULES_CFG);
    let s = base();
    assert_eq!(a.choose(&s), a.choose(&s));
    assert_eq!(Act::parse("verify"), Some(Act::Verify));
    assert_eq!(Act::parse("improvise"), None);
    for act in Act::ALL {
        assert_eq!(Act::parse(act.as_str()), Some(act));
    }
}
