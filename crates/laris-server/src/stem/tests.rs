//! Tests of the STEM profile with a scripted engine and scripted tools. The parity tests replay the scenarios that
//! `scripts/stem_profile_fixtures.py` ran through the Python reference harness: the server's loop must make the same
//! calls (prompt, seed, token cap, sampling mode) and reach the same trace.

use super::checks::Checks;
use super::config::{Entry, StemConfig};
use super::engine::{Engine, Reply};
use super::*;
use futures_util::future::BoxFuture;
use laris_protocol::{ChatMessage, Role};
use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::Mutex;

const CONFIG: &str = include_str!("../../../../configs/stem-benchmarks.json");
const BRAIN: &str = include_str!("../../../../configs/stem-brain.json");
const FIXTURE: &str = include_str!("../../tests/fixtures/stem_parity.json");

/// A folder with the brain configuration and a snapshot record, as the profile reads them.
fn root() -> PathBuf {
    static N: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let n = N.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!("laris-stem-{}-{n}", std::process::id()));
    let cfg: Value = serde_json::from_str(CONFIG).expect("config");
    let brain: Value = serde_json::from_str(BRAIN).expect("brain");
    let snap = dir
        .join(brain["data_dir"].as_str().expect("data_dir"))
        .join("snapshots")
        .join(
            cfg["harness"]["retrieval"]["snapshot"]
                .as_str()
                .expect("snapshot"),
        );
    std::fs::create_dir_all(snap.join("vault")).expect("dirs");
    std::fs::write(
        snap.join("snapshot.json"),
        r#"{"snapshot_sha256": "abc123"}"#,
    )
    .expect("snap");
    let cfgdir = dir.join("configs");
    std::fs::create_dir_all(&cfgdir).expect("configs");
    std::fs::write(cfgdir.join("stem-brain.json"), BRAIN).expect("brain");
    dir
}

/// The configuration with `override` (dotted paths into `harness`) applied.
fn config(entry: Entry, overrides: &Map<String, Value>) -> Arc<StemConfig> {
    let mut cfg: Value = serde_json::from_str(CONFIG).expect("config");
    for (path, value) in overrides {
        let mut node = &mut cfg["harness"];
        let parts: Vec<&str> = path.split('.').collect();
        for part in &parts[..parts.len() - 1] {
            node = &mut node[*part];
        }
        node[parts[parts.len() - 1]] = value.clone();
    }
    let bytes = serde_json::to_vec(&cfg).expect("bytes");
    Arc::new(StemConfig::parse(entry, "http://engine", &bytes, &root()).expect("parse"))
}

#[derive(Debug, Clone, PartialEq)]
struct Call {
    kind: String,
    text: String,
    seed: u64,
    max_tokens: u32,
    mode: String,
}

struct ScriptedEngine {
    cfg: Arc<StemConfig>,
    replies: Mutex<VecDeque<Reply>>,
    calls: Mutex<Vec<Call>>,
}

impl ScriptedEngine {
    fn new(cfg: Arc<StemConfig>, replies: Vec<Reply>) -> Self {
        Self {
            cfg,
            replies: Mutex::new(replies.into()),
            calls: Mutex::new(Vec::new()),
        }
    }

    fn mode_name(&self, mode: &super::config::Mode) -> String {
        if *mode == self.cfg.thinking {
            "thinking_on".to_owned()
        } else if *mode == self.cfg.mode {
            self.cfg.harness.mode.clone()
        } else {
            "other".to_owned()
        }
    }

    fn take(&self, call: Call) -> BoxFuture<'static, Result<Reply, StemError>> {
        self.calls.lock().expect("calls").push(call);
        let next = self.replies.lock().expect("replies").pop_front();
        Box::pin(async move { next.ok_or(StemError::Engine("no scripted reply")) })
    }
}

impl Engine for ScriptedEngine {
    fn chat(
        &self,
        prompt: String,
        mode: super::config::Mode,
        seed: u64,
        max_tokens: u32,
    ) -> BoxFuture<'static, Result<Reply, StemError>> {
        let mode = self.mode_name(&mode);
        self.take(Call {
            kind: "chat".into(),
            text: prompt,
            seed,
            max_tokens,
            mode,
        })
    }

    fn complete(
        &self,
        raw: String,
        mode: super::config::Mode,
        seed: u64,
        max_tokens: u32,
    ) -> BoxFuture<'static, Result<Reply, StemError>> {
        let mode = self.mode_name(&mode);
        self.take(Call {
            kind: "complete".into(),
            text: raw,
            seed,
            max_tokens,
            mode,
        })
    }

    fn template(
        &self,
        prompt: String,
        thinking: bool,
    ) -> BoxFuture<'static, Result<String, StemError>> {
        let raw = format!("<T{}>{prompt}</T>", u8::from(thinking));
        Box::pin(async move { Ok(raw) })
    }
}

