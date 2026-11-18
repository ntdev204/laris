//! The system brain service (SR-S5): progressive disclosure over `.laris/brain/`, budgets, the evidence list and the
//! absence of any write path. The brain is the repository's own; no model and no database is involved.

use laris_server::brain::{BRAIN_TOOL, Brain, BrainSettings, Consulted};
use laris_server::policy::{Policy, PolicyConfig};
use laris_vault::{HierarchyRules, VaultIndex, lint_hierarchy};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn brain() -> Brain {
    Brain::load(&repo(), BrainSettings::default())
}

fn call(brain: &Brain, used: &mut Consulted, args: Value) -> Result<String, String> {
    brain.consult(&args, used).map_err(|e| e.0)
}

#[test]
fn the_brain_loads_and_every_note_is_in_the_tree_within_max_depth() {
    let brain = brain();
    assert!(brain.offered(), "{:?}", brain.problems);
    assert!(brain.problems.is_empty(), "{:?}", brain.problems);
    let titles = brain.titles();
    assert_eq!(titles.len(), 65);
    let max = brain.settings().max_depth;
    for title in &titles {
        let depth = brain.depth_of(title).expect("in the tree");
        assert!(depth <= max, "{title} is {depth} steps from the root");
    }
    assert_eq!(brain.depth_of("Brain Index"), Some(0));
}

#[test]
fn the_brain_follows_the_hub_tree_rules() {
    let index = VaultIndex::build(&repo().join(".laris/brain"), None).expect("the folder reads");
    let problems = lint_hierarchy(
        &index,
        &HierarchyRules {
            root_title: "Brain Index",
            max_depth: 3,
            max_children: 10,
            required: &["type", "domain", "level", "summary"],
            summary_max_chars: 260,
            relations: &["uses", "feeds", "requires", "contrasts", "validates"],
        },
    );
    assert!(problems.is_empty(), "{problems:?}");
}

/// Plays the shortest honest path of a model: the index, the hub, then the playbook; returns the steps it took.
fn walk_to_the_playbook(brain: &Brain, hub: &str) -> (usize, Consulted) {
    let mut used = Consulted::default();
    call(brain, &mut used, json!({"action": "index"})).expect("the index");
    let opened = call(brain, &mut used, json!({"action": "open", "id": hub})).expect("the hub");
    let playbook = opened
        .lines()
        .find_map(|l| {
            let title = l.strip_prefix("- ")?.split(" — ").next()?;
            title.ends_with("Playbook").then(|| title.to_owned())
        })
        .unwrap_or_else(|| panic!("{hub} lists a playbook:\n{opened}"));
    call(brain, &mut used, json!({"action": "read", "id": playbook})).expect("the playbook");
    (used.calls(), used)
}

#[test]
fn each_direction_reaches_its_playbook_within_max_depth_without_search() {
    let brain = brain();
    let max = brain.settings().max_depth;
    let mut with_playbook = 0;
    for (route, hub) in brain.routes() {
        assert_eq!(brain.depth_of(hub), Some(1), "{route} leads to a hub");
        let brief = brain.brief(route).expect("a brief for every route");
        assert_eq!(brief.titles[0], *hub);
        if brief.titles.len() == 2 {
            with_playbook += 1;
            assert!(brain.depth_of(&brief.titles[1]).unwrap() <= max);
            let (steps, used) = walk_to_the_playbook(&brain, hub);
            assert!(steps <= max, "{route}: {steps} steps, the limit is {max}");
            assert_eq!(used.titles(), [hub.as_str(), brief.titles[1].as_str()]);
        }
    }
    assert!(
        with_playbook >= 10,
        "most routes end at a playbook, {with_playbook} did"
    );
    // every playbook of the brain is within reach
    let index = VaultIndex::build(&repo().join(".laris/brain"), None).unwrap();
    let playbooks: Vec<&str> = index
        .notes
        .values()
        .filter(|n| n.prop_list("type") == ["playbook"])
        .map(|n| n.title.as_str())
        .collect();
    assert!(playbooks.len() >= 5);
    for p in playbooks {
        assert!(brain.depth_of(p).unwrap() <= max, "{p}");
    }
}

#[test]
fn every_workflow_of_the_policy_has_a_route() {
    let policy = Policy::load(&PolicyConfig::with_root(repo()), std::iter::empty(), None)
        .expect("the repository policy loads");
    for workflow in policy.workflows().all() {
        assert!(
            policy.brain().route(&workflow.name).is_some(),
            "workflow {} has no route in the Brain Index",
            workflow.name
        );
    }
}

