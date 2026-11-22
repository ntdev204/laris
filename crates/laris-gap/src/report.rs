//! Step 5: the report, with the fixed sections of the research-gap workflow. It is written from the analysis alone,
//! so every sentence in it can be traced to a candidate, an item or a field.

use crate::analyze::Analysis;

fn esc(text: &str) -> String {
    text.replace('|', "\\|").replace('\n', " ")
}

/// The report in Markdown.
pub fn render(a: &Analysis, topic_title: &str) -> String {
    let mut out = format!("# Research gaps: {topic_title}\n\n");
    out.push_str(&format!(
        "Papers given: {}; records parsed: {}. Every gap below is a gap among the papers read, not a claim about the whole literature.\n\n",
        a.counts.papers, a.counts.papers_parsed
    ));
    out.push_str("## Paper register\n\n| Id | Title | Year | Read by | Sections found |\n|---|---|---|---|---|\n");
    for p in &a.papers {
        out.push_str(&format!(
            "| {} | {} | {} | {} | {} |\n",
            p.id,
            esc(&p.title),
            p.year.map_or("?".into(), |y| y.to_string()),
            p.read_by,
            p.sections.join(", ")
        ));
    }
    out.push_str("\n## What is known\n\n");
    for facet in ["method", "setting", "issue"] {
        if let Some(m) = a.concepts.get(facet) {
            out.push_str(&format!("**{facet}**\n\n"));
            for (c, ps) in m {
                out.push_str(&format!("- {c} ({})\n", ps.join(", ")));
            }
            out.push('\n');
        }
    }
    out.push_str("## Conflicts\n\n");
    if a.conflicts.is_empty() {
        out.push_str("No pair of claims of rule G2 was found.\n\n");
    }
    // the paper's own words between quotation marks, the model's record as a paraphrase
    let said = |c: &crate::analyze::Claim| {
        if c.via.ends_with(":abstract") || c.via.ends_with(":introduction") {
            format!("{} [{}]: \"{}\"", c.paper, c.via, esc(&c.sentence))
        } else {
            format!("{} [{}, paraphrase]: {}", c.paper, c.via, esc(&c.sentence))
        }
    };
    for k in &a.conflicts {
        out.push_str(&format!(
            "- {} — {} — vs {} — {}\n",
            k.method,
            said(&k.negative),
            said(&k.positive),
            k.explanation
        ));
    }
    out.push_str("\n## Research gaps\n\n");
    if a.ranking.is_empty() {
        out.push_str("The papers read support no gap under rules G1–G4.\n\n");
    }
    for r in &a.ranking {
        let Some(c) = a.candidates.iter().find(|c| c.id == r.candidate) else {
            continue;
        };
        out.push_str(&format!(
            "### {} ({}, score {})\n\n{}\n\n",
            r.gap, c.rule, r.score, c.statement
        ));
        for e in c.evidence.iter().take(8) {
            // only a quotation found in the paper stands between quotation marks
            out.push_str(&if e.verified {
                format!(
                    "- {} [{}; {}] ✓ found in the paper: \"{}\"\n",
                    e.paper,
                    e.via,
                    e.section,
                    esc(&e.text)
                )
            } else {
                format!(
                    "- {} [{}; {}] paraphrase, no verified quotation: {}\n",
                    e.paper,
                    e.via,
                    e.section,
                    esc(&e.text)
                )
            });
        }
        out.push('\n');
    }
    out.push_str("## Not read\n\n");
    let unread: Vec<_> = a.papers.iter().filter(|p| !p.error.is_empty()).collect();
    if unread.is_empty() {
        out.push_str("Every paper given was read and extracted.\n\n");
    }
    for p in unread {
        out.push_str(&format!(
            "- {} {}: {}\n",
            p.id,
            esc(&p.title),
            esc(&p.error)
        ));
    }
    out.push_str("\n## Sources\n\n");
    for p in &a.papers {
        out.push_str(&format!("- [{}] {}\n", p.id, esc(&p.title)));
    }
    out
}
