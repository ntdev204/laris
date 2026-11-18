//! The Agent rung of the capability ladder (SR-S9, SR-H4), end to end and in one process: a project folder, the system
//! (the core loop, the permission gate and the real local tools, `Bash` inside the OS sandbox), the server (HTTP, the
//! policy gateway with the system brain, the scientific remote tools at `/v1/laris/tools/{name}`, content-free
//! traces) and a model that follows a script.
//!
//! One scenario mixes both kinds of tools: the brain (server side), `Read`, `Write` and `Bash` (local), and
//! `extract_discourse` and `normalize_quantities` (remote). The loop cannot tell local from remote tools; the traces
//! show tool names and nothing else.
//!
//! The model is scripted and the remote tools answer with the outputs recorded from the real tool box
//! (`crates/laris-protocol/tests/fixtures/scientific`; `tests/tools.rs` proves the real service reproduces them), so
//! this proves mechanics only. It says nothing about how well any model uses tools; the foundation model is NOT
//! QUALIFIED.
#![cfg(target_os = "linux")]

mod support;
use laris_server::trace::TraceRecord;
use serde_json::json;
use support::*;

const QUESTION: &str = "Summarise paper.txt and write the summary to report.md.";
const SUMMARY: &str = "The paper makes direct author claims, one limitation, and reports quantities \
     (see report.md, verified with the shell).";

fn script() -> Vec<Script> {
    let quantities = fixture("normalize_quantities.request.json")["arguments"].clone();
    vec![
        // the server's own steps: its brain, never seen by the client
        calls("b1", "use_system_brain", json!({"action": "index"})),
        calls(
            "b2",
            "use_system_brain",
            json!({"action": "read", "id": "Research QA Playbook"}),
        ),
        // the client's tools
        calls("l1", "Read", json!({"path": "paper.txt"})),
        calls(
            "r1",
            "extract_discourse",
            fixture("extract_discourse.request.json")["arguments"].clone(),
        ),
        calls("r2", "normalize_quantities", quantities),
        calls(
            "w1",
            "Write",
            json!({"path": "report.md", "content": REPORT}),
        ),
        // a denied path, a command inside the sandbox, a command that tries to leave it
        calls(
            "w2",
            "Write",
            json!({"path": "secret/key.txt", "content": "HYENA-DENIED-TEXT"}),
        ),
        calls(
            "s1",
            "Bash",
            json!({"command": format!("wc -c report.md && echo {SHELL_MARK}")}),
        ),
        calls(
            "s2",
            "Bash",
            json!({"command": "echo escaped > ../outside.txt; echo done"}),
        ),
        answer(SUMMARY),
    ]
}