#[test]
fn a_brief_is_summaries_only_and_inside_its_budget() {
    let brain = brain();
    let brief = brain.brief("citation-analysis").unwrap();
    assert!(brief.text.contains("Citation Analysis"));
    assert!(brief.text.contains("Citation Analysis Playbook"));
    assert!(brief.text.chars().count() <= brain.settings().brief_chars);
    // nothing of a note's body: the playbook's own steps are not in the brief
    assert!(!brief.text.contains("Parse reference strings into author"));
    assert!(brain.brief("no-such-route").is_none());
    let small = Brain::load(
        &repo(),
        BrainSettings {
            brief_chars: 120,
            ..BrainSettings::default()
        },
    );
    assert!(
        small
            .brief("citation-analysis")
            .unwrap()
            .text
            .chars()
            .count()
            <= 120
    );
}

#[test]
fn open_shows_links_and_summaries_and_read_shows_the_text() {
    let brain = brain();
    let mut used = Consulted::default();
    let opened = call(
        &brain,
        &mut used,
        json!({"action": "open", "id": "Citation Analysis"}),
    )
    .unwrap();
    assert!(opened.contains("Notes under it:") && opened.contains("Citation Extraction — "));
    assert!(!opened.contains("Parse reference strings into author"));
    let read = call(
        &brain,
        &mut used,
        json!({"action": "read", "id": "Citation Analysis Playbook"}),
    )
    .unwrap();
    assert!(read.contains("Parse reference strings into author"));
    // a link form works as well as a title
    call(
        &brain,
        &mut used,
        json!({"action": "open", "id": "[[Reference Parsing]]"}),
    )
    .unwrap();
    assert_eq!(
        used.titles(),
        [
            "Citation Analysis",
            "Citation Analysis Playbook",
            "Reference Parsing"
        ]
    );
}

#[test]
fn results_report_the_budget_and_the_budget_holds() {
    let brain = Brain::load(
        &repo(),
        BrainSettings {
            turn_chars: 900,
            open_chars: 500,
            max_calls: 4,
            ..BrainSettings::default()
        },
    );
    let mut used = Consulted::default();
    let first = call(
        &brain,
        &mut used,
        json!({"action": "read", "id": "Citation Analysis Playbook"}),
    )
    .unwrap();
    assert!(first.contains("[brain budget: 1 of 4 calls"), "{first}");
    assert!(
        first.chars().count() < 500 + 80,
        "one result is cut to open_chars"
    );
    assert!(first.contains('…'));
    let second = call(
        &brain,
        &mut used,
        json!({"action": "read", "id": "Research QA Playbook"}),
    )
    .unwrap();
    assert!(second.contains("of 900 characters"));
    assert!(used.chars() <= 900);
    let third = call(&brain, &mut used, json!({"action": "index"}));
    let fourth = call(&brain, &mut used, json!({"action": "index"}));
    let refused = [third, fourth].into_iter().find_map(Result::err);
    let refused = refused.expect("the character budget or the call limit stops the walk");
    assert!(
        refused.contains("budget") || refused.contains("limit"),
        "{refused}"
    );
    // calls over the limit are refused whatever the characters left
    let mut many = Consulted::default();
    let mut last = Ok(String::new());
    for _ in 0..5 {
        last = call(
            &brain,
            &mut many,
            json!({"action": "open", "id": "Evaluation"}),
        );
    }
    assert!(last.unwrap_err().contains("limit of brain calls"));
}

#[test]
fn a_note_deeper_than_max_depth_is_refused_and_mistakes_are_answered_for_the_model() {
    let brain = Brain::load(
        &repo(),
        BrainSettings {
            max_depth: 1,
            ..BrainSettings::default()
        },
    );
    let mut used = Consulted::default();
    call(
        &brain,
        &mut used,
        json!({"action": "open", "id": "Evaluation"}),
    )
    .expect("a hub");
    let deep = call(
        &brain,
        &mut used,
        json!({"action": "read", "id": "Retrieval Metrics"}),
    )
    .unwrap_err();
    assert!(
        deep.contains("steps from the root; the limit is 1"),
        "{deep}"
    );
    let unknown = call(
        &brain,
        &mut used,
        json!({"action": "read", "id": "No Such Note"}),
    )
    .unwrap_err();
    assert!(unknown.starts_with("Error: no note named 'No Such Note'"));
    let bad = call(
        &brain,
        &mut used,
        json!({"action": "write", "id": "Evaluation"}),
    )
    .unwrap_err();
    assert!(bad.contains("Use index, open or read"));
    // the ids of what was refused never enter the evidence list
    assert_eq!(used.titles(), ["Evaluation"]);
}

#[test]
fn the_tool_names_the_hubs_and_has_no_writing_action() {
    let brain = brain();
    let schema = brain.tool_schema();
    assert_eq!(schema["function"]["name"], BRAIN_TOOL);
    let description = schema["function"]["description"].as_str().unwrap();
    assert!(description.contains("Citation Analysis") && description.contains("Ontology"));
    let actions = &schema["function"]["parameters"]["properties"]["action"]["enum"];
    assert_eq!(actions, &json!(["index", "open", "read"]));
}

