//! The gate on real tools: a denied path is never written, approvals, hooks that block, and the loop's log.

mod common;

use common::{Scripted, args, exists, permissions, rig};
use laris_config::settings::{PermissionMode, Permissions};
use laris_config::{Catalogue, Settings};
use laris_core::{
    Driver, FollowModel, ModelAnswer, Recorder, ScriptedModel, ToolGate, ToolRunner, decode_record,
    replay,
};
use laris_policy::{
    Answer, Engine, HookRunner, HookedRunner, NoApprover, PolicyGate, ProjectState, Remember,
    writes_of,
};
use laris_protocol::{Event, ToolCall, ToolCallFunction};
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use laris_tools::{Context, Registry, RemoteTools, ToolError, function_schema, object_schema};
use serde_json::{Map, Value, json};
use std::sync::Arc;

struct Setup {
    rig: common::Rig,
    engine: Arc<Engine>,
    registry: Registry,
}

fn setup(name: &str, permissions: Permissions) -> Setup {
    let rig = rig(name);
    let ctx = Context::new(&rig.project, &Settings::default()).expect("context");
    let registry = Registry::with_local_tools(ctx);
    let engine = Arc::new(rig.engine_with(permissions, false));
    Setup {
        rig,
        engine,
        registry,
    }
}

impl Setup {
    fn gate(&self, approver: impl laris_policy::Approver + 'static) -> PolicyGate {
        PolicyGate::new(
            Arc::clone(&self.engine),
            writes_of(&self.registry),
            approver,
        )
    }

    /// The gate first, then the tool, as the loop does.
    fn through(&mut self, gate: &PolicyGate, name: &str, arguments: Value) -> Value {
        let arguments = args(arguments);
        match gate.check(name, &arguments) {
            Some(refusal) => json!({"error": {"code": refusal.code, "message": refusal.message}}),
            None => self.registry.call(name, &arguments),
        }
    }
}

fn code(result: &Value) -> &str {
    result["error"]["code"].as_str().unwrap_or("")
}

#[test]
fn a_denied_path_is_never_written_however_it_is_spelled() {
    let mut s = setup(
        "denied-path",
        permissions(
            &["Write", "Edit"],
            &[],
            &["Write(secret/**)", "Edit(secret/**)"],
        ),
    );
    s.rig.write_file("secret/old.txt", "keep\n");
    std::fs::create_dir_all(s.rig.project.join("src")).expect("src");
    #[cfg(unix)]
    std::os::unix::fs::symlink(
        s.rig.project.join("secret"),
        s.rig.project.join("src/alias"),
    )
    .expect("link");
    let gate = s.gate(NoApprover);

    let spellings = [
        "secret/new.txt",
        "./secret/new.txt",
        "src/../secret/new.txt",
        "secret//new.txt",
        "src/alias/new.txt",
    ];
    for path in spellings {
        let result = s.through(&gate, "Write", json!({"path": path, "content": "x"}));
        if cfg!(not(unix)) && path.contains("alias") {
            continue;
        }
        assert_eq!(code(&result), "permission_denied", "{path}: {result}");
    }
    let edit = s.through(
        &gate,
        "Edit",
        json!({"path": "src/alias/old.txt", "old_string": "keep", "new_string": "lost"}),
    );
    assert_eq!(code(&edit), "permission_denied");
    assert!(!exists(&s.rig.project.join("secret/new.txt")));
    assert_eq!(
        s.rig
            .project
            .join("secret/old.txt")
            .metadata()
            .map(|m| m.len())
            .ok(),
        Some(5)
    );
    assert_eq!(
        std::fs::read_to_string(s.rig.project.join("secret/old.txt")).expect("file"),
        "keep\n"
    );
    // outside the rule the same allow works
    let ok = s.through(
        &gate,
        "Write",
        json!({"path": "src/fine.txt", "content": "x"}),
    );
    assert!(ok.get("error").is_none(), "{ok}");
}

#[test]
fn deny_beats_an_approval_that_would_have_said_yes() {
    let mut s = setup("deny-vs-yes", permissions(&[], &[], &["Write(secret/**)"]));
    let yes = Scripted::new(vec![Answer::Once; 5]);
    let gate = s.gate(yes.clone());
    let result = s.through(&gate, "Write", json!({"path": "secret/k", "content": "x"}));
    assert_eq!(code(&result), "permission_denied");
    assert_eq!(yes.count(), 0, "a denied call is not even asked about");
    assert!(!exists(&s.rig.project.join("secret/k")));
}

