//! The Agentic scenarios (`docs/testing/AGENTIC_SCENARIOS.md`) translated to the Rust loop, and the
//! decider seam. A scripted model plays the model, so nothing here says anything about the quality of a trained
//! model: the foundation model is NOT QUALIFIED.

use laris_config::Catalogue;
use laris_config::settings::{Agent, PlanMode, PlanSettings, Reflect};
use laris_core::{
    Action, Clock, CoreError, Decider, Driver, FollowModel, Model, ModelAnswer, ModelError,
    ModelRequest, Pending, Record, Recorder, Refusal, ScriptedModel, ToolGate, ToolRunner, replay,
};
use laris_protocol::{ChatMessage, Content, Event, Role, ToolCall, ToolCallFunction, ToolSchema};
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use serde_json::{Map, Value, json};
use std::cell::RefCell;
use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

const CITED: &str = "Perovskite cells reach 25% efficiency [source #1].";
const LONG_GOAL: &str =
    "Find the efficiency of perovskite solar cells then compare it with silicon and report";

// -- rig ---------------------------------------------------------------------------------------

fn temp_dir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("laris-agentic-{name}-{}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir
}

fn store(dir: &Path) -> Store {
    Store::open(dir.join("space.sqlite"), DEFAULT_BUSY_TIMEOUT).expect("store")
}

fn recorder(dir: &Path) -> Recorder {
    Recorder::open(store(dir), "s1", "t", 1.0).expect("open").0
}

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

fn plan(id: &str, steps: &[(&str, &str)]) -> ToolCall {
    let steps: Vec<Value> = steps
        .iter()
        .map(|(text, status)| json!({"text": text, "status": status}))
        .collect();
    call(id, "update_plan", json!({ "steps": steps }))
}

fn search(id: &str, query: &str) -> ToolCall {
    call(id, "search_corpus", json!({"query": query, "top_k": 3}))
}

fn turn(text: &str, calls: Vec<ToolCall>) -> ModelAnswer {
    ModelAnswer {
        text: text.to_owned(),
        tool_calls: calls,
        usage: None,
    }
}

fn schema(name: &str) -> ToolSchema {
    serde_json::from_value(json!({"type": "function", "function": {"name": name}})).expect("schema")
}

/// The tools of the scenarios: a corpus holding one passage, a file writer, and a log of what ran.
#[derive(Clone, Default)]
struct Tools {
    ran: Rc<RefCell<Vec<String>>>,
    empty_corpus: bool,
    interrupt: Rc<RefCell<Option<Arc<AtomicBool>>>>,
}

impl ToolRunner for Tools {
    fn run(&mut self, name: &str, arguments: &Map<String, Value>) -> Value {
        self.ran.borrow_mut().push(name.to_owned());
        if let Some(flag) = self.interrupt.borrow().as_ref() {
            flag.store(true, Ordering::SeqCst);
        }
        match name {
            "search_corpus" if self.empty_corpus => {
                json!({"error": {"code": "no_documents", "message": "no documents were ingested"}})
            }
            "search_corpus" => {
                let query = arguments.get("query").and_then(Value::as_str).unwrap_or("");
                if query.contains("perovskite") {
                    json!({"hits": [{"text": "Perovskite cells reach 25% efficiency."}]})
                } else {
                    json!({"hits": []})
                }
            }
            "write_file" => json!({"written": true}),
            _ => json!({"error": {"code": "unknown_tool", "message": name}}),
        }
    }
}

/// A gate that refuses writes, as a mode without approval does (the real policy is T133).
struct NoWrites;

impl ToolGate for NoWrites {
    fn check(&self, name: &str, _arguments: &Map<String, Value>) -> Option<Refusal> {
        (name == "write_file").then(|| Refusal {
            code: "approval_denied".to_owned(),
            message: "this action was not approved".to_owned(),
        })
    }
}

type Rig = Driver<ScriptedModel, Tools, FollowModel>;

fn agent(change: impl FnOnce(&mut Agent)) -> Agent {
    let mut agent = Agent::default();
    change(&mut agent);
    agent
}

fn make_rig(dir: &Path, script: Vec<ModelAnswer>, agent: Agent, tools: Tools) -> Rig {
    let decider = FollowModel::new(agent, Catalogue::english()).with_gate(NoWrites);
    Driver::new(
        recorder(dir),
        ScriptedModel::new(script),
        tools,
        decider,
        ["update_plan", "search_corpus", "write_file"]
            .map(schema)
            .to_vec(),
        || 1.0,
    )
}

