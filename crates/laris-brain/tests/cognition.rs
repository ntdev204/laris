//! The cognitive evaluation (T172, SR-K7): the harness of `examples/cognitive_eval.rs` runs on the scripted advisors of
//! `configs/cognitive-eval.json` and the report keeps its invariants. These are properties of the system under
//! scripted advisors, not claims about any model. Set `LARIS_COGNITION_REPORT` to write the report.

#[path = "../examples/cognitive_eval.rs"]
#[allow(dead_code)]
mod harness;

use std::sync::atomic::{AtomicU32, Ordering};

use serde_json::Value;

fn report() -> Value {
    // one file per call: the tests run in parallel and each removes its own report
    static N: AtomicU32 = AtomicU32::new(0);
    let out = std::env::temp_dir().join(format!(
        "laris-cognition-report-{}-{}.json",
        std::process::id(),
        N.fetch_add(1, Ordering::SeqCst)
    ));
    let config = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../configs/cognitive-eval.json"
    );
    harness::run(&[
        "--config".into(),
        config.into(),
        "--out".into(),
        out.to_string_lossy().into_owned(),
    ])
    .expect("the evaluation runs");
    let text = std::fs::read_to_string(&out).expect("report");
    if let Ok(keep) = std::env::var("LARIS_COGNITION_REPORT") {
        std::fs::copy(&out, keep).expect("copy the report");
    }
    let _ = std::fs::remove_file(&out);
    serde_json::from_str(&text).expect("json")
}

fn advisor<'a>(r: &'a Value, name: &str) -> &'a Value {
    r["per_advisor"]
        .as_array()
        .expect("advisors")
        .iter()
        .find(|a| a["advisor"] == name)
        .unwrap_or_else(|| panic!("no advisor {name}"))
}

#[test]
fn more_than_one_advisor_is_measured_and_the_report_is_not_a_qualification() {
    let r = report();
    assert!(r["advisors_measured"].as_array().expect("list").len() >= 2);
    assert_eq!(r["qualified"], false);
    assert!(
        r["read_this"]
            .to_string()
            .contains("ResearchLLM was not loaded")
    );
}

#[test]
fn the_brain_never_lets_an_unsupported_reply_reach_the_user_and_never_completes_falsely() {
    let r = report();
    for a in r["per_advisor"].as_array().expect("advisors") {
        let name = &a["advisor"];
        let loop_ = &a["unsupported_claim_pass_through"]["loop_brain_decides"];
        assert_eq!(loop_["reached_the_user"], 0, "{name}");
        assert_eq!(a["false_completion"]["brain_decides"], 0.0, "{name}");
        let abstention = &a["abstention_calibration"]["brain_decides"];
        assert_eq!(abstention["abstention_recall"], 1.0, "{name}");
        assert_eq!(abstention["abstention_precision"], 1.0, "{name}");
        assert_eq!(
            a["faithfulness"]["outside_set_check_problems_in_final_answers"], 0,
            "{name}"
        );
    }
}

#[test]
fn an_advisor_that_decides_lets_every_unsupported_reply_through() {
    let r = report();
    for name in [
        "hallucinating-scripted",
        "overconfident-scripted",
        "corrupting-scripted",
    ] {
        let a = advisor(&r, name);
        let loop_ = &a["unsupported_claim_pass_through"]["loop_advisor_decides"];
        assert_eq!(loop_["rate"], 1.0, "{name}");
        assert_eq!(a["false_completion"]["advisor_decides"], 1.0, "{name}");
    }
    // an honest advisor is safe either way: the comparison is about the others
    assert_eq!(
        advisor(&r, "faithful-scripted")["false_completion"]["advisor_decides"],
        0.0
    );
}

#[test]
fn the_gate_refuses_model_only_and_fabricated_claims_but_keeps_supported_ones() {
    let r = report();
    let gate = &advisor(&r, "hallucinating-scripted")["unsupported_claim_pass_through"]["gate"];
    assert_eq!(gate["unsupported_accepted"], 0, "{gate}");
    for a in r["per_advisor"].as_array().expect("advisors") {
        let g = &a["unsupported_claim_pass_through"]["gate"];
        assert!(
            g["supported_accept_rate"].is_null() || g["supported_accept_rate"] == 1.0,
            "{}",
            a["advisor"]
        );
    }
}

#[test]
fn a_faithful_reworded_answer_is_kept_and_a_flipped_or_changed_one_is_not() {
    let r = report();
    let faithful = advisor(&r, "faithful-scripted");
    assert_eq!(faithful["faithfulness"]["rate"], 1.0);
    let corrupting =
        &advisor(&r, "corrupting-scripted")["unsupported_claim_pass_through"]["rewording"];
    assert_eq!(corrupting["unfaithful_kept"], 0, "{corrupting}");
}

#[test]
fn pinned_constraints_survive_compaction_at_every_length() {
    let r = report();
    let by_turns = r["constraint_recall"]["by_turns"].as_array().expect("list");
    assert!(
        by_turns.iter().any(|t| t["compacted"] == true),
        "no length forced compaction"
    );
    assert!(by_turns.iter().all(|t| t["recall"] == 1.0), "{by_turns:?}");
}
