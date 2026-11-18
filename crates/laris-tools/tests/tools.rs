//! One test group per tool: `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash`, `save_memory`, `use_skill`, and
//! rewind. They run on a temporary project folder; nothing touches anything outside it.

mod common;

use common::{exists, rig, rig_with};
use serde_json::json;
use std::time::{Duration, Instant};

// -- Read --------------------------------------------------------------------------------------

#[test]
fn read_numbers_lines_and_honours_the_range() {
    let mut r = rig("read-range");
    r.write_file("a.txt", "one\ntwo\nthree\nfour\n");
    let out = r.ok("Read", json!({"path": "a.txt", "offset": 2, "limit": 2}));
    assert_eq!(out["text"], "     2\ttwo\n     3\tthree");
    assert_eq!(out["total_lines"], 4);
    assert_eq!(
        (out["start"].as_u64(), out["end"].as_u64()),
        (Some(2), Some(3))
    );
    assert_eq!(out["truncated"], true);
    assert!(
        !out["path"].as_str().expect("path").starts_with('/'),
        "never an absolute path"
    );
    assert_eq!(r.ok("Read", json!({"path": "a.txt"}))["truncated"], false);
    // beyond the end: nothing, not a failure
    assert_eq!(
        r.ok("Read", json!({"path": "a.txt", "offset": 99}))["text"],
        ""
    );
}

#[test]
fn read_never_returns_more_lines_than_the_setting_allows() {
    let mut r = rig_with("read-cap", |s| s.tools.read_max_lines = 3);
    r.write_file("long.txt", "1\n2\n3\n4\n5\n");
    let out = r.ok("Read", json!({"path": "long.txt", "limit": 100}));
    assert_eq!(out["text"].as_str().expect("text").lines().count(), 3);
    assert_eq!(out["truncated"], true);
}

#[test]
fn read_refuses_secrets_binary_missing_large_folders_and_other_places() {
    let mut r = rig_with("read-refuse", |s| s.tools.edit_max_bytes = 100);
    r.write_file(".env", "TOKEN=abc");
    r.write_file("sub/key.pem", "-----BEGIN");
    r.write_file("bin.dat", "\u{0}\u{1}\u{2}");
    r.write_file("big.txt", &"x".repeat(200));
    std::fs::write(r.base.join("outside.txt"), "x").expect("outside");
    std::os::unix::fs::symlink(r.base.join("outside.txt"), r.project.join("link")).expect("link");
    std::os::unix::fs::symlink(r.project.join(".env"), r.project.join("innocent")).expect("link");
    assert_eq!(r.code("Read", json!({"path": ".env"})), "denied");
    assert_eq!(r.code("Read", json!({"path": "sub/key.pem"})), "denied");
    assert_eq!(
        r.code("Read", json!({"path": "innocent"})),
        "denied",
        "a link to a secret is a secret"
    );
    assert_eq!(r.code("Read", json!({"path": "bin.dat"})), "binary");
    assert_eq!(r.code("Read", json!({"path": "big.txt"})), "too_large");
    assert_eq!(r.code("Read", json!({"path": "missing.txt"})), "not_found");
    assert_eq!(r.code("Read", json!({"path": "sub"})), "is_directory");
    assert_eq!(
        r.code("Read", json!({"path": "../outside.txt"})),
        "outside_project"
    );
    assert_eq!(
        r.code("Read", json!({"path": "link"})),
        "outside_project",
        "a link cannot leave"
    );
    let absolute = r.base.join("outside.txt");
    assert_eq!(r.code("Read", json!({"path": absolute})), "outside_project");
}

#[test]
fn an_additional_directory_is_readable_and_writable() {
    let base = common::temp_dir("extra");
    let extra = base.join("extra");
    std::fs::create_dir_all(&extra).expect("extra");
    std::fs::write(extra.join("n.txt"), "note\n").expect("file");
    let extra_text = extra.to_string_lossy().into_owned();
    let mut r = rig_with("extra-rig", |s| {
        s.permissions.additional_directories = vec![extra_text]
    });
    let path = extra.join("n.txt");
    assert_eq!(r.ok("Read", json!({"path": path}))["total_lines"], 1);
    r.ok(
        "Write",
        json!({"path": extra.join("m.txt"), "content": "x"}),
    );
    assert!(extra.join("m.txt").is_file());
}