fn kinds(events: &[Event]) -> Vec<&'static str> {
    events
        .iter()
        .map(|e| match e {
            Event::Text { .. } => "text",
            Event::ToolCall { .. } => "tool_call",
            Event::ToolResult { .. } => "tool_result",
            Event::Plan { .. } => "plan",
            Event::Status { .. } => "status",
            Event::Goal { .. } => "goal",
            Event::Done { .. } => "done",
            _ => "other",
        })
        .collect()
}

fn position(events: &[Event], wanted: &str) -> usize {
    kinds(events)
        .iter()
        .position(|k| *k == wanted)
        .unwrap_or_else(|| panic!("no {wanted} event"))
}

fn plans(events: &[Event]) -> Vec<(&str, &[Map<String, Value>])> {
    events
        .iter()
        .filter_map(|e| match e {
            Event::Plan { source, steps } => Some((source.as_str(), steps.as_slice())),
            _ => None,
        })
        .collect()
}

fn goals(events: &[Event]) -> Vec<(bool, &Vec<Value>, bool)> {
    events
        .iter()
        .filter_map(|e| match e {
            Event::Goal {
                complete,
                open,
                retry,
                ..
            } => Some((*complete, open, *retry)),
            _ => None,
        })
        .collect()
}

fn reflects(events: &[Event]) -> Vec<&Map<String, Value>> {
    events
        .iter()
        .filter_map(|e| match e {
            Event::Status { kind, data } if kind == "reflect" => Some(data),
            _ => None,
        })
        .collect()
}

fn done(events: &[Event]) -> (&str, &str) {
    match events.last() {
        Some(Event::Done { status, answer }) => (status, answer),
        other => panic!("the turn must end with done, ended with {other:?}"),
    }
}

fn text_of(message: &ChatMessage) -> &str {
    match &message.content {
        Some(Content::Text(t)) => t,
        _ => "",
    }
}

/// Every call of every assistant message has its result: the conversation is valid for the next request.
fn assert_consistent(messages: &[ChatMessage]) {
    for (i, m) in messages.iter().enumerate() {
        for c in &m.tool_calls {
            let answered = messages[i + 1..]
                .iter()
                .any(|r| r.role == Role::Tool && r.tool_call_id == c.id);
            assert!(answered, "call {:?} has no result", c.id);
        }
    }
}

/// The log of a driven session replays byte for byte, with a model rebuilt from the log and no decider.
fn assert_replays(rig: &Rig) {
    let events = rig.recorder().store().events("s1", 0).expect("events");
    let records: Vec<Record> = events
        .iter()
        .map(|e| laris_core::decode_record(&e.data).expect("record"))
        .collect();
    let mut model = ScriptedModel::from_records(records.iter());
    let replayed = replay(&events, Some(&mut model)).expect("replay");
    let recorded: String = events
        .iter()
        .filter(|e| e.kind == "event")
        .map(|e| format!("{}\n", e.data))
        .collect();
    assert_eq!(replayed.output, recorded, "bytes differ");
    assert_eq!(&replayed.session, rig.session());
    assert_eq!(model.remaining(), 0);
    assert!(replayed.missing.is_empty());
}

// -- 1. a visible plan exists before the first tool call ---------------------------------------

#[test]
fn the_plan_is_shown_before_the_first_tool_call_and_tracked() {
    let script = vec![
        turn(
            "",
            vec![plan(
                "p1",
                &[("find efficiency", "in_progress"), ("compare", "pending")],
            )],
        ),
        turn("", vec![search("s1", "perovskite efficiency")]),
        turn(
            "",
            vec![plan(
                "p2",
                &[("find efficiency", "done"), ("compare", "done")],
            )],
        ),
        turn(CITED, vec![]),
    ];
    let mut rig = make_rig(
        &temp_dir("plan"),
        script,
        Agent::default(),
        Tools::default(),
    );
    let events = rig.send(LONG_GOAL).expect("turn");
    let first_search = events
        .iter()
        .position(|e| matches!(e, Event::ToolCall { name, .. } if name == "search_corpus"))
        .expect("search");
    assert!(position(&events, "plan") < first_search);
    let all = plans(&events);
    assert_eq!(all[0].0, "model");
    assert_eq!(
        all.last().expect("plan").1.last().expect("step")["status"],
        "done"
    );
    let goal = goals(&events);
    assert_eq!(goal.len(), 1);
    assert!(goal[0].0, "the goal is complete");
    assert_eq!(done(&events), ("completed", CITED));
    // The model is shown its own plan on every call after the first update.
    let seen = rig.model().seen();
    assert!(
        seen[1]
            .note
            .as_deref()
            .is_some_and(|n| n.contains("find efficiency"))
    );
    assert!(
        seen[0]
            .note
            .as_deref()
            .is_some_and(|n| n.contains("update_plan")),
        "asked for a plan first"
    );
    assert_consistent(rig.session().messages());
    assert_replays(&rig);
}

