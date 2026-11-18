//! The evidence gate: fabricated citation, missing span, unsupported claim, absence rule, valid answers unchanged
//! (SR-H7; SEC-EVD tests of the threat model, collected by T154).

use laris_evidence::{Evidence, FindingKind, Gate, Target, citation};
use laris_protocol::LarisMeta;
use serde_json::json;

const TOOL_TEXT: &str = "\
Evidence (2 hits):
- [smith2020.pdf #1] Results: Compound X reduced tumour volume by 40% in mice after 14 days of treatment.
- [lee2021.pdf #2] Methods: The cohort had 120 participants, and attrition was
  below five percent over the study period.
";

fn evidence() -> Evidence {
    let mut e = Evidence::new();
    assert_eq!(e.absorb_text(TOOL_TEXT), 2);
    e
}

fn kinds(answer: &str, e: &Evidence) -> Vec<FindingKind> {
    Gate::new()
        .check(answer, e)
        .findings
        .iter()
        .map(|f| f.kind)
        .collect()
}

#[test]
fn a_valid_answer_comes_back_unchanged() {
    let answer = "Compound X reduced tumour volume by 40% in mice [smith2020.pdf #1]. \
        The cohort had 120 participants [lee2021.pdf #2].\n\n\
        Assumptions: the two studies measure comparable outcomes.\n\
        Sources: smith2020.pdf, lee2021.pdf\n";
    let verdict = Gate::new().check(answer, &evidence());
    assert!(verdict.is_clean(), "{:?}", verdict.findings);
    assert_eq!(verdict.text, answer);
}

#[test]
fn a_valid_quote_passes_after_folding() {
    let answer = "The paper reports \u{201C}reduced tumour volume by 40%\u{201D} [smith2020.pdf #1]. \
        Attrition was \"below five percent over the study period\" [lee2021.pdf #2].";
    assert_eq!(Gate::new().check(answer, &evidence()).text, answer);
    // An ellipsis stands for text left out.
    let answer = "It says \"Compound X reduced ... after 14 days\" [smith2020.pdf #1].";
    assert!(Gate::new().check(answer, &evidence()).is_clean());
}

#[test]
fn a_fabricated_citation_is_caught_and_marked() {
    let answer = "Compound X cured the disease in humans [smith2020.pdf #9].";
    let verdict = Gate::new().check(answer, &evidence());
    assert_eq!(verdict.findings.len(), 1);
    assert_eq!(verdict.findings[0].kind, FindingKind::FabricatedCitation);
    assert_eq!(verdict.findings[0].text, "[smith2020.pdf #9]");
    assert!(verdict.text.starts_with(
        "Compound X cured the disease in humans [smith2020.pdf #9] [citation not found"
    ));
    // A source nobody retrieved, and any citation when nothing was retrieved.
    assert_eq!(
        kinds("It is known [ghost.pdf #1].", &evidence()),
        [FindingKind::FabricatedCitation]
    );
    assert_eq!(
        kinds("It is known [smith2020.pdf #1].", &Evidence::new()),
        [FindingKind::FabricatedCitation]
    );
}

#[test]
fn a_missing_span_is_caught() {
    let answer = "The paper states \"the treatment cured every mouse\" [smith2020.pdf #1].";
    let verdict = Gate::new().check(answer, &evidence());
    assert_eq!(verdict.findings.len(), 1);
    assert_eq!(verdict.findings[0].kind, FindingKind::SpanMissing);
    assert!(
        verdict
            .text
            .contains("[quote not found in the cited evidence]")
    );
    // The quote is in another hit: still missing from the one cited.
    let answer = "It says \"The cohort had 120 participants\" [smith2020.pdf #1].";
    assert_eq!(kinds(answer, &evidence()), [FindingKind::SpanMissing]);
}

#[test]
fn an_unsupported_claim_is_caught_and_marked() {
    let answer = "Compound X reduced tumour volume by 40% [smith2020.pdf #1]. \
        It will certainly work in humans within five years.";
    let verdict = Gate::new().check(answer, &evidence());
    assert_eq!(verdict.findings.len(), 1);
    assert_eq!(verdict.findings[0].kind, FindingKind::UnsupportedStatement);
    assert_eq!(
        verdict.findings[0].text,
        "It will certainly work in humans within five years."
    );
    assert!(
        verdict
            .text
            .ends_with("five years. [unsupported: no citation, not marked as assumed]")
    );
}

#[test]
fn assumed_or_speculative_statements_are_not_flagged() {
    let answer = "Compound X reduced tumour volume by 40% [smith2020.pdf #1].\n\
        Speculative: it may also help in other cancers of the same family.\n\
        This is an assumption that the dose scales to humans.\n\
        Giả thuyết: liều này có thể áp dụng cho người với kết quả tương tự.";
    assert!(Gate::new().check(answer, &evidence()).is_clean());
}

#[test]
fn chat_without_evidence_is_left_alone() {
    let answer = "Binary search halves the range at each step until the value is found.";
    assert!(Gate::new().check(answer, &Evidence::new()).is_clean());
    // Held to the research rules on request.
    assert_eq!(
        Gate::strict()
            .check(answer, &Evidence::new())
            .findings
            .iter()
            .map(|f| f.kind)
            .collect::<Vec<_>>(),
        [FindingKind::UnsupportedStatement]
    );
}

#[test]
fn absence_of_a_hit_is_not_evidence_of_absence() {
    let e = evidence();
    assert_eq!(
        kinds(
            "There is no research on compound X in children, so this is a gap.",
            &e
        ),
        [FindingKind::AbsenceClaim]
    );
    assert_eq!(
        kinds(
            "The literature has never been explored for this compound.",
            &e
        ),
        [FindingKind::AbsenceClaim]
    );
    assert_eq!(
        kinds("Không có nghiên cứu nào về hợp chất này ở trẻ em.", &e),
        [FindingKind::AbsenceClaim]
    );
    // Stating what was searched makes it a report, not a conclusion.
    let scoped = "In the corpus I searched, there is no study of compound X in children.";
    assert!(Gate::new().check(scoped, &e).is_clean());
    let scoped =
        "The retrieved passages contain no evidence on dosage in children [smith2020.pdf #1].";
    assert!(Gate::new().check(scoped, &e).is_clean());
    let verdict = Gate::new().check("There is no evidence for this anywhere.", &e);
    assert!(
        verdict
            .text
            .contains("[absence of a hit is not evidence of absence")
    );
}

#[test]
fn brain_citations_are_checked_against_larismeta() {
    let meta = LarisMeta {
        brain: vec!["Dose Escalation Basics".into()],
        ..LarisMeta::default()
    };
    let e = Evidence::new().with_brain(&meta);
    assert!(
        Gate::new()
            .check(
                "Start low and escalate [brain: dose escalation basics].",
                &e
            )
            .is_clean()
    );
    assert_eq!(
        kinds("Start low and escalate [brain: Secret Notes].", &e),
        [FindingKind::FabricatedCitation]
    );
    assert_eq!(
        kinds(
            "Start low and escalate [brain: Dose Escalation Basics].",
            &Evidence::new()
        ),
        [FindingKind::FabricatedCitation]
    );
}

#[test]
fn json_tool_results_are_read() {
    let mut e = Evidence::new();
    let result = json!({"hits": [
        {"source": "smith2020.pdf", "rank": 1, "title": "Results", "text": "Compound X reduced tumour volume by 40%."},
        {"source": "lee2021.pdf", "rank": 2, "excerpt": "The cohort had 120 participants."}
    ], "note": "2 hits"});
    assert_eq!(e.absorb_json(&result), 2);
    assert!(
        Gate::new()
            .check(
                "Volume fell by \"tumour volume by 40%\" [smith2020.pdf #1].",
                &e
            )
            .is_clean()
    );
    assert_eq!(e.hits().len(), 2);
    // The same hit twice is kept once.
    e.absorb_json(&result);
    assert_eq!(e.hits().len(), 2);
}

#[test]
fn the_parser_reads_citations_and_their_quotes() {
    let found = citation::parse(
        "A \u{201C}quoted span here\u{201D} [Smith et al. 2020 #3]. See [brain: Hub] and [link](http://x.y#z).",
    );
    assert_eq!(found.len(), 2);
    assert_eq!(
        found[0].target,
        Target::Workspace {
            source: "Smith et al. 2020".into(),
            rank: 3
        }
    );
    assert_eq!(found[0].quote.as_deref(), Some("quoted span here"));
    assert_eq!(
        found[1].target,
        Target::Brain {
            title: "Hub".into()
        }
    );
    assert_eq!(found[1].quote, None);
}

#[test]
fn code_is_not_read() {
    let answer = "Use this form:\n```\n[ghost.pdf #1] is how you cite, and no evidence exists here at all.\n```\nInline `[ghost.pdf #2]` too.";
    assert!(Gate::new().check(answer, &evidence()).is_clean());
}

#[test]
fn a_full_stop_inside_a_citation_or_abbreviation_does_not_split() {
    let answer = "Compound X reduced volume, e.g. by 40% in mice [Smith et al. 2020 #1]. Lee et al. found attrition below five percent [lee2021.pdf #2].";
    let mut e = Evidence::new();
    e.add(laris_evidence::Hit {
        source: "Smith et al. 2020".into(),
        rank: 1,
        title: String::new(),
        text: "x".into(),
    });
    e.absorb_text(TOOL_TEXT);
    assert!(
        Gate::new().check(answer, &e).is_clean(),
        "{:?}",
        Gate::new().check(answer, &e).findings
    );
}

#[test]
fn headings_tables_questions_and_closing_blocks_are_not_statements() {
    let answer = "## Findings on the dose response\n\
        | dose | effect |\n| --- | --- |\n| 1 | 40% |\n\n\
        Compound X reduced tumour volume by 40% [smith2020.pdf #1].\n\n\
        Would you like me to look for studies on children?\n\n\
        Uncertainties:\n\
        - the studies used different animal strains and different follow-up times\n\
        Next step: search for trials in humans with a longer follow-up period.\n";
    let verdict = Gate::new().check(answer, &evidence());
    assert!(verdict.is_clean(), "{:?}", verdict.findings);
}

#[test]
fn several_findings_are_marked_in_place_and_in_order() {
    let answer = "Compound X is safe for everyone without exception. It cured mice [ghost.pdf #1]. There is no research on other treatments.";
    let verdict = Gate::new().check(answer, &evidence());
    let got: Vec<_> = verdict.findings.iter().map(|f| f.kind).collect();
    assert_eq!(
        got,
        [
            FindingKind::UnsupportedStatement,
            FindingKind::FabricatedCitation,
            FindingKind::AbsenceClaim
        ]
    );
    let first = verdict.text.find("[unsupported").unwrap();
    let second = verdict.text.find("[citation not found").unwrap();
    let third = verdict.text.find("[absence of a hit").unwrap();
    assert!(first < second && second < third);
    // Everything but the marks is the original.
    let stripped = verdict
        .text
        .replace(" [unsupported: no citation, not marked as assumed]", "")
        .replace(" [citation not found in the evidence]", "")
        .replace(
            " [absence of a hit is not evidence of absence: state what was searched]",
            "",
        );
    assert_eq!(stripped, answer);
}