// -- Write -------------------------------------------------------------------------------------

#[test]
fn write_creates_overwrites_redacts_and_checkpoints() {
    let mut r = rig("write");
    let out = r.ok(
        "Write",
        json!({"path": "pkg/new.txt", "content": "print(1)\n"}),
    );
    assert_eq!(
        out,
        json!({"path": "pkg/new.txt", "bytes": 9, "created": true})
    );
    assert_eq!(r.read_file("pkg/new.txt"), "print(1)\n");
    assert_eq!(
        r.ok(
            "Write",
            json!({"path": "pkg/new.txt", "content": "print(2)\n"})
        )["created"],
        false
    );
    let tools: Vec<String> = r
        .registry
        .context()
        .checkpoints
        .as_ref()
        .expect("on")
        .list()
        .into_iter()
        .map(|(_, t)| t)
        .collect();
    assert_eq!(tools, ["Write", "Write"]);
    assert!(
        !exists(&r.project.join("pkg/new.txt.laris-tmp")),
        "no temporary file is left"
    );
}

#[test]
fn write_runs_the_redactor_before_anything_is_stored() {
    let base = common::temp_dir("redact");
    let project = base.join("p");
    std::fs::create_dir_all(&project).expect("project");
    let ctx = laris_tools::Context::new(&project, &laris_config::Settings::default())
        .expect("ctx")
        .with_redactor(Box::new(|t| t.replace("sk-secret", "[redacted]")));
    let mut registry = laris_tools::Registry::with_local_tools(ctx);
    registry.call(
        "Write",
        &common::args(json!({"path": "c.txt", "content": "key = sk-secret\n"})),
    );
    assert_eq!(
        std::fs::read_to_string(project.join("c.txt")).expect("file"),
        "key = [redacted]\n"
    );
}

#[test]
fn write_and_edit_never_touch_forbidden_places() {
    let mut r = rig("write-forbidden");
    for (path, code) in [
        (".git/config", "denied"),
        ("sub/.git/hooks/pre-commit", "denied"),
        (".laris/prompts/x.md", "denied"),
        (".laris/commands/evil.md", "denied"),
        (".env", "denied"),
        ("deploy/id_rsa", "denied"),
        ("../escape.txt", "outside_project"),
        ("/etc/laris-test", "outside_project"),
    ] {
        assert_eq!(
            r.code("Write", json!({"path": path, "content": "x"})),
            code,
            "Write {path}"
        );
        let edit = r.code(
            "Edit",
            json!({"path": path, "old_string": "a", "new_string": "b"}),
        );
        assert!(edit == code || edit == "not_found", "Edit {path}: {edit}");
    }
    assert!(!exists(&r.base.join("escape.txt")));
    assert!(!exists(&r.project.join(".git")));
    assert!(!exists(&r.project.join(".laris")));
    assert!(
        r.registry
            .context()
            .checkpoints
            .as_ref()
            .expect("on")
            .list()
            .is_empty(),
        "nothing changed, nothing saved"
    );
}

#[test]
fn write_cannot_follow_a_link_out_of_the_project() {
    let mut r = rig("write-link");
    std::fs::write(r.base.join("victim.txt"), "keep").expect("victim");
    std::os::unix::fs::symlink(&r.base, r.project.join("sneaky")).expect("folder link");
    std::os::unix::fs::symlink(r.base.join("victim.txt"), r.project.join("file-link"))
        .expect("file link");
    std::os::unix::fs::symlink(r.base.join("not-yet"), r.project.join("dangling"))
        .expect("dangling");
    assert_eq!(
        r.code(
            "Write",
            json!({"path": "sneaky/victim.txt", "content": "x"})
        ),
        "outside_project"
    );
    assert_eq!(
        r.code("Write", json!({"path": "file-link", "content": "x"})),
        "outside_project"
    );
    assert_eq!(
        r.code("Write", json!({"path": "dangling", "content": "x"})),
        "outside_project"
    );
    assert_eq!(
        std::fs::read_to_string(r.base.join("victim.txt")).expect("victim"),
        "keep"
    );
    assert!(!exists(&r.base.join("not-yet")));
}