#[test]
fn without_a_plan_the_loop_records_one_before_acting() {
    let script = vec![
        turn("", vec![search("s1", "perovskite efficiency")]),
        turn(CITED, vec![]),
    ];
    let mut rig = make_rig(
        &temp_dir("auto"),
        script,
        Agent::default(),
        Tools::default(),
    );
    let events = rig.send(LONG_GOAL).expect("turn");
    assert!(position(&events, "plan") < position(&events, "tool_call"));
    let all = plans(&events);
    assert_eq!(all[0].0, "auto");
    assert_eq!(all[0].1[0]["status"], "in_progress");
    let goal = goals(&events);
    assert!(
        goal[0].0,
        "the loop closed its own step when the tool succeeded"
    );
    assert!(
        rig.model().seen()[0].note.is_some(),
        "the first call already asked for a plan"
    );
    assert_replays(&rig);
}

#[test]
fn a_short_question_needs_no_plan() {
    let script = vec![
        turn("", vec![search("s1", "perovskite")]),
        turn(CITED, vec![]),
    ];
    let mut rig = make_rig(
        &temp_dir("short"),
        script,
        Agent::default(),
        Tools::default(),
    );
    let events = rig.send("perovskite?").expect("turn");
    assert!(plans(&events).is_empty() && goals(&events).is_empty());
    assert!(rig.model().seen().iter().all(|s| s.note.is_none()));
}

#[test]
fn planning_can_be_switched_off() {
    let script = vec![
        turn("", vec![search("s1", "perovskite")]),
        turn(CITED, vec![]),
    ];
    let off = agent(|a| {
        a.plan = PlanSettings {
            mode: PlanMode::Off,
            ..PlanSettings::default()
        }
    });
    let mut rig = make_rig(&temp_dir("off"), script, off, Tools::default());
    let events = rig.send(LONG_GOAL).expect("turn");
    assert!(plans(&events).is_empty());
    assert!(
        rig.model()
            .seen()
            .iter()
            .all(|s| !s.tools.contains(&"update_plan".to_owned()))
    );
    assert!(
        rig.model()
            .seen()
            .iter()
            .all(|s| s.tools.contains(&"search_corpus".to_owned()))
    );
}

// -- 2. reflect and replan, bounded ------------------------------------------------------------

#[test]
fn an_empty_result_triggers_a_replan_that_can_succeed() {
    let script = vec![
        turn("", vec![plan("p1", &[("search", "in_progress")])]),
        turn("", vec![search("s1", "quantum gravity")]),
        turn(
            "",
            vec![
                plan("p2", &[("search again with other words", "in_progress")]),
                search("s2", "perovskite efficiency"),
            ],
        ),
        turn(
            "",
            vec![plan("p3", &[("search again with other words", "done")])],
        ),
        turn(CITED, vec![]),
    ];
    let mut rig = make_rig(
        &temp_dir("replan"),
        script,
        Agent::default(),
        Tools::default(),
    );
    let events = rig.send(LONG_GOAL).expect("turn");
    let reflect = reflects(&events);
    assert_eq!(reflect.len(), 1);
    assert_eq!(reflect[0]["replans"], 1);
    assert!(
        reflect[0]["issues"][0]
            .as_str()
            .expect("issue")
            .contains("search_corpus")
    );
    assert_eq!(done(&events).0, "completed");
    let third_view = rig.model().seen()[2]
        .messages
        .iter()
        .map(text_of)
        .collect::<Vec<_>>()
        .join("\n");
    assert!(third_view.contains("1 replans left"), "{third_view}");
    assert_replays(&rig);
}

