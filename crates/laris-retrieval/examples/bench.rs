//! Measures retrieval at scale (SR-L3): a synthetic vault of N notes, deterministic content.
//!
//!     cargo run --release -p laris-retrieval --example bench -- --notes 10000 --out reports/performance/retrieval.json
//!     cargo run --release -p laris-retrieval --example bench -- --notes 500 --keep DIR --dump FILE
//!
//! `--keep` leaves the vault in DIR and `--dump` writes every query with its BM25 and graph results (tab separated),
//! so another implementation can be run on the same vault and compared.
//!
//! Reports the index build, BM25 and graph-expansion latency (median and P95 over 200 queries), and the fixture
//! metrics. This is an experiment, not a test; timings depend on the machine.

use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use laris_retrieval::{GraphConfig, GraphRetriever, NoteSearch};
use laris_vault::VaultIndex;

const WORDS: [&str; 34] = [
    "perovskite",
    "lithium",
    "transformer",
    "attention",
    "citation",
    "graph",
    "vault",
    "note",
    "concept",
    "method",
    "dataset",
    "metric",
    "claim",
    "limitation",
    "source",
    "evidence",
    "retrieval",
    "ranking",
    "passage",
    "index",
    "cache",
    "cell",
    "energy",
    "battery",
    "language",
    "model",
    "protein",
    "folding",
    "sequence",
    "structure",
    "analysis",
    "result",
    "figure",
    "table",
];

/// A small deterministic generator (xorshift64*), so the vault is the same on every machine.
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }

    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
}

fn build_vault(root: &Path, count: usize) {
    let mut rng = Rng(7);
    for i in 0..count {
        let folder = root.join(format!("Folder{}", i % 20));
        fs::create_dir_all(&folder).expect("folder");
        let links: Vec<String> = (0..4)
            .map(|_| format!("[[Note {}]]", rng.below(count)))
            .collect();
        let body: Vec<&str> = (0..120).map(|_| WORDS[rng.below(WORDS.len())]).collect();
        let text = format!(
            "---\ntype: concept\ncreated: 2026-01-01\ntags: [t{}]\n---\n# Note {i}\n{}\n{}\n",
            i % 50,
            body.join(" "),
            links.join(" ")
        );
        fs::write(folder.join(format!("Note {i}.md")), text).expect("note");
    }
}

fn percentile(sorted: &[f64], p: f64) -> f64 {
    let i = ((sorted.len() as f64 - 1.0) * p).round() as usize;
    sorted[i]
}

fn ms(sorted: &mut [f64]) -> (f64, f64) {
    sorted.sort_by(f64::total_cmp);
    (percentile(sorted, 0.5), percentile(sorted, 0.95))
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let value = |flag: &str| {
        args.iter()
            .position(|a| a == flag)
            .and_then(|i| args.get(i + 1))
            .cloned()
    };
    let count: usize = value("--notes")
        .and_then(|v| v.parse().ok())
        .unwrap_or(10_000);
    let keep = value("--keep").map(PathBuf::from);
    let out = value("--out").map(PathBuf::from);
    let dump = value("--dump").map(PathBuf::from);

    let tmp = std::env::temp_dir().join(format!("laris-retrieval-bench-{}", std::process::id()));
    let root = keep.clone().unwrap_or_else(|| tmp.join("vault"));
    let _ = fs::remove_dir_all(&root);
    build_vault(&root, count);

    let started = Instant::now();
    let index = VaultIndex::build(&root, None).expect("index");
    let index_s = started.elapsed().as_secs_f64();

    let started = Instant::now();
    let search = NoteSearch::new(&index, &[]);
    let search_build_s = started.elapsed().as_secs_f64();
    let graph = GraphRetriever::new(&index, &[], GraphConfig::default());

    let mut rng = Rng(11);
    let queries: Vec<String> = (0..200)
        .map(|_| {
            (0..3)
                .map(|_| WORDS[rng.below(WORDS.len())])
                .collect::<Vec<_>>()
                .join(" ")
        })
        .collect();
    let (mut bm25_ms, mut graph_ms) = (Vec::new(), Vec::new());
    for q in &queries {
        let t = Instant::now();
        std::hint::black_box(search.search(q, 10));
        bm25_ms.push(t.elapsed().as_secs_f64() * 1000.0);
        let t = Instant::now();
        std::hint::black_box(graph.retrieve(q, 10));
        graph_ms.push(t.elapsed().as_secs_f64() * 1000.0);
    }
    if let Some(path) = dump {
        let mut lines = String::new();
        for q in &queries {
            let bm25: Vec<String> = search
                .search(q, 10)
                .iter()
                .map(|h| format!("{}={}", h.path, h.score))
                .collect();
            let rows: Vec<String> = graph
                .retrieve(q, 10)
                .iter()
                .map(|r| format!("{}={}={}={}", r.path, r.score, r.via.as_str(), r.seed))
                .collect();
            lines.push_str(&format!("{q}\t{}\t{}\n", bm25.join(";"), rows.join(";")));
        }
        fs::write(path, lines).expect("dump");
    }
    let (bm25_med, bm25_p95) = ms(&mut bm25_ms);
    let (graph_med, graph_p95) = ms(&mut graph_ms);
    let r = |x: f64| (x * 1000.0).round() / 1000.0;
    let report = format!(
        "{{\n  \"bm25_median_ms\": {},\n  \"bm25_p95_ms\": {},\n  \"graph_median_ms\": {},\n  \"graph_p95_ms\": {},\n  \"index_build_s\": {},\n  \"notes\": {count},\n  \"queries\": {},\n  \"search_build_s\": {},\n  \"target_p95_ms\": 300.0\n}}\n",
        r(bm25_med),
        r(bm25_p95),
        r(graph_med),
        r(graph_p95),
        r(index_s),
        queries.len(),
        r(search_build_s)
    );
    match out {
        Some(path) => fs::write(path, &report).expect("write report"),
        None => print!("{report}"),
    }
    if keep.is_none() {
        let _ = fs::remove_dir_all(&tmp);
    }
}