#[test]
fn write_refuses_a_folder_and_content_over_the_limit() {
    let mut r = rig_with("write-limit", |s| s.tools.edit_max_bytes = 10);
    r.write_file("d/x", "1");
    assert_eq!(
        r.code("Write", json!({"path": "d", "content": "x"})),
        "is_directory"
    );
    assert_eq!(
        r.code("Write", json!({"path": "big", "content": "01234567890"})),
        "too_large"
    );
    assert!(!exists(&r.project.join("big")));
}

// -- Edit --------------------------------------------------------------------------------------

#[test]
fn edit_needs_a_unique_exact_match() {
    let mut r = rig("edit");
    r.write_file("m.txt", "a = 1\nb = 2\na = 1\n");
    let same =
        |old: &str, new: &str| json!({"path": "m.txt", "old_string": old, "new_string": new});
    assert_eq!(r.code("Edit", same("zzz", "y")), "not_found");
    assert_eq!(r.code("Edit", same("b = 2", "b = 2")), "no_change");
    assert_eq!(r.code("Edit", same("", "x")), "invalid_arguments");
    let many = r.call("Edit", same("a = 1", "a = 9"));
    assert_eq!(many["error"]["code"], "not_unique");
    assert_eq!(many["error"]["matches"], 2);
    assert_eq!(
        r.read_file("m.txt"),
        "a = 1\nb = 2\na = 1\n",
        "nothing changed so far"
    );
    assert_eq!(r.ok("Edit", same("b = 2", "b = 3"))["replacements"], 1);
    assert_eq!(r.read_file("m.txt"), "a = 1\nb = 3\na = 1\n");
    let all = r.ok(
        "Edit",
        json!({"path": "m.txt", "old_string": "a = 1", "new_string": "a = 9", "replace_all": true}),
    );
    assert_eq!(all["replacements"], 2);
    assert_eq!(r.read_file("m.txt"), "a = 9\nb = 3\na = 9\n");
    assert_eq!(
        r.code(
            "Edit",
            json!({"path": "nope.txt", "old_string": "a", "new_string": "b"})
        ),
        "not_found"
    );
}

#[test]
fn edit_keeps_the_file_mode_and_leaves_no_temporary_file() {
    use std::os::unix::fs::PermissionsExt;
    let mut r = rig("edit-mode");
    r.write_file("run.sh", "echo a\n");
    std::fs::set_permissions(
        r.project.join("run.sh"),
        std::fs::Permissions::from_mode(0o750),
    )
    .expect("mode");
    r.ok(
        "Edit",
        json!({"path": "run.sh", "old_string": "a", "new_string": "b"}),
    );
    let mode = std::fs::metadata(r.project.join("run.sh"))
        .expect("meta")
        .permissions()
        .mode()
        & 0o777;
    assert_eq!(mode, 0o750);
    assert!(!exists(&r.project.join("run.sh.laris-tmp")));
}

// -- Glob and Grep -----------------------------------------------------------------------------

fn tree(r: &common::Rig) {
    r.write_file("src/main.rs", "fn main() {}\n// TODO one\n");
    r.write_file("src/util/mod.rs", "pub fn util() {}\n// todo two\n");
    r.write_file("src/util/notes.md", "TODO three\n");
    r.write_file("README.md", "readme\n");
    r.write_file("node_modules/dep/index.js", "TODO hidden\n");
    r.write_file(".git/HEAD", "TODO hidden\n");
    r.write_file(".env", "TODO=secret\n");
    r.write_file("bin.dat", "TODO\u{0}");
}

