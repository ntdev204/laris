//! Storage tests (SR-S3). They need a PostgreSQL 16 server named by `LARIS_TEST_PG_DSN` (a role that may create
//! schemas); without it every test here prints a notice and passes, so an environment without PostgreSQL stays
//! green but proves nothing. Each test works in its own schema and drops it at the end.

use laris_server::storage::{
    MIGRATIONS, RetentionHandle, Storage, StorageConfig, StorageError, migrate,
};
use sqlx::ConnectOptions;
use sqlx::postgres::{PgConnectOptions, PgPool, PgPoolOptions};
use std::str::FromStr;
use std::sync::Arc;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::Duration;

static COUNTER: AtomicU32 = AtomicU32::new(0);

fn dsn() -> Option<String> {
    let v = std::env::var("LARIS_TEST_PG_DSN")
        .ok()
        .filter(|v| !v.trim().is_empty());
    if v.is_none() {
        eprintln!("LARIS_TEST_PG_DSN is not set: PostgreSQL test skipped");
    }
    v
}

/// A schema of its own, dropped when the test calls `finish`.
struct Case {
    dsn: String,
    schema: String,
}

impl Case {
    fn new() -> Option<Self> {
        let dsn = dsn()?;
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        Some(Self {
            dsn,
            schema: format!("t142_{}_{n}", std::process::id()),
        })
    }

    fn config(&self) -> StorageConfig {
        let mut c = StorageConfig::with_dsn(&self.dsn);
        c.schema = Some(self.schema.clone());
        c.pool_max = 4;
        c
    }

    /// A pool on the case schema without running any migration.
    async fn raw_pool(&self) -> PgPool {
        let options = PgConnectOptions::from_str(&self.dsn)
            .unwrap()
            .options([("search_path", self.schema.as_str())]);
        PgPoolOptions::new()
            .max_connections(4)
            .connect_with(options)
            .await
            .unwrap()
    }

    async fn admin(&self) -> sqlx::PgConnection {
        PgConnectOptions::from_str(&self.dsn)
            .unwrap()
            .connect()
            .await
            .unwrap()
    }

    /// Restores a generation-1 dump (see `tests/fixtures/make_gen1_dumps.sh`) into the case schema.
    async fn restore(&self, dump: &str) {
        let sql = dump.replace("__schema__", &self.schema);
        let mut c = self.admin().await;
        sqlx::raw_sql(&sql).execute(&mut c).await.unwrap();
    }

    async fn finish(self) {
        let mut c = self.admin().await;
        sqlx::raw_sql(&format!(
            "DROP SCHEMA IF EXISTS \"{}\" CASCADE",
            self.schema
        ))
        .execute(&mut c)
        .await
        .unwrap();
    }
}

type UsageRow = (i64, String, f64, String, String, i64, i64);
type TraceRow = (
    i64,
    String,
    f64,
    String,
    String,
    String,
    String,
    String,
    String,
    String,
    i32,
);
type KeyRow = (String, String, String, String, i64, i64, i64);

async fn usage_rows(pool: &PgPool) -> Vec<UsageRow> {
    sqlx::query_as("SELECT id, key_id, ts, session_id, kind, prompt_tokens, completion_tokens FROM usage ORDER BY id")
        .fetch_all(pool)
        .await
        .unwrap()
}

async fn trace_rows(pool: &PgPool) -> Vec<TraceRow> {
    sqlx::query_as(
        "SELECT id, key_id, ts, session_id, model, prompt_sha256, task, reasoning, tool_calls, brain, answer_chars \
         FROM traces ORDER BY id",
    )
    .fetch_all(pool)
    .await
    .unwrap()
}

async fn key_rows(pool: &PgPool) -> Vec<KeyRow> {
    sqlx::query_as("SELECT id, digest, label, role, tokens_used, tokens_reserved, created_at::bigint FROM keys ORDER BY id")
        .fetch_all(pool)
        .await
        .unwrap()
}

