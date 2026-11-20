//! The main brain on the server (T240, ADR-025 D50): ingestion, the write gate and retraction through the admin API,
//! retrieval over what the gate stored, and access by role. The model is a scripted backend; nothing here says
//! anything about how well a real model answers. The tests with keys need PostgreSQL (`LARIS_TEST_PG_DSN`) and
//! pass with a notice without it, like `tests/access.rs`.

use futures_util::future::BoxFuture;
use futures_util::{StreamExt, stream};
use laris_brain::gate::GateSettings;
use laris_protocol::p1::{ChatRequest, ChatResponseChunk, EmbedRequest, EmbedResponse};
use laris_server::access::{Access, AccessConfig, Master, NewKey, Roles};
use laris_server::mainbrain::{MainBrain, MainBrainConfig};
use laris_server::pipeline::{Grounding, Pipeline, PipelineConfig};
use laris_server::policy::{MemoryReasoning, Policy, PolicyConfig, PolicyGateway};
use laris_server::storage::{Storage, StorageConfig};
use laris_server::{
    ApiError, AppState, Backend, Caller, ChunkStream, MemorySink, ServerConfig, StreamFailure,
    serve,
};
use serde_json::{Value, json};
use sqlx::ConnectOptions;
use sqlx::postgres::PgConnectOptions;
use std::collections::{HashMap, VecDeque};
use std::path::{Path, PathBuf};
use std::str::FromStr;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::net::TcpListener;

static COUNTER: AtomicU32 = AtomicU32::new(0);
const MASTER: &str = "0123456789abcdef0123456789abcdef";

const GATE: GateSettings = GateSettings {
    min_support: 0.9,
    min_equivalence: 0.6,
    subject_overlap: 0.5,
    search_depth: 10,
    max_bytes: 100_000,
};

const PAPER: &str = "Aspirin reduces fever in adults. A dose of 500 mg was used in 2020.";
const FACT: &str = "Aspirin reduces fever in adults.";
const QUESTION: &str = "Does aspirin reduce fever in adults?";

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn fresh_dir(label: &str) -> PathBuf {
    let n = COUNTER.fetch_add(1, Ordering::Relaxed);
    let dir = Path::new(env!("CARGO_TARGET_TMPDIR")).join(format!("mainbrain-{label}-{n}"));
    let _ = std::fs::remove_dir_all(&dir);
    dir
}

fn open_brain(label: &str) -> (Arc<MainBrain>, PathBuf) {
    let dir = fresh_dir(label);
    let config = MainBrainConfig {
        dir: dir.clone(),
        gate: GATE,
    };
    (Arc::new(MainBrain::open(&config).unwrap()), dir)
}

type Script = Vec<Result<ChatResponseChunk, StreamFailure>>;

fn answer(text: &str) -> Script {
    let chunk = |delta: Value, finish: Option<&str>| -> ChatResponseChunk {
        serde_json::from_value(json!({
            "id": "m1", "object": "chat.completion.chunk", "model": "scripted",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]
        }))
        .unwrap()
    };
    vec![
        Ok(chunk(json!({"content": text}), None)),
        Ok(chunk(json!({}), Some("stop"))),
    ]
}

struct Scripted {
    scripts: Mutex<VecDeque<Script>>,
    calls: Arc<AtomicU32>,
}

impl Backend for Scripted {
    fn chat(&self, _request: ChatRequest) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let next = self.scripts.lock().unwrap().pop_front();
        Box::pin(async move {
            match next {
                Some(s) => Ok(stream::iter(s).boxed()),
                None => Err(ApiError::BadGateway("no more answers".into())),
            }
        })
    }

    fn embed(&self, _r: EmbedRequest) -> BoxFuture<'static, Result<EmbedResponse, ApiError>> {
        Box::pin(async { Err(ApiError::BadGateway("no embed".into())) })
    }
}

struct Server {
    port: u16,
    model_calls: Arc<AtomicU32>,
    brain_dir: PathBuf,
    _stop: tokio::sync::oneshot::Sender<()>,
}

/// A server with the main brain, grounding required, and either open access or keys.
async fn start(access: Option<Arc<Access>>, scripts: Vec<Script>, label: &str) -> Server {
    let config = PipelineConfig {
        grounding: Grounding::Required,
        ..PipelineConfig::default()
    };
    start_with(config, access, scripts, label).await
}