#[test]
fn glob_matches_patterns_and_skips_dependencies_git_and_secrets() {
    let mut r = rig("glob");
    tree(&r);
    let files = |r: &mut common::Rig, pattern: &str| -> Vec<String> {
        let out = r.ok("Glob", json!({"pattern": pattern}));
        out["files"]
            .as_array()
            .expect("files")
            .iter()
            .map(|v| v.as_str().expect("s").to_owned())
            .collect()
    };
    assert_eq!(files(&mut r, "**/*.rs"), ["src/main.rs", "src/util/mod.rs"]);
    assert_eq!(files(&mut r, "src/*.rs"), ["src/main.rs"]);
    assert_eq!(
        files(&mut r, "**/*.{md,rs}"),
        [
            "README.md",
            "src/main.rs",
            "src/util/mod.rs",
            "src/util/notes.md"
        ]
    );
    assert_eq!(
        files(&mut r, "src/**"),
        ["src/main.rs", "src/util/mod.rs", "src/util/notes.md"]
    );
    assert_eq!(files(&mut r, "*.md"), ["README.md"]);
    assert_eq!(
        files(&mut r, "**/index.js"),
        Vec::<String>::new(),
        "node_modules is skipped"
    );
    assert_eq!(
        files(&mut r, ".env"),
        Vec::<String>::new(),
        "a secret is not listed"
    );
    assert_eq!(
        files(&mut r, "**/HEAD"),
        Vec::<String>::new(),
        ".git is skipped"
    );
    let inner = r.ok("Glob", json!({"pattern": "*.rs", "path": "src/util"}));
    assert_eq!(inner["files"], json!(["src/util/mod.rs"]));
    assert_eq!(
        r.code("Glob", json!({"pattern": "*", "path": "README.md"})),
        "not_a_directory"
    );
    assert_eq!(r.code("Glob", json!({"pattern": "[a"})), "invalid_pattern");
    assert_eq!(
        r.code("Glob", json!({"pattern": "*", "path": ".."})),
        "outside_project"
    );
}

#[test]
fn glob_is_cut_at_the_limit_and_hides_links_that_leave_the_project() {
    let mut r = rig_with("glob-cut", |s| s.tools.glob_max_results = 2);
    for n in 0..5 {
        r.write_file(&format!("f{n}.txt"), "x");
    }
    std::fs::write(r.base.join("outside.txt"), "x").expect("outside");
    std::os::unix::fs::symlink(r.base.join("outside.txt"), r.project.join("zz-link.txt"))
        .expect("link");
    let out = r.ok("Glob", json!({"pattern": "*.txt"}));
    assert_eq!(out["files"], json!(["f0.txt", "f1.txt"]));
    assert_eq!(out["truncated"], true);
    let mut r2 = rig("glob-link");
    std::fs::write(r2.base.join("outside.txt"), "x").expect("outside");
    std::os::unix::fs::symlink(r2.base.join("outside.txt"), r2.project.join("l.txt"))
        .expect("link");
    assert_eq!(
        r2.ok("Glob", json!({"pattern": "*.txt"}))["files"],
        json!([])
    );
}

#[test]
fn grep_finds_lines_with_numbers_and_honours_filters() {
    let mut r = rig("grep");
    tree(&r);
    let out = r.ok("Grep", json!({"pattern": "TODO"}));
    let hits: Vec<(String, u64)> = out["matches"]
        .as_array()
        .expect("m")
        .iter()
        .map(|m| {
            (
                m["path"].as_str().expect("p").to_owned(),
                m["line"].as_u64().expect("l"),
            )
        })
        .collect();
    assert_eq!(
        hits,
        [
            ("src/main.rs".to_owned(), 2),
            ("src/util/notes.md".to_owned(), 1)
        ]
    );
    assert_eq!(out["truncated"], false);
    let folded = r.ok(
        "Grep",
        json!({"pattern": "todo", "ignore_case": true, "glob": "*.rs"}),
    );
    assert_eq!(folded["matches"].as_array().expect("m").len(), 2);
    let single = r.ok(
        "Grep",
        json!({"pattern": "util", "path": "src/util/mod.rs"}),
    );
    assert_eq!(single["matches"][0]["text"], "pub fn util() {}");
    assert_eq!(r.code("Grep", json!({"pattern": "("})), "invalid_pattern");
    assert_eq!(
        r.code("Grep", json!({"pattern": "x", "glob": "[a"})),
        "invalid_pattern"
    );
    assert_eq!(
        r.code("Grep", json!({"pattern": "x", "path": "../"})),
        "outside_project"
    );
}