async fn versions(pool: &PgPool) -> Vec<(i32, String)> {
    sqlx::query_as("SELECT version, name FROM schema_version ORDER BY version")
        .fetch_all(pool)
        .await
        .unwrap()
}

async fn epoch(pool: &PgPool, text: &str) -> f64 {
    sqlx::query_scalar("SELECT extract(epoch FROM $1::timestamptz)::double precision")
        .bind(text)
        .fetch_one(pool)
        .await
        .unwrap()
}

async fn add_usage(pool: &PgPool, key: &str, ts: f64, prompt: i64, completion: i64) {
    sqlx::query(
        "INSERT INTO usage (key_id, ts, prompt_tokens, completion_tokens) VALUES ($1, $2, $3, $4)",
    )
    .bind(key)
    .bind(ts)
    .bind(prompt)
    .bind(completion)
    .execute(pool)
    .await
    .unwrap();
}

async fn add_trace(pool: &PgPool, key: &str, ts: f64) {
    sqlx::query("INSERT INTO traces (key_id, ts) VALUES ($1, $2)")
        .bind(key)
        .bind(ts)
        .execute(pool)
        .await
        .unwrap();
}

async fn timestamps(pool: &PgPool, table: &str) -> Vec<f64> {
    sqlx::query_scalar(&format!("SELECT ts FROM {table} ORDER BY ts"))
        .fetch_all(pool)
        .await
        .unwrap()
}

#[tokio::test]
async fn a_fresh_database_gets_every_migration_once() {
    let Some(case) = Case::new() else { return };
    let storage = Storage::connect(&case.config()).await.unwrap();
    let got = versions(storage.pool()).await;
    let want: Vec<(i32, String)> = MIGRATIONS
        .iter()
        .map(|m| (m.version, m.name.to_string()))
        .collect();
    assert_eq!(got, want);
    assert_eq!(migrate(storage.pool()).await.unwrap(), 0);
    storage.close().await;
    let again = Storage::connect(&case.config()).await.unwrap();
    assert_eq!(versions(again.pool()).await, want);
    again.close().await;
    case.finish().await;
}

#[tokio::test]
async fn generation_1_database_before_partitioning_migrates_without_loss() {
    let Some(case) = Case::new() else { return };
    case.restore(include_str!("fixtures/gen1_v2.sql")).await;
    let raw = case.raw_pool().await;
    assert_eq!(versions(&raw).await.len(), 2);
    let (usage, traces, keys) = (
        usage_rows(&raw).await,
        trace_rows(&raw).await,
        key_rows(&raw).await,
    );
    assert_eq!((usage.len(), traces.len(), keys.len()), (4, 2, 2));

    let storage = Storage::connect(&case.config()).await.unwrap();
    assert_eq!(versions(storage.pool()).await.len(), 3);
    assert_eq!(usage_rows(storage.pool()).await, usage);
    assert_eq!(trace_rows(storage.pool()).await, traces);
    assert_eq!(key_rows(storage.pool()).await, keys);
    // the rows live in their months' partitions and the old tables are gone
    let m = storage.maintenance();
    let parts = m.partitions("usage").await.unwrap();
    assert!(parts.contains(&"usage_202608".to_string()), "{parts:?}");
    assert!(parts.contains(&"usage_202609".to_string()), "{parts:?}");
    assert!(parts.contains(&"usage_202610".to_string()), "{parts:?}");
    let old: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM pg_tables WHERE schemaname = $1 AND tablename LIKE '%\\_old'",
    )
    .bind(&case.schema)
    .fetch_one(storage.pool())
    .await
    .unwrap();
    assert_eq!(old, 0);
    // numbering continues after the largest id
    let ts = epoch(storage.pool(), "2026-10-02 00:00:00+00").await;
    add_usage(storage.pool(), "k1", ts, 1, 1).await;
    let ids: Vec<i64> = usage_rows(storage.pool())
        .await
        .iter()
        .map(|r| r.0)
        .collect();
    assert_eq!(ids, vec![1, 2, 3, 4, 5]);
    storage.close().await;
    case.finish().await;
}