#[test]
fn a_call_that_needs_approval_shows_a_diff_and_runs_only_on_yes() {
    let mut s = setup("approval", Permissions::default());
    s.rig.write_file("a.txt", "one\ntwo\nthree\n");
    let approver = Scripted::new(vec![Answer::Deny, Answer::Once]);
    let gate = s.gate(approver.clone());
    let change = json!({"path": "a.txt", "content": "one\nTWO\nthree\n"});

    let refused = s.through(&gate, "Write", change.clone());
    assert_eq!(code(&refused), "approval_denied");
    assert_eq!(s.rig.read("a.txt"), "one\ntwo\nthree\n", "nothing changed");

    let done = s.through(&gate, "Write", change);
    assert!(done.get("error").is_none(), "{done}");
    assert_eq!(s.rig.read("a.txt"), "one\nTWO\nthree\n");

    let asked = approver.asked.lock().expect("lock");
    assert_eq!(asked.len(), 2);
    assert_eq!(asked[0].tool, "Write");
    assert_eq!(asked[0].suggested_rule, "write(a.txt)");
    let diff = asked[0].preview.as_deref().expect("a diff");
    assert!(diff.contains("-two") && diff.contains("+TWO"), "{diff}");
    assert!(!diff.contains("one"), "common lines are left out: {diff}");
}

#[test]
fn a_new_file_is_previewed_as_all_added_lines() {
    let mut s = setup("preview-new", Permissions::default());
    let approver = Scripted::new(vec![Answer::Deny]);
    let gate = s.gate(approver.clone());
    s.through(
        &gate,
        "Write",
        json!({"path": "n.txt", "content": "a\nb\n"}),
    );
    let asked = approver.asked.lock().expect("lock");
    let diff = asked[0].preview.as_deref().expect("a diff");
    let removed = diff
        .lines()
        .any(|l| l.starts_with('-') && !l.starts_with("---"));
    assert!(
        diff.contains("+a") && diff.contains("+b") && !removed,
        "{diff}"
    );
    let mut s2 = setup("preview-edit", Permissions::default());
    let approver = Scripted::new(vec![Answer::Deny]);
    let gate = s2.gate(approver.clone());
    s2.through(
        &gate,
        "Edit",
        json!({"path": "n.txt", "old_string": "x", "new_string": "y"}),
    );
    let edit = approver.asked.lock().expect("lock")[0]
        .preview
        .clone()
        .expect("diff");
    assert!(edit.contains("-x") && edit.contains("+y"), "{edit}");
    // other tools have no preview
    let approver = Scripted::new(vec![Answer::Deny]);
    let gate = s2.gate(approver.clone());
    s2.through(&gate, "Bash", json!({"command": "make"}));
    assert!(approver.asked.lock().expect("lock")[0].preview.is_none());
}

#[test]
fn always_saves_the_rule_and_the_next_call_is_not_asked() {
    let mut s = setup("always", Permissions::default());
    let approver = Scripted::new(vec![Answer::Always(Remember::Project)]);
    let gate = s.gate(approver.clone());
    let first = s.through(&gate, "Bash", json!({"command": "echo hi"}));
    assert_eq!(
        first["output"].as_str().map(str::trim),
        Some("hi"),
        "{first}"
    );
    let second = s.through(&gate, "Bash", json!({"command": "echo hi there"}));
    assert_eq!(second["output"].as_str().map(str::trim), Some("hi there"));
    assert_eq!(approver.count(), 1);
    // a command of another name is still asked
    let other = s.through(&gate, "Bash", json!({"command": "rm -rf x"}));
    assert_eq!(code(&other), "approval_denied");
    assert_eq!(approver.count(), 2);
}

#[test]
fn plan_mode_refuses_changes_and_commands_but_reads() {
    let mut s = setup("plan-gate", permissions(&["Write", "Bash"], &[], &[]));
    s.engine.set_mode(PermissionMode::Plan).expect("mode");
    s.rig.write_file("a.txt", "x\n");
    let approver = Scripted::new(vec![Answer::Once; 3]);
    let gate = s.gate(approver.clone());
    for (tool, arguments) in [
        ("Write", json!({"path": "b.txt", "content": "x"})),
        ("Bash", json!({"command": "touch c"})),
        (
            "Edit",
            json!({"path": "a.txt", "old_string": "x", "new_string": "y"}),
        ),
    ] {
        let result = s.through(&gate, tool, arguments);
        assert_eq!(code(&result), "permission_denied", "{tool}: {result}");
    }
    assert!(!exists(&s.rig.project.join("b.txt")) && !exists(&s.rig.project.join("c")));
    assert_eq!(s.rig.read("a.txt"), "x\n");
    assert_eq!(approver.count(), 0);
    let read = s.through(&gate, "Read", json!({"path": "a.txt"}));
    assert_eq!(read["total_lines"], 1);
}

