//! Inference of the decision network (T169): parity with the Python reference on fixtures (gate N6), refusal of a
//! malformed file, and the safety properties of the chooser (gate N8): only legal candidates, rule-decider fallback below
//! the threshold. The fixture network has seeded random weights and was never trained: these tests prove the mechanics
//! and say nothing about the quality of its decisions.

use laris_brain::dataset::scenario_examples;
use laris_brain::decide::{Act, Chooser, RuleDecider, RuleSettings, Signals, legal};
use laris_brain::network::{FEATURE_NAMES, Network, NetworkChooser, features};
use laris_vault::brain::Level;
use serde_json::Value;

const NET: &str = include_str!("fixtures/decision-net/net.json");
const CASES: &str = include_str!("fixtures/decision-net/cases.json");
const RULES: RuleSettings = RuleSettings {
    required_level: Level::Sourced,
    min_coverage: 0.6,
    max_retrievals: 2,
    max_acquisitions: 2,
    max_advisor_asks: 3,
    max_repeats: 3,
};

fn net() -> Network {
    Network::from_json(NET).expect("fixture net")
}

#[test]
fn rust_inference_matches_the_python_reference_to_1e_5() {
    let net = net();
    let cases: Value = serde_json::from_str(CASES).expect("cases");
    let cases = cases["cases"].as_array().expect("list");
    assert_eq!(cases.len(), 40);
    let mut worst = 0.0f64;
    let mut checked = 0;
    for case in cases {
        let signals = Signals::from_json(&case["signals"]).expect("signals");
        let candidates: Vec<Act> = case["candidates"]
            .as_array()
            .expect("candidates")
            .iter()
            .map(|a| Act::parse(a.as_str().expect("name")).expect("action"))
            .collect();
        let mut best: Option<(Act, f64)> = None;
        for act in &candidates {
            let x = features(&signals, *act, candidates.len());
            let name = act.as_str();
            let logit = net.logit(&x);
            let p = net.probability(&x);
            worst = worst
                .max((logit - case["logits"][name].as_f64().expect("logit")).abs())
                .max((p - case["probabilities"][name].as_f64().expect("p")).abs());
            if best.is_none_or(|(_, q)| p > q) {
                best = Some((*act, p));
            }
            checked += 1;
        }
        let (act, confidence) = best.expect("a candidate");
        assert_eq!(act.as_str(), case["chosen"].as_str().expect("chosen"));
        assert!((confidence - case["confidence"].as_f64().expect("c")).abs() <= 1e-5);
    }
    assert!(checked > 100);
    println!("max absolute difference {worst:e} over {checked} scores");
    assert!(worst <= 1e-5, "max absolute difference {worst}");
}

#[test]
fn the_feature_names_are_the_ones_python_exports() {
    let v: Value = serde_json::from_str(NET).expect("net");
    let names: Vec<&str> = v["features"]
        .as_array()
        .expect("names")
        .iter()
        .filter_map(Value::as_str)
        .collect();
    assert_eq!(names, FEATURE_NAMES);
    assert_eq!(net().parameters(), 2273);
}

#[test]
fn a_malformed_network_is_refused() {
    let bad = |from: &str, to: &str| {
        assert!(NET.contains(from), "{from} is not in the fixture");
        Network::from_json(&NET.replacen(from, to, 1)).expect_err(to)
    };
    bad("\"version\":1", "\"version\":2");
    bad("\"candidate_stop\"", "\"candidate_halt\"");
    bad("\"activation\":\"relu\"", "\"activation\":\"gelu\"");
    bad("\"temperature\":1.7", "\"temperature\":0.0");
    bad("\"threshold\":0.55", "\"threshold\":-1.0");
    bad("\"bias\":[", "\"bias\":[1.0,");
    assert!(Network::from_json("not json").is_err());
    assert!(Network::from_json("{}").is_err());
}

/// Every distinct state of the scenario grid.
fn states() -> Vec<Signals> {
    let mut seen = std::collections::BTreeSet::new();
    scenario_examples(&RULES)
        .into_iter()
        .filter(|e| seen.insert(e.group.clone()))
        .map(|e| e.signals)
        .collect()
}

fn chooser(threshold: &str) -> NetworkChooser {
    let text = NET.replacen(
        "\"threshold\":0.55",
        &format!("\"threshold\":{threshold}"),
        1,
    );
    NetworkChooser::new(
        Network::from_json(&text).expect("net"),
        RuleDecider::new(RULES),
    )
}

#[test]
fn the_chooser_only_ever_picks_a_legal_candidate() {
    let states = states();
    assert!(states.len() > 4_000);
    for threshold in ["0.0", "0.55", "1.5"] {
        let mut chooser = chooser(threshold);
        for s in &states {
            let c = chooser.choose(s);
            assert!(c.candidates.contains(&c.act), "{:?}", c.act);
            assert_eq!(c.candidates, legal(s, &RULES));
            assert!(c.confidence.is_some());
            assert_eq!(c, chooser.choose(s), "deterministic");
        }
    }
}

#[test]
fn below_the_threshold_the_rule_decider_decides_and_both_are_recorded() {
    let states = states();
    let rules = RuleDecider::new(RULES);
    // threshold above any probability: every decision falls back
    let mut always = chooser("1.5");
    for s in &states {
        let c = always.choose(s);
        let cautious = rules.decide(s);
        assert_eq!((c.act, c.rule.as_str()), (cautious.act, "fallback"));
        assert!(c.reason.contains("rule decider") && c.reason.contains(&cautious.rule));
        assert!(c.reason.contains("network chose"));
        let json = c.to_json();
        assert_eq!(json["rule"], "fallback");
        assert!(json["confidence"].is_number());
    }
    // threshold zero: the network always decides, and says so
    let mut never = chooser("0.0");
    let mut differs = 0;
    for s in &states {
        let c = never.choose(s);
        assert_eq!(c.rule, "network");
        assert!(c.confidence.expect("confidence") >= 0.0);
        differs += usize::from(c.act != rules.decide(s).act);
    }
    // a random network disagrees with the rules often: the fallback is doing something
    assert!(differs > 0);
}