#[tokio::test]
async fn generation_1_database_already_partitioned_is_taken_as_it_is() {
    let Some(case) = Case::new() else { return };
    case.restore(include_str!("fixtures/gen1_v3.sql")).await;
    let raw = case.raw_pool().await;
    let (usage, traces, keys) = (
        usage_rows(&raw).await,
        trace_rows(&raw).await,
        key_rows(&raw).await,
    );
    let stamps: Vec<String> =
        sqlx::query_scalar("SELECT applied_at::text FROM schema_version ORDER BY version")
            .fetch_all(&raw)
            .await
            .unwrap();
    assert_eq!(usage.len(), 5);
    assert_eq!(migrate(&raw).await.unwrap(), 0);

    let storage = Storage::connect(&case.config()).await.unwrap();
    assert_eq!(usage_rows(storage.pool()).await, usage);
    assert_eq!(trace_rows(storage.pool()).await, traces);
    assert_eq!(key_rows(storage.pool()).await, keys);
    let after: Vec<String> =
        sqlx::query_scalar("SELECT applied_at::text FROM schema_version ORDER BY version")
            .fetch_all(storage.pool())
            .await
            .unwrap();
    assert_eq!(after, stamps, "no migration ran again");
    // the next id follows the dump's sequence
    let ts = epoch(storage.pool(), "2026-10-03 00:00:00+00").await;
    add_usage(storage.pool(), "k2", ts, 2, 2).await;
    assert_eq!(usage_rows(storage.pool()).await.last().unwrap().0, 6);
    storage.close().await;
    case.finish().await;
}

#[tokio::test]
async fn a_database_from_a_newer_server_is_refused_and_left_alone() {
    let Some(case) = Case::new() else { return };
    let mut c = case.admin().await;
    sqlx::raw_sql(&format!(
        "CREATE SCHEMA \"{s}\"; SET search_path = \"{s}\"; \
         CREATE TABLE schema_version (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TIMESTAMPTZ DEFAULT now()); \
         INSERT INTO schema_version (version, name) VALUES (1, '0001_initial.sql'), (4, '0004_future.sql');",
        s = case.schema
    ))
    .execute(&mut c)
    .await
    .unwrap();
    let err = Storage::connect(&case.config()).await.unwrap_err();
    assert!(matches!(err, StorageError::Migration(_)), "{err}");
    let raw = case.raw_pool().await;
    assert_eq!(versions(&raw).await.len(), 2);
    let tables: i64 = sqlx::query_scalar("SELECT count(*) FROM pg_tables WHERE schemaname = $1")
        .bind(&case.schema)
        .fetch_one(&raw)
        .await
        .unwrap();
    assert_eq!(tables, 1, "only schema_version exists, nothing was applied");
    case.finish().await;
}

#[tokio::test]
async fn a_version_recorded_under_another_name_is_refused() {
    let Some(case) = Case::new() else { return };
    let mut c = case.admin().await;
    sqlx::raw_sql(&format!(
        "CREATE SCHEMA \"{s}\"; SET search_path = \"{s}\"; \
         CREATE TABLE schema_version (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TIMESTAMPTZ DEFAULT now()); \
         INSERT INTO schema_version (version, name) VALUES (1, '0001_something_else.sql');",
        s = case.schema
    ))
    .execute(&mut c)
    .await
    .unwrap();
    let err = Storage::connect(&case.config()).await.unwrap_err();
    assert!(matches!(err, StorageError::Migration(_)), "{err}");
    case.finish().await;
}

