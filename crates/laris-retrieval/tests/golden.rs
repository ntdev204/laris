//! Generation 1 is the reference: `tests/golden/retrieval/cases.json` was written by `generate.py` from the
//! generation-1 `NoteSearch`, `GraphRetriever`, `fuse_with_corpus` and `evaluate`; this crate must reproduce every
//! order and every number on `tests/fixtures/retrieval/`.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use laris_retrieval::{
    GraphConfig, GraphRetriever, NoteSearch, RetrievalResult, evaluate, fuse_with_corpus, mrr,
    ndcg_at_k, recall_at_k, tokens,
};
use laris_vault::VaultIndex;
use serde_json::Value;

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn cases() -> Value {
    let text =
        fs::read_to_string(root().join("tests/golden/retrieval/cases.json")).expect("golden");
    serde_json::from_str(&text).expect("json")
}

fn index() -> VaultIndex {
    VaultIndex::build(&root().join("tests/fixtures/retrieval/vault"), None).expect("build")
}

fn row(r: &RetrievalResult) -> Value {
    serde_json::json!([r.path, r.score, r.via.as_str(), r.seed, r.detail])
}

#[test]
fn tokens_equal_generation_1() {
    for case in cases()["tokens"].as_array().unwrap() {
        let text = case[0].as_str().unwrap();
        let expected: Vec<String> = case[1]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        assert_eq!(tokens(text), expected, "{text:?}");
    }
}

#[test]
fn bm25_rankings_and_scores_equal_generation_1() {
    let index = index();
    let search = NoteSearch::new(&index, &[]);
    for case in cases()["search"].as_array().unwrap() {
        let query = case["query"].as_str().unwrap();
        let got: Vec<Value> = search
            .search(query, 10)
            .iter()
            .map(|h| serde_json::json!([h.path, h.score]))
            .collect();
        assert_eq!(Value::Array(got), case["hits"], "{query:?}");
    }
}

#[test]
fn graph_expansion_equals_generation_1() {
    let index = index();
    let mut n = 0;
    for case in cases()["graph"].as_array().unwrap() {
        let cfg = &case["config"];
        let config = GraphConfig {
            seeds: cfg["seeds"].as_u64().unwrap() as usize,
            link_weight: cfg["link_weight"].as_f64().unwrap(),
            decay: cfg["decay"].as_f64().unwrap(),
        };
        let query = case["query"].as_str().unwrap();
        let k = case["k"].as_u64().unwrap() as usize;
        let got: Vec<Value> = GraphRetriever::new(&index, &[], config)
            .retrieve(query, k)
            .iter()
            .map(row)
            .collect();
        assert_eq!(Value::Array(got), case["results"], "{query:?} k={k} {cfg}");
        n += 1;
    }
    assert_eq!(n, 90);
}

#[test]
fn corpus_fusion_equals_generation_1() {
    let index = index();
    let notes =
        GraphRetriever::new(&index, &[], GraphConfig::default()).retrieve("perovskite solar", 10);
    for case in cases()["fuse"].as_array().unwrap() {
        let sources: Vec<String> = case["sources"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        let k = case["k"].as_u64().unwrap() as usize;
        let got: Vec<Value> = fuse_with_corpus(&notes, &sources, k)
            .iter()
            .map(row)
            .collect();
        assert_eq!(Value::Array(got), case["results"], "{sources:?} k={k}");
    }
}

fn qrels(v: &Value) -> BTreeMap<String, BTreeSet<String>> {
    v.as_object()
        .unwrap()
        .iter()
        .map(|(q, rel)| {
            (
                q.clone(),
                rel.as_array()
                    .unwrap()
                    .iter()
                    .map(|p| p.as_str().unwrap().to_string())
                    .collect(),
            )
        })
        .collect()
}

fn as_map(v: &Value) -> BTreeMap<String, f64> {
    v.as_object()
        .unwrap()
        .iter()
        .map(|(k, x)| (k.clone(), x.as_f64().unwrap()))
        .collect()
}

#[test]
fn metrics_equal_generation_1() {
    let index = index();
    let golden = cases();
    let m = &golden["metrics"];
    let queries = qrels(&m["qrels"]);
    let graph = GraphRetriever::new(&index, &[], GraphConfig::default());
    let by_graph = evaluate(
        &queries,
        |q| graph.retrieve(q, 10).into_iter().map(|r| r.path).collect(),
        5,
    );
    assert_eq!(by_graph, as_map(&m["by_graph"]));
    let search = NoteSearch::new(&index, &[]);
    let by_bm25 = evaluate(
        &queries,
        |q| search.search(q, 10).into_iter().map(|h| h.path).collect(),
        5,
    );
    assert_eq!(by_bm25, as_map(&m["by_bm25"]));
    for s in m["single"].as_array().unwrap() {
        let ranked: Vec<String> = s["ranked"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().into())
            .collect();
        let relevant: BTreeSet<String> = s["relevant"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().into())
            .collect();
        let k = s["k"].as_u64().unwrap() as usize;
        assert_eq!(
            recall_at_k(&ranked, &relevant, k),
            s["recall"].as_f64().unwrap()
        );
        assert_eq!(mrr(&ranked, &relevant), s["mrr"].as_f64().unwrap());
        assert_eq!(
            ndcg_at_k(&ranked, &relevant, k),
            s["ndcg"].as_f64().unwrap()
        );
    }
}

#[test]
fn rerun_is_byte_identical() {
    let index = index();
    let run = || {
        let graph = GraphRetriever::new(&index, &[], GraphConfig::default());
        format!("{:?}", graph.retrieve("perovskite solar", 10))
    };
    assert_eq!(run(), run());
}