#[test]
fn replanning_is_bounded_then_the_agent_reports_the_gap() {
    let mut script = vec![turn("", vec![plan("p0", &[("search", "in_progress")])])];
    for i in 1..=5 {
        script.push(turn(
            "",
            vec![search(&format!("s{i}"), &format!("nothing here {i}"))],
        ));
    }
    script.push(turn("", vec![plan("p9", &[("search", "failed")])]));
    script.push(turn("No evidence was found for this request.", vec![]));
    let mut rig = make_rig(
        &temp_dir("bounded"),
        script,
        Agent::default(),
        Tools::default(),
    );
    let events = rig.send(LONG_GOAL).expect("turn");
    let reflect = reflects(&events);
    assert_eq!(
        reflect
            .iter()
            .filter(|r| !r.contains_key("budget_out"))
            .count(),
        2,
        "max_replans"
    );
    assert_eq!(
        reflect
            .iter()
            .filter(|r| r.contains_key("budget_out"))
            .count(),
        1,
        "told once"
    );
    assert_eq!(done(&events).0, "completed");
    assert!(rig.session().turn().steps() <= Agent::default().max_steps);
    assert_replays(&rig);
}

// -- 3. completion check -----------------------------------------------------------------------

#[test]
fn a_goal_is_not_closed_while_steps_are_open() {
    let script = vec![
        turn(
            "",
            vec![plan(
                "p1",
                &[("find", "in_progress"), ("compare", "pending")],
            )],
        ),
        turn("", vec![search("s1", "perovskite efficiency")]),
        turn(CITED, vec![]), // tries to finish with "compare" still pending
        turn(
            "",
            vec![plan("p2", &[("find", "done"), ("compare", "skipped")])],
        ),
        turn(CITED, vec![]),
    ];
    let mut rig = make_rig(
        &temp_dir("open"),
        script,
        Agent::default(),
        Tools::default(),
    );
    let events = rig.send(LONG_GOAL).expect("turn");
    let all = goals(&events);
    let retries: Vec<_> = all.iter().filter(|g| g.2).collect();
    assert_eq!(retries.len(), 1);
    assert_eq!(retries[0].1, &vec![json!("find"), json!("compare")]);
    assert!(all.last().expect("goal").0);
    assert_eq!(done(&events).0, "completed");
    assert_replays(&rig);
}

#[test]
fn an_unfinished_goal_is_reported_when_the_model_will_not_finish_it() {
    let mut script = vec![
        turn(
            "",
            vec![plan(
                "p1",
                &[("find", "in_progress"), ("compare", "pending")],
            )],
        ),
        turn("", vec![search("s1", "perovskite efficiency")]),
    ];
    script.extend((0..4).map(|_| turn(CITED, vec![])));
    let mut rig = make_rig(
        &temp_dir("stuck"),
        script,
        Agent::default(),
        Tools::default(),
    );
    let events = rig.send(LONG_GOAL).expect("turn");
    let (status, answer) = done(&events);
    assert_eq!(status, "completed");
    assert!(
        answer.contains("Not complete") && answer.contains("compare"),
        "{answer}"
    );
    assert!(!goals(&events).last().expect("goal").0);
    assert_replays(&rig);
}

// -- 4. resume: an interrupted goal continues without repeating finished steps -----------------

#[test]
fn an_interrupted_plan_survives_resume_and_is_not_repeated() {
    let dir = temp_dir("resume");
    let first = vec![
        turn(
            "",
            vec![plan(
                "p1",
                &[("find efficiency", "in_progress"), ("compare", "pending")],
            )],
        ),
        turn("", vec![search("s1", "perovskite efficiency")]),
        turn(
            "",
            vec![plan(
                "p2",
                &[("find efficiency", "done"), ("compare", "in_progress")],
            )],
        ),
    ];
    let mut rig1 = make_rig(&dir, first, Agent::default(), Tools::default());
    let events = rig1.send(LONG_GOAL).expect("turn"); // runs out of script: the model fails
    assert_eq!(done(&events).0, "provider_error");
    drop(rig1);

    // A new process: the plan is rebuilt from the log.
    let second = vec![
        turn(
            "",
            vec![plan(
                "p3",
                &[("find efficiency", "done"), ("compare", "done")],
            )],
        ),
        turn(CITED, vec![]),
    ];
    let tools = Tools::default();
    let ran = tools.ran.clone();
    let mut rig2 = make_rig(&dir, second, Agent::default(), tools);
    let statuses: Vec<_> = rig2
        .session()
        .plan()
        .iter()
        .map(|s| s.status.as_str())
        .collect();
    assert_eq!(statuses, ["done", "in_progress"]);
    let events = rig2.send("continue").expect("turn");
    assert_eq!(plans(&events)[0].0, "resumed");
    let shown = rig2.model().seen()[0].note.clone().expect("note");
    assert!(shown.contains("find efficiency (done)") && shown.contains("compare (in_progress)"));
    assert!(ran.borrow().is_empty(), "no tool ran again");
    assert_eq!(done(&events).0, "completed");
    assert_eq!(
        rig2.session().plan().last().expect("step").status.as_str(),
        "done"
    );
    assert_replays(&rig2);
}

