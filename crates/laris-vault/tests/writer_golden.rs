//! Recorded expectations: `tests/golden/vault/writer_lint.json` holds rendered notes, managed blocks, safe titles and
//! lint results, and this crate must reproduce every entry.

use std::fs;
use std::path::{Path, PathBuf};

use laris_vault::lint::{HierarchyRules, lint_content, lint_format, lint_hierarchy};
use laris_vault::note::value_from_json;
use laris_vault::schema::{BUILTIN_YAML, Schema, lint_schema};
use laris_vault::writer::{BlockStatus, render_note, safe_title, upsert_block};
use laris_vault::{Problem, VaultIndex, yaml};
use serde_json::Value as Json;

fn golden() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/golden/vault")
}

fn load() -> Json {
    serde_json::from_str(&fs::read_to_string(golden().join("writer_lint.json")).expect("golden"))
        .expect("json")
}

fn problems(list: &[Problem]) -> Json {
    Json::Array(
        list.iter()
            .map(|p| serde_json::json!([p.path, p.code, p.message]))
            .collect(),
    )
}

#[test]
fn rendered_notes_equal_the_recorded_text() {
    let data = load();
    for case in data["render"].as_array().expect("cases") {
        let props: Vec<(String, yaml::Value)> = case["props"]
            .as_array()
            .expect("props")
            .iter()
            .map(|pair| {
                (
                    pair[0].as_str().expect("key").to_string(),
                    value_from_json(&pair[1]).expect("value"),
                )
            })
            .collect();
        let text = render_note(&props, "Body text.").expect("render");
        assert_eq!(
            text,
            case["text"].as_str().expect("text"),
            "props {props:?}"
        );
        // and the text reads back to the same properties
        let front = text
            .strip_prefix("---\n")
            .and_then(|t| t.split_once("\n---\n"))
            .expect("front matter")
            .0;
        let back = yaml::parse(front).expect("reads back");
        let expected = if props.is_empty() {
            yaml::Value::Map(Vec::new())
        } else {
            yaml::Value::Map(props.clone())
        };
        assert_eq!(back, expected, "round trip of {front}");
    }
}

#[test]
fn managed_blocks_behave_as_recorded() {
    let data = load();
    for case in data["blocks"].as_array().expect("cases") {
        let text = case["text"].as_str().expect("text");
        let name = case["name"].as_str().expect("name");
        let content = case["content"].as_str().expect("content");
        let status = |s: &str| match s {
            "created" => BlockStatus::Created,
            "updated" => BlockStatus::Updated,
            "unchanged" => BlockStatus::Unchanged,
            _ => BlockStatus::Conflict,
        };
        let (new, s1) = upsert_block(text, name, content).expect("upsert");
        assert_eq!(
            (new.as_str(), s1),
            (
                case["new"].as_str().expect("new"),
                status(case["status"].as_str().expect("s"))
            )
        );
        let (again, s2) = upsert_block(&new, name, content).expect("upsert");
        assert_eq!(
            (again.as_str(), s2),
            (
                case["again"].as_str().expect("again"),
                status(case["status2"].as_str().expect("s"))
            )
        );
        let more = format!("{content} more");
        let (changed, s3) = upsert_block(&new, name, &more).expect("upsert");
        assert_eq!(
            (changed.as_str(), s3),
            (
                case["changed"].as_str().expect("c"),
                status(case["status3"].as_str().expect("s"))
            )
        );
    }
}

#[test]
fn safe_titles_equal_the_recorded_ones() {
    for pair in load()["titles"].as_array().expect("titles") {
        let (raw, expected) = (
            pair[0].as_str().expect("raw"),
            pair[1].as_str().expect("expected"),
        );
        assert_eq!(safe_title(raw, "Untitled"), expected, "title {raw:?}");
    }
}

#[test]
fn lint_of_the_golden_vaults_equals_the_recorded_results() {
    let data = load();
    let lint = &data["lint"];
    let fixture = VaultIndex::build(&golden().join("fixture"), None).expect("build");
    let brain = VaultIndex::build(&golden().join("brain"), None).expect("build");
    assert_eq!(problems(&lint_format(&fixture)), lint["format"]);
    assert_eq!(problems(&lint_format(&brain)), lint["brain_format"]);
    assert_eq!(
        problems(&lint_schema(&fixture, &Schema::builtin())),
        lint["schema"]
    );
    assert_eq!(
        problems(&lint_content(&fixture, 120, 25, None)),
        lint["content_plain"]
    );
    // a stub redactor: letters in front of `[[` become a marker
    let redact = |t: &str| {
        let mut out = String::new();
        let chars: Vec<char> = t.chars().collect();
        let mut i = 0;
        while i < chars.len() {
            let mut j = i;
            while j < chars.len() && chars[j].is_ascii_alphabetic() {
                j += 1;
            }
            if j > i && chars.get(j) == Some(&'[') && chars.get(j + 1) == Some(&'[') {
                out.push_str("<secret>");
                i = j;
            } else {
                out.push(chars[i]);
                i += 1;
            }
        }
        out
    };
    assert_eq!(
        problems(&lint_content(&fixture, 120, 25, Some(&redact))),
        lint["content"]
    );
    let rules = HierarchyRules {
        root_title: "Root",
        max_depth: 2,
        max_children: 2,
        required: &["summary", "level"],
        summary_max_chars: 60,
        relations: &["requires", "uses"],
    };
    assert_eq!(problems(&lint_hierarchy(&brain, &rules)), lint["hierarchy"]);
    let no_root = HierarchyRules {
        root_title: "Missing",
        required: &[],
        relations: &[],
        ..rules
    };
    assert_eq!(
        problems(&lint_hierarchy(&brain, &no_root)),
        lint["hierarchy_no_root"]
    );
}

#[test]
fn the_builtin_schema_is_the_default_and_a_file_can_replace_it() {
    let dir = std::env::temp_dir().join(format!("laris-schema-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let file = dir.join("schema.yaml");
    std::fs::write(&file, BUILTIN_YAML).unwrap();
    assert_eq!(Schema::load(Some(&file)).expect("file"), Schema::builtin());
    std::fs::write(
        &file,
        "version: 1\ntypes:\n  note: {required: [type], folder: Notes}\n",
    )
    .unwrap();
    let own = Schema::load(Some(&file)).expect("own");
    assert_eq!(own.folder_of("note"), "Notes");
    assert!(BUILTIN_YAML.contains("knowledge-hub"));
    assert_eq!(
        Schema::load(Some(Path::new("/nonexistent/schema.yaml"))).expect("fallback"),
        Schema::builtin()
    );
    assert!(Schema::from_text("types: [unclosed").is_err());
    assert_eq!(Schema::builtin().folder_of("source"), "Sources");
}