#[test]
fn grep_is_cut_at_the_limit_and_skips_large_files_and_long_lines_are_clipped() {
    let mut r = rig_with("grep-cut", |s| {
        s.tools.grep_max_results = 3;
        s.tools.grep_max_file_bytes = 500;
    });
    r.write_file("many.txt", &"hit\n".repeat(10));
    r.write_file("huge.txt", &format!("hit {}\n", "x".repeat(1000)));
    r.write_file("long.txt", &format!("needle {}\n", "y".repeat(1000)));
    let out = r.ok("Grep", json!({"pattern": "hit"}));
    assert_eq!(out["matches"].as_array().expect("m").len(), 3);
    assert_eq!(out["truncated"], true);
    assert!(
        out["matches"]
            .as_array()
            .expect("m")
            .iter()
            .all(|m| m["path"] != "huge.txt")
    );
    let two = r.ok("Grep", json!({"pattern": "hit", "max_results": 2}));
    assert_eq!(two["matches"].as_array().expect("m").len(), 2);
    let long = r.ok("Grep", json!({"pattern": "needle", "path": "long.txt"}));
    assert!(
        long["matches"].as_array().expect("m").is_empty(),
        "a file over the size limit is not searched"
    );
    let mut r = rig("grep-long");
    r.write_file("long.txt", &format!("needle {}\n", "y".repeat(1000)));
    let clipped = r.ok("Grep", json!({"pattern": "needle"}));
    assert_eq!(
        clipped["matches"][0]["text"]
            .as_str()
            .expect("t")
            .chars()
            .count(),
        300
    );
}

// -- Bash --------------------------------------------------------------------------------------

#[test]
fn bash_runs_a_command_and_reports_its_exit_code_and_merged_output() {
    let mut r = rig("bash");
    let out = r.ok("Bash", json!({"command": "echo out; echo err >&2; exit 3"}));
    assert_eq!(out["exit_code"], 3);
    assert_eq!(out["timed_out"], false);
    assert_eq!(out["output"], "out\nerr\n");
    assert_eq!(out["cwd"], ".");
    r.write_file("sub/f.txt", "x");
    let inner = r.ok("Bash", json!({"command": "ls; pwd", "cwd": "sub"}));
    assert!(inner["output"].as_str().expect("o").starts_with("f.txt\n"));
    assert_eq!(inner["cwd"], "sub");
    assert_eq!(
        r.code("Bash", json!({"command": "true", "cwd": "../.."})),
        "outside_project"
    );
    assert_eq!(
        r.code("Bash", json!({"command": "true", "cwd": "sub/f.txt"})),
        "not_a_directory"
    );
}

#[test]
fn bash_ends_a_command_that_runs_too_long_with_everything_it_started() {
    let mut r = rig("bash-timeout");
    let started = Instant::now();
    let out = r.ok("Bash", json!({"command": "echo start; (sleep 30; echo late > late.txt) & sleep 30", "timeout_s": 1}));
    assert!(
        started.elapsed() < Duration::from_secs(20),
        "returned at the limit, not when the command ended"
    );
    assert_eq!(out["timed_out"], true);
    assert_eq!(out["exit_code"], json!(null));
    assert!(out["output"].as_str().expect("o").contains("start"));
    std::thread::sleep(Duration::from_millis(300));
    assert!(
        !exists(&r.project.join("late.txt")),
        "the child was killed too"
    );
}

#[test]
fn bash_asks_for_no_more_time_than_the_setting_allows() {
    let mut r = rig_with("bash-max", |s| s.tools.bash_max_timeout_seconds = 1.0);
    let started = Instant::now();
    let out = r.ok("Bash", json!({"command": "sleep 20", "timeout_s": 100}));
    assert_eq!(out["timed_out"], true);
    assert!(started.elapsed() < Duration::from_secs(10));
}

#[test]
fn bash_output_is_cut_and_a_noisy_command_does_not_hang() {
    let mut r = rig_with("bash-out", |s| s.tools.bash_output_max_chars = 50);
    let out = r.ok("Bash", json!({"command": "yes line | head -c 3000000"}));
    let text = out["output"].as_str().expect("o");
    assert!(text.ends_with("… (output truncated)"));
    assert_eq!(
        text.chars().count(),
        50 + "\n… (output truncated)".chars().count()
    );
    assert_eq!(out["exit_code"], 0);
}