// -- 6. bounded autonomy: planning never widens a limit ----------------------------------------

#[test]
fn planning_does_not_widen_tools_steps_or_approvals() {
    let script = vec![
        turn("", vec![plan("p1", &[("write the file", "in_progress")])]),
        turn(
            "",
            vec![call(
                "w1",
                "write_file",
                json!({"path": "x.txt", "content": "hi"}),
            )],
        ),
        turn("", vec![plan("p2", &[("write the file", "failed")])]),
        turn(
            "The file could not be written: it was not approved.",
            vec![],
        ),
    ];
    let tools = Tools::default();
    let ran = tools.ran.clone();
    let mut rig = make_rig(&temp_dir("approval"), script, Agent::default(), tools);
    let events = rig.send(LONG_GOAL).expect("turn");
    let result = events
        .iter()
        .find_map(|e| match e {
            Event::ToolResult { name, result, .. } if name == "write_file" => Some(result),
            _ => None,
        })
        .expect("result");
    assert_eq!(result["error"]["code"], "approval_denied");
    assert!(
        !ran.borrow().iter().any(|n| n == "write_file"),
        "the tool must not run"
    );
    assert_replays(&rig);
}

#[test]
fn the_step_ceiling_holds_even_for_a_planner_that_never_stops() {
    let script = (0..40)
        .map(|i| {
            turn(
                "",
                vec![plan(
                    &format!("p{i}"),
                    &[(&format!("step {i}"), "in_progress")],
                )],
            )
        })
        .collect();
    let mut rig = make_rig(
        &temp_dir("ceiling"),
        script,
        Agent::default(),
        Tools::default(),
    );
    let events = rig.send(LONG_GOAL).expect("turn");
    assert_eq!(done(&events).0, "max_steps");
    assert_eq!(
        rig.model().remaining(),
        40 - Agent::default().max_steps as usize
    );
    assert_consistent(rig.session().messages());
    assert_replays(&rig);
}

#[test]
fn a_bad_plan_is_refused_with_a_typed_error() {
    let bad = call(
        "b1",
        "update_plan",
        json!({"steps": [{"text": "x", "status": "someday"}]}),
    );
    let script = vec![turn("", vec![bad]), turn(CITED, vec![])];
    let mut rig = make_rig(
        &temp_dir("badplan"),
        script,
        Agent::default(),
        Tools::default(),
    );
    let events = rig.send("perovskite?").expect("turn");
    let result = events
        .iter()
        .find_map(|e| match e {
            Event::ToolResult { result, .. } => Some(result),
            _ => None,
        })
        .expect("result");
    assert_eq!(result["error"]["code"], "invalid_plan");
    assert!(rig.session().plan().is_empty());
}

// -- 2b. an empty corpus cannot be fixed by another keyword ------------------------------------

#[test]
fn an_empty_corpus_is_told_once_and_spends_no_replan() {
    let script = vec![
        turn("", vec![search("s1", "hello")]),
        turn(
            "No documents were ingested, so I cannot answer yet.",
            vec![],
        ),
    ];
    let tools = Tools {
        empty_corpus: true,
        ..Tools::default()
    };
    let mut rig = make_rig(&temp_dir("empty"), script, Agent::default(), tools);
    let events = rig.send("hello").expect("turn");
    let result = events
        .iter()
        .find_map(|e| match e {
            Event::ToolResult { result, .. } => Some(result),
            _ => None,
        })
        .expect("result");
    assert_eq!(result["error"]["code"], "no_documents");
    let reflect = reflects(&events);
    assert_eq!(reflect.len(), 1);
    assert_eq!(reflect[0]["permanent"], true);
    assert!(!reflect[0].contains_key("replans"));
    let told = rig
        .session()
        .messages()
        .iter()
        .filter(|m| m.role == Role::User && text_of(m).contains("Do not call that tool again"))
        .count();
    assert_eq!(told, 1);
    let (status, answer) = done(&events);
    assert_eq!(status, "completed");
    assert!(answer.contains("No documents"));
}

