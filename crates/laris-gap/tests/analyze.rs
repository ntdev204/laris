//! The gap rules, their filters, the ranking, the audit and the evaluation on a small hand-made corpus.

use laris_gap::analyze::{Found, analyze};
use laris_gap::audit::audit;
use laris_gap::config::{Settings, Topic};
use laris_gap::evaluate::{GoldItem, extraction};
use laris_gap::extract::{Paper, RawItem, Record};
use std::collections::BTreeMap;

const POLICY: &str = include_str!("../../../.laris/gap.toml");

const TOPIC: &str = r#"
id = "t"
title = "T"
question = "Q?"
[concepts.method]
"NMPC" = ["nmpc"]
"Hierarchical" = ["hierarchical"]
[concepts.setting]
"MCU" = ["microcontroller"]
"Car" = ["car"]
[concepts.issue]
"Robustness" = ["robust", "mismatch"]
"Swarm" = ["swarm"]
"Cost" = ["computational cost"]
[conflict]
negative = ["\\binfeasible\\b"]
positive = ["\\breal[- ]time\\b"]
"#;

fn item(text: &str, quote: &str) -> RawItem {
    RawItem {
        text: text.into(),
        quote: quote.into(),
    }
}

fn paper(id: &str, text: &str) -> Paper {
    Paper {
        id: id.into(),
        title: format!("Paper {id}"),
        origin: String::new(),
        year: Some(2024),
        read_by: "text_layer".into(),
        text: text.into(),
    }
}

fn corpus() -> (Vec<Paper>, BTreeMap<String, Result<Record, String>>) {
    let papers = vec![
        paper(
            "P1",
            "Abstract\nWe run NMPC on a microcontroller.\nConclusion\nOur guarantees hold only without model mismatch in the plant.\n",
        ),
        paper(
            "P2",
            "Abstract\nNMPC on a microcontroller in real time.\nLimitations\nThe controller is not robust to strong wind gusts at all.\n",
        ),
        paper(
            "P3",
            "Abstract\nA hierarchical controller for a car.\nConclusion\nOnline NMPC is infeasible on a car computer.\nIn future work we will study a swarm of many cars together.\n",
        ),
        paper("P4", "Abstract\nNMPC on a car.\n"),
    ];
    let mut records = BTreeMap::new();
    records.insert(
        "P1".into(),
        Ok(Record {
            problem: "NMPC on small hardware".into(),
            method: "NMPC".into(),
            setting: "microcontroller".into(),
            result: "runs at 100 Hz in real time".into(),
            limitations: vec![item(
                "valid without mismatch",
                "Our guarantees hold only without model mismatch",
            )],
            future_work: vec![],
        }),
    );
    records.insert(
        "P2".into(),
        Ok(Record {
            problem: "tracking".into(),
            method: "NMPC".into(),
            setting: "microcontroller".into(),
            result: "real-time tracking".into(),
            limitations: vec![item(
                "not robust to wind",
                "The controller is not robust to strong wind gusts",
            )],
            future_work: vec![],
        }),
    );
    records.insert(
        "P3".into(),
        Ok(Record {
            problem: "online NMPC is infeasible on a car computer".into(),
            method: "hierarchical MPC".into(),
            setting: "car".into(),
            result: "longer horizon".into(),
            limitations: vec![item(
                "NMPC infeasible",
                "Online NMPC is infeasible on a car computer",
            )],
            future_work: vec![item("swarm", "we will study a swarm of many cars")],
        }),
    );
    records.insert(
        "P4".into(),
        Ok(Record {
            problem: "driving".into(),
            method: "NMPC".into(),
            setting: "car".into(),
            result: "real time driving".into(),
            limitations: vec![item("made up", "this sentence is not in the paper at all")],
            future_work: vec![],
        }),
    );
    (papers, records)
}