#[test]
fn bash_gets_a_clean_environment_plus_the_settings_env() {
    let mut r = rig_with("bash-env", |s| {
        s.env.insert("LARIS_TEST_VALUE".to_owned(), "42".to_owned());
    });
    let out = r.ok(
        "Bash",
        json!({"command": "echo \"[$LARIS_TEST_VALUE][${CARGO_MANIFEST_DIR:-unset}]\""}),
    );
    assert_eq!(
        out["output"], "[42][unset]\n",
        "the test process has CARGO_MANIFEST_DIR; the command must not"
    );
    let mut inherit = rig_with("bash-inherit", |s| s.sandbox.inherit_env = true);
    let out = inherit.ok(
        "Bash",
        json!({"command": "echo \"${CARGO_MANIFEST_DIR:-unset}\""}),
    );
    assert_ne!(out["output"], "unset\n");
}

// -- save_memory and use_skill -----------------------------------------------------------------

#[test]
fn save_memory_creates_appends_replaces_and_checks_the_name() {
    let mut r = rig("memory");
    let made = r.ok(
        "save_memory",
        json!({"name": "style", "content": "  use tabs  "}),
    );
    assert_eq!(made, json!({"path": "memory/style.md", "mode": "created"}));
    assert_eq!(
        r.ok(
            "save_memory",
            json!({"name": "style.md", "content": "no semicolons"})
        )["mode"],
        "appended"
    );
    let file = r.base.join("memory/style.md");
    assert_eq!(
        std::fs::read_to_string(&file).expect("file"),
        "use tabs\n\nno semicolons\n"
    );
    assert_eq!(
        r.ok(
            "save_memory",
            json!({"name": "style", "content": "fresh", "append": false})
        )["mode"],
        "replaced"
    );
    assert_eq!(std::fs::read_to_string(&file).expect("file"), "fresh\n");
    for bad in ["../x", "Upper", "a/b", "", "-x", &"n".repeat(65)] {
        assert_eq!(
            r.code("save_memory", json!({"name": bad, "content": "x"})),
            "invalid_arguments",
            "{bad}"
        );
    }
    assert_eq!(
        r.code("save_memory", json!({"name": "ok", "content": "  "})),
        "invalid_arguments"
    );
    assert!(!exists(&r.base.join("x.md")));
}

#[test]
fn save_memory_is_off_without_a_memory_folder() {
    let base = common::temp_dir("no-memory");
    let ctx = laris_tools::Context::new(&base, &laris_config::Settings::default()).expect("ctx");
    let mut registry = laris_tools::Registry::with_local_tools(ctx);
    let out = registry.call(
        "save_memory",
        &common::args(json!({"name": "a", "content": "b"})),
    );
    assert_eq!(out["error"]["code"], "no_memory");
}

fn skill(r: &common::Rig, name: &str, front: &str, body: &str) {
    let dir = r.base.join("skills").join(name);
    std::fs::create_dir_all(dir.join("references")).expect("skill folder");
    std::fs::write(
        dir.join("SKILL.md"),
        format!("---\n{front}\n---\n\n{body}\n"),
    )
    .expect("skill");
}

#[test]
fn use_skill_loads_instructions_references_and_refuses_the_rest() {
    let mut r = rig_with("skills", |s| s.tools.skill_max_chars = 40);
    skill(
        &r,
        "review",
        "name: review\ndescription: >\n  Review a change\n  carefully.",
        "Step one.\nStep two.",
    );
    std::fs::write(
        r.base.join("skills/review/references/checklist.md"),
        "- a\n",
    )
    .expect("ref");
    skill(&r, "wrong", "name: other\ndescription: x", "body");
    skill(
        &r,
        "long",
        "name: long\ndescription: \"A long one\"",
        &"word ".repeat(30),
    );
    let out = r.ok(
        "use_skill",
        json!({"name": "/Review", "arguments": "the diff"}),
    );
    assert_eq!(out["name"], "review");
    assert_eq!(out["description"], "Review a change carefully.");
    assert_eq!(out["instructions"], "Step one.\nStep two.");
    assert_eq!(out["truncated"], false);
    assert_eq!(out["arguments"], "the diff");
    assert_eq!(
        out["references"],
        json!([{"path": "references/checklist.md", "bytes": 4}])
    );
    let long = r.ok("use_skill", json!({"name": "long"}));
    assert_eq!(long["truncated"], true);
    assert_eq!(
        long["instructions"].as_str().expect("i").chars().count(),
        40
    );
    assert_eq!(
        r.code("use_skill", json!({"name": "wrong"})),
        "invalid_skill"
    );
    let unknown = r.call("use_skill", json!({"name": "nope"}));
    assert_eq!(unknown["error"]["code"], "unknown_skill");
    assert!(
        unknown["error"]["message"]
            .as_str()
            .expect("m")
            .contains("long, review, wrong")
    );
    assert_eq!(
        r.code("use_skill", json!({"name": "../skills/review"})),
        "unknown_skill"
    );
}