#[tokio::test]
async fn processes_that_start_together_apply_each_migration_once() {
    let Some(case) = Case::new() else { return };
    let mut c = case.admin().await;
    sqlx::raw_sql(&format!("CREATE SCHEMA \"{}\"", case.schema))
        .execute(&mut c)
        .await
        .unwrap();
    let mut tasks = Vec::new();
    for _ in 0..6 {
        let config = case.config();
        tasks.push(tokio::spawn(async move {
            let s = Storage::connect(&config).await.unwrap();
            let n = versions(s.pool()).await.len();
            s.close().await;
            n
        }));
    }
    for t in tasks {
        assert_eq!(t.await.unwrap(), MIGRATIONS.len());
    }
    case.finish().await;
}

#[tokio::test]
async fn connecting_makes_the_current_months_partitions_and_a_row_needs_its_month() {
    let Some(case) = Case::new() else { return };
    let storage = Storage::connect(&case.config()).await.unwrap();
    let m = storage.maintenance();
    // previous, this and the next two months for both tables
    assert_eq!(m.partitions("usage").await.unwrap().len(), 4);
    assert_eq!(m.partitions("traces").await.unwrap().len(), 4);
    // a month nobody made cannot take a row
    let far = epoch(storage.pool(), "2031-05-10 00:00:00+00").await;
    let failed = sqlx::query("INSERT INTO usage (key_id, ts) VALUES ('k', $1)")
        .bind(far)
        .execute(storage.pool())
        .await;
    assert!(failed.is_err());
    let made = m.ensure_partitions(far, 0).await.unwrap();
    assert!(
        made.contains(&"usage_203105".to_string()) && made.contains(&"traces_203104".to_string()),
        "{made:?}"
    );
    add_usage(storage.pool(), "k", far, 1, 1).await;
    // making them again changes nothing
    let before = m.partitions("usage").await.unwrap();
    m.ensure_partitions(far, 0).await.unwrap();
    assert_eq!(m.partitions("usage").await.unwrap(), before);
    // a transaction opened through `begin` can write now
    let mut tx = storage.begin().await.unwrap();
    sqlx::query("INSERT INTO usage (key_id, ts) VALUES ('k', extract(epoch FROM now()))")
        .execute(&mut *tx)
        .await
        .unwrap();
    tx.commit().await.unwrap();
    storage.close().await;
    case.finish().await;
}

#[tokio::test]
async fn the_daily_summary_counts_per_key_and_utc_day_and_can_be_rerun() {
    let Some(case) = Case::new() else { return };
    let storage = Storage::connect(&case.config()).await.unwrap();
    let p = storage.pool();
    let m = storage.maintenance();
    let d1_late = epoch(p, "2026-10-01 23:59:59+00").await;
    let d2_early = epoch(p, "2026-10-02 00:00:00+00").await;
    let d2_noon = epoch(p, "2026-10-02 12:00:00+00").await;
    m.ensure_partitions(d2_noon, 1).await.unwrap();
    add_usage(p, "a", d1_late, 10, 1).await;
    add_usage(p, "a", d2_early, 20, 2).await;
    add_usage(p, "a", d2_noon, 30, 3).await;
    add_usage(p, "b", d2_noon, 5, 0).await;
    let now = epoch(p, "2026-10-02 13:00:00+00").await;
    assert_eq!(m.summarise(now).await.unwrap(), 3);
    let day = |d: &str, k: &str, r, pt, ct| laris_server::storage::DailyUsage {
        day: d.into(),
        key_id: k.into(),
        requests: r,
        prompt_tokens: pt,
        completion_tokens: ct,
    };
    let want = vec![
        day("2026-10-01", "a", 1, 10, 1),
        day("2026-10-02", "a", 2, 50, 5),
        day("2026-10-02", "b", 1, 5, 0),
    ];
    assert_eq!(m.daily("0000-00-00").await.unwrap(), want);
    // a later request on the last day is picked up, nothing is counted twice
    add_usage(p, "b", epoch(p, "2026-10-02 12:30:00+00").await, 7, 7).await;
    let later = epoch(p, "2026-10-02 14:00:00+00").await;
    m.summarise(later).await.unwrap();
    m.summarise(later).await.unwrap();
    let got = m.daily("2026-10-02").await.unwrap();
    assert_eq!(
        got,
        vec![
            day("2026-10-02", "a", 2, 50, 5),
            day("2026-10-02", "b", 2, 12, 7)
        ]
    );
    assert_eq!(m.daily("0000-00-00").await.unwrap().len(), 3);
    storage.close().await;
    case.finish().await;
}

