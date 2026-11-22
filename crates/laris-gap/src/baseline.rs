//! The baselines, built from the same papers and the same model as the system:
//!
//! * **closed** (a): the question alone; the model answers from what it remembers.
//! * **context** (a2): the question with the register and excerpts of every paper (abstract first, then
//!   conclusion and limitation sentences), cut evenly to the budget.
//! * **rag** (b): plain retrieval-augmented generation: the papers are cut into passages, every query of the
//!   policy is a BM25 ranking over them ([`laris_retrieval::PassageIndex`]), the rankings are fused by reciprocal
//!   rank ([`laris_retrieval::fuse_ranked`], `k = 60`), and the best passages go into the prompt with their paper
//!   ids. No concepts, no rules, no checks.

use crate::config::Settings;
use crate::extract::{self, Paper};
use crate::sections;
use laris_retrieval::{Channel, PassageIndex, PassageRecord, fuse_ranked};
use serde::Serialize;

/// A passage retrieval gave baseline (b).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Retrieved {
    /// `P3#12`.
    pub id: String,
    /// Paper.
    pub paper: String,
    /// Fused score.
    pub score: f64,
    /// `(query index, rank)` for every query that returned it.
    pub ranks: Vec<(String, usize)>,
    /// Text.
    pub text: String,
}

/// The register as the prompts show it.
pub fn register(papers: &[Paper]) -> String {
    papers
        .iter()
        .map(|p| {
            format!(
                "[{}] {}{}",
                p.id,
                p.title,
                p.year.map_or(String::new(), |y| format!(" ({y})"))
            )
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// Prompt of baseline (a).
pub fn closed(settings: &Settings, question: &str) -> String {
    settings.prompts.closed.replace("{question}", question)
}

/// Prompt of baseline (a2).
pub fn context(settings: &Settings, question: &str, papers: &[Paper]) -> String {
    let each = settings.budget.context_chars / papers.len().max(1);
    let mut blocks = Vec::new();
    for p in papers {
        let secs = sections::split(&p.text);
        let (ex, _) = extract::excerpts(&p.text, &secs, &settings.limitation_cues, each.max(400));
        blocks.push(format!("=== [{}] {}\n{}", p.id, p.title, ex));
    }
    settings
        .prompts
        .context
        .replace("{question}", question)
        .replace("{register}", &register(papers))
        .replace("{excerpts}", &blocks.join("\n"))
}

fn passages(papers: &[Paper], max_chars: usize) -> Vec<PassageRecord> {
    let mut out = Vec::new();
    for p in papers {
        let secs = sections::split(&p.text);
        let mut n = 0;
        for s in secs
            .iter()
            .filter(|s| s.name != "references" && s.name != "acknowledgements")
        {
            let body = p.text.get(s.start..s.end).unwrap_or("");
            let mut start = s.start;
            let mut buf = String::new();
            for para in body.split("\n\n") {
                let flat = para.split_whitespace().collect::<Vec<_>>().join(" ");
                if flat.is_empty() {
                    continue;
                }
                if !buf.is_empty() && buf.len() + flat.len() > max_chars {
                    n += 1;
                    out.push(PassageRecord {
                        id: format!("{}#{n}", p.id),
                        source: p.id.clone(),
                        start,
                        end: start + buf.len(),
                        text: std::mem::take(&mut buf),
                    });
                    start += 1;
                }
                if !buf.is_empty() {
                    buf.push(' ');
                }
                buf.push_str(&flat);
            }
            if !buf.is_empty() {
                n += 1;
                out.push(PassageRecord {
                    id: format!("{}#{n}", p.id),
                    source: p.id.clone(),
                    start,
                    end: start + buf.len(),
                    text: buf,
                });
            }
        }
    }
    out
}

/// Retrieval of baseline (b): the fused passages, best first.
pub fn retrieve(settings: &Settings, question: &str, papers: &[Paper]) -> Vec<Retrieved> {
    let records = passages(papers, settings.budget.passage_chars);
    let by_id: std::collections::HashMap<String, PassageRecord> =
        records.iter().map(|r| (r.id.clone(), r.clone())).collect();
    let index = PassageIndex::new(records);
    let channels: Vec<Channel> = settings
        .rag_queries
        .iter()
        .enumerate()
        .map(|(i, q)| Channel {
            name: format!("q{}", i + 1),
            weight: 1.0,
            qualified: true,
            items: index
                .search(&q.replace("{question}", question), 100)
                .into_iter()
                .map(|h| h.passage.id)
                .collect(),
        })
        .collect();
    fuse_ranked(&channels, settings.budget.rag_passages)
        .into_iter()
        .filter_map(|f| {
            by_id.get(&f.id).map(|r| Retrieved {
                id: f.id.clone(),
                paper: r.source.clone(),
                score: f.score,
                ranks: f.ranks.clone(),
                text: r.text.clone(),
            })
        })
        .collect()
}

/// Prompt of baseline (b).
pub fn rag(settings: &Settings, question: &str, papers: &[Paper], hits: &[Retrieved]) -> String {
    let block = hits
        .iter()
        .map(|h| format!("[{}] {}", h.paper, h.text))
        .collect::<Vec<_>>()
        .join("\n\n");
    settings
        .prompts
        .rag
        .replace("{question}", question)
        .replace("{register}", &register(papers))
        .replace("{passages}", &block)
}