// -- limits of the loop itself -----------------------------------------------------------------

#[test]
fn by_default_a_step_may_call_as_many_tools_as_the_model_asks() {
    let calls: Vec<ToolCall> = (1..=9)
        .map(|i| search(&format!("s{i}"), &format!("perovskite {i}")))
        .collect();
    let script = vec![turn("", calls), turn(CITED, vec![])];
    let tools = Tools::default();
    let ran = tools.ran.clone();
    let mut rig = make_rig(&temp_dir("nocap"), script, Agent::default(), tools);
    rig.send("perovskite?").expect("turn");
    assert_eq!(ran.borrow().len(), 9, "no cap by default");
}

#[test]
fn too_many_calls_unlisted_tools_and_repeats_are_refused_without_running() {
    let calls: Vec<ToolCall> = (1..=5)
        .map(|i| search(&format!("s{i}"), &format!("perovskite {i}")))
        .collect();
    let script = vec![turn("", calls), turn(CITED, vec![])];
    let tools = Tools::default();
    let ran = tools.ran.clone();
    let capped = Agent {
        max_tool_calls_per_step: 4,
        ..Agent::default()
    };
    let mut rig = make_rig(&temp_dir("many"), script, capped, tools);
    let events = rig.send("perovskite?").expect("turn");
    assert_eq!(ran.borrow().len(), 4, "the fifth call is over the cap");
    let refused = events.iter().any(|e| matches!(e, Event::ToolResult { result, .. } if result["error"]["code"] == "too_many_calls"));
    assert!(refused);

    // A tool outside the workflow's set.
    let script = vec![
        turn("", vec![call("w1", "write_file", json!({}))]),
        turn(CITED, vec![]),
    ];
    let decider = FollowModel::new(Agent::default(), Catalogue::english())
        .allow_only(["search_corpus".to_owned()]);
    let tools = Tools::default();
    let ran = tools.ran.clone();
    let mut driver = Driver::new(
        recorder(&temp_dir("allowed")),
        ScriptedModel::new(script),
        tools,
        decider,
        ["update_plan", "search_corpus", "write_file"]
            .map(schema)
            .to_vec(),
        || 1.0,
    );
    let events = driver.send("perovskite?").expect("turn");
    assert!(events.iter().any(|e| matches!(e, Event::ToolResult { result, .. } if result["error"]["code"] == "tool_not_allowed")));
    assert!(ran.borrow().is_empty());
    assert!(
        driver
            .model()
            .seen()
            .iter()
            .all(|s| !s.tools.contains(&"write_file".to_owned()))
    );

    // An identical call is refused, the model sees the refusal and may still answer.
    let script = vec![
        turn("", vec![search("a", "perovskite")]),
        turn("", vec![search("b", "perovskite")]),
        turn(CITED, vec![]),
    ];
    let mut rig = make_rig(
        &temp_dir("cyclic"),
        script,
        Agent::default(),
        Tools::default(),
    );
    let events = rig.send("perovskite?").expect("turn");
    assert_ne!(done(&events).0, "cyclic");
    assert!(events.iter().any(|e| matches!(e, Event::ToolResult { result, .. } if result["error"]["code"] == "cyclic_call")));
    assert_consistent(rig.session().messages());
    assert_replays(&rig);

    // A model that keeps repeating past `maxRepeatedCalls` stops the turn.
    let script = vec![
        turn("", vec![search("a", "perovskite")]),
        turn("", vec![search("b", "perovskite")]),
        turn("", vec![search("c", "perovskite")]),
        turn(CITED, vec![]),
    ];
    let mut rig = make_rig(
        &temp_dir("cyclic-stop"),
        script,
        agent(|a| a.max_repeated_calls = 2),
        Tools::default(),
    );
    let events = rig.send("perovskite?").expect("turn");
    assert_eq!(done(&events).0, "cyclic");
    assert!(done(&events).1.contains("repeated"));
    assert_consistent(rig.session().messages());
    assert_replays(&rig);
}