/// Tools answering from the fixture's tables.
struct ScriptedChecks {
    scenario: Value,
    solver: Mutex<VecDeque<Value>>,
    solved: Mutex<Vec<Value>>,
    ops: Mutex<Vec<String>>,
}

impl ScriptedChecks {
    fn new(scenario: &Value) -> Self {
        Self {
            scenario: scenario.clone(),
            solver: Mutex::new(
                scenario["solver"]
                    .as_array()
                    .cloned()
                    .unwrap_or_default()
                    .into(),
            ),
            solved: Mutex::new(Vec::new()),
            ops: Mutex::new(Vec::new()),
        }
    }

    fn lookup(&self, table: &str, wanted: &Value) -> Value {
        let tables = &self.scenario["tables"][table];
        for (k, v) in tables.as_object().expect("table") {
            let key: Value = serde_json::from_str(k).expect("key");
            if key == *wanted {
                return v.clone();
            }
        }
        panic!("{table}: no entry for {wanted}");
    }
}

impl Checks for ScriptedChecks {
    fn solve(&self, problem: Map<String, Value>) -> BoxFuture<'static, (Option<Value>, String)> {
        self.solved
            .lock()
            .expect("solved")
            .push(Value::Object(problem));
        let next = self.solver.lock().expect("solver").pop_front();
        Box::pin(async move {
            let next = next.expect("a scripted solver result");
            let result = (!next[0].is_null()).then(|| next[0].clone());
            (result, next[1].as_str().unwrap_or("").to_owned())
        })
    }

    fn check(&self, args: Value) -> BoxFuture<'static, Result<Value, StemError>> {
        let op = args["op"].as_str().unwrap_or("").to_owned();
        self.ops.lock().expect("ops").push(op.clone());
        let out = match op.as_str() {
            "model_free" => self.scenario["model_free"].clone(),
            "repair" => self.lookup("repair", &args["problem"]),
            "solver_answer" => json!({"answer": self.lookup("solver_answer", &args["result"])}),
            "equivalent" => {
                json!({"equal": self.lookup("equivalent", &json!([args["a"], args["b"]]))})
            }
            "crosscheck" => {
                let mut out = self.lookup("crosscheck", &args["problem"]);
                out["checked"] = json!(true);
                out["action"] = json!("record");
                out
            }
            other => panic!("unexpected op {other}"),
        };
        Box::pin(async move { Ok(out) })
    }
}

fn replies(scenario: &Value) -> Vec<Reply> {
    scenario["replies"]
        .as_array()
        .expect("replies")
        .iter()
        .map(|r| Reply {
            text: r["text"].as_str().expect("text").to_owned(),
            prompt_tokens: r["prompt_tokens"].as_u64().expect("prompt"),
            generated_tokens: r["generated_tokens"].as_u64().expect("generated"),
            truncated: r["truncated"].as_bool().expect("truncated"),
            seconds: 0.0,
        })
        .collect()
}

fn strings(v: &Value) -> Vec<String> {
    v.as_array()
        .map(|a| {
            a.iter()
                .filter_map(|s| s.as_str().map(str::to_owned))
                .collect()
        })
        .unwrap_or_default()
}

fn no_steps() -> harness::OnStep {
    Arc::new(|_: &Value| {})
}