fn tree_state(dir: &Path, out: &mut BTreeMap<String, Vec<u8>>) {
    for entry in std::fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            tree_state(&path, out);
        } else {
            out.insert(path.display().to_string(), std::fs::read(&path).unwrap());
        }
    }
}

#[test]
fn there_is_no_write_path_into_the_brain() {
    // 1. consulting everything changes nothing on disk
    let root = Path::new(env!("CARGO_TARGET_TMPDIR")).join("brain-no-write");
    let _ = std::fs::remove_dir_all(&root);
    copy(&repo().join(".laris/brain"), &root.join(".laris/brain"));
    let brain = Brain::load(&root, BrainSettings::default());
    let mut before = BTreeMap::new();
    tree_state(&root, &mut before);
    for title in brain.titles() {
        let mut used = Consulted::default();
        for action in ["open", "read"] {
            let _ = brain.consult(&json!({"action": action, "id": title}), &mut used);
        }
    }
    let mut after = BTreeMap::new();
    tree_state(&root, &mut after);
    assert_eq!(before, after);
    // 2. the service is built from reads only
    let source =
        std::fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("src/brain.rs"))
            .unwrap();
    for forbidden in [
        "fs::write",
        "File::create",
        "OpenOptions",
        "fs::remove",
        "fs::rename",
        "fs::copy",
        "create_dir",
        "VaultWriter",
    ] {
        assert!(!source.contains(forbidden), "brain.rs uses {forbidden}");
    }
}

fn copy(from: &Path, to: &Path) {
    std::fs::create_dir_all(to).unwrap();
    for entry in std::fs::read_dir(from).unwrap() {
        let entry = entry.unwrap();
        let target = to.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), target).unwrap();
        }
    }
}

#[test]
fn a_missing_or_broken_brain_is_a_problem_and_serves_nothing() {
    let empty = Path::new(env!("CARGO_TARGET_TMPDIR")).join("brain-missing");
    let _ = std::fs::remove_dir_all(&empty);
    std::fs::create_dir_all(&empty).unwrap();
    let none = Brain::load(&empty, BrainSettings::default());
    assert!(!none.offered() && none.problems == ["the brain folder is missing"]);
    assert_eq!(none.max_calls(), 0);
    assert!(none.brief("grounded-qa").is_none());
    let rootless = Path::new(env!("CARGO_TARGET_TMPDIR")).join("brain-rootless");
    let _ = std::fs::remove_dir_all(&rootless);
    std::fs::create_dir_all(rootless.join(".laris/brain")).unwrap();
    std::fs::write(rootless.join(".laris/brain/Other.md"), "text").unwrap();
    let broken = Brain::load(&rootless, BrainSettings::default());
    assert!(!broken.offered());
    assert_eq!(broken.problems, ["root note 'Brain Index' is missing"]);
    let off = Brain::load(
        &repo(),
        BrainSettings {
            enabled: false,
            ..BrainSettings::default()
        },
    );
    assert!(!off.offered() && off.texts().is_empty());
}

#[test]
fn a_route_to_nothing_is_a_problem_not_a_crash() {
    let root = Path::new(env!("CARGO_TARGET_TMPDIR")).join("brain-badroute");
    let _ = std::fs::remove_dir_all(&root);
    copy(&repo().join(".laris/brain"), &root.join(".laris/brain"));
    let index = root.join(".laris/brain/Brain Index.md");
    let mut text = std::fs::read_to_string(&index).unwrap();
    text.push_str("\nroute: ghost -> [[Nowhere]]\n");
    std::fs::write(&index, text).unwrap();
    let brain = Brain::load(&root, BrainSettings::default());
    assert!(brain.offered());
    assert_eq!(brain.problems, ["route 'ghost' points at nothing"]);
    assert!(brain.route("ghost").is_none());
}

#[test]
fn the_whole_brain_is_inside_the_guards_memory_budget() {
    let policy = Policy::load(&PolicyConfig::with_root(repo()), std::iter::empty(), None)
        .expect("the repository policy loads");
    let guard = policy.guard();
    assert!(
        !guard.leak.truncated,
        "the leak detector must cover every note: raise LARIS_SERVER__LEAK_MAX_SHINGLES"
    );
    // a run of the brain's own words is recognised
    let note = policy
        .brain()
        .texts()
        .into_iter()
        .find(|t| t.split_whitespace().count() > 40)
        .unwrap();
    let run = note
        .split_whitespace()
        .skip(5)
        .take(20)
        .collect::<Vec<_>>()
        .join(" ");
    assert!(guard.leak.leaked(&run));
}
