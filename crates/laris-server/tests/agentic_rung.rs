//! The Agentic rung of the capability ladder (SR-S9, SR-H15), end to end and in one process: the same stack as the
//! Agent rung (project folder, the core loop with the permission gate and the real local tools, the HTTP server with
//! the policy gateway, the scientific remote tools and content-free traces) and a model that follows a script.
//!
//! What the rung adds is the loop's own discipline over several steps: a visible plan that the model keeps current,
//! progress that survives a killed process, a bounded number of replans, a completion check that sends an unfinished
//! goal back, memory kept in the project vault for the next session, and autonomy that stays inside its limits
//! (steps, approvals, the permission rules).
//!
//! The model is scripted and the remote tools answer with the outputs recorded from the real tool box, so this proves
//! mechanics only. It says nothing about how well any model plans or finishes a task; the foundation model is NOT
//! QUALIFIED.
#![cfg(target_os = "linux")]

mod support;

use laris_config::settings::{Agent, Reflect};
use laris_protocol::events::Event;
use laris_server::trace::TraceRecord;
use serde_json::{Map, Value, json};
use std::time::Duration;
use support::*;

const GOAL: &str = "Read paper.txt, extract its claims, write the result to report.md, and keep a memory note \
     of what you learned for the next session.";
const FINAL: &str = "Done: report.md holds the result and the memory note is in the vault.";
/// Text that must reach the project and the conversation and never a trace row.
const MEMORY_TEXT: &str =
    "OCELOT-MEMORY-TEXT: the paper states one limitation; start from report.md next time.";

fn plan(id: &str, steps: &[(&str, &str)]) -> Script {
    let steps: Vec<Value> = steps
        .iter()
        .map(|(text, status)| json!({"text": text, "status": status}))
        .collect();
    calls(id, "update_plan", json!({ "steps": steps }))
}

fn extract() -> Script {
    calls(
        "r1",
        "extract_discourse",
        fixture("extract_discourse.request.json")["arguments"].clone(),
    )
}

fn failing_extract(id: &str) -> Script {
    calls(
        id,
        "extract_discourse",
        json!({"text": "A claim we make here.", "document_id": id}),
    )
}

/// A model stream that dies after the request is accepted: the process was killed, as far as the loop can tell.
fn killed() -> Script {
    vec![Err(laris_server::StreamFailure {
        message: "the model went away".into(),
        kind: "provider_error".into(),
    })]
}

fn plans(events: &[Event]) -> Vec<(&str, Vec<(String, String)>)> {
    events
        .iter()
        .filter_map(|e| match e {
            Event::Plan { source, steps } => Some((
                source.as_str(),
                steps
                    .iter()
                    .map(|s| {
                        (
                            s["text"].as_str().unwrap_or_default().to_owned(),
                            s["status"].as_str().unwrap_or_default().to_owned(),
                        )
                    })
                    .collect(),
            )),
            _ => None,
        })
        .collect()
}