async fn start_with(
    pipeline: PipelineConfig,
    access: Option<Arc<Access>>,
    scripts: Vec<Script>,
    label: &str,
) -> Server {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let mut cfg = ServerConfig::with_bind(addr);
    cfg.stream_idle = Duration::from_secs(5);
    let policy =
        Arc::new(Policy::load(&PolicyConfig::with_root(repo()), std::iter::empty(), None).unwrap());
    let calls = Arc::new(AtomicU32::new(0));
    let model = Scripted {
        scripts: Mutex::new(scripts.into()),
        calls: calls.clone(),
    };
    let reasoning = Arc::new(MemoryReasoning::new(20));
    let gateway = Arc::new(PolicyGateway::new(
        policy.clone(),
        Arc::new(model),
        reasoning.clone(),
    ));
    let (brain, brain_dir) = open_brain(label);
    let backend = Arc::new(
        Pipeline::new(
            gateway,
            pipeline,
            None,
            policy.harness().cloned(),
            Some(brain.clone()),
        )
        .unwrap(),
    );
    let state = match access {
        Some(a) => AppState::new(cfg, backend, a),
        None => AppState::open(cfg, backend),
    }
    .with_policy(policy, reasoning)
    .with_main_brain(brain);
    let (tx, rx) = tokio::sync::oneshot::channel::<()>();
    tokio::spawn(async move {
        let _ = serve(
            listener,
            Arc::new(state),
            Arc::new(MemorySink::default()),
            async {
                let _ = rx.await;
            },
        )
        .await;
    });
    Server {
        port: addr.port(),
        model_calls: calls,
        brain_dir,
        _stop: tx,
    }
}

async fn post(server: &Server, path: &str, key: Option<&str>, body: Value) -> (u16, Value, String) {
    let mut req = reqwest::Client::new()
        .post(format!("http://127.0.0.1:{}{path}", server.port))
        .header(
            "x-laris-protocol",
            laris_protocol::PROTOCOL_VERSION.to_string(),
        )
        .json(&body);
    if let Some(key) = key {
        req = req.bearer_auth(key);
    }
    let response = req.send().await.unwrap();
    let status = response.status().as_u16();
    let text = response.text().await.unwrap();
    (
        status,
        serde_json::from_str(&text).unwrap_or(Value::Null),
        text,
    )
}

/// The text and the steps of a chat answer.
async fn chat(
    server: &Server,
    key: Option<&str>,
    question: &str,
) -> (u16, String, Vec<(String, String, String)>) {
    let body = json!({"stream": true, "messages": [{"role": "user", "content": question}],
        "laris": {"kind": "turn", "session_id": "sess-1"}});
    let (status, _, wire) = post(server, "/v1/laris/chat", key, body).await;
    let mut text = String::new();
    let mut steps = Vec::new();
    for line in wire.lines() {
        let Some(data) = line.strip_prefix("data: ") else {
            continue;
        };
        let Ok(value) = serde_json::from_str::<Value>(data) else {
            continue;
        };
        if let Some(list) = value.pointer("/laris/steps").and_then(Value::as_array) {
            for s in list {
                let get = |k: &str| s[k].as_str().unwrap_or("").to_owned();
                steps.push((get("stage"), get("outcome"), get("code")));
            }
        }
        if let Some(t) = value
            .pointer("/choices/0/delta/content")
            .and_then(Value::as_str)
        {
            text.push_str(t);
        }
    }
    (status, text, steps)
}

fn source_body() -> Value {
    json!({"title": "Paper A", "kind": "document", "identifier": "doi:10.1/a", "text": PAPER,
        "metadata": {"kind": "verified", "registry": "registry-fixture"}})
}

fn claim_body(source: Option<&str>) -> Value {
    let mut body = json!({"statement": FACT, "quote": FACT, "requested": "sourced"});
    if let Some(s) = source {
        body["source"] = json!(s);
    }
    body
}

fn abstain_no_source() -> String {
    let text = std::fs::read_to_string(repo().join(".laris/harness.toml")).unwrap();
    laris_policy::HarnessConfig::from_toml(&text)
        .unwrap()
        .abstain_no_source
}

