//! Keys, roles and quotas (SR-S2) over real sockets against PostgreSQL named by `LARIS_TEST_PG_DSN` (the tests print
//! a notice and pass without it, as in `tests/storage.rs`). Each test works in its own schema.

use futures_util::future::BoxFuture;
use futures_util::{StreamExt, stream};
use laris_protocol::p1::{ChatRequest, ChatResponseChunk, EmbedRequest, EmbedResponse};
use laris_server::access::{Access, AccessConfig, KeyError, Master, NewKey};
use laris_server::storage::{Storage, StorageConfig};
use laris_server::{ApiError, AppState, Backend, ChunkStream, MemorySink, ServerConfig, serve};
use serde_json::{Value, json};
use sqlx::postgres::PgConnectOptions;
use sqlx::{ConnectOptions, Row};
use std::collections::{BTreeSet, HashMap};
use std::str::FromStr;
use std::sync::Arc;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::oneshot;

const MASTER: &str = "0123456789abcdef0123456789abcdef";
static COUNTER: AtomicU32 = AtomicU32::new(0);

#[derive(Clone, Copy)]
enum Model {
    /// One chunk "ok" then the end.
    Short,
    /// One chunk, then silence until the client leaves.
    Hang,
    /// A 502 before any chunk.
    Down,
}

struct Scripted(Model);

fn chunk(text: &str) -> ChatResponseChunk {
    serde_json::from_value(json!({
        "id": "c1", "object": "chat.completion.chunk", "model": "m",
        "choices": [{"index": 0, "delta": {"content": text}}]
    }))
    .unwrap()
}

impl Backend for Scripted {
    fn chat(&self, _r: ChatRequest) -> BoxFuture<'static, Result<ChunkStream, ApiError>> {
        let model = self.0;
        Box::pin(async move {
            Ok(match model {
                Model::Short => stream::iter(vec![Ok(chunk("ok"))]).boxed(),
                Model::Hang => stream::iter(vec![Ok(chunk("0123456789abcdefghij"))])
                    .chain(stream::pending())
                    .boxed(),
                Model::Down => {
                    return Err(ApiError::BadGateway("the model service is down".into()));
                }
            })
        })
    }

    fn embed(&self, _r: EmbedRequest) -> BoxFuture<'static, Result<EmbedResponse, ApiError>> {
        let model = self.0;
        Box::pin(async move {
            if let Model::Down = model {
                return Err(ApiError::BadGateway("the model service is down".into()));
            }
            Ok(serde_json::from_value(json!({
                "object": "list", "model": "m",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.5]}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 0, "total_tokens": 3}
            }))
            .unwrap())
        })
    }
}

struct Env {
    dsn: String,
    schema: String,
}

impl Env {
    fn new() -> Option<Self> {
        let Some(dsn) = std::env::var("LARIS_TEST_PG_DSN")
            .ok()
            .filter(|v| !v.trim().is_empty())
        else {
            eprintln!("LARIS_TEST_PG_DSN is not set: PostgreSQL test skipped");
            return None;
        };
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        Some(Self {
            dsn,
            schema: format!("t143_{}_{n}", std::process::id()),
        })
    }

