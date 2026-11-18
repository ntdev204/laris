//! Rule syntax and matching: names, patterns, resolved paths, chained commands.

mod common;

use common::{args, rig};
use laris_policy::{parse_rule, rule_matches, suggest_rule};
use serde_json::json;

#[test]
fn rules_parse_with_and_without_a_pattern() {
    let edit = parse_rule("Edit(src/**)").expect("rule");
    assert_eq!(
        (edit.tool.as_str(), edit.pattern.as_deref()),
        ("edit", Some("src/**"))
    );
    let bash = parse_rule("Bash").expect("rule");
    assert_eq!((bash.tool.as_str(), bash.pattern), ("bash", None));
    assert_eq!(parse_rule("*").expect("rule").tool, "*");
    assert!(parse_rule("((").is_none());
    assert!(parse_rule("").is_none());
    assert!(parse_rule("Edit(src").is_none());
}

#[test]
fn rule_matching_table() {
    let r = rig("table");
    std::fs::create_dir_all(r.project.join("src")).expect("src");
    let scope = r.scope();
    let cases = [
        ("Edit(src/**)", "Edit", json!({"path": "src/a/b.py"}), true),
        ("Edit(src/**)", "Edit", json!({"path": "tests/a.py"}), false),
        ("Edit(src/**)", "Write", json!({"path": "src/a.py"}), false),
        ("Write(*.md)", "Write", json!({"path": "README.md"}), true),
        (
            "Write(*.md)",
            "Write",
            json!({"path": "docs/README.md"}),
            false,
        ),
        (
            "Write(**/*.md)",
            "Write",
            json!({"path": "docs/README.md"}),
            true,
        ),
        (
            "Write(./notes.txt)",
            "Write",
            json!({"path": "notes.txt"}),
            true,
        ),
        (
            "Bash(git status:*)",
            "Bash",
            json!({"command": "git status"}),
            true,
        ),
        (
            "Bash(git status:*)",
            "Bash",
            json!({"command": "git status -s"}),
            true,
        ),
        (
            "Bash(git status:*)",
            "Bash",
            json!({"command": "git statusx"}),
            false,
        ),
        (
            "Bash(git status:*)",
            "Bash",
            json!({"command": "git push"}),
            false,
        ),
        ("Bash(ls)", "Bash", json!({"command": "ls"}), true),
        ("Bash(ls*)", "Bash", json!({"command": "ls -la"}), true),
        ("Bash", "Bash", json!({"command": "anything"}), true),
        ("*", "search_corpus", json!({"query": "x"}), true),
        ("read", "Read", json!({"path": "a"}), true),
        ("READ", "read", json!({"path": "a"}), true),
        ("Bash(ls)", "Read", json!({"path": "a"}), false),
        ("not a rule(", "Bash", json!({"command": "ls"}), false),
        (
            "search(perov*)",
            "search",
            json!({"query": "perovskite"}),
            true,
        ),
    ];
    for (rule, tool, arguments, expected) in cases {
        assert_eq!(
            rule_matches(rule, tool, &args(arguments.clone()), &scope, false),
            expected,
            "{rule} on {tool} {arguments}"
        );
    }
}

#[test]
fn path_rules_follow_the_resolved_path_not_the_spelling() {
    let r = rig("resolved");
    std::fs::create_dir_all(r.project.join("src")).expect("src");
    std::fs::create_dir_all(r.project.join("secret")).expect("secret");
    let scope = r.scope();
    let hit = |rule: &str, path: &str| {
        rule_matches(rule, "Write", &args(json!({ "path": path })), &scope, true)
    };
    assert!(hit("Write(src/**)", "src/../src/a.py"));
    assert!(!hit("Write(src/**)", "src/../secret/k"));
    assert!(hit("Write(secret/**)", "src/../secret/k"));
    // an absolute spelling of the same file is the same file
    let absolute = r.project.join("secret").join("k");
    assert!(hit("Write(secret/**)", absolute.to_str().expect("utf8")));
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(r.project.join("secret"), r.project.join("src/alias"))
            .expect("link");
        assert!(
            hit("Write(secret/**)", "src/alias/k"),
            "a link to a denied folder is that folder"
        );
        assert!(!hit("Write(src/**)", "src/alias/k"));
    }
}

#[test]
fn an_allow_rule_for_one_command_does_not_allow_a_chain() {
    let r = rig("chain");
    let scope = r.scope();
    let allow = |command: &str| {
        rule_matches(
            "Bash(git status:*)",
            "Bash",
            &args(json!({ "command": command })),
            &scope,
            false,
        )
    };
    assert!(allow("git status"));
    assert!(!allow("git status && rm -rf ~"));
    assert!(!allow("git status; rm -rf ~"));
    assert!(!allow("git status | sh"));
    assert!(!allow("git status $(rm -rf ~)"));
    assert!(!allow("git status `id`"));
    assert!(!allow("git status > /etc/passwd"));
    assert!(!allow("git status\nrm -rf ~"));
    // each part allowed: the chain is allowed
    assert!(rule_matches(
        "Bash(git:*)",
        "Bash",
        &args(json!({"command": "git status && git diff"})),
        &scope,
        false
    ));
}

#[test]
fn a_deny_or_ask_rule_fits_any_command_of_a_chain() {
    let r = rig("chain-deny");
    let scope = r.scope();
    let fits = |rule: &str, command: &str| {
        rule_matches(
            rule,
            "Bash",
            &args(json!({ "command": command })),
            &scope,
            true,
        )
    };
    assert!(fits("Bash(rm:*)", "ls && rm -rf x"));
    assert!(fits("Bash(rm:*)", "ls; rm x"));
    assert!(fits("Bash(rm:*)", "echo $(rm x)"));
    assert!(fits("Bash(rm:*)", "echo hi | rm x"));
    assert!(!fits("Bash(rm:*)", "ls && echo hi"));
}

#[test]
fn the_rule_an_always_answer_saves() {
    let s = |tool: &str, value: serde_json::Value| suggest_rule(tool, &args(value));
    assert_eq!(
        s("Bash", json!({"command": "git status -s"})),
        "bash(git status:*)"
    );
    assert_eq!(s("Bash", json!({"command": "make"})), "bash(make:*)");
    assert_eq!(
        s("Bash", json!({"command": "ls -la /tmp"})),
        "bash(ls:*)",
        "a flag is not part of the command name"
    );
    assert_eq!(s("Write", json!({"path": "src/a.rs"})), "write(src/a.rs)");
    assert_eq!(s("search", json!({"query": "x"})), "search");
    for rule in [
        suggest_rule("Bash", &args(json!({"command": "git status"}))),
        suggest_rule("Write", &args(json!({"path": "a.rs"}))),
    ] {
        assert!(parse_rule(&rule).is_some(), "{rule} parses");
    }
}