#[test]
fn a_tool_the_gate_does_not_know_is_taken_to_change_state() {
    let s = setup("unknown-tool", Permissions::default());
    let approver = Scripted::new(vec![Answer::Deny]);
    let gate = s.gate(approver.clone());
    let refusal = gate
        .check("mystery", &args(json!({"x": 1})))
        .expect("asked and refused");
    assert_eq!(refusal.code, "approval_denied");
    assert_eq!(approver.count(), 1);
}

struct Remote;

impl RemoteTools for Remote {
    fn schemas(&self) -> Vec<laris_protocol::ToolSchema> {
        vec![function_schema(
            "web_search",
            "search",
            object_schema(json!({"query": {"type": "string"}}), &["query"]),
        )]
    }

    fn call(&mut self, _name: &str, _arguments: &Map<String, Value>) -> Result<Value, ToolError> {
        Ok(json!({"text": "found"}))
    }
}

#[test]
fn a_remote_tool_is_asked_about_until_a_rule_allows_it() {
    let mut s = setup("remote", Permissions::default());
    s.registry.add_remote(Box::new(Remote)).expect("remote");
    let approver = Scripted::new(vec![Answer::Deny]);
    let gate = s.gate(approver.clone());
    let refused = s.through(&gate, "web_search", json!({"query": "x"}));
    assert_eq!(code(&refused), "approval_denied");
    assert_eq!(approver.count(), 1);

    s.engine
        .set_permissions(permissions(&["web_search"], &[], &[]));
    let allowed = s.through(&gate, "web_search", json!({"query": "x"}));
    assert_eq!(allowed["text"], "found");
    assert_eq!(approver.count(), 1, "the rule answered");
}

// -- hooks in the gate ---------------------------------------------------------------------------

fn hooked(s: &Setup, hooks: Value) -> Arc<HookRunner> {
    let settings = Settings {
        hooks: serde_json::from_value(hooks).expect("hooks"),
        ..Settings::default()
    };
    Arc::new(HookRunner::new(&settings, &s.rig.project, "s1"))
}

#[test]
fn a_pre_tool_hook_can_block_a_call_that_a_rule_allows() {
    let mut s = setup("hook-block", permissions(&["Write"], &[], &[]));
    let hooks = hooked(
        &s,
        json!({"PreToolUse": [{"matcher": "Write", "hooks": [
            {"type": "command", "command": "echo 'no writes today' >&2; exit 2"}]}]}),
    );
    let gate = s.gate(NoApprover).with_hooks(hooks);
    let result = s.through(&gate, "Write", json!({"path": "a.txt", "content": "x"}));
    assert_eq!(code(&result), "hook_blocked");
    assert!(
        result["error"]["message"]
            .as_str()
            .expect("m")
            .contains("no writes today")
    );
    assert!(!exists(&s.rig.project.join("a.txt")));
    // the matcher is for Write: a read is not touched
    s.rig.write_file("r.txt", "x\n");
    assert_eq!(
        s.through(&gate, "Read", json!({"path": "r.txt"}))["total_lines"],
        1
    );
}

#[test]
fn a_pre_tool_hook_cannot_grant_a_permission() {
    let mut s = setup("hook-grant", Permissions::default());
    let hooks = hooked(
        &s,
        json!({"PreToolUse": [{"matcher": "", "hooks": [
            {"type": "command", "command": "echo '{\"decision\": \"allow\", \"permissionDecision\": \"allow\"}'"}]}]}),
    );
    let approver = Scripted::new(vec![Answer::Deny]);
    let gate = s.gate(approver.clone()).with_hooks(hooks);
    let result = s.through(&gate, "Write", json!({"path": "a.txt", "content": "x"}));
    assert_eq!(code(&result), "approval_denied");
    assert_eq!(approver.count(), 1, "the person was still asked");
    assert!(!exists(&s.rig.project.join("a.txt")));
}

#[test]
fn a_denied_call_does_not_run_its_hooks() {
    let mut s = setup("hook-after-deny", permissions(&[], &[], &["Write"]));
    let marker = s.rig.base.join("ran");
    let hooks = hooked(
        &s,
        json!({"PreToolUse": [{"matcher": "", "hooks": [
            {"type": "command", "command": format!("touch {}", marker.display())}]}]}),
    );
    let gate = s.gate(NoApprover).with_hooks(hooks);
    let result = s.through(&gate, "Write", json!({"path": "a.txt", "content": "x"}));
    assert_eq!(code(&result), "permission_denied");
    assert!(!exists(&marker));
}

