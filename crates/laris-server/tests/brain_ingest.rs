//! T277: offline ingestion goes through the write gate (a model-only line is refused, a quote is checked), the
//! snapshot manifest hashes every file and changes when a note changes, and retrieval reads what the gate accepted.

use laris_brain::gate::GateSettings;
use laris_server::brain_ingest::{freeze, import, retrieve};
use laris_server::mainbrain::MainBrainConfig;
use std::fs;
use std::path::PathBuf;

const GATE: GateSettings = GateSettings {
    min_support: 0.9,
    min_equivalence: 0.6,
    subject_overlap: 0.5,
    search_depth: 10,
    max_bytes: 100_000,
};

fn temp(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("laris-ingest-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).expect("temp");
    dir
}

const LINES: &str = r#"{"type":"source","title":"Book Motion","kind":"document","identifier":"https://example.org/motion","text":"Source: fixture.\n\nVelocity is the rate of change of position with time.\n\nAcceleration is the rate of change of velocity with time.","metadata":{"kind":"verified","registry":"fixture"},"proposer":"tool:test"}
{"type":"source","title":"Unchecked","kind":"document","identifier":"https://example.org/x","text":"Anything.","metadata":{"kind":"unresolved"},"proposer":"tool:test"}
{"type":"claim","statement":"Velocity is the rate of change of position with time.","source":"Book Motion","quote":"Velocity is the rate of change of position with time.","requested":"sourced","proposer":"tool:test"}
{"type":"claim","statement":"Acceleration is the rate of change of velocity with time.","source":"Book Motion","quote":"Acceleration is the rate of change of velocity with time.","requested":"sourced","proposer":"tool:test"}
{"type":"claim","statement":"Momentum is always conserved.","quote":"Momentum is always conserved.","requested":"sourced","proposer":"tool:test"}
{"type":"claim","statement":"Mass is energy.","source":"Book Motion","quote":"Mass is energy.","requested":"sourced","proposer":"tool:test"}
"#;

#[test]
fn import_freeze_and_retrieve_go_through_the_gate() {
    let dir = temp("vault");
    let file = temp("input").join("proposals.jsonl");
    fs::write(&file, LINES).expect("proposals");
    let config = MainBrainConfig {
        dir: dir.clone(),
        gate: GATE,
    };
    assert!(
        import(&config, &file, "23-11-2026").is_err(),
        "a bad date is refused"
    );
    let report = import(&config, &file, "2026-11-23").expect("import");
    assert_eq!(report["sources"]["accepted"], 1);
    assert_eq!(report["sources"]["refused"]["metadata"], 1);
    assert_eq!(report["claims"]["accepted"], 2);
    assert_eq!(report["claims"]["refused"]["model-only"], 1);
    assert_eq!(report["claims"]["refused"]["span"], 1);
    assert_eq!(report["claims"]["levels"]["sourced"], 2);

    let manifest = freeze(&dir).expect("freeze");
    assert_eq!(manifest["notes_by_type"]["source"], 1);
    assert_eq!(manifest["notes_by_type"]["claim"], 2);
    assert_eq!(manifest["lint_problems"], 0);
    let files = manifest["file_sha256"].as_object().expect("files");
    assert!(files.keys().any(|k| k.starts_with("Sources/")));
    assert!(
        files.keys().any(|k| k.starts_with(".laris/")),
        "the audit is part of the snapshot"
    );
    assert_eq!(
        freeze(&dir).expect("again"),
        manifest,
        "freezing is deterministic"
    );

    let queries = temp("queries").join("q.jsonl");
    fs::write(
        &queries,
        "{\"id\":\"q1\",\"query\":\"rate of change of velocity\"}\n",
    )
    .expect("q");
    let mut out = Vec::new();
    assert_eq!(
        retrieve(&config, &queries, 3, None, &mut out).expect("retrieve"),
        1
    );
    let row: serde_json::Value =
        serde_json::from_str(String::from_utf8(out).expect("utf8").trim()).expect("json");
    assert_eq!(row["id"], "q1");
    let hits = row["hits"].as_array().expect("hits");
    assert!(!hits.is_empty() && hits.len() <= 3);
    assert!(hits.iter().any(|h| {
        h["text"]
            .as_str()
            .unwrap_or("")
            .contains("rate of change of velocity")
    }));

    // a changed note changes the snapshot's identity
    let claim = files
        .keys()
        .find(|k| k.starts_with("Claims/"))
        .expect("claim")
        .clone();
    let path = dir.join(&claim);
    let text = fs::read_to_string(&path).expect("claim");
    fs::write(&path, format!("{text}edited\n")).expect("edit");
    assert_ne!(
        freeze(&dir).expect("changed")["snapshot_sha256"],
        manifest["snapshot_sha256"]
    );
}

const ADMITTED: &str = r#"{"type":"source","title":"Paper Cells","kind":"document","identifier":"doi:10.1/cells","text":"Source: fixture.\n\nRibosomes translate messenger RNA into protein in living cells.","metadata":{"kind":"verified","registry":"crossref"},"admission":{"class":"journal_paper","resolved_by":"crossref","resolution_sha256":"4f1d3b0c9a8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d6c5b4a392817060000","licence":"cc-by-4.0","venue":"2041-1723","retraction_check":"crossref:none"},"proposer":"tool:test"}
{"type":"source","title":"Paper Closed","kind":"document","identifier":"doi:10.1/closed","text":"Source: fixture.\n\nMitochondria produce most of the ATP in eukaryotic cells.","metadata":{"kind":"verified","registry":"crossref"},"admission":{"class":"journal_paper","resolved_by":"crossref","resolution_sha256":"4f1d3b0c9a8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d6c5b4a392817060000","licence":"cc-by-nc-4.0","venue":"2041-1723","retraction_check":"crossref:none"},"proposer":"tool:test"}
{"type":"claim","statement":"Ribosomes translate messenger RNA into protein in living cells.","source":"Paper Cells","quote":"Ribosomes translate messenger RNA into protein in living cells.","requested":"sourced","proposer":"tool:test"}
{"type":"claim","statement":"Mitochondria produce most of the ATP in eukaryotic cells.","source":"Paper Closed","quote":"Mitochondria produce most of the ATP in eukaryotic cells.","requested":"sourced","proposer":"tool:test"}
"#;

#[test]
fn an_admission_record_is_stored_and_certify_and_retrieve_name_the_verdicts() {
    use laris_brain::certain::Admissibility;
    use laris_server::brain_ingest::certify;
    let dir = temp("admitted");
    let file = temp("admitted-input").join("proposals.jsonl");
    fs::write(&file, ADMITTED).expect("proposals");
    let config = MainBrainConfig {
        dir: dir.clone(),
        gate: GATE,
    };
    let report = import(&config, &file, "2026-11-23").expect("import");
    assert_eq!(report["sources"]["accepted"], 2);
    assert_eq!(report["claims"]["accepted"], 2);
    let note = fs::read_to_string(dir.join("Sources/Paper Cells.md")).expect("source note");
    for prop in [
        "source_class: journal_paper",
        "resolved_by: crossref",
        "licence: cc-by-4.0",
        "retraction_check: crossref:none",
    ] {
        assert!(note.contains(prop), "{prop} in {note}");
    }
    assert_eq!(freeze(&dir).expect("freeze")["lint_problems"], 0);

    let classes =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../configs/admissible-sources.json");
    let rules = Admissibility::load(&classes).expect("classes");
    let counts = certify(&dir, &rules).expect("certify");
    assert_eq!(counts["sources"]["admitted:journal_paper"], 1, "{counts}");
    assert_eq!(counts["sources"]["not:licence"], 1, "{counts}");
    assert_eq!(counts["claims"]["certain"], 1, "{counts}");
    assert_eq!(counts["claims"]["not:licence"], 1, "{counts}");
    assert_eq!(counts["certain_by_class"]["journal_paper"], 1, "{counts}");

    let queries = temp("admitted-queries").join("q.jsonl");
    fs::write(
        &queries,
        "{\"id\":\"q\",\"query\":\"ribosomes translate messenger RNA\"}\n",
    )
    .expect("q");
    let mut out = Vec::new();
    retrieve(&config, &queries, 5, Some(&rules), &mut out).expect("retrieve");
    let row: serde_json::Value =
        serde_json::from_str(String::from_utf8(out).expect("utf8").trim()).expect("json");
    let hits = row["hits"].as_array().expect("hits");
    assert!(hits.iter().all(|h| h["certain"].is_boolean()), "{row}");
    assert!(
        hits.iter()
            .any(|h| h["certain"] == true
                && h["source"].as_str().unwrap_or("").starts_with("Claims/")),
        "{row}"
    );
}