// ---------------------------------------------------------------- the gate through the API

#[tokio::test]
async fn a_model_only_claim_is_refused_through_the_api_and_a_sourced_one_is_stored() {
    let server = start(None, vec![], "gate").await;
    let (status, body, _) = post(&server, "/v1/admin/brain/sources", None, source_body()).await;
    assert_eq!((status, body["decision"].as_str()), (200, Some("accepted")));

    // text with no Source never becomes a Claim
    let (status, body, _) = post(&server, "/v1/admin/brain/claims", None, claim_body(None)).await;
    assert_eq!(status, 200);
    assert_eq!(body["decision"], "refused");
    assert_eq!(body["reason"], "model-only");
    // a quote that is not in the Source is refused too
    let mut forged = claim_body(Some("Paper A"));
    forged["quote"] = json!("Aspirin cures every disease.");
    let (_, body, _) = post(&server, "/v1/admin/brain/claims", None, forged).await;
    assert_eq!(body["decision"], "refused");
    assert_eq!(body["reason"], "span");

    let (_, body, _) = post(
        &server,
        "/v1/admin/brain/claims",
        None,
        claim_body(Some("Paper A")),
    )
    .await;
    assert_eq!(body["decision"], "accepted");
    assert_eq!(body["level"], "sourced");
    // the audit record names the key (here: an open server), never a name the body chose
    let audit = std::fs::read_to_string(server.brain_dir.join(".laris/brain-audit.jsonl")).unwrap();
    assert!(audit.contains("key:open"), "{audit}");
    assert!(!audit.contains("advisor"));
}

#[tokio::test]
async fn a_proposer_in_the_body_is_refused_not_trusted() {
    let server = start(None, vec![], "proposer").await;
    let mut body = source_body();
    body["proposer"] = json!("the-owner");
    let (status, _, _) = post(&server, "/v1/admin/brain/sources", None, body).await;
    assert_eq!(status, 400);
}

#[tokio::test]
async fn what_the_gate_stored_grounds_the_next_answer_and_a_retraction_ends_it() {
    let server = start(None, vec![answer("unused")], "retract").await;
    // nothing stored: the turn abstains and the model is not asked
    let (_, text, steps) = chat(&server, None, QUESTION).await;
    assert_eq!(text, abstain_no_source());
    assert!(steps.contains(&("gate".into(), "stop".into(), "no_evidence".into())));
    assert_eq!(server.model_calls.load(Ordering::SeqCst), 0);

    post(&server, "/v1/admin/brain/sources", None, source_body()).await;
    let (_, body, _) = post(
        &server,
        "/v1/admin/brain/claims",
        None,
        claim_body(Some("Paper A")),
    )
    .await;
    assert_eq!(body["decision"], "accepted");
    let claim_path = body["path"].as_str().unwrap().to_owned();
    assert!(claim_path.starts_with("Claims/"));
    // the retrieval index follows the write: the next turn finds the Claim and asks the model
    let (_, _, steps) = chat(&server, None, QUESTION).await;
    assert!(steps.contains(&("retrieval".into(), "ok".into(), "".into())));
    assert!(
        server.model_calls.load(Ordering::SeqCst) >= 1,
        "a covered question reaches the model"
    );

    // retraction: the Claim leaves the brain and the next turn finds nothing
    let (status, report, _) = post(
        &server,
        "/v1/admin/brain/retract",
        None,
        json!({"title": "Paper A", "reason": "withdrawn by the journal"}),
    )
    .await;
    assert_eq!(status, 200, "{report}");
    let touched = report["retired"].as_array().unwrap().len()
        + report["downgraded"].as_array().unwrap().len();
    assert!(
        touched >= 1,
        "the Claim was retired or downgraded: {report}"
    );
    let before = server.model_calls.load(Ordering::SeqCst);
    let (_, text, _) = chat(&server, None, QUESTION).await;
    assert_eq!(text, abstain_no_source());
    assert_eq!(server.model_calls.load(Ordering::SeqCst), before);

    let (status, _, _) = post(
        &server,
        "/v1/admin/brain/retract",
        None,
        json!({"title": "No Such Paper", "reason": "x"}),
    )
    .await;
    assert_eq!(status, 404);
}

