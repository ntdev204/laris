//! `laris learn`: collect from a recorded session, export, rate, purge; off means nothing happens. Run with an
//! isolated home, never the real `~/.laris`.

use laris_cli::learn::{Context, run};
use laris_config::Catalogue;
use laris_config::settings::Agent;
use laris_core::{Driver, FollowModel, ModelAnswer, Recorder, ScriptedModel, ToolRunner};
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use serde_json::{Map, Value};
use std::path::{Path, PathBuf};

struct NoTools;

impl ToolRunner for NoTools {
    fn run(&mut self, _name: &str, _arguments: &Map<String, Value>) -> Value {
        Value::Null
    }
}

fn temp_dir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("laris-cli-{name}-{}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir
}

fn context(root: &Path) -> Context {
    Context {
        home: root.join("home"),
        project: root.join("project"),
        env: Vec::new(),
        now: 5.0,
    }
}

/// A recorded session with one finished turn, in the space of the context's project.
fn record(cx: &Context) {
    std::fs::create_dir_all(&cx.project).expect("project");
    let store =
        Store::open_space(&cx.home, &cx.project, None, DEFAULT_BUSY_TIMEOUT).expect("store");
    let (recorder, _) = Recorder::open(store, "s1", "t", 1.0).expect("open");
    let answer = ModelAnswer {
        text: "Hello! I can search your documents and answer with citations.".to_owned(),
        tool_calls: Vec::new(),
        usage: None,
    };
    let mut driver = Driver::new(
        recorder,
        ScriptedModel::new([answer]),
        NoTools,
        FollowModel::new(Agent::default(), Catalogue::english()),
        Vec::new(),
        || 1.0,
    );
    driver.send("Hi").expect("turn");
}

fn args(list: &[&str]) -> Vec<String> {
    list.iter().map(|s| (*s).to_owned()).collect()
}

fn json(text: &str) -> Value {
    serde_json::from_str(text).expect("json output")
}

#[test]
fn collect_export_rate_and_purge() {
    let root = temp_dir("flow");
    let cx = context(&root);
    record(&cx);

    let got = json(&run(&args(&["collect"]), &cx).expect("collect"));
    assert_eq!(got["stored"], 1);
    assert_eq!(
        json(&run(&args(&["collect"]), &cx).unwrap())["duplicates"],
        1
    );
    assert_eq!(
        json(&run(&args(&["stats"]), &cx).unwrap())["examples"]["sft"],
        1
    );

    let out = root.join("exports/sft.jsonl");
    let manifest = json(
        &run(
            &args(&["export", "--kind", "sft", "--out", out.to_str().unwrap()]),
            &cx,
        )
        .expect("export"),
    );
    assert_eq!(manifest["count"], 1);
    let line: Value = serde_json::from_str(std::fs::read_to_string(&out).unwrap().trim()).unwrap();
    let id = line["id"].as_str().unwrap().to_owned();

    run(&args(&["rate", &id, "down"]), &cx).expect("rate");
    let none = json(
        &run(
            &args(&["export", "--kind", "sft", "--out", out.to_str().unwrap()]),
            &cx,
        )
        .unwrap(),
    );
    assert_eq!(none["count"], 0);

    assert!(run(&args(&["purge"]), &cx).is_err());
    assert_eq!(
        run(&args(&["purge", "--yes"]), &cx).unwrap(),
        "removed 2 rows"
    );
    assert_eq!(
        json(&run(&args(&["stats"]), &cx).unwrap())["examples"]["sft"],
        0
    );
}

#[test]
fn an_export_inside_a_git_work_tree_is_refused() {
    let root = temp_dir("repo");
    let cx = context(&root);
    record(&cx);
    run(&args(&["collect"]), &cx).expect("collect");
    let tree = root.join("checkout");
    std::fs::create_dir_all(tree.join(".git")).unwrap();
    let out = tree.join("sft.jsonl");
    let err = run(
        &args(&["export", "--kind", "sft", "--out", out.to_str().unwrap()]),
        &cx,
    )
    .unwrap_err();
    assert!(err.contains("Git work tree"), "{err}");
    assert!(!out.exists());
}

#[test]
fn nothing_is_collected_when_the_setting_is_off() {
    let root = temp_dir("off");
    let cx = context(&root);
    record(&cx);
    std::fs::write(
        cx.home.join("settings.json"),
        r#"{"learning": {"collect": false}}"#,
    )
    .unwrap();
    let got = json(&run(&args(&["collect"]), &cx).expect("collect"));
    assert_eq!(got["enabled"], false);
    assert_eq!(
        json(&run(&args(&["stats"]), &cx).unwrap())["examples"]["sft"],
        0
    );
}

#[test]
fn bad_arguments_are_named() {
    let cx = context(&temp_dir("args"));
    assert!(
        run(&args(&["export", "--kind", "bogus", "--out", "x"]), &cx)
            .unwrap_err()
            .contains("--kind")
    );
    assert!(
        run(&args(&["export", "--kind", "sft"]), &cx)
            .unwrap_err()
            .contains("--out")
    );
    assert!(
        run(&args(&["rate", "nope", "up"]), &cx)
            .unwrap_err()
            .contains("no example")
    );
    assert!(run(&args(&["frobnicate"]), &cx).is_err());
}