#[test]
fn the_time_budget_ends_a_turn_before_the_next_model_call() {
    let mut decider =
        FollowModel::new(agent(|a| a.time_budget_seconds = 5.0), Catalogue::english());
    let mut rec = recorder(&temp_dir("time"));
    rec.record(
        Record::Command {
            command: laris_protocol::Command::UserMessage {
                text: "hello".to_owned(),
                attachments: Vec::new(),
            },
        },
        1.0,
    )
    .expect("user");
    let within = Clock {
        elapsed: Duration::from_secs(4),
    };
    assert!(matches!(
        decider.decide(rec.session(), &within),
        Some(Action::AskModel { .. })
    ));
    let over = Clock {
        elapsed: Duration::from_secs(6),
    };
    assert!(matches!(
        decider.decide(rec.session(), &over),
        Some(Action::Stop { status, .. }) if status == "timeout"
    ));
}

#[test]
fn reflection_can_be_switched_off() {
    let off = agent(|a| {
        a.reflect = Reflect {
            enabled: false,
            ..Reflect::default()
        }
    });
    let script = vec![
        turn("", vec![search("s1", "nothing")]),
        turn("", vec![search("s2", "still nothing")]),
        turn("No evidence.", vec![]),
    ];
    let mut rig = make_rig(&temp_dir("noreflect"), script, off, Tools::default());
    let events = rig.send("nothing?").expect("turn");
    assert!(reflects(&events).is_empty());
    assert_eq!(done(&events).0, "completed");
}

// -- interrupt and resume ----------------------------------------------------------------------

#[test]
fn an_interrupt_leaves_a_consistent_session() {
    let script = vec![
        turn(
            "",
            vec![
                search("a", "perovskite one"),
                search("b", "perovskite two"),
                search("c", "perovskite three"),
            ],
        ),
        turn(CITED, vec![]),
    ];
    let slot = Rc::new(RefCell::new(None));
    let tools = Tools {
        interrupt: slot.clone(),
        ..Tools::default()
    };
    let ran = tools.ran.clone();
    let mut driver = make_rig(&temp_dir("interrupt"), script, Agent::default(), tools);
    // The first tool sets the flag while it runs, as a user pressing Esc would.
    *slot.borrow_mut() = Some(driver.interrupt_handle());
    let events = driver.send("perovskite?").expect("turn");
    assert_eq!(ran.borrow().len(), 1, "only the running call ran");
    assert_eq!(done(&events), ("interrupted", ""));
    let sealed = events
        .iter()
        .filter(|e| matches!(e, Event::ToolResult { result, .. } if result["error"]["code"] == "interrupted"))
        .count();
    assert_eq!(sealed, 2, "the calls that did not run are answered");
    assert_eq!(driver.session().pending(), &Pending::Idle);
    assert_consistent(driver.session().messages());
    assert_replays(&driver);
    // The session is usable afterwards.
    *slot.borrow_mut() = None;
    let events = driver.send("perovskite again?").expect("next turn");
    assert_eq!(done(&events).0, "completed");
}

// -- the decider seam --------------------------------------------------------------------------

/// A decider that plays a fixed list of actions, whatever the state says.
struct Fixed(VecDeque<Action>);

impl Decider for Fixed {
    fn decide(&mut self, session: &laris_core::Session, _clock: &Clock) -> Option<Action> {
        if session.pending() == &Pending::Idle {
            return None;
        }
        self.0.pop_front()
    }

    fn model_failed(&mut self, _session: &laris_core::Session, _error: &ModelError) -> Action {
        Action::Stop {
            status: "provider_error".to_owned(),
            notice: "model failed".to_owned(),
        }
    }
}

/// Counts the calls it receives.
struct Counting(Rc<RefCell<u32>>);

impl Model for Counting {
    fn answer(&mut self, _request: &ModelRequest<'_>) -> Result<ModelAnswer, ModelError> {
        *self.0.borrow_mut() += 1;
        Ok(turn("an answer", vec![]))
    }
}