// -- checkpoints and rewind --------------------------------------------------------------------

#[test]
fn rewind_undoes_edits_newest_first_and_removes_files_that_were_created() {
    let mut r = rig("rewind");
    r.write_file("a.txt", "v0\n");
    r.ok(
        "Edit",
        json!({"path": "a.txt", "old_string": "v0", "new_string": "v1"}),
    );
    r.ok("Write", json!({"path": "a.txt", "content": "v2\n"}));
    r.ok("Write", json!({"path": "new/b.txt", "content": "b\n"}));
    r.ok("save_memory", json!({"name": "n", "content": "remember"}));

    let done = r.registry.rewind(Some(2)).expect("rewind");
    let status: Vec<(&str, &str)> = done
        .iter()
        .map(|d| {
            (
                d["path"].as_str().expect("p"),
                d["status"].as_str().expect("s"),
            )
        })
        .collect();
    assert_eq!(
        status,
        [("memory/n.md", "removed"), ("new/b.txt", "removed")]
    );
    assert!(!exists(&r.base.join("memory/n.md")) && !exists(&r.project.join("new/b.txt")));
    assert_eq!(r.read_file("a.txt"), "v2\n");

    let done = r.registry.rewind(None).expect("rewind all");
    assert_eq!(done.len(), 2);
    assert_eq!(r.read_file("a.txt"), "v0\n");
    assert!(
        r.registry
            .context()
            .checkpoints
            .as_ref()
            .expect("on")
            .list()
            .is_empty()
    );
    assert!(r.registry.rewind(Some(1)).expect("nothing").is_empty());
}

#[test]
fn rewind_never_writes_where_a_tool_could_not_and_checkpoints_are_capped() {
    let mut r = rig_with("rewind-cap", |s| s.tools.checkpoint_keep = 2);
    for n in 0..4 {
        r.ok(
            "Write",
            json!({"path": format!("f{n}.txt"), "content": "x"}),
        );
    }
    let kept: Vec<_> = r
        .registry
        .context()
        .checkpoints
        .as_ref()
        .expect("on")
        .list();
    assert_eq!(kept.len(), 2, "the oldest are dropped");

    // an index a hostile process rewrote to point at a protected file is skipped, not obeyed
    let folder = r.base.join("checkpoints");
    std::fs::write(r.project.join("keep.txt"), "mine").expect("keep");
    std::fs::create_dir_all(r.project.join(".git")).expect("git");
    let evil = r.project.join(".git/config");
    std::fs::write(&evil, "original").expect("git config");
    std::fs::write(folder.join("9.blob"), "planted").expect("blob");
    let line = json!({"seq": 9, "path": evil.to_string_lossy(), "existed": true, "tool": "Write"});
    let mut index = std::fs::read_to_string(folder.join("index.jsonl")).expect("index");
    index.push_str(&format!("{line}\n"));
    std::fs::write(folder.join("index.jsonl"), index).expect("index");
    let done = r.registry.rewind(Some(1)).expect("rewind");
    assert_eq!(done[0]["status"], "skipped");
    assert_eq!(done[0]["why"], "not allowed");
    assert_eq!(std::fs::read_to_string(&evil).expect("config"), "original");
}

#[test]
fn rewind_without_checkpoints_is_a_typed_error() {
    let base = common::temp_dir("no-checkpoints");
    let ctx = laris_tools::Context::new(&base, &laris_config::Settings::default()).expect("ctx");
    let registry = laris_tools::Registry::with_local_tools(ctx);
    assert_eq!(
        registry.rewind(None).expect_err("none").code,
        "no_checkpoints"
    );
}