#[tokio::test]
async fn retention_drops_old_months_keeps_the_summary_and_trims_the_straddling_month() {
    let Some(case) = Case::new() else { return };
    let mut config = case.config();
    config.usage_retention_days = 90.0;
    config.trace_retention_days = 30.0;
    let storage = Storage::connect(&config).await.unwrap();
    let p = storage.pool();
    let m = storage.maintenance();
    let now = epoch(p, "2026-09-21 00:00:00+00").await;
    // usage cutoff 2026-06-23, trace cutoff 2026-08-22
    let (apr, jun_old, jun_new, aug_old, aug_new, sep) = (
        epoch(p, "2026-04-12 10:00:00+00").await,
        epoch(p, "2026-06-10 10:00:00+00").await,
        epoch(p, "2026-06-30 10:00:00+00").await,
        epoch(p, "2026-08-10 10:00:00+00").await,
        epoch(p, "2026-08-30 10:00:00+00").await,
        epoch(p, "2026-09-20 10:00:00+00").await,
    );
    for ts in [apr, jun_old, jun_new, aug_old, aug_new, sep] {
        m.ensure_partitions(ts, 0).await.unwrap();
    }
    for ts in [apr, jun_old, jun_new, sep] {
        add_usage(p, "k", ts, 10, 5).await;
    }
    for ts in [apr, jun_old, aug_old, aug_new, sep] {
        add_trace(p, "k", ts).await;
    }
    let report = m.run_once(now).await.unwrap();
    assert!(
        report.purge.dropped.contains(&"usage_202604".to_string()),
        "{report:?}"
    );
    assert!(
        report.purge.dropped.contains(&"traces_202606".to_string()),
        "{report:?}"
    );
    assert!(
        !report.purge.dropped.contains(&"usage_202606".to_string()),
        "June still holds a kept day"
    );
    // June 10 (usage) and August 10 (traces) were trimmed out of months that straddle their cutoffs
    assert_eq!(report.purge.rows_deleted, 2, "{report:?}");
    assert_eq!(timestamps(p, "usage").await, vec![jun_new, sep]);
    assert_eq!(timestamps(p, "traces").await, vec![aug_new, sep]);
    // the summary kept every day, including the ones whose raw rows are gone
    let days: Vec<String> = m
        .daily("0000-00-00")
        .await
        .unwrap()
        .into_iter()
        .map(|d| d.day)
        .collect();
    assert_eq!(
        days,
        vec!["2026-04-12", "2026-06-10", "2026-06-30", "2026-09-20"]
    );
    // a second round finds nothing more to remove
    let again = m.purge(now).await.unwrap();
    assert!(
        again.dropped.is_empty() && again.rows_deleted == 0,
        "{again:?}"
    );
    storage.close().await;
    case.finish().await;
}

#[tokio::test]
async fn the_retention_task_runs_at_start_reports_a_failure_and_stops() {
    let Some(case) = Case::new() else { return };
    let storage = Arc::new(Storage::connect(&case.config()).await.unwrap());
    let handle = RetentionHandle::spawn(storage.clone(), Duration::from_millis(50));
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert_eq!(storage.last_retention_error(), None);
    // break the schema under it: the error shows, the task goes on
    sqlx::raw_sql("DROP TABLE usage_daily")
        .execute(storage.pool())
        .await
        .unwrap();
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert!(storage.last_retention_error().is_some());
    tokio::time::timeout(Duration::from_secs(5), handle.stop())
        .await
        .expect("the task stops");
    storage.close().await;
    case.finish().await;
}