#[tokio::test]
async fn the_server_loop_makes_the_reference_calls_and_reaches_its_trace() {
    let fixture: Value = serde_json::from_str(FIXTURE).expect("fixture");
    let scenarios = fixture["scenarios"].as_array().expect("scenarios");
    assert!(scenarios.len() >= 10);
    for s in scenarios {
        let name = s["name"].as_str().expect("name");
        let overrides = s["override"].as_object().cloned().unwrap_or_default();
        let cfg = config(Entry::Request, &overrides);
        let engine = Arc::new(ScriptedEngine::new(cfg.clone(), replies(s)));
        let checks = Arc::new(ScriptedChecks::new(s));
        let harness = Harness::new(cfg.clone(), engine.clone(), checks.clone());
        let item = Item {
            question: s["item"]["question"].as_str().expect("q").to_owned(),
            options: strings(&s["item"]["options"]),
        };
        let quantities = (!s["quantities"].is_null()).then(|| s["quantities"].clone());
        let trace = harness
            .answer(
                &item,
                s["seed"].as_u64().expect("seed"),
                &strings(&s["notes"]),
                &strings(&s["certain"]),
                quantities.as_ref(),
                no_steps(),
            )
            .await
            .unwrap_or_else(|e| panic!("{name}: {e}"));

        // the calls, in order: model calls through the engine, solver calls through the tool
        let mut made: Vec<Value> = Vec::new();
        let calls = engine.calls.lock().expect("calls").clone();
        let solved = checks.solved.lock().expect("solved").clone();
        let (mut ci, mut si) = (0, 0);
        for expected in s["calls"].as_array().expect("calls") {
            if expected["kind"] == "solve" {
                made.push(json!({"kind": "solve", "problem": solved[si]}));
                si += 1;
            } else {
                let c = &calls[ci];
                ci += 1;
                let mut v = json!({"kind": c.kind, "text": c.text, "seed": c.seed, "max_tokens": c.max_tokens});
                if c.kind == "complete" {
                    v["mode"] = json!(c.mode);
                } else {
                    assert_eq!(
                        c.mode, cfg.harness.mode,
                        "{name}: a chat call in another mode"
                    );
                }
                made.push(v);
            }
        }
        assert_eq!(
            ci,
            calls.len(),
            "{name}: more engine calls than the reference"
        );
        assert_eq!(
            si,
            solved.len(),
            "{name}: more solver calls than the reference"
        );
        assert_eq!(
            made,
            *s["calls"].as_array().expect("calls"),
            "{name}: calls differ"
        );

        let mut got = serde_json::to_value(&trace).expect("trace");
        for key in ["model_seconds", "solver_seconds"] {
            got.as_object_mut().expect("object").remove(key);
        }
        assert_eq!(got, s["expected"], "{name}: trace differs");
    }
}

#[test]
fn the_item_seed_is_the_runners() {
    // int(sha256(id).hexdigest()[:8], 16) % 100000 + 2752, from the Python runner
    assert_eq!(item_seed(2752, 0, "math-dev-0001"), 47624);
    assert_eq!(item_seed(2752, 0, "abc"), 35071);
    assert_eq!(item_seed(2752, 100_003, "abc"), 35071 + 100_003);
}

#[test]
fn the_frozen_candidate_is_what_the_server_reads() {
    let cfg = config(Entry::Auto, &Map::new());
    assert_eq!(cfg.harness.draft.thinking.get("computable"), Some(&56_000));
    assert_eq!(cfg.harness.draft.thinking.get("knowledge"), Some(&2_048));
    assert!(cfg.harness.conclude.enabled && cfg.harness.conclude.replace_retry);
    assert!(cfg.harness.self_consistency.enabled);
    assert_eq!(cfg.snapshot_sha256, "abc123");
    assert!(cfg.thinking.enable_thinking && !cfg.mode.enable_thinking);
}

#[test]
fn levers_the_server_does_not_carry_are_refused() {
    for (path, value) in [
        ("draft.escalate", json!({"enabled": true})),
        ("repetition", json!({"enabled": true})),
        ("router.network", json!("net.json")),
        ("deterministic_only", json!(true)),
        (
            "brain_only",
            json!({"enabled": true, "min_option_words": 2}),
        ),
    ] {
        let mut cfg: Value = serde_json::from_str(CONFIG).expect("config");
        let mut node = &mut cfg["harness"];
        let parts: Vec<&str> = path.split('.').collect();
        for part in &parts[..parts.len() - 1] {
            node = &mut node[*part];
        }
        node[parts[parts.len() - 1]] = value;
        let bytes = serde_json::to_vec(&cfg).expect("bytes");
        assert!(
            StemConfig::parse(Entry::Auto, "http://e", &bytes, &root()).is_err(),
            "{path} was accepted"
        );
    }
}

#[test]
fn the_profile_is_off_unless_asked_and_needs_its_settings() {
    let env = |pairs: &[(&str, &str)]| -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect()
    };
    assert!(StemConfig::from_env(&env(&[])).expect("off").is_none());
    assert!(
        StemConfig::from_env(&env(&[("LARIS_SERVER__STEM_PROFILE", "off")]))
            .expect("off")
            .is_none()
    );
    assert!(StemConfig::from_env(&env(&[("LARIS_SERVER__STEM_PROFILE", "yes")])).is_err());
    assert!(StemConfig::from_env(&env(&[("LARIS_SERVER__STEM_PROFILE", "auto")])).is_err());
}