#[test]
fn the_rules_their_filters_and_the_ranking() {
    let settings = Settings::from_toml(POLICY).unwrap();
    let topic = Topic::from_toml(TOPIC).unwrap();
    let (papers, records) = corpus();
    let a = analyze(&topic, &settings, &papers, &records);

    // quotations
    let found: Vec<Found> = a.items.iter().map(|i| i.found).collect();
    assert_eq!(a.counts.quotes_missing, 1, "{found:?}");
    assert_eq!(
        a.items.iter().find(|i| i.id == "P2-L1").unwrap().section,
        "limitations"
    );

    // G1: robustness is stated by P1 and P2, verified, addressed by nobody else
    let g1 = a
        .candidates
        .iter()
        .find(|c| c.rule == "G1" && c.concepts[0] == "Robustness")
        .unwrap();
    assert_eq!(g1.status, "kept", "{g1:?}");
    assert_eq!(g1.papers, vec!["P1", "P2"]);
    // swarm: one paper only
    let swarm = a
        .candidates
        .iter()
        .find(|c| c.rule == "G1" && c.concepts[0] == "Swarm")
        .unwrap();
    assert_eq!(swarm.reason, "g1_one_paper");

    // G2: P3 says NMPC is infeasible on a car; P4 runs NMPC in real time on a car (same setting): not explained.
    // P1 and P2 run it on a microcontroller: explained by (a).
    let open: Vec<_> = a.conflicts.iter().filter(|k| !k.explained).collect();
    assert_eq!(open.len(), 1, "{:?}", a.conflicts);
    assert_eq!(open[0].positive.paper, "P4");
    assert!(
        a.conflicts
            .iter()
            .any(|k| k.explained && k.explanation.starts_with("(a)"))
    );
    let g2 = a.candidates.iter().find(|c| c.rule == "G2").unwrap();
    assert_eq!(g2.status, "kept");

    // G3: Hierarchical (P3) x MCU (P1, P2): the groups share no issue, filtered
    let g3 = a
        .candidates
        .iter()
        .find(|c| c.rule == "G3" && c.concepts[0] == "Hierarchical")
        .unwrap();
    assert_eq!(g3.reason, "g3_no_common_issue");

    // G4: Hierarchical rests on P3 alone
    assert!(
        a.candidates
            .iter()
            .any(|c| c.rule == "G4" && c.papers == vec!["P3"] && c.status == "kept")
    );

    // ranking: s = w1·papers + w2·primary + w3·verified − w4·single
    let w = settings.weights;
    let r = a.ranking.iter().find(|r| r.candidate == g1.id).unwrap();
    assert_eq!(r.score, w.w1 * 2.0 + w.w2 + w.w3 * 2.0);
    assert_eq!(a.ranking[0].rank, 1);
    assert!(a.ranking.windows(2).all(|p| p[0].score >= p[1].score));
    let report = laris_gap::report::render(&a, "T");
    for section in [
        "## Paper register",
        "## What is known",
        "## Conflicts",
        "## Research gaps",
        "## Not read",
        "## Sources",
    ] {
        assert!(report.contains(section));
    }
}

#[test]
fn the_audit_counts_what_a_reader_cannot_check() {
    let settings = Settings::from_toml(POLICY).unwrap();
    let (papers, _) = corpus();
    let answer = "1. Robustness is open [P1], as \"The controller is not robust to strong wind gusts\" shows.\n\
2. No prior work has studied swarms of cars on embedded hardware.\n\
3. Among the papers read, no paper has studied swarms [P3].\n\
4. Smith et al. (2019) proved stability for every embedded controller ever built.\n\
5. Results in [P9] show \"a quotation that was never written down\".";
    let a = audit(answer, &papers, &settings);
    assert_eq!(a.counts.citations_nonexistent, 1, "{:?}", a.citations); // P9; Smith is unchecked
    assert_eq!(a.counts.citations_unchecked, 1);
    assert_eq!(a.counts.quotations_fabricated, 1);
    assert_eq!(a.counts.absence_claims, 2);
    assert_eq!(a.counts.absence_unscoped, 1, "{:#?}", a.claims);
    assert_eq!(a.counts.claims_uncited, 1, "{:#?}", a.claims);
}

#[test]
fn extraction_is_scored_item_by_item() {
    let settings = Settings::from_toml(POLICY).unwrap();
    let topic = Topic::from_toml(TOPIC).unwrap();
    let (papers, records) = corpus();
    let a = analyze(&topic, &settings, &papers, &records);
    let mut gold = BTreeMap::new();
    gold.insert(
        "P2".to_owned(),
        vec![
            GoldItem {
                id: "G1".into(),
                kind: "limitation".into(),
                text: "not robust to wind".into(),
                quote: "The controller is not robust to strong wind gusts at all".into(),
                section: "limitations".into(),
            },
            GoldItem {
                id: "G2".into(),
                kind: "future_work".into(),
                text: "test outdoors".into(),
                quote: "we will test outdoors next year in the field".into(),
                section: "conclusion".into(),
            },
        ],
    );
    let e = extraction(&a, &gold, 0.5);
    assert_eq!(e.total.system, 1);
    assert_eq!(e.total.gold, 2);
    assert_eq!(e.total.matched, 1);
    assert_eq!(e.total.precision, 1.0);
    assert_eq!(e.total.recall, 0.5);
    assert_eq!(e.missed, vec!["P2:G2"]);
}

#[test]
fn a_closed_book_answer_names_its_sources_by_title() {
    let settings = Settings::from_toml(POLICY).unwrap();
    let (papers, _) = corpus();
    let answer = "### 1. Gap\n**Why it is a gap:** solvers are slow.\n**Supporting Paper:**\n*   **Authors:** Rawlings, J. B.\n*   **Year:** 2009\n*   **Title:** *Model Predictive Control: Theory, Computation, and Design*\n*   **Quotation:** \"The computational burden of solving these problems is a major limiting factor\"\n\nSee also *Paper P2*.";
    let a = audit(answer, &papers, &settings);
    let titles: Vec<_> = a
        .citations
        .iter()
        .filter(|c| c.kind == "reference")
        .collect();
    assert_eq!(titles.len(), 1, "{titles:?}");
    assert!(titles[0].text.starts_with("Model Predictive Control"));
    assert!(titles[0].resolved.is_none());
    assert_eq!(a.counts.quotations_fabricated, 1);
}