#[tokio::test]
async fn the_pool_is_bounded_and_a_waiter_times_out() {
    let Some(case) = Case::new() else { return };
    let mut config = case.config();
    config.pool_max = 2;
    config.acquire_timeout = Duration::from_millis(300);
    let storage = Storage::connect(&config).await.unwrap();
    let a = storage.pool().acquire().await.unwrap();
    let b = storage.pool().acquire().await.unwrap();
    assert!(storage.pool().acquire().await.is_err());
    drop((a, b));
    storage.pool().acquire().await.unwrap();
    storage.close().await;
    case.finish().await;
}

#[tokio::test]
async fn an_unreachable_database_error_holds_neither_address_nor_password() {
    let mut config = StorageConfig::with_dsn("postgres://someone:hunter2-secret@127.0.0.1:1/laris");
    config.acquire_timeout = Duration::from_secs(2);
    let err = Storage::connect(&config).await.unwrap_err();
    let text = format!("{err} {err:?}");
    assert!(matches!(err, StorageError::Unreachable(_)), "{text}");
    for leak in ["hunter2", "someone", "127.0.0.1"] {
        assert!(!text.contains(leak), "{text}");
    }
    assert!(!format!("{config:?}").contains("hunter2"));
}

#[test]
fn settings_come_from_the_environment_and_refuse_nonsense() {
    use std::collections::HashMap;
    let env = |pairs: &[(&str, &str)]| -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    };
    let e = StorageConfig::from_env(&env(&[])).unwrap_err();
    assert!(e.to_string().contains("LARIS_SERVER__DATABASE_URL"));
    let c = StorageConfig::from_env(&env(&[
        ("LARIS_SERVER__DATABASE_URL", "postgres://u:pw@h/d"),
        ("LARIS_SERVER__DB_POOL_MAX", "3"),
        ("LARIS_SERVER__USAGE_RETENTION_DAYS", "120"),
        ("LARIS_SERVER__TRACE_RETENTION_DAYS", "7.5"),
        ("LARIS_SERVER__RETENTION_INTERVAL_S", "60"),
        ("LARIS_SERVER__DATABASE_SCHEMA", "laris_x"),
    ]))
    .unwrap();
    assert_eq!(
        (c.pool_max, c.usage_retention_days, c.trace_retention_days),
        (3, 120.0, 7.5)
    );
    assert_eq!(c.retention_interval, Duration::from_secs(60));
    assert_eq!(c.schema.as_deref(), Some("laris_x"));
    let ok = ("LARIS_SERVER__DATABASE_URL", "postgres://u:pw@h/d");
    for (name, value) in [
        ("LARIS_SERVER__DB_POOL_MAX", "0"),
        ("LARIS_SERVER__DB_POOL_MAX", "many"),
        ("LARIS_SERVER__USAGE_RETENTION_DAYS", "0"),
        ("LARIS_SERVER__TRACE_RETENTION_DAYS", "-1"),
        ("LARIS_SERVER__TRACE_RETENTION_DAYS", "NaN"),
        ("LARIS_SERVER__RETENTION_INTERVAL_S", "0"),
        (
            "LARIS_SERVER__DATABASE_SCHEMA",
            "x\"; DROP SCHEMA public; --",
        ),
        ("LARIS_SERVER__DATABASE_SCHEMA", "1abc"),
    ] {
        let err = StorageConfig::from_env(&env(&[ok, (name, value)])).unwrap_err();
        let text = err.to_string();
        assert!(
            text.contains(name) && !text.contains("pw") && !text.contains(value),
            "{name}: {text}"
        );
    }
}