use std::collections::HashMap;

fn request(messages: Vec<(Role, &str)>, stem: Option<Value>) -> ChatRequest {
    let mut laris = laris_protocol::LarisRequest::default();
    if let Some(item) = stem {
        laris.extra.insert(STEM_KEY.to_owned(), item);
    }
    ChatRequest {
        messages: messages
            .into_iter()
            .map(|(role, text)| ChatMessage {
                role,
                content: Some(laris_protocol::chat::Content::Text(text.to_owned())),
                tool_calls: Vec::new(),
                tool_call_id: None,
                name: None,
                extra: Map::new(),
            })
            .collect(),
        tools: Vec::new(),
        stream: true,
        laris,
        extra: Map::new(),
    }
}

fn profile(entry: Entry, checks: Arc<dyn Checks>, replies: Vec<Reply>) -> Arc<StemProfile> {
    let cfg = config(entry, &Map::new());
    let engine = Arc::new(ScriptedEngine::new(cfg.clone(), replies));
    Arc::new(StemProfile::new(
        cfg,
        engine,
        checks,
        None,
        Arc::new(Redactor::standard()),
    ))
}

/// Tools for the turn tests: a filter that passes with a STEM signal unless the question says "poem".
struct TurnChecks;

impl Checks for TurnChecks {
    fn solve(&self, _problem: Map<String, Value>) -> BoxFuture<'static, (Option<Value>, String)> {
        Box::pin(async { (None, "refused:rejected".to_owned()) })
    }

    fn check(&self, args: Value) -> BoxFuture<'static, Result<Value, StemError>> {
        let out = match args["op"].as_str() {
            Some("screen") => {
                let q = args["question"].as_str().unwrap_or("");
                let stop = q.contains("ignore");
                json!({
                    "status": if stop { "stop" } else { "pass" }, "stopped": stop,
                    "rule": if stop { json!("injection:x") } else { Value::Null },
                    "question": q.split_whitespace().collect::<Vec<_>>().join(" "),
                    "options": args["options"], "quantities": [],
                    "stem_signal": !q.contains("poem"), "record": {"status": "pass"}
                })
            }
            Some("model_free") => {
                json!({"pattern": null, "status": "not_formalised", "answer": null})
            }
            _ => json!({}),
        };
        Box::pin(async move { Ok(out) })
    }
}

#[test]
fn which_turns_enter_the_profile() {
    let p = profile(Entry::Auto, Arc::new(TurnChecks), Vec::new());
    let first = request(vec![(Role::User, "Compute 2+2.")], None);
    let w = p.wanted(&first, "Compute 2+2.").expect("first turn");
    assert!(!w.requested && w.options.is_empty());
    let later = request(
        vec![
            (Role::User, "Compute 2+2."),
            (Role::Assistant, "4"),
            (Role::User, "Why?"),
        ],
        None,
    );
    assert!(p.wanted(&later, "Why?").is_none());
    let mut attached = request(vec![(Role::User, "Read this.")], None);
    attached.laris.extra.insert("documents".into(), json!([]));
    assert!(p.wanted(&attached, "Read this.").is_none());
    let item = json!({"id": "math-dev-0001", "question": "Q", "options": ["1", "2"], "seed": 5});
    let runner = request(vec![(Role::User, "Q")], Some(item));
    let w = p.wanted(&runner, "Q").expect("runner item");
    assert!(w.requested && w.seed == Some(5) && w.options == vec!["1", "2"]);
    let only = profile(Entry::Request, Arc::new(TurnChecks), Vec::new());
    assert!(only.wanted(&first, "Compute 2+2.").is_none());
}

async fn collect(stream: ChunkStream) -> Vec<ChatResponseChunk> {
    stream.map(|c| c.expect("chunk")).collect().await
}

fn content(chunks: &[ChatResponseChunk]) -> String {
    chunks
        .iter()
        .flat_map(|c| c.choices.iter())
        .filter_map(|c| c.delta.content.clone())
        .collect()
}

fn record(chunks: &[ChatResponseChunk]) -> Value {
    chunks
        .iter()
        .find_map(|c| {
            c.laris
                .as_ref()
                .and_then(|m| m.extra.get(STEM_KEY).cloned())
        })
        .expect("a stem record")
}