    async fn storage(&self) -> Arc<Storage> {
        let mut c = StorageConfig::with_dsn(&self.dsn);
        c.schema = Some(self.schema.clone());
        c.pool_max = 8;
        Arc::new(Storage::connect(&c).await.unwrap())
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

fn access_config() -> AccessConfig {
    let env: HashMap<String, String> =
        [("LARIS_SERVER__MASTER".to_string(), MASTER.to_string())].into();
    AccessConfig::from_env(&env).unwrap()
}

fn access_over(storage: &Arc<Storage>, master: &str) -> Arc<Access> {
    Arc::new(Access::new(
        storage.clone(),
        Master::new(master).unwrap(),
        &access_config(),
    ))
}

struct Server {
    addr: std::net::SocketAddr,
    sink: Arc<MemorySink>,
    stop: Option<oneshot::Sender<()>>,
    task: tokio::task::JoinHandle<()>,
}

impl Server {
    async fn start(access: Arc<Access>, model: Model) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let mut config = ServerConfig::with_bind(addr);
        config.shutdown_grace = Duration::from_millis(200);
        let state = Arc::new(AppState::new(config, Arc::new(Scripted(model)), access));
        let sink = Arc::new(MemorySink::default());
        let (tx, rx) = oneshot::channel::<()>();
        let sink2 = sink.clone();
        let task = tokio::spawn(async move {
            let _ = serve(listener, state, sink2, async {
                let _ = rx.await;
            })
            .await;
        });
        Self {
            addr,
            sink,
            stop: Some(tx),
            task,
        }
    }

    /// Sends one request and returns (status, body text).
    async fn call(
        &self,
        method: &str,
        path: &str,
        key: Option<&str>,
        body: Option<&str>,
    ) -> (u16, String) {
        let mut s = TcpStream::connect(self.addr).await.unwrap();
        let auth = key
            .map(|k| format!("Authorization: Bearer {k}\r\n"))
            .unwrap_or_default();
        let (ctype, len, payload) = match body {
            Some(b) => ("Content-Type: application/json\r\n", b.len(), b),
            None => ("", 0, ""),
        };
        let req = format!(
            "{method} {path} HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Laris-Protocol: 1\r\n{auth}{ctype}Content-Length: {len}\r\n\r\n{payload}"
        );
        s.write_all(req.as_bytes()).await.unwrap();
        let mut raw = Vec::new();
        let _ = tokio::time::timeout(Duration::from_secs(5), s.read_to_end(&mut raw)).await;
        let text = String::from_utf8_lossy(&raw).into_owned();
        let status = text
            .split_whitespace()
            .nth(1)
            .and_then(|c| c.parse().ok())
            .unwrap_or(0);
        let body = text.split("\r\n\r\n").nth(1).unwrap_or("").to_string();
        (status, body)
    }

    async fn chat(&self, key: Option<&str>) -> (u16, String) {
        self.call("POST", "/v1/laris/chat", key, Some(CHAT)).await
    }

    async fn shutdown(mut self) {
        if let Some(tx) = self.stop.take() {
            let _ = tx.send(());
        }
        let _ = tokio::time::timeout(Duration::from_secs(3), self.task).await;
    }
}

const CHAT: &str =
    r#"{"messages":[{"role":"user","content":"hello there, how are you doing today"}]}"#;

fn new_key(role: &str, limit: Option<i64>) -> NewKey {
    NewKey {
        label: "test".into(),
        role: role.into(),
        token_limit: limit,
        ..NewKey::default()
    }
}

/// The random part of a key text (`lk_<id>_<secret>`; the secret may itself hold `_`).
fn secret_of(text: &str) -> &str {
    text.splitn(3, '_').nth(2).unwrap()
}

fn set(items: &[&str]) -> BTreeSet<String> {
    items.iter().map(|s| (*s).to_string()).collect()
}

async fn key_row(storage: &Storage, id: &str) -> (i64, i64) {
    let r = sqlx::query("SELECT tokens_used, tokens_reserved FROM keys WHERE id = $1")
        .bind(id)
        .fetch_one(storage.pool())
        .await
        .unwrap();
    (r.get(0), r.get(1))
}

/// Waits until the key holds no reservation and has settled `requests` usage rows.
async fn settled(storage: &Storage, id: &str, requests: i64) -> (i64, i64) {
    for _ in 0..150 {
        let rows: i64 = sqlx::query_scalar("SELECT count(*) FROM usage WHERE key_id = $1")
            .bind(id)
            .fetch_one(storage.pool())
            .await
            .unwrap();
        let (used, reserved) = key_row(storage, id).await;
        if rows >= requests && reserved == 0 {
            return (used, rows);
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    panic!("the key did not settle: {:?}", key_row(storage, id).await);
}

#[tokio::test]
async fn a_key_is_stored_as_a_digest_only_and_needs_the_master_secret() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    let (record, text) = access
        .keys()
        .create(&new_key("user", None), 1000.0)
        .await
        .unwrap();
    assert!(text.starts_with("lk_") && text.contains(&record.id));
    let secret = secret_of(&text);
    // no column of the row holds the text, the secret part or the id-plus-secret form
    let row = sqlx::query("SELECT digest, secret_enc, label, role, extra_permissions, allowed_ips FROM keys WHERE id = $1")
        .bind(&record.id)
        .fetch_one(storage.pool())
        .await
        .unwrap();
    let digest: String = row.get("digest");
    assert_eq!(digest.len(), 64);
    assert!(row.get::<Option<Vec<u8>>, _>("secret_enc").is_none());
    for column in [
        "digest",
        "label",
        "role",
        "extra_permissions",
        "allowed_ips",
    ] {
        let v: String = row.get(column);
        assert!(
            !v.contains(secret) && !v.contains(&text),
            "{column} holds the key"
        );
    }
    // the right master verifies it, another master or a wrong secret does not
    assert!(access.keys().verify(&text, 1001.0).await.unwrap().is_some());
    let other = access_over(&storage, "fedcba9876543210fedcba9876543210");
    assert!(other.keys().verify(&text, 1001.0).await.unwrap().is_none());
    let forged = format!("lk_{}_{}", record.id, "A".repeat(secret.len()));
    assert!(
        access
            .keys()
            .verify(&forged, 1001.0)
            .await
            .unwrap()
            .is_none()
    );
    assert!(access.keys().verify("", 1001.0).await.unwrap().is_none());
    // two keys never share a text
    let (_, again) = access
        .keys()
        .create(&new_key("user", None), 1000.0)
        .await
        .unwrap();
    assert_ne!(text, again);
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn keys_made_by_generation_1_still_verify() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    // digests computed by the generation-1 Python for this master and text
    let text = "lk_deadbeef_secretsecretsecretsecretsecret";
    let keyed = "c7574f3259642fa2f40e30dceeb0fe4a3fde1ed7b2b54a6590a69c3e3821aba7";
    let plain = "da432d422e14af82e08a1baff59c942c19c4b47b462b1ddf98e8d72b6f3255ba";
    for (id, digest) in [("deadbeef", keyed), ("cafebabe", plain)] {
        sqlx::query("INSERT INTO keys (id, digest, label, role, created_at) VALUES ($1, $2, 'gen1', 'user', 1)")
            .bind(id)
            .bind(digest)
            .execute(storage.pool())
            .await
            .unwrap();
    }
    assert!(access.keys().verify(text, 5.0).await.unwrap().is_some());
    // a key stored with the plain SHA-256 works once and is rewritten as a keyed digest
    let legacy_text = "lk_cafebabe_secretsecretsecretsecretsecret";
    let legacy_digest = da_plain(legacy_text);
    sqlx::query("UPDATE keys SET digest = $1 WHERE id = 'cafebabe'")
        .bind(&legacy_digest)
        .execute(storage.pool())
        .await
        .unwrap();
    assert!(
        access
            .keys()
            .verify(legacy_text, 5.0)
            .await
            .unwrap()
            .is_some()
    );
    let now: String = sqlx::query_scalar("SELECT digest FROM keys WHERE id = 'cafebabe'")
        .fetch_one(storage.pool())
        .await
        .unwrap();
    assert_ne!(now, legacy_digest);
    assert!(
        access
            .keys()
            .verify(legacy_text, 5.0)
            .await
            .unwrap()
            .is_some()
    );
    storage.close().await;
    env.finish().await;
}

/// SHA-256 as 64 hex characters, computed by PostgreSQL-independent code in the test crate.
fn da_plain(text: &str) -> String {
    use sha2::{Digest, Sha256};
    Sha256::digest(text.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

#[tokio::test]
async fn expiry_and_revocation_end_a_key() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    let mut short = new_key("user", None);
    short.expires_in_days = Some(1.0);
    let (_, text) = access.keys().create(&short, 1000.0).await.unwrap();
    assert!(
        access
            .keys()
            .verify(&text, 1000.0 + 86_399.0)
            .await
            .unwrap()
            .is_some()
    );
    assert!(
        access
            .keys()
            .verify(&text, 1000.0 + 86_400.0)
            .await
            .unwrap()
            .is_none()
    );
    let (rec, text) = access
        .keys()
        .create(&new_key("user", None), 1000.0)
        .await
        .unwrap();
    assert!(access.keys().verify(&text, 2000.0).await.unwrap().is_some());
    let revoked = access.keys().revoke(&rec.id, 3000.0).await.unwrap();
    assert_eq!(revoked.status(3001.0), "revoked");
    assert!(access.keys().verify(&text, 3001.0).await.unwrap().is_none());
    // revoking again keeps the first time
    assert_eq!(
        access
            .keys()
            .revoke(&rec.id, 9000.0)
            .await
            .unwrap()
            .revoked_at,
        Some(3000.0)
    );
    assert!(matches!(
        access.keys().revoke("00000000", 1.0).await,
        Err(KeyError::NotFound)
    ));
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn every_way_of_not_being_a_valid_key_answers_401_alike() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    let (rec, text) = access
        .keys()
        .create(&new_key("user", None), 1.0)
        .await
        .unwrap();
    let (gone, gone_text) = access
        .keys()
        .create(&new_key("user", None), 1.0)
        .await
        .unwrap();
    access.keys().revoke(&gone.id, 2.0).await.unwrap();
    let server = Server::start(access.clone(), Model::Short).await;
    let wrong_secret = format!("lk_{}_{}", rec.id, "B".repeat(32));
    let unknown_id = "lk_00000000_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    let mut bodies = BTreeSet::new();
    for key in [
        None,
        Some(""),
        Some("nonsense"),
        Some(unknown_id),
        Some(wrong_secret.as_str()),
        Some(gone_text.as_str()),
    ] {
        let (status, body) = server.chat(key).await;
        assert_eq!(status, 401, "{key:?}");
        bodies.insert(body);
    }
    assert_eq!(bodies.len(), 1, "the answers differ: {bodies:?}");
    let (status, _) = server.chat(Some(&text)).await;
    assert_eq!(status, 200);
    // a header without the Bearer scheme is not a key
    let mut s = TcpStream::connect(server.addr).await.unwrap();
    let req = format!(
        "POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nConnection: close\r\nX-Laris-Protocol: 1\r\nAuthorization: Basic {text}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{CHAT}",
        CHAT.len()
    );
    s.write_all(req.as_bytes()).await.unwrap();
    let mut raw = Vec::new();
    let _ = tokio::time::timeout(Duration::from_secs(5), s.read_to_end(&mut raw)).await;
    assert!(String::from_utf8_lossy(&raw).starts_with("HTTP/1.1 401"));
    server.shutdown().await;
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn a_role_without_the_permission_gets_403_and_extras_follow_the_privilege_rule() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    let (_, readonly) = access
        .keys()
        .create(&new_key("readonly", None), 1.0)
        .await
        .unwrap();
    let (_, user) = access
        .keys()
        .create(&new_key("user", None), 1.0)
        .await
        .unwrap();
    let mut extra = new_key("readonly", None);
    extra.extra_permissions = set(&["chat"]);
    let (_, readonly_chat) = access.keys().create(&extra, 1.0).await.unwrap();
    let server = Server::start(access.clone(), Model::Short).await;
    assert_eq!(server.chat(Some(&readonly)).await.0, 403);
    assert_eq!(
        server
            .call(
                "POST",
                "/v1/laris/embed",
                Some(&readonly),
                Some(r#"{"input":"x"}"#)
            )
            .await
            .0,
        403
    );
    assert_eq!(
        server
            .call("GET", "/v1/laris/account", Some(&readonly), None)
            .await
            .0,
        200
    );
    assert_eq!(server.chat(Some(&readonly_chat)).await.0, 200);
    for (path, method) in [("/v1/admin/usage", "GET"), ("/v1/admin/keys", "GET")] {
        assert_eq!(
            server.call(method, path, Some(&user), None).await.0,
            403,
            "{path}"
        );
    }
    assert_eq!(
        server
            .call(
                "POST",
                "/v1/admin/keys",
                Some(&user),
                Some(r#"{"role":"user"}"#)
            )
            .await
            .0,
        403
    );
    // a privileged permission cannot be handed to an ordinary role
    let mut bad = new_key("user", None);
    bad.extra_permissions = set(&["keys.manage"]);
    assert!(matches!(
        access.keys().create(&bad, 1.0).await,
        Err(KeyError::Invalid(_))
    ));
    bad.extra_permissions = set(&["no.such.permission"]);
    assert!(matches!(
        access.keys().create(&bad, 1.0).await,
        Err(KeyError::Invalid(_))
    ));
    assert!(matches!(
        access.keys().create(&new_key("emperor", None), 1.0).await,
        Err(KeyError::Invalid(_))
    ));
    server.shutdown().await;
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn a_key_without_tokens_gets_429_and_the_request_costs_nothing() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    let (zero, zero_text) = access
        .keys()
        .create(&new_key("user", Some(0)), 1.0)
        .await
        .unwrap();
    let (tiny, tiny_text) = access
        .keys()
        .create(&new_key("user", Some(5)), 1.0)
        .await
        .unwrap();
    let server = Server::start(access.clone(), Model::Short).await;
    assert_eq!(server.chat(Some(&zero_text)).await.0, 429);
    assert_eq!(
        server.chat(Some(&tiny_text)).await.0,
        429,
        "the request needs more than 5 tokens"
    );
    assert_eq!(key_row(&storage, &zero.id).await, (0, 0));
    assert_eq!(key_row(&storage, &tiny.id).await, (0, 0));
    let usage: i64 = sqlx::query_scalar("SELECT count(*) FROM usage")
        .fetch_one(storage.pool())
        .await
        .unwrap();
    assert_eq!(usage, 0);
    server.shutdown().await;
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn parallel_reservations_never_pass_the_limit() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    let (rec, _) = access
        .keys()
        .create(&new_key("user", Some(95)), 1.0)
        .await
        .unwrap();
    let principal = laris_server::access::Principal {
        key_id: rec.id.clone(),
        role: "user".into(),
        permissions: set(&["chat"]),
    };
    let mut tasks = Vec::new();
    for _ in 0..40 {
        let (access, principal) = (access.clone(), principal.clone());
        tasks.push(tokio::spawn(
            async move { access.reserve(&principal, 10).await },
        ));
    }
    let mut held = Vec::new();
    let mut refused = 0;
    for t in tasks {
        match t.await.unwrap() {
            Ok(r) => held.push(r),
            Err(ApiError::TooManyRequests { .. }) => refused += 1,
            Err(e) => panic!("{e:?}"),
        }
    }
    assert_eq!(
        (held.len(), refused),
        (9, 31),
        "95 tokens hold nine reservations of 10, no more"
    );
    assert_eq!(key_row(&storage, &rec.id).await, (0, 90));
    // settling at the reserved size keeps the total at the limit; the next reservation is still refused
    for r in &held {
        let used = laris_server::access::Used {
            prompt_tokens: 6,
            completion_tokens: 4,
            kind: "chat".into(),
            session_id: String::new(),
        };
        r.settle(&used, laris_server::access::now()).await.unwrap();
        r.settle(&used, laris_server::access::now()).await.unwrap(); // a second settle does nothing
    }
    assert_eq!(key_row(&storage, &rec.id).await, (90, 0));
    assert!(matches!(
        access.reserve(&principal, 10).await,
        Err(ApiError::TooManyRequests { .. })
    ));
    assert!(access.reserve(&principal, 5).await.is_ok());
    let rows: i64 = sqlx::query_scalar("SELECT count(*) FROM usage WHERE key_id = $1")
        .bind(&rec.id)
        .fetch_one(storage.pool())
        .await
        .unwrap();
    assert_eq!(rows, 9, "one usage row per settled request");
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn parallel_requests_over_http_get_exactly_what_the_quota_covers() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    let estimate = access.estimate_tokens(CHAT.len() as u64);
    let (rec, text) = access
        .keys()
        .create(&new_key("user", Some(estimate * 4 + estimate / 2)), 1.0)
        .await
        .unwrap();
    let server = Arc::new(Server::start(access.clone(), Model::Short).await);
    let mut tasks = Vec::new();
    for _ in 0..16 {
        let (server, text) = (server.clone(), text.clone());
        tasks.push(tokio::spawn(
            async move { server.chat(Some(&text)).await.0 },
        ));
    }
    let mut statuses = Vec::new();
    for t in tasks {
        statuses.push(t.await.unwrap());
    }
    assert_eq!(
        statuses.iter().filter(|s| **s == 200).count(),
        4,
        "{statuses:?}"
    );
    assert_eq!(
        statuses.iter().filter(|s| **s == 429).count(),
        12,
        "{statuses:?}"
    );
    let (used, rows) = settled(&storage, &rec.id, 4).await;
    assert_eq!(rows, 4);
    assert!(
        used <= estimate * 4 + 4,
        "used {used} for four requests of {estimate} plus one token each"
    );
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn a_request_that_fails_or_a_client_that_leaves_is_settled_or_released() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    let (rec, text) = access
        .keys()
        .create(&new_key("user", Some(10_000)), 1.0)
        .await
        .unwrap();
    // the model is down: 502, nothing charged, nothing held
    let down = Server::start(access.clone(), Model::Down).await;
    assert_eq!(down.chat(Some(&text)).await.0, 502);
    assert_eq!(
        down.call(
            "POST",
            "/v1/laris/embed",
            Some(&text),
            Some(r#"{"input":"x"}"#)
        )
        .await
        .0,
        502
    );
    assert_eq!(key_row(&storage, &rec.id).await, (0, 0));
    down.shutdown().await;
    // the client reads the first chunk and leaves: what was produced is charged, the rest is released
    let hang = Server::start(access.clone(), Model::Hang).await;
    let mut s = TcpStream::connect(hang.addr).await.unwrap();
    let req = format!(
        "POST /v1/laris/chat HTTP/1.1\r\nHost: t\r\nX-Laris-Protocol: 1\r\nAuthorization: Bearer {text}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{CHAT}",
        CHAT.len()
    );
    s.write_all(req.as_bytes()).await.unwrap();
    let mut seen = Vec::new();
    let mut buf = [0u8; 4096];
    while !String::from_utf8_lossy(&seen).contains("0123456789abcdefghij") {
        let n = tokio::time::timeout(Duration::from_secs(5), s.read(&mut buf))
            .await
            .unwrap()
            .unwrap();
        assert!(n > 0, "the stream ended early");
        seen.extend_from_slice(&buf[..n]);
    }
    drop(s);
    let (used, rows) = settled(&storage, &rec.id, 1).await;
    assert_eq!(rows, 1);
    let prompt = access.estimate_tokens(CHAT.len() as u64);
    assert_eq!(
        used,
        prompt + access.estimate_tokens(20),
        "prompt estimate plus the 20 characters sent"
    );
    hang.shutdown().await;
    // an embed settles with the usage the model reported
    let ok = Server::start(access.clone(), Model::Short).await;
    assert_eq!(
        ok.call(
            "POST",
            "/v1/laris/embed",
            Some(&text),
            Some(r#"{"input":"x"}"#)
        )
        .await
        .0,
        200
    );
    let (used2, rows2) = settled(&storage, &rec.id, 2).await;
    assert_eq!((used2 - used, rows2), (3, 2));
    ok.shutdown().await;
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn the_account_route_shows_role_permissions_and_tokens_left() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    let (_, limited) = access
        .keys()
        .create(&new_key("user", Some(1000)), 1.0)
        .await
        .unwrap();
    let (_, free) = access
        .keys()
        .create(&new_key("readonly", None), 1.0)
        .await
        .unwrap();
    let server = Server::start(access, Model::Short).await;
    let (status, body) = server
        .call("GET", "/v1/laris/account", Some(&limited), None)
        .await;
    let v: Value = serde_json::from_str(&body).unwrap();
    assert_eq!(status, 200);
    assert_eq!(v["role"], "user");
    assert_eq!(
        (
            v["token_limit"].clone(),
            v["tokens_used"].clone(),
            v["tokens_left"].clone()
        ),
        (json!(1000), json!(0), json!(1000))
    );
    assert!(
        v["permissions"]
            .as_array()
            .unwrap()
            .contains(&json!("chat"))
    );
    let (_, body) = server
        .call("GET", "/v1/laris/account", Some(&free), None)
        .await;
    let v: Value = serde_json::from_str(&body).unwrap();
    assert!(v["token_limit"].is_null() && v["tokens_left"].is_null());
    assert_eq!(
        server.call("GET", "/v1/laris/account", None, None).await.0,
        401
    );
    // the protocol version is still checked first
    let mut s = TcpStream::connect(server.addr).await.unwrap();
    s.write_all(b"GET /v1/laris/account HTTP/1.1\r\nHost: t\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
        .await
        .unwrap();
    let mut raw = Vec::new();
    let _ = s.read_to_end(&mut raw).await;
    assert!(String::from_utf8_lossy(&raw).starts_with("HTTP/1.1 426"));
    server.shutdown().await;
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn the_admin_routes_run_a_key_through_its_life() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    let first = access
        .ensure_builtin_key("default (server only)")
        .await
        .unwrap()
        .expect("made on first start");
    assert!(
        access.ensure_builtin_key("again").await.unwrap().is_none(),
        "made once"
    );
    let server = Server::start(access.clone(), Model::Short).await;
    // create
    let (status, body) = server
        .call(
            "POST",
            "/v1/admin/keys",
            Some(&first),
            Some(r#"{"label":"ci","role":"user","token_limit":50000,"expires_in_days":30,"allowed_ips":["127.0.0.0/8"]}"#),
        )
        .await;
    assert_eq!(status, 201, "{body}");
    let made: Value = serde_json::from_str(&body).unwrap();
    let text = made["key"].as_str().unwrap().to_string();
    let id = made["record"]["id"].as_str().unwrap().to_string();
    assert_eq!(made["record"]["status"], "active");
    assert!(made["record"].get("digest").is_none());
    assert_eq!(server.chat(Some(&text)).await.0, 200);
    // list: the key text is in no listing
    let (status, body) = server
        .call("GET", "/v1/admin/keys", Some(&first), None)
        .await;
    assert_eq!(status, 200);
    assert!(
        !body.contains(&text) && !body.contains(secret_of(&text)),
        "{body}"
    );
    assert_eq!(
        serde_json::from_str::<Value>(&body).unwrap()["keys"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
    // limit: set, add, lift
    let (status, body) = server
        .call(
            "POST",
            &format!("/v1/admin/keys/{id}/limit"),
            Some(&first),
            Some(r#"{"token_limit":10}"#),
        )
        .await;
    assert_eq!(status, 200, "{body}");
    assert_eq!(server.chat(Some(&text)).await.0, 429);
    let (_, body) = server
        .call(
            "POST",
            &format!("/v1/admin/keys/{id}/limit"),
            Some(&first),
            Some(r#"{"token_limit":1000,"add":true}"#),
        )
        .await;
    assert_eq!(
        serde_json::from_str::<Value>(&body).unwrap()["record"]["token_limit"],
        1010
    );
    assert_eq!(server.chat(Some(&text)).await.0, 200);
    let (_, body) = server
        .call(
            "POST",
            &format!("/v1/admin/keys/{id}/limit"),
            Some(&first),
            Some(r#"{"token_limit":null}"#),
        )
        .await;
    assert!(serde_json::from_str::<Value>(&body).unwrap()["record"]["token_limit"].is_null());
    // usage
    settled(&storage, &id, 2).await;
    let (status, body) = server
        .call("GET", "/v1/admin/usage", Some(&first), None)
        .await;
    assert_eq!(status, 200);
    let usage: Value = serde_json::from_str(&body).unwrap();
    let line = usage["usage"]
        .as_array()
        .unwrap()
        .iter()
        .find(|l| l["key_id"] == id.as_str())
        .unwrap()
        .clone();
    assert_eq!(line["requests"], 2);
    // revoke: the very next request fails
    let (status, body) = server
        .call(
            "POST",
            &format!("/v1/admin/keys/{id}/revoke"),
            Some(&first),
            None,
        )
        .await;
    assert_eq!(status, 200, "{body}");
    assert_eq!(
        serde_json::from_str::<Value>(&body).unwrap()["record"]["status"],
        "revoked"
    );
    assert_eq!(server.chat(Some(&text)).await.0, 401);
    // mistakes
    assert_eq!(
        server
            .call("POST", "/v1/admin/keys/00000000/revoke", Some(&first), None)
            .await
            .0,
        404
    );
    assert_eq!(
        server
            .call(
                "POST",
                "/v1/admin/keys",
                Some(&first),
                Some(r#"{"role":"emperor"}"#)
            )
            .await
            .0,
        400
    );
    assert_eq!(
        server
            .call(
                "POST",
                "/v1/admin/keys",
                Some(&first),
                Some(r#"{"role":"user","token_limit":-1}"#)
            )
            .await
            .0,
        400
    );
    assert_eq!(
        server
            .call(
                "POST",
                "/v1/admin/keys",
                Some(&first),
                Some(r#"{"role":"user","allowed_ips":["not an ip"]}"#)
            )
            .await
            .0,
        400
    );
    assert_eq!(
        server
            .call(
                "POST",
                "/v1/admin/keys",
                Some(&first),
                Some(r#"{"role":"user","surprise":1}"#)
            )
            .await
            .0,
        400
    );
    assert_eq!(
        server
            .call("DELETE", "/v1/admin/keys", Some(&first), None)
            .await
            .0,
        405
    );
    server.shutdown().await;
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn address_rules_make_a_key_look_unknown_from_other_addresses() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    let mut elsewhere = new_key("user", None);
    elsewhere.allowed_ips = vec!["10.0.0.0/8".into()];
    let (_, away) = access.keys().create(&elsewhere, 1.0).await.unwrap();
    let mut here = new_key("user", None);
    here.allowed_ips = vec!["@server".into()];
    let (_, local) = access.keys().create(&here, 1.0).await.unwrap();
    let mut bad = new_key("user", None);
    bad.allowed_ips = vec!["10.0.0.0/99".into()];
    assert!(access.keys().create(&bad, 1.0).await.is_err());
    let server = Server::start(access.clone(), Model::Short).await;
    assert_eq!(server.chat(Some(&away)).await.0, 401);
    assert_eq!(server.chat(Some(&local)).await.0, 200);
    server.shutdown().await;
    storage.close().await;
    env.finish().await;
}

#[tokio::test]
async fn no_key_appears_in_the_log_an_error_or_a_debug_print() {
    let Some(env) = Env::new() else { return };
    let storage = env.storage().await;
    let access = access_over(&storage, MASTER);
    let first = access.ensure_builtin_key("default").await.unwrap().unwrap();
    let (record, user) = access
        .keys()
        .create(&new_key("user", Some(3)), 1.0)
        .await
        .unwrap();
    let server = Server::start(access.clone(), Model::Short).await;
    let wrong = format!("lk_{}_{}", record.id, "Z".repeat(32));
    let mut answers = Vec::new();
    for key in [
        Some(user.as_str()),
        Some(wrong.as_str()),
        Some(first.as_str()),
        None,
    ] {
        answers.push(server.chat(key).await.1);
    }
    answers.push(
        server
            .call("GET", "/v1/admin/keys", Some(&user), None)
            .await
            .1,
    );
    answers.push(
        server
            .call("GET", "/v1/admin/keys", Some(&first), None)
            .await
            .1,
    );
    tokio::time::sleep(Duration::from_millis(200)).await;
    let log = format!("{:?}", server.sink.records());
    let debug = format!(
        "{record:?} {access:?} {storage:?} {:?}",
        Master::new(MASTER).unwrap()
    );
    for key in [&user, &first, &wrong] {
        let secret = secret_of(key);
        for text in answers.iter().chain([&log, &debug]) {
            assert!(
                !text.contains(key.as_str()) && !text.contains(secret),
                "a key leaked into: {text}"
            );
        }
    }
    assert!(!debug.contains(MASTER) && !log.contains(MASTER));
    server.shutdown().await;
    storage.close().await;
    env.finish().await;
}

#[test]
fn access_settings_come_from_the_environment_and_refuse_nonsense() {
    let env = |pairs: &[(&str, &str)]| -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    };
    let e = AccessConfig::from_env(&env(&[])).unwrap_err();
    assert!(e.to_string().contains("MASTER"));
    let c = AccessConfig::from_env(&env(&[
        ("LARIS_SERVER__MASTER", MASTER),
        ("LARIS_SERVER__ROLES", r#"{"solo":["chat"]}"#),
        ("LARIS_SERVER__SERVER_IPS", "10.1.0.0/16, 192.168.1.5"),
        ("LARIS_SERVER__CHARS_PER_TOKEN", "3.5"),
        ("LARIS_SERVER__FIRST_ADMIN_FILE", "/run/first.key"),
    ]))
    .unwrap();
    assert_eq!((c.server_ips.len(), c.chars_per_token), (2, 3.5));
    assert!(c.load_master().is_ok());
    assert!(c.roles.has_role("solo") && !c.roles.has_role("admin"));
    for (name, value) in [
        ("LARIS_SERVER__ROLES", "not json"),
        ("LARIS_SERVER__SERVER_IPS", "nowhere"),
        ("LARIS_SERVER__CHARS_PER_TOKEN", "0"),
        ("LARIS_SERVER__CHARS_PER_TOKEN", "many"),
        ("LARIS_SERVER__PRIVILEGED_ROLES", "admin"),
    ] {
        let err = AccessConfig::from_env(&env(&[("LARIS_SERVER__MASTER", MASTER), (name, value)]))
            .unwrap_err();
        let text = err.to_string();
        assert!(
            text.contains(name) || text.contains("PRIVILEGED"),
            "{name}: {text}"
        );
        assert!(!text.contains(MASTER), "{text}");
    }
    // a short master is refused when it is loaded, without echoing it
    let short = AccessConfig::from_env(&env(&[("LARIS_SERVER__MASTER", "tooshort")])).unwrap();
    let err = short.load_master().unwrap_err().to_string();
    assert!(!err.contains("tooshort"), "{err}");
    assert!(!format!("{short:?}").contains("tooshort"));
}