#[tokio::test]
async fn no_route_returns_a_note_or_lists_the_vault() {
    let server = start(None, vec![], "noread").await;
    post(&server, "/v1/admin/brain/sources", None, source_body()).await;
    for path in [
        "/v1/admin/brain",
        "/v1/admin/brain/sources",
        "/v1/laris/brain",
        "/v1/admin/brain/notes",
    ] {
        let response = reqwest::Client::new()
            .get(format!("http://127.0.0.1:{}{path}", server.port))
            .header(
                "x-laris-protocol",
                laris_protocol::PROTOCOL_VERSION.to_string(),
            )
            .send()
            .await
            .unwrap();
        assert!(
            matches!(response.status().as_u16(), 404 | 405),
            "{path}: {}",
            response.status()
        );
        assert!(!response.text().await.unwrap().contains("Aspirin"));
    }
}

#[tokio::test]
async fn the_evidence_of_one_answer_stays_within_its_budget() {
    // a passage is never cut (the quote check needs it whole), so one that does not fit is not shown at all
    let config = PipelineConfig {
        grounding: Grounding::Required,
        max_evidence_chars: 10,
        ..PipelineConfig::default()
    };
    let server = start_with(config, None, vec![answer("unused")], "budget").await;
    post(&server, "/v1/admin/brain/sources", None, source_body()).await;
    post(
        &server,
        "/v1/admin/brain/claims",
        None,
        claim_body(Some("Paper A")),
    )
    .await;
    let (_, text, steps) = chat(&server, None, QUESTION).await;
    assert_eq!(text, abstain_no_source());
    assert!(
        steps.contains(&("gate".into(), "stop".into(), "no_evidence".into())),
        "{steps:?}"
    );
    assert_eq!(server.model_calls.load(Ordering::SeqCst), 0);
}

// ---------------------------------------------------------------- roles (PostgreSQL)

struct Env {
    dsn: String,
    schema: String,
}

impl Env {
    fn new() -> Option<Self> {
        let dsn = std::env::var("LARIS_TEST_PG_DSN")
            .ok()
            .filter(|v| !v.trim().is_empty());
        let Some(dsn) = dsn else {
            eprintln!("LARIS_TEST_PG_DSN is not set: PostgreSQL test skipped");
            return None;
        };
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        Some(Self {
            dsn,
            schema: format!("t240_{}_{n}", std::process::id()),
        })
    }

    async fn access(&self, roles: Option<&str>) -> Arc<Access> {
        let mut c = StorageConfig::with_dsn(&self.dsn);
        c.schema = Some(self.schema.clone());
        c.pool_max = 4;
        let storage = Arc::new(Storage::connect(&c).await.unwrap());
        let mut env: HashMap<String, String> =
            [("LARIS_SERVER__MASTER".to_string(), MASTER.to_string())].into();
        if let Some(r) = roles {
            env.insert("LARIS_SERVER__ROLES".into(), r.into());
        }
        Arc::new(Access::new(
            storage,
            Master::new(MASTER).unwrap(),
            &AccessConfig::from_env(&env).unwrap(),
        ))
    }

    async fn finish(self) {
        let mut c = PgConnectOptions::from_str(&self.dsn)
            .unwrap()
            .connect()
            .await
            .unwrap();
        sqlx::raw_sql(&format!(
            "DROP SCHEMA IF EXISTS \"{}\" CASCADE",
            self.schema
        ))
        .execute(&mut c)
        .await
        .unwrap();
    }
}

async fn key(access: &Access, role: &str) -> String {
    access
        .keys()
        .create(
            &NewKey {
                label: "test".into(),
                role: role.into(),
                ..NewKey::default()
            },
            1000.0,
        )
        .await
        .unwrap()
        .1
}