#[test]
fn a_post_tool_hook_adds_context_marked_untrusted() {
    let mut s = setup("hook-post", Permissions::default());
    s.rig.write_file("a.txt", "x\n");
    let hooks = hooked(
        &s,
        json!({"PostToolUse": [{"matcher": "Read", "hooks": [
            {"type": "command", "command": "cat >/dev/null; echo '{\"additionalContext\": \"remember the linter\"}'"}]}]}),
    );
    let taken = std::mem::replace(
        &mut s.registry,
        Registry::with_local_tools(
            Context::new(&s.rig.project, &Settings::default()).expect("context"),
        ),
    );
    let mut runner = HookedRunner::new(taken, hooks);
    let read = runner.run("Read", &args(json!({"path": "a.txt"})));
    assert_eq!(read["hook_context"], json!(["remember the linter"]));
    assert_eq!(read["untrusted"], true);
    assert_eq!(read["total_lines"], 1);
    // no hook for this tool: the result is untouched
    let glob = runner.run("Glob", &args(json!({"pattern": "*.txt"})));
    assert!(glob.get("hook_context").is_none());
}

// -- the loop ------------------------------------------------------------------------------------

fn call(id: &str, name: &str, arguments: Value) -> ToolCall {
    ToolCall {
        index: None,
        id: Some(id.to_owned()),
        kind: Default::default(),
        function: ToolCallFunction {
            name: name.to_owned(),
            arguments: arguments.to_string(),
            extra: Map::new(),
        },
        extra: Map::new(),
    }
}

fn turn(text: &str, calls: Vec<ToolCall>) -> ModelAnswer {
    ModelAnswer {
        text: text.to_owned(),
        tool_calls: calls,
        usage: None,
    }
}

#[test]
fn the_loop_refuses_through_the_gate_and_the_log_replays() {
    let s = setup("loop", permissions(&[], &[], &["Write(secret/**)"]));
    s.rig.write_file("a.txt", "alpha\n");
    let approver = Scripted::new(vec![Answer::Deny]);
    let gate = s.gate(approver.clone());
    let schemas = s.registry.schemas();
    let script = vec![
        turn(
            "",
            vec![
                call("c1", "Read", json!({"path": "a.txt"})),
                call("c2", "Write", json!({"path": "secret/k", "content": "x"})),
                call("c3", "Write", json!({"path": "b.txt", "content": "x"})),
            ],
        ),
        turn("done", vec![]),
    ];
    let store = Store::open(s.rig.base.join("space.sqlite"), DEFAULT_BUSY_TIMEOUT).expect("store");
    let recorder = Recorder::open(store, "s1", "t", 1.0).expect("open").0;
    let decider = FollowModel::new(Default::default(), Catalogue::english()).with_gate(gate);
    let mut driver = Driver::new(
        recorder,
        ScriptedModel::new(script),
        s.registry,
        decider,
        schemas,
        || 1.0,
    );
    let events = driver.send("go").expect("turn");
    let results: Vec<(String, Value)> = events
        .iter()
        .filter_map(|e| match e {
            Event::ToolResult { name, result, .. } => Some((name.clone(), result.clone())),
            _ => None,
        })
        .collect();
    assert_eq!(results.len(), 3, "every call was answered: {results:?}");
    assert_eq!(results[0].1["total_lines"], 1);
    assert_eq!(code(&results[1].1), "permission_denied");
    assert_eq!(code(&results[2].1), "approval_denied");
    assert!(!exists(&s.rig.project.join("secret/k")) && !exists(&s.rig.project.join("b.txt")));
    assert_eq!(
        approver.count(),
        1,
        "only the call no rule decided was asked"
    );

    let stored = driver.recorder().store().events("s1", 0).expect("events");
    let records: Vec<_> = stored
        .iter()
        .map(|e| decode_record(&e.data).expect("record"))
        .collect();
    let mut model = ScriptedModel::from_records(records.iter());
    let replayed = replay(&stored, Some(&mut model)).expect("replay");
    let recorded: String = stored
        .iter()
        .filter(|e| e.kind == "event")
        .map(|e| format!("{}\n", e.data))
        .collect();
    assert_eq!(
        replayed.output, recorded,
        "replay needs no gate and no approver"
    );
}

#[test]
fn the_state_file_is_kept_in_the_home_and_private() {
    let s = setup("state-private", Permissions::default());
    let state = ProjectState::new(&s.rig.home, &s.rig.project);
    state.add_allow("read").expect("save");
    assert!(state.path().starts_with(&s.rig.home));
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = state.path().metadata().expect("meta").permissions().mode();
        assert_eq!(mode & 0o777, 0o600);
    }
}
