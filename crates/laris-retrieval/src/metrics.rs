//! Recall@k, MRR and nDCG@k with binary relevance.

use std::collections::{BTreeMap, BTreeSet};

use crate::text::round_to;

/// Share of the relevant items found in the first `k`.
pub fn recall_at_k(ranked: &[String], relevant: &BTreeSet<String>, k: usize) -> f64 {
    if relevant.is_empty() {
        return 0.0;
    }
    let found: BTreeSet<&String> = ranked.iter().take(k).collect();
    let hits = relevant.iter().filter(|r| found.contains(r)).count();
    hits as f64 / relevant.len() as f64
}

/// Reciprocal rank of the first relevant item, 0 when none.
pub fn mrr(ranked: &[String], relevant: &BTreeSet<String>) -> f64 {
    ranked
        .iter()
        .position(|item| relevant.contains(item))
        .map_or(0.0, |i| 1.0 / (i as f64 + 1.0))
}

/// Normalised discounted cumulative gain of the first `k`.
pub fn ndcg_at_k(ranked: &[String], relevant: &BTreeSet<String>, k: usize) -> f64 {
    let dcg: f64 = ranked
        .iter()
        .take(k)
        .enumerate()
        .filter(|(_, item)| relevant.contains(*item))
        .map(|(i, _)| 1.0 / (i as f64 + 2.0).log2())
        .sum();
    let ideal: f64 = (0..k.min(relevant.len()))
        .map(|i| 1.0 / (i as f64 + 2.0).log2())
        .sum();
    if ideal == 0.0 { 0.0 } else { dcg / ideal }
}

/// Mean recall@k, MRR and nDCG@k of `retrieve(query) -> [path, ...]` over the queries, rounded to four places.
/// The keys are `recall@k`, `mrr` and `ndcg@k`.
pub fn evaluate(
    queries: &BTreeMap<String, BTreeSet<String>>,
    mut retrieve: impl FnMut(&str) -> Vec<String>,
    k: usize,
) -> BTreeMap<String, f64> {
    let rows: Vec<(Vec<String>, &BTreeSet<String>)> =
        queries.iter().map(|(q, rel)| (retrieve(q), rel)).collect();
    let n = if rows.is_empty() {
        1.0
    } else {
        rows.len() as f64
    };
    let mean = |f: &dyn Fn(&[String], &BTreeSet<String>) -> f64| {
        round_to(rows.iter().map(|(r, rel)| f(r, rel)).sum::<f64>() / n, 4)
    };
    let mut out = BTreeMap::new();
    out.insert(
        format!("recall@{k}"),
        mean(&|r, rel| recall_at_k(r, rel, k)),
    );
    out.insert("mrr".to_string(), mean(&|r, rel| mrr(r, rel)));
    out.insert(format!("ndcg@{k}"), mean(&|r, rel| ndcg_at_k(r, rel, k)));
    out
}