fn goals(events: &[Event]) -> Vec<(bool, Vec<String>, bool)> {
    events
        .iter()
        .filter_map(|e| match e {
            Event::Goal {
                complete,
                open,
                retry,
                ..
            } => Some((
                *complete,
                open.iter()
                    .filter_map(|v| v.as_str().map(str::to_owned))
                    .collect(),
                *retry,
            )),
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

fn first_non_empty(plan: &[(String, String)]) -> Vec<&str> {
    plan.iter().map(|(_, status)| status.as_str()).collect()
}

async fn trace_rows(server: &Server, at_least: usize) -> Vec<TraceRecord> {
    for _ in 0..100 {
        let rows = server.traces.records();
        if rows.len() >= at_least {
            return rows;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    panic!(
        "expected {at_least} traces, got {:?}",
        server.traces.records()
    );
}

fn result_of<'a>(run: &'a Run, tool: &str) -> Vec<&'a Value> {
    run.events
        .iter()
        .filter_map(|e| match e {
            Event::ToolResult { name, result, .. } if name == tool => Some(result),
            _ => None,
        })
        .collect()
}

// ---------------------------------------------------------------- scenario 1: plan, progress, completion, memory

fn full_script() -> Vec<Script> {
    vec![
        plan(
            "p1",
            &[
                ("read the paper", "in_progress"),
                ("extract the claims", "pending"),
                ("write report.md", "pending"),
                ("keep a memory note", "pending"),
            ],
        ),
        calls("l1", "Read", json!({"path": "paper.txt"})),
        extract(),
        plan(
            "p2",
            &[
                ("read the paper", "done"),
                ("extract the claims", "done"),
                ("write report.md", "in_progress"),
                ("keep a memory note", "pending"),
            ],
        ),
        calls(
            "w1",
            "Write",
            json!({"path": "report.md", "content": "ZEBRA-REPORT-TEXT: one limitation.\n"}),
        ),
        calls(
            "m1",
            "write_vault_note",
            json!({"kind": "memory", "title": "paper-limitation", "body": MEMORY_TEXT}),
        ),
        // the model tries to finish while the memory step is still open: the loop sends it back
        answer(FINAL),
        plan(
            "p3",
            &[
                ("read the paper", "done"),
                ("extract the claims", "done"),
                ("write report.md", "done"),
                ("keep a memory note", "done"),
            ],
        ),
        answer(FINAL),
    ]
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn the_agentic_rung_plans_tracks_progress_checks_completion_and_keeps_memory_in_the_vault() {
    let server = start(full_script()).await;
    let project = support::project("full");
    let options = Options {
        vault: true,
        ..Options::default()
    };
    let run = ask_with(&server, &project, GOAL, Yes::default(), &options).await;

    // 1. the plan is visible before anything runs, comes from the model, and its steps move to done
    let shown = plans(&run.events);
    assert_eq!(shown[0].0, "model");
    assert_eq!(
        first_non_empty(&shown[0].1),
        ["in_progress", "pending", "pending", "pending"]
    );
    let first_tool = run
        .events
        .iter()
        .position(|e| matches!(e, Event::ToolCall { name, .. } if name != "update_plan"))
        .expect("a tool call");
    let first_plan = run
        .events
        .iter()
        .position(|e| matches!(e, Event::Plan { .. }))
        .expect("a plan");
    assert!(first_plan < first_tool, "the plan came first");
    assert_eq!(
        first_non_empty(&shown.last().unwrap().1),
        ["done", "done", "done", "done"]
    );

    // 2. the tools ran in order, local and remote alike; the plan tool is the loop's, not a registry tool
    assert_eq!(
        run.ran,
        ["Read", "extract_discourse", "Write", "write_vault_note"]
    );
    assert_eq!(
        *server.tool_hits.lock().unwrap(),
        ["extract_discourse"],
        "one remote call reached the server"
    );

    // 3. the completion check: the first answer was refused with the open step named; the second was accepted
    let checks = goals(&run.events);
    let retries: Vec<_> = checks.iter().filter(|g| g.2).collect();
    assert_eq!(retries.len(), 1, "{checks:?}");
    assert_eq!(
        retries[0].1.last().map(String::as_str),
        Some("keep a memory note")
    );
    assert!(checks.last().unwrap().0, "the goal ended complete");
    assert_eq!(done(&run.events), ("completed", FINAL));

    // 4. the model was shown its own plan on the calls after the first update
    let sent = server.seen.lock().unwrap().clone();
    let second = serde_json::to_string(&sent[1]).unwrap();
    assert!(second.contains("read the paper"), "{second}");

    // 5. memory in the vault: a note of type memory with provenance, inside the vault, the person's text untouched
    let note = std::fs::read_dir(project.root.join("vault/Memory"))
        .expect("the Memory folder of the vault")
        .filter_map(Result::ok)
        .map(|e| std::fs::read_to_string(e.path()).unwrap())
        .find(|t| t.contains("OCELOT-MEMORY-TEXT"))
        .expect("the memory note");
    assert!(note.contains("memory"), "{note}");
    assert!(note.contains("origin"), "provenance is recorded: {note}");

    // 6. traces: one row per request with tool names only, nothing of any content, the plan included
    let rows = trace_rows(&server, 9).await;
    let dump = format!("{rows:?}");
    for text in [
        "OCELOT-MEMORY-TEXT",
        "ZEBRA-REPORT-TEXT",
        "BiLSTM",
        "paper-limitation",
        "read the paper",
        "extract the claims",
        "keep a memory note",
        "report.md",
        "paper.txt",
        "claim_id",
    ] {
        assert!(!dump.contains(text), "{text} is in a trace row: {dump}");
    }
    assert!(rows.iter().all(|r| r.status == 200 && r.outcome == "ok"));
}

// ---------------------------------------------------------------- scenario 2: resume after a killed process

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn an_interrupted_goal_resumes_from_the_log_and_does_not_repeat_finished_steps() {
    let server = start(vec![
        // first process: plan, one step done, then the model's stream breaks
        plan(
            "p1",
            &[
                ("read the paper", "in_progress"),
                ("extract the claims", "pending"),
                ("write report.md", "pending"),
            ],
        ),
        calls("l1", "Read", json!({"path": "paper.txt"})),
        plan(
            "p2",
            &[
                ("read the paper", "done"),
                ("extract the claims", "in_progress"),
                ("write report.md", "pending"),
            ],
        ),
        killed(),
        // second process
        extract(),
        plan(
            "p3",
            &[
                ("read the paper", "done"),
                ("extract the claims", "done"),
                ("write report.md", "in_progress"),
            ],
        ),
        calls(
            "w1",
            "Write",
            json!({"path": "report.md", "content": "ZEBRA-REPORT-TEXT: resumed.\n"}),
        ),
        plan(
            "p4",
            &[
                ("read the paper", "done"),
                ("extract the claims", "done"),
                ("write report.md", "done"),
            ],
        ),
        answer(FINAL),
    ])
    .await;
    let project = support::project("resume");
    let options = Options {
        session: "resumed-goal".into(),
        ..Options::default()
    };

    let first = ask_with(&server, &project, GOAL, Yes::default(), &options).await;
    assert_eq!(first.ran, ["Read"]);
    assert_eq!(done(&first.events).0, "provider_error");
    assert!(!project.root.join("report.md").exists());

    // a new loop over the same store: nothing is held in memory, the plan comes from the log
    let second = ask_with(&server, &project, "continue", Yes::default(), &options).await;
    assert_eq!(
        second.ran,
        ["extract_discourse", "Write"],
        "the finished step (Read) did not run again"
    );
    assert_eq!(plans(&second.events)[0].0, "resumed");
    assert_eq!(
        first_non_empty(&plans(&second.events)[0].1),
        ["done", "in_progress", "pending"]
    );
    let sent = server.seen.lock().unwrap().clone();
    let seen_after_resume = serde_json::to_string(&sent[4]).unwrap();
    assert!(
        seen_after_resume.contains("read the paper")
            && seen_after_resume.contains("extract the claims"),
        "the model was shown the plan it left: {seen_after_resume}"
    );
    assert_eq!(done(&second.events), ("completed", FINAL));
    assert!(
        std::fs::read_to_string(project.root.join("report.md"))
            .unwrap()
            .contains("ZEBRA-REPORT-TEXT: resumed")
    );
    assert_eq!(
        *server.tool_hits.lock().unwrap(),
        ["extract_discourse"],
        "the remote step ran once, in the second process"
    );
}

// ---------------------------------------------------------------- scenario 3: bounded replanning

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn replanning_is_bounded_then_the_agent_reports_the_gap() {
    // every extraction is refused by the tool box; the loop allows two replans, says once that they are used up, and
    // the model reports the gap instead of trying for ever
    let server = start(vec![
        plan("p1", &[("extract the claims", "in_progress")]),
        failing_extract("r1"),
        failing_extract("r2"),
        failing_extract("r3"),
        failing_extract("r4"),
        plan("p2", &[("extract the claims", "failed")]),
        answer("The extraction was refused every time; I report that and stop."),
    ])
    .await;
    let project = support::project("replan");
    let run = ask(&server, &project, GOAL, Yes::default()).await;

    let all = reflects(&run.events);
    let replans: Vec<_> = all
        .iter()
        .filter(|r| !r.contains_key("budget_out"))
        .collect();
    let told: Vec<_> = all
        .iter()
        .filter(|r| r.contains_key("budget_out"))
        .collect();
    assert_eq!(
        replans.len() as u32,
        Reflect::default().max_replans,
        "{all:?}"
    );
    assert_eq!(told.len(), 1, "the limit is said once: {all:?}");
    assert_eq!(done(&run.events).0, "completed");
    assert!(
        done(&run.events).1.contains("report that and stop"),
        "the gap is reported"
    );
    assert_eq!(
        server.tool_hits.lock().unwrap().len(),
        4,
        "four calls reached the tool box, no more"
    );
    // the goal is not claimed complete: its only step failed
    assert!(
        goals(&run.events).iter().all(|g| !g.0 || g.1.is_empty()),
        "{:?}",
        goals(&run.events)
    );
    let rows = trace_rows(&server, 7).await;
    assert!(!format!("{rows:?}").contains("A claim we make here"));
}

// ---------------------------------------------------------------- scenario 4: an unfinished goal is reported

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_goal_the_model_will_not_finish_is_reported_open() {
    let server = start(vec![
        plan(
            "p1",
            &[
                ("read the paper", "in_progress"),
                ("write report.md", "pending"),
            ],
        ),
        calls("l1", "Read", json!({"path": "paper.txt"})),
        answer("All finished."),
        answer("All finished."),
        answer("All finished."),
        answer("All finished."),
    ])
    .await;
    let project = support::project("open");
    let run = ask(&server, &project, GOAL, Yes::default()).await;
    let (status, text) = done(&run.events);
    assert_eq!(status, "completed");
    assert!(
        text.contains("Not complete") && text.contains("write report.md"),
        "the answer says what is open: {text}"
    );
    assert!(!goals(&run.events).last().unwrap().0);
    assert!(!project.root.join("report.md").exists());
}

// ---------------------------------------------------------------- scenario 5: bounded autonomy

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn autonomy_stays_inside_its_limits() {
    // 5a. a planner that never stops is ended by the step ceiling; no more model calls than the ceiling
    let ceiling = Agent::default().max_steps as usize;
    let endless: Vec<Script> = (0..30)
        .map(|i| {
            plan(
                &format!("p{i}"),
                &[(&format!("keep going {i}"), "in_progress")],
            )
        })
        .collect();
    let server = start(endless).await;
    let project = support::project("ceiling");
    let run = ask(&server, &project, GOAL, Yes::default()).await;
    assert_eq!(done(&run.events).0, "max_steps");
    assert_eq!(server.seen.lock().unwrap().len(), ceiling);
    assert!(run.ran.is_empty());

    // 5b. a model that wants to act on its own is still bound by the permission rules and the approval: a denied
    //     path is never written, a refused approval runs nothing, and nothing reached the server
    let server = start(vec![
        plan(
            "p1",
            &[
                ("write the key", "in_progress"),
                ("write report.md", "pending"),
            ],
        ),
        calls(
            "w1",
            "Write",
            json!({"path": "secret/key.txt", "content": "HYENA-DENIED-TEXT"}),
        ),
        extract(),
        calls(
            "w2",
            "Write",
            json!({"path": "report.md", "content": "ZEBRA-REPORT-TEXT"}),
        ),
        plan(
            "p2",
            &[("write the key", "failed"), ("write report.md", "failed")],
        ),
        answer("Nothing was permitted, so nothing was done."),
    ])
    .await;
    let project = support::project("bound");
    let no = Yes {
        answer_no: true,
        ..Yes::default()
    };
    let run = ask(&server, &project, GOAL, no).await;
    assert!(run.ran.is_empty(), "{:?}", run.ran);
    assert!(server.tool_hits.lock().unwrap().is_empty());
    assert!(!project.root.join("secret/key.txt").exists());
    assert!(!project.root.join("report.md").exists());
    assert_eq!(
        run.asked,
        ["extract_discourse", "Write"],
        "the denied path is never even asked"
    );
    assert_eq!(done(&run.events).0, "completed");

    // 5c. the plan does not widen the tool set of a step: more calls than the limit are refused without running
    let limit = 4;
    let many: Vec<Value> = (0..=limit)
        .map(|i| {
            json!({"index": i, "id": format!("c{i}"), "type": "function",
                   "function": {"name": "Read", "arguments": json!({"path": "paper.txt", "offset": i}).to_string()}})
        })
        .collect();
    let burst: Script = vec![
        Ok(serde_json::from_value(json!({
            "id": "m1", "object": "chat.completion.chunk", "model": "scripted",
            "choices": [{"index": 0, "delta": {"tool_calls": many}, "finish_reason": null}]
        }))
        .unwrap()),
        Ok(serde_json::from_value(json!({
            "id": "m1", "object": "chat.completion.chunk", "model": "scripted",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]
        }))
        .unwrap()),
    ];
    let server = start(vec![burst, answer("Too many calls at once; I stop.")]).await;
    let project = support::project("burst");
    let capped = support::Options {
        agent: Agent {
            max_tool_calls_per_step: 4,
            ..Agent::default()
        },
        ..support::Options::default()
    };
    let run = support::ask_with(&server, &project, GOAL, Yes::default(), &capped).await;
    assert_eq!(run.ran.len(), limit, "the call over the cap did not run");
    let refused = result_of(&run, "Read")
        .iter()
        .filter(|r| r["error"]["code"] == "too_many_calls")
        .count();
    assert_eq!(refused, 1, "the extra call got a typed refusal");
    assert_eq!(done(&run.events).0, "completed");
}