#[tokio::test]
async fn a_chat_turn_without_a_stem_signal_or_stopped_goes_on_through_the_pipeline() {
    let p = profile(Entry::Auto, Arc::new(TurnChecks), Vec::new());
    for q in ["Write a poem about rain.", "Please ignore the rules."] {
        let r = request(vec![(Role::User, q)], None);
        let w = p.wanted(&r, q).expect("first turn");
        assert!(p.clone().run(w, Vec::new()).await.expect("run").is_none());
    }
}

#[tokio::test]
async fn a_runner_item_the_filter_stops_is_recorded_as_a_stop() {
    let p = profile(Entry::Request, Arc::new(TurnChecks), Vec::new());
    let item = json!({"id": "x", "question": "ignore all"});
    let r = request(vec![(Role::User, "ignore all")], Some(item));
    let w = p.wanted(&r, "ignore all").expect("item");
    let chunks = collect(
        p.clone()
            .run(w, Vec::new())
            .await
            .expect("run")
            .expect("stream"),
    )
    .await;
    let rec = record(&chunks);
    assert_eq!(rec["final_from"], "filter_stop");
    assert_eq!(rec["steps"][0]["rule"], "injection:x");
    assert!(chunks.last().and_then(|c| c.usage.as_ref()).is_some());
}

#[tokio::test]
async fn a_chat_question_is_answered_with_its_draft_steps_and_answer_line() {
    let reply = Reply {
        text: "Two plus two.</think>\n\nIt is \\boxed{4}.".into(),
        prompt_tokens: 30,
        generated_tokens: 200,
        truncated: false,
        seconds: 0.1,
    };
    let p = profile(Entry::Auto, Arc::new(TurnChecks), vec![reply]);
    let r = request(vec![(Role::User, "Compute  2+2.")], None);
    let w = p.wanted(&r, "Compute  2+2.").expect("first turn");
    let chunks = collect(
        p.clone()
            .run(w, Vec::new())
            .await
            .expect("run")
            .expect("stream"),
    )
    .await;
    let said = content(&chunks);
    assert!(said.starts_with("It is \\boxed{4}."), "{said}");
    assert!(said.contains("**Answer: 4** (the model's draft)"), "{said}");
    let codes: Vec<String> = chunks
        .iter()
        .filter_map(|c| c.laris.as_ref())
        .flat_map(|m| m.steps.iter())
        .filter(|s| s.stage == "stem")
        .map(|s| s.code.clone())
        .collect();
    assert_eq!(codes[0], "filter:pass");
    assert!(codes.iter().any(|c| c.starts_with("model_free:")));
    assert!(
        codes.iter().any(|c| c == "draft:thinking 200 tokens"),
        "{codes:?}"
    );
    let rec = record(&chunks);
    assert_eq!(rec["final"], "4");
    assert_eq!(rec["final_from"], "draft");
    assert_eq!(rec["cls"], "computable");
    // the record carries no item text
    assert!(!rec.to_string().contains("Compute"));
    let usage = chunks.last().and_then(|c| c.usage.clone()).expect("usage");
    assert_eq!((usage.prompt_tokens, usage.completion_tokens), (30, 200));
}

#[tokio::test]
async fn an_answer_in_latex_is_put_in_the_answer_line_as_math() {
    let reply = Reply {
        text: "Fall time.</think>\n\nSo \\boxed{t = 3 \\, \\text{s}}.".into(),
        prompt_tokens: 30,
        generated_tokens: 200,
        truncated: false,
        seconds: 0.1,
    };
    let p = profile(Entry::Auto, Arc::new(TurnChecks), vec![reply]);
    let r = request(vec![(Role::User, "Compute  2+2.")], None);
    let w = p.wanted(&r, "Compute  2+2.").expect("first turn");
    let chunks = collect(
        p.clone()
            .run(w, Vec::new())
            .await
            .expect("run")
            .expect("stream"),
    )
    .await;
    let said = content(&chunks);
    assert!(
        said.contains("**Answer: $t = 3 \\, \\text{s}$** (the model's draft)"),
        "{said}"
    );
}

#[test]
fn step_codes_carry_no_text() {
    assert_eq!(
        step_code(&json!({"step": "solver", "status": "verified"})),
        "solver:verified"
    );
    assert_eq!(
        step_code(&json!({"step": "vote", "groups": 2, "top": 3})),
        "vote:3/2"
    );
    assert_eq!(
        step_code(&json!({"step": "retry", "tokens": 9, "truncated": true})),
        "retry:9 tokens, cut"
    );
}
