//! The held-out gates of the decision network (T171): the mechanics of the measurement on the scenario grid and an
//! untrained fixture network. No gate here says anything about a trained network; these tests show that a gate fails
//! when it should, that a missing measurement is not a pass and that a broken set is refused.

use laris_brain::dataset::{Example, scenario_examples};
use laris_brain::decide::{Act, RuleDecider, RuleSettings};
use laris_brain::gates::{
    Inputs, Limits, State, Status, evaluate, expected_calibration_error, states,
};
use laris_brain::network::{Network, NetworkChooser};
use laris_vault::brain::Level;

const RULES: RuleSettings = RuleSettings {
    required_level: Level::Sourced,
    min_coverage: 0.6,
    max_retrievals: 2,
    max_acquisitions: 2,
    max_advisor_asks: 3,
    max_repeats: 3,
};

fn limits() -> Limits {
    Limits {
        min_gain_points: 3.0,
        confidence_pct: 95.0,
        bootstrap_resamples: 200,
        bootstrap_seed: 171,
        max_unsupported_rate: 0.01,
        max_ece: 0.05,
        ece_bins: 10,
        min_abstain_recall: 0.90,
        max_overabstain_margin_points: 5.0,
        max_parity_diff: 1e-5,
        max_p95_ms: 10.0,
        latency_repeats: 1,
    }
}

fn fixture() -> NetworkChooser {
    let text = std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/fixtures/decision-net/net.json"
    ))
    .expect("fixture");
    NetworkChooser::new(
        Network::from_json(&text).expect("network"),
        RuleDecider::new(RULES),
    )
}

fn grid() -> Vec<State> {
    states(&scenario_examples(&RULES)).expect("states")
}

fn status(report: &laris_brain::gates::Report, id: &str) -> Status {
    report
        .gates
        .iter()
        .find(|g| g.id == id)
        .unwrap_or_else(|| panic!("no gate {id}"))
        .status
}

#[test]
fn the_grid_groups_into_one_state_per_scenario() {
    let all = grid();
    assert_eq!(all.len(), 4608);
    assert!(all.iter().all(|s| s.good.len() == s.candidates.len()));
}

#[test]
fn an_untrained_network_fails_the_accuracy_gate_and_the_rule_decider_is_the_baseline() {
    let all = grid();
    let mut chooser = fixture();
    let report = evaluate(
        &Inputs {
            heldout: &all,
            unseen_advisor: None,
            parity_max_diff: None,
        },
        &mut chooser,
        &RuleDecider::new(RULES),
        &limits(),
    );
    assert_eq!(report.gates.len(), 8);
    assert_eq!(status(&report, "N1"), Status::Fail);
    assert!(!report.all_pass());
    // always legal, whatever the weights
    assert_eq!(status(&report, "N8"), Status::Pass);
    let n1 = &report.gates[0].measured;
    assert!(
        n1["rule_accuracy"].as_f64().expect("rule accuracy") > 0.9,
        "the rule decider is the baseline: {n1}"
    );
}

#[test]
fn a_missing_measurement_is_not_a_pass() {
    let all = grid();
    let mut chooser = fixture();
    let report = evaluate(
        &Inputs {
            heldout: &all,
            unseen_advisor: None,
            parity_max_diff: None,
        },
        &mut chooser,
        &RuleDecider::new(RULES),
        &limits(),
    );
    assert_eq!(status(&report, "N5"), Status::NotVerified);
    assert_eq!(status(&report, "N6"), Status::NotVerified);
    let with = evaluate(
        &Inputs {
            heldout: &all,
            unseen_advisor: None,
            parity_max_diff: Some(1e-3),
        },
        &mut chooser,
        &RuleDecider::new(RULES),
        &limits(),
    );
    assert_eq!(status(&with, "N6"), Status::Fail);
    let within = evaluate(
        &Inputs {
            heldout: &all,
            unseen_advisor: None,
            parity_max_diff: Some(1e-12),
        },
        &mut chooser,
        &RuleDecider::new(RULES),
        &limits(),
    );
    assert_eq!(status(&within, "N6"), Status::Pass);
}

#[test]
fn a_network_that_only_repeats_the_rules_cannot_beat_them() {
    // threshold above every probability: every decision falls back to the rule decider
    let text = std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/tests/fixtures/decision-net/net.json"
    ))
    .expect("fixture");
    let mut v: serde_json::Value = serde_json::from_str(&text).expect("json");
    v["abstention"]["threshold"] = serde_json::json!(1.5);
    let network = Network::from_json(&v.to_string()).expect("network");
    let rules = RuleDecider::new(RULES);
    let mut chooser = NetworkChooser::new(network, rules);
    let all = grid();
    let report = evaluate(
        &Inputs {
            heldout: &all,
            unseen_advisor: None,
            parity_max_diff: Some(0.0),
        },
        &mut chooser,
        &rules,
        &limits(),
    );
    let n1 = &report.gates[0].measured;
    assert_eq!(n1["gain_points"].as_f64(), Some(0.0), "{n1}");
    assert_eq!(status(&report, "N1"), Status::Fail, "a tie is not a gain");
    // the same choices, so the same unsupported-answer rate and the same abstentions
    assert_eq!(status(&report, "N2"), status_of_rules(&report));
    assert_eq!(
        report.gates[3].measured["network_recall"],
        report.gates[3].measured["rule_recall"]
    );
}

fn status_of_rules(report: &laris_brain::gates::Report) -> Status {
    let m = &report.gates[1].measured;
    if m["network_answers"].as_u64() == Some(0) {
        Status::NotVerified
    } else if m["network_rate"].as_f64() <= Some(0.01) {
        Status::Pass
    } else {
        Status::Fail
    }
}

#[test]
fn the_unseen_advisor_split_is_measured_when_it_exists() {
    let all = grid();
    let mut chooser = fixture();
    let report = evaluate(
        &Inputs {
            heldout: &all,
            unseen_advisor: Some(&all[..200]),
            parity_max_diff: None,
        },
        &mut chooser,
        &RuleDecider::new(RULES),
        &limits(),
    );
    assert_ne!(status(&report, "N5"), Status::NotVerified);
}

#[test]
fn a_broken_group_is_refused() {
    let mut examples: Vec<Example> = scenario_examples(&RULES);
    // two examples of one group that disagree on the state
    let other = examples[examples.len() - 1].signals.clone();
    examples[0].signals = other;
    assert!(states(&examples).is_err());
    // a label that is missing for a candidate
    let mut fewer = scenario_examples(&RULES);
    fewer.remove(0);
    assert!(states(&fewer).is_err());
    // a label given twice
    let mut twice = scenario_examples(&RULES);
    let copy = twice[0].clone();
    twice.push(copy);
    assert!(states(&twice).is_err());
}

#[test]
fn calibration_error_is_zero_for_a_perfect_forecaster_and_large_for_a_wrong_one() {
    let perfect: Vec<(f64, bool)> = (0..100)
        .map(|i| (if i % 2 == 0 { 1.0 } else { 0.0 }, i % 2 == 0))
        .collect();
    assert!(expected_calibration_error(&perfect, 10) < 1e-12);
    let wrong: Vec<(f64, bool)> = (0..100).map(|_| (0.9, false)).collect();
    assert!((expected_calibration_error(&wrong, 10) - 0.9).abs() < 1e-12);
    // two bins, half right at 0.5: calibrated
    let half: Vec<(f64, bool)> = (0..100).map(|i| (0.5, i % 2 == 0)).collect();
    assert!(expected_calibration_error(&half, 10) < 1e-12);
    assert_eq!(Act::Answer.as_str(), "answer");
}
