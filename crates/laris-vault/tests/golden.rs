//! Recorded expectations: `tests/golden/vault/index.json` is the index of the fixture vault and `yaml_cases.json`
//! holds property documents with the values PyYAML reads from them; this crate must reproduce both.

use std::fs;
use std::path::{Path, PathBuf};

use laris_vault::VaultIndex;
use laris_vault::note::value_to_json;
use laris_vault::yaml;
use serde_json::Value as Json;

fn golden() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/golden/vault")
}

#[test]
fn index_of_the_fixture_vault_equals_the_recorded_index_byte_for_byte() {
    let index = VaultIndex::build(&golden().join("fixture"), None).expect("build");
    let expected = fs::read_to_string(golden().join("index.json")).expect("golden");
    assert_eq!(index.export_string(), expected);
}

#[test]
fn fixture_covers_every_row_of_the_format_spec() {
    let index = VaultIndex::build(&golden().join("fixture"), None).expect("build");
    // ignored folders hold notes, hidden folders that are not ignored are scanned
    assert!(
        index
            .notes
            .keys()
            .all(|p| !p.starts_with(".obsidian/") && !p.starts_with(".trash/"))
    );
    assert!(!index.notes.contains_key("_templates/Template.md"));
    assert!(index.notes.contains_key(".hidden/Secret.md"));
    let forms = &index.notes["Notes/Alpha.md"];
    assert_eq!(
        forms.tags.iter().cloned().collect::<Vec<_>>(),
        ["inline", "physics", "review/2026", "topic/sub-topic"]
    );
    assert_eq!(
        index
            .unresolved
            .iter()
            .filter(|(p, _)| p == "Notes/Alpha.md")
            .count(),
        1
    );
    assert_eq!(
        index
            .ambiguous
            .iter()
            .filter(|(p, _)| p == "Notes/Alpha.md")
            .count(),
        1
    );
    assert_eq!(
        index
            .backlinks("Notes/Gamma.md")
            .first()
            .map(String::as_str),
        Some("Links/Forms.md")
    );
    assert!(index.orphans().contains(&"Lonely.md".to_string()));
    // assertions on the original fixture
    assert_eq!(index.notes["Code/Fenced.md"].links.len(), 1);
    assert!(index.notes["Code/Fenced.md"].tags.is_empty());
}

#[test]
fn rerun_is_byte_identical_and_the_cache_round_trips() {
    let root = golden().join("fixture");
    let a = VaultIndex::build(&root, None).expect("build");
    let b = VaultIndex::build(&root, None).expect("build");
    assert_eq!(a.export_string(), b.export_string());
    assert_eq!(a.dumps(), b.dumps());
    let cache = a.dumps();
    let loaded = VaultIndex::loads(&root, &cache).expect("cache");
    let c = VaultIndex::build(&root, Some(&loaded)).expect("build");
    assert_eq!(c.export_string(), a.export_string());
    assert_eq!(
        c.stats.parsed,
        Vec::<String>::new(),
        "an unchanged vault reads nothing"
    );
    assert_eq!(c.stats.reused.len(), a.notes.len());
    assert_eq!(c.dumps(), cache);
    assert!(VaultIndex::loads(&root, "{\"version\":99,\"notes\":{}}").is_none());
    assert!(VaultIndex::loads(&root, "not json").is_none());
}

#[test]
fn yaml_reader_gives_the_values_pyyaml_gives() {
    let text = fs::read_to_string(golden().join("yaml_cases.json")).expect("cases");
    let cases: Vec<Json> = serde_json::from_str(&text).expect("json");
    assert!(cases.len() > 50);
    let mut failures = Vec::new();
    for case in &cases {
        let source = case["yaml"].as_str().expect("yaml");
        let got = yaml::parse(source);
        if case.get("error").is_some() {
            if got.is_ok() {
                failures.push(format!("{source:?}: PyYAML refuses it, this read {got:?}"));
            }
            continue;
        }
        match got {
            Err(e) => failures.push(format!("{source:?}: PyYAML reads it, this fails: {e}")),
            Ok(value) => {
                if value_to_json(&value) != case["value"] {
                    failures.push(format!(
                        "{source:?}: expected {} got {}",
                        case["value"],
                        value_to_json(&value)
                    ));
                }
            }
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn forms_that_stay_refused_or_text_on_purpose() {
    // PyYAML reads these; this reader refuses or keeps text, and says so in the module documentation
    assert!(yaml::parse("a: !!str 1").is_err());
    assert!(yaml::parse("? complex\n: key").is_err());
    assert!(yaml::parse("a: [a: 1]").is_err());
    assert!(yaml::parse("a: |2\n   x").is_err());
    assert_eq!(
        yaml::parse("a: 99999999999999999999").unwrap(),
        yaml::Value::Map(vec![(
            "a".into(),
            yaml::Value::Str("99999999999999999999".into())
        )])
    );
    assert_eq!(
        yaml::parse("a: .inf").unwrap(),
        yaml::Value::Map(vec![("a".into(), yaml::Value::Str(".inf".into()))])
    );
}