#[test]
fn the_loop_runs_with_a_scripted_decider_and_calls_no_model_outside_its_actions() {
    let finish = || Action::Finish {
        warning: String::new(),
    };
    let calls = Rc::new(RefCell::new(0));

    // A decider that stops at once: the model is never called.
    let stop = Action::Stop {
        status: "stopped".to_owned(),
        notice: "stop".to_owned(),
    };
    let mut driver = Driver::new(
        recorder(&temp_dir("seam-a")),
        Counting(calls.clone()),
        Tools::default(),
        Fixed(VecDeque::from([stop])),
        Vec::new(),
        || 1.0,
    );
    let events = driver.send("hello").expect("turn");
    assert_eq!(*calls.borrow(), 0);
    assert_eq!(done(&events).0, "stopped");

    // Two asks, two calls: the model is called exactly when the decider asks.
    let script = VecDeque::from([
        Action::AskModel {
            note: Some("note".to_owned()),
        },
        Action::Retry {
            text: "again".to_owned(),
            open: vec![],
        },
        Action::AskModel { note: None },
        finish(),
    ]);
    let mut driver = Driver::new(
        recorder(&temp_dir("seam-b")),
        Counting(calls.clone()),
        Tools::default(),
        Fixed(script),
        Vec::new(),
        || 1.0,
    );
    let events = driver.send("hello").expect("turn");
    assert_eq!(*calls.borrow(), 2);
    assert_eq!(done(&events), ("completed", "an answer"));

    // A decider that asks for an action the state cannot take is refused, and nothing is written for it.
    let mut driver = Driver::new(
        recorder(&temp_dir("seam-c")),
        Counting(calls.clone()),
        Tools::default(),
        Fixed(VecDeque::from([finish()])),
        Vec::new(),
        || 1.0,
    );
    let before = driver
        .recorder()
        .store()
        .events("s1", 0)
        .expect("events")
        .len();
    assert!(matches!(
        driver.send("hello"),
        Err(CoreError::Unexpected(_))
    ));
    // Only the user message was written.
    assert_eq!(
        driver
            .recorder()
            .store()
            .events("s1", 0)
            .expect("events")
            .len(),
        before + 1
    );
    assert_eq!(*calls.borrow(), 2);
}

#[test]
fn an_answer_or_a_tool_outcome_nobody_decided_is_refused() {
    let mut rec = recorder(&temp_dir("undecided"));
    rec.record(
        Record::Command {
            command: laris_protocol::Command::UserMessage {
                text: "hello".to_owned(),
                attachments: Vec::new(),
            },
        },
        1.0,
    )
    .expect("user");
    let answer = Record::ModelAnswer {
        request_digest: rec.session().digest(),
        answer: turn("sneaky", vec![search("s1", "perovskite")]),
    };
    assert!(matches!(
        rec.record(answer.clone(), 1.0),
        Err(CoreError::Unexpected(_))
    ));
    rec.record(
        Record::Decision {
            action: Action::AskModel { note: None },
        },
        1.0,
    )
    .expect("ask");
    rec.record(answer, 1.0).expect("decided answer");
    let outcome = Record::ToolOutcome {
        id: "s1".to_owned(),
        name: "search_corpus".to_owned(),
        result: json!({"hits": []}),
    };
    assert!(
        matches!(rec.record(outcome, 1.0), Err(CoreError::Unexpected(m)) if m.contains("not cleared")),
        "a tool outcome needs the decision to run it"
    );
}

#[test]
fn a_call_cut_off_by_a_killed_process_is_answered_as_interrupted_not_run_again() {
    let dir = temp_dir("killed-call");
    // Everything up to the decision to run the tool, then the process "dies" before the outcome.
    let mut rec = recorder(&dir);
    rec.record(
        Record::Command {
            command: laris_protocol::Command::UserMessage {
                text: "perovskite?".to_owned(),
                attachments: Vec::new(),
            },
        },
        1.0,
    )
    .expect("user");
    rec.record(
        Record::Decision {
            action: Action::AskModel { note: None },
        },
        1.0,
    )
    .expect("ask");
    let answer = Record::ModelAnswer {
        request_digest: rec.session().digest(),
        answer: turn("", vec![search("s1", "perovskite")]),
    };
    rec.record(answer, 1.0).expect("answer");
    rec.record(
        Record::Decision {
            action: Action::RunTool {
                id: "s1".to_owned(),
            },
        },
        1.0,
    )
    .expect("run");
    drop(rec);

    let tools = Tools::default();
    let ran = tools.ran.clone();
    let mut again = make_rig(&dir, vec![turn(CITED, vec![])], Agent::default(), tools);
    assert!(matches!(again.session().pending(), Pending::Tools(_)));
    let events = again.run().expect("resume");
    assert!(ran.borrow().is_empty(), "the call must not run again");
    assert!(events.iter().any(|e| matches!(e, Event::ToolResult { result, .. } if result["error"]["code"] == "interrupted")));
    assert_eq!(done(&events).0, "completed");
    assert_consistent(again.session().messages());
    assert_replays(&again);
}