// ---------------------------------------------------------------- the scenario

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn the_agent_rung_mixes_local_and_remote_tools_and_the_traces_hold_names_only() {
    let server = start(script()).await;
    let project = project("good");
    let run = ask(&server, &project, QUESTION, Yes::default()).await;

    // 1. the loop ran the client's tools, local and remote alike; the server's brain never reached it
    assert_eq!(
        run.ran,
        [
            "Read",
            "extract_discourse",
            "normalize_quantities",
            "Write",
            "Bash",
            "Bash"
        ],
        "the denied write never ran: the gate stopped it"
    );
    assert!(!run.wire.contains("use_system_brain"));
    for secret in ["Decide whether the question", "LARIS-CANARY", "<brain"] {
        assert!(!run.wire.contains(secret), "{secret} reached the client");
    }

    // 2. local tools did their work on the project
    let read = result_of(&run, "Read");
    assert!(read[0].to_string().contains("BiLSTM"));
    assert_eq!(
        std::fs::read_to_string(project.root.join("report.md")).unwrap(),
        REPORT
    );
    let bash = result_of(&run, "Bash");
    assert!(bash[0].to_string().contains(SHELL_MARK), "{}", bash[0]);
    assert!(bash[0].to_string().contains("report.md"));

    // 3. remote tools returned what the tool box recorded, marked untrusted like every remote result
    let extraction = result_of(&run, "extract_discourse");
    assert_eq!(extraction.len(), 1);
    let recorded = fixture("extract_discourse.response.json")["result"].clone();
    assert_eq!(extraction[0]["claims"], recorded["claims"]);
    assert_eq!(extraction[0]["untrusted"], true);
    assert!(!extraction[0]["claims"].as_array().unwrap().is_empty());
    let quantities = result_of(&run, "normalize_quantities");
    assert_eq!(
        quantities[0]["quantities"],
        fixture("normalize_quantities.response.json")["result"]["quantities"]
    );
    assert_eq!(
        *server.tool_hits.lock().unwrap(),
        ["extract_discourse", "normalize_quantities"]
    );

    // 4. the gate: reads were free; writes, commands and remote tools were asked about; the denied path was never
    //    written and the sandboxed command could not leave the project
    assert_eq!(
        run.asked,
        [
            "extract_discourse",
            "normalize_quantities",
            "Write",
            "Bash",
            "Bash"
        ]
    );
    let denied = result_of(&run, "Write");
    assert_eq!(denied[1]["error"]["code"], "permission_denied");
    assert!(!project.root.join("secret/key.txt").exists());
    assert!(
        !project.base.join("outside.txt").exists(),
        "the sandbox kept the command inside the project"
    );

    // 5. the model saw the tools' results, and the turn ended with its answer
    let sent = server.seen.lock().unwrap().clone();
    let offered: Vec<&str> = sent[2]
        .tools
        .iter()
        .map(|s| s.function.name.as_str())
        .collect();
    for name in [
        "Read",
        "Write",
        "Bash",
        "extract_discourse",
        "mine_literature",
    ] {
        assert!(
            offered.contains(&name),
            "{name} was not offered: {offered:?}"
        );
    }
    let after_remote = serde_json::to_string(&sent[4].messages).unwrap();
    assert!(
        after_remote.contains("claim_id"),
        "the model saw the extraction"
    );
    assert_eq!(done_answer(&run.events), SUMMARY);

    // 6. traces: one row per request, tool names only, nothing from any content
    let rows = trace_rows(&server, 10).await;
    let chat: Vec<&TraceRecord> = rows.iter().filter(|r| r.route == "chat").collect();
    // the list of tools is a request of its own and names nothing; each remote call is one row with its name
    let listing: Vec<&TraceRecord> = rows
        .iter()
        .filter(|r| r.route == "tools" && r.tools.is_empty())
        .collect();
    assert_eq!(listing.len(), 1);
    let tools_rows: Vec<&TraceRecord> = rows
        .iter()
        .filter(|r| r.route == "tools" && !r.tools.is_empty())
        .collect();
    let names: Vec<Vec<&str>> = chat
        .iter()
        .map(|r| r.tools.iter().map(String::as_str).collect())
        .collect();
    assert_eq!(
        names,
        [
            vec!["Read"],
            vec!["extract_discourse"],
            vec!["normalize_quantities"],
            vec!["Write"],
            vec!["Write"],
            vec!["Bash"],
            vec!["Bash"],
            vec![]
        ],
        "the model's calls to client tools, one request each"
    );
    assert_eq!(
        tools_rows.len(),
        2,
        "one row for each remote call, plus none for the rest"
    );
    assert_eq!(tools_rows[0].tools, ["extract_discourse"]);
    assert_eq!(tools_rows[1].tools, ["normalize_quantities"]);
    assert!(
        chat[0].brain.contains(&"Research QA Playbook".to_owned()),
        "the first request names the notes it drew on: {:?}",
        chat[0].brain
    );
    assert!(rows.iter().all(|r| r.status == 200 && r.outcome == "ok"));
    let dump = format!("{rows:?}");
    for text in [
        "BiLSTM",
        "ZEBRA-REPORT-TEXT",
        SHELL_MARK,
        "HYENA-DENIED-TEXT",
        "report.md",
        "paper.txt",
        "outside.txt",
        "claim_id",
        "Decide whether the question",
        "Summarise",
        "verified with the shell",
    ] {
        assert!(!dump.contains(text), "{text} is in a trace row: {dump}");
    }
    let record = server.reasoning.newest(5);
    assert!(
        record
            .iter()
            .any(|r| r.brain.contains(&"Research QA Playbook".to_owned()))
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_call_nobody_approved_never_leaves_the_machine() {
    let server = start(vec![
        calls(
            "r1",
            "extract_discourse",
            fixture("extract_discourse.request.json")["arguments"].clone(),
        ),
        calls(
            "w1",
            "Write",
            json!({"path": "report.md", "content": REPORT}),
        ),
        answer("I could not run anything: nothing was approved."),
    ])
    .await;
    let project = project("denied");
    let no = Yes {
        answer_no: true,
        ..Yes::default()
    };
    let run = ask(&server, &project, QUESTION, no).await;
    assert!(run.ran.is_empty(), "{:?}", run.ran);
    assert_eq!(run.asked, ["extract_discourse", "Write"]);
    assert!(server.tool_hits.lock().unwrap().is_empty());
    assert!(!project.root.join("report.md").exists());
    let refused = result_of(&run, "extract_discourse");
    assert_eq!(refused[0]["error"]["code"], "approval_denied");
    let rows = trace_rows(&server, 3).await;
    assert!(
        rows.iter()
            .all(|r| r.route != "tools" || r.tools.is_empty()),
        "only the list of tools was asked of the server: {rows:?}"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_remote_tool_that_refuses_is_a_typed_result_and_the_loop_goes_on() {
    // arguments that differ from the recorded ones: the tool box refuses, the loop gets an error result
    let server = start(vec![
        calls(
            "r1",
            "extract_discourse",
            json!({"text": "A claim we make here.", "document_id": "other"}),
        ),
        answer("The extraction refused my input; I report that and stop."),
    ])
    .await;
    let project = project("refused");
    let run = ask(&server, &project, QUESTION, Yes::default()).await;
    let result = result_of(&run, "extract_discourse");
    assert_eq!(result[0]["error"]["code"], "invalid_arguments");
    assert_eq!(result[0]["untrusted"], true);
    assert_eq!(
        done_answer(&run.events),
        "The extraction refused my input; I report that and stop."
    );
    let rows = trace_rows(&server, 3).await;
    let tools: Vec<_> = rows
        .iter()
        .filter(|r| r.route == "tools" && !r.tools.is_empty())
        .collect();
    assert_eq!(tools.len(), 1);
    assert_eq!(tools[0].tools, ["extract_discourse"]);
    assert!(!format!("{rows:?}").contains("A claim we make here"));
}