#[tokio::test]
async fn only_an_admin_may_write_the_brain_and_a_user_may_read_through_the_pipeline() {
    let Some(env) = Env::new() else { return };
    let access = env.access(None).await;
    let admin = key(&access, "admin").await;
    let user = key(&access, "user").await;
    let readonly = key(&access, "readonly").await;
    let server = start(Some(access), vec![answer("unused")], "roles").await;

    for path in ["sources", "claims", "retract"] {
        for who in [Some(user.as_str()), Some(readonly.as_str()), None] {
            let (status, _, _) =
                post(&server, &format!("/v1/admin/brain/{path}"), who, json!({})).await;
            assert!(matches!(status, 401 | 403), "{path}: {status}");
        }
    }
    let (status, body, _) = post(
        &server,
        "/v1/admin/brain/sources",
        Some(&admin),
        source_body(),
    )
    .await;
    assert_eq!((status, body["decision"].as_str()), (200, Some("accepted")));
    let (_, body, _) = post(
        &server,
        "/v1/admin/brain/claims",
        Some(&admin),
        claim_body(Some("Paper A")),
    )
    .await;
    assert_eq!(body["decision"], "accepted");
    // the audit names the key that proposed it
    let audit = std::fs::read_to_string(server.brain_dir.join(".laris/brain-audit.jsonl")).unwrap();
    assert!(audit.contains("\"key:"), "{audit}");

    // a user has brain.read: retrieval runs and finds the Claim
    let (status, _, steps) = chat(&server, Some(&user), QUESTION).await;
    assert_eq!(status, 200);
    assert!(
        steps.contains(&("retrieval".into(), "ok".into(), "".into())),
        "{steps:?}"
    );
    env.finish().await;
}

#[tokio::test]
async fn a_role_without_brain_read_gets_no_grounding_and_the_permission_cannot_be_lent() {
    let Some(env) = Env::new() else { return };
    let roles = r#"{"guest":["chat","account"],"admin":["chat","brain.manage","brain.read"]}"#;
    let access = env.access(Some(roles)).await;
    let guest = key(&access, "guest").await;
    let server = start(Some(access.clone()), vec![], "guest").await;
    let (status, text, steps) = chat(&server, Some(&guest), QUESTION).await;
    assert_eq!(status, 200);
    assert_eq!(text, abstain_no_source());
    assert!(
        steps.contains(&("retrieval".into(), "skipped".into(), "no_permission".into())),
        "{steps:?}"
    );
    // brain.manage is privileged: a key of a non-privileged role cannot be given it as an extra
    let lend = access
        .keys()
        .create(
            &NewKey {
                label: "lend".into(),
                role: "guest".into(),
                extra_permissions: ["brain.manage".to_string()].into(),
                ..NewKey::default()
            },
            1000.0,
        )
        .await;
    assert!(lend.is_err());
    env.finish().await;
}

#[test]
fn the_default_roles_give_brain_read_to_users_and_brain_manage_to_admins_only() {
    let roles = Roles::default();
    assert!(roles.of("user").contains("brain.read"));
    assert!(!roles.of("user").contains("brain.manage"));
    assert!(!roles.of("readonly").contains("brain.read"));
    assert!(roles.of("admin").contains("brain.manage") && roles.of("admin").contains("brain.read"));
    let extras = ["brain.manage".to_string()].into();
    assert!(roles.check_extras("user", &extras).is_err());
    assert!(roles.check_extras("admin", &extras).is_ok());
}

#[tokio::test]
async fn the_pipeline_skips_retrieval_for_a_caller_without_brain_read() {
    let (brain, _) = open_brain("direct");
    let model = Scripted {
        scripts: Mutex::new(vec![answer("free")].into()),
        calls: Arc::default(),
    };
    let policy = Policy::load(&PolicyConfig::with_root(repo()), std::iter::empty(), None).unwrap();
    let pipeline = Pipeline::new(
        Arc::new(model),
        PipelineConfig {
            grounding: Grounding::Optional,
            ..PipelineConfig::default()
        },
        None,
        policy.harness().cloned(),
        Some(brain),
    )
    .unwrap();
    let request: ChatRequest = serde_json::from_value(json!({
        "messages": [{"role": "user", "content": QUESTION}], "stream": true,
        "laris": {"kind": "turn", "session_id": "sess-1"}
    }))
    .unwrap();
    let who = Caller {
        key_id: Some("k1".into()),
        brain_read: false,
    };
    let mut out = pipeline.chat_as(request, &who).await.unwrap();
    let mut wire = String::new();
    while let Some(Ok(c)) = out.next().await {
        wire.push_str(&serde_json::to_string(&c).unwrap());
    }
    assert!(wire.contains("no_permission"), "{wire}");
    assert!(wire.contains("free"), "a free answer still streams: {wire}");
}
