//! PostgreSQL storage of the server (SR-S3): numbered migrations that continue generation 1, a pool, monthly
//! partitions, retention and the daily usage summary.
//!
//! The schema is the generation-1 schema: migrations `0001` to `0003` are the generation-1 files byte for byte and
//! the version table is the same `schema_version`, so a generation-1 database is already at version 3 and a
//! generation-1 dump restored into a fresh database migrates to the same state without a rewrite. A database that
//! holds a version this build does not know (a newer server wrote it) is refused, never changed.
//!
//! Nothing here prints a connection string; errors name the failing step, not the address or the password.

mod maintenance;
mod migrate;

pub use maintenance::{DailyUsage, Maintenance, PurgeReport, RetentionHandle, RunReport};
pub use migrate::{MIGRATIONS, Migration, migrate};

use sqlx::postgres::{PgConnectOptions, PgPool, PgPoolOptions};
use sqlx::{Postgres, Transaction};
use std::collections::HashMap;
use std::fmt;
use std::str::FromStr;
use std::sync::Mutex;
use std::sync::atomic::{AtomicI64, Ordering};
use std::time::Duration;

/// Variable holding the connection string (`LARIS_SERVER__DATABASE_URL`, required).
pub const ENV_DATABASE_URL: &str = "LARIS_SERVER__DATABASE_URL";

/// A storage failure. Messages never hold the connection string.
#[derive(Debug, thiserror::Error)]
pub enum StorageError {
    /// A setting is missing or has the wrong form.
    #[error("{name} is invalid: {reason}")]
    Config {
        /// Variable name.
        name: &'static str,
        /// What is wrong.
        reason: &'static str,
    },
    /// The database could not be reached or refused the login.
    #[error("cannot reach PostgreSQL ({0})")]
    Unreachable(&'static str),
    /// The schema is not at a state this build can continue from.
    #[error("migration refused: {0}")]
    Migration(String),
    /// A statement failed.
    #[error("database error: {0}")]
    Database(#[from] sqlx::Error),
}

/// Settings of the storage layer.
#[derive(Clone, PartialEq)]
pub struct StorageConfig {
    dsn: String,
    /// Schema used instead of `public` (`LARIS_SERVER__DATABASE_SCHEMA`); tests use one per case.
    pub schema: Option<String>,
    /// Largest number of pooled connections (`LARIS_SERVER__DB_POOL_MAX`).
    pub pool_max: u32,
    /// Longest wait for a pooled connection (`LARIS_SERVER__DB_ACQUIRE_TIMEOUT_MS`).
    pub acquire_timeout: Duration,
    /// Days raw usage rows are kept (`LARIS_SERVER__USAGE_RETENTION_DAYS`).
    pub usage_retention_days: f64,
    /// Days traces are kept (`LARIS_SERVER__TRACE_RETENTION_DAYS`).
    pub trace_retention_days: f64,
    /// Time between two maintenance rounds (`LARIS_SERVER__RETENTION_INTERVAL_S`).
    pub retention_interval: Duration,
}

impl fmt::Debug for StorageConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("StorageConfig")
            .field("dsn", &"<redacted>")
            .field("schema", &self.schema)
            .field("pool_max", &self.pool_max)
            .finish_non_exhaustive()
    }
}

impl StorageConfig {
    /// Settings for `dsn` with every other value at its default.
    pub fn with_dsn(dsn: impl Into<String>) -> Self {
        Self {
            dsn: dsn.into(),
            schema: None,
            pool_max: 10,
            acquire_timeout: Duration::from_secs(10),
            usage_retention_days: 90.0,
            trace_retention_days: 30.0,
            retention_interval: Duration::from_secs(3600),
        }
    }

    /// Reads the settings from `env` (variable name to value), as `ServerConfig::from_env` does.
    pub fn from_env(env: &HashMap<String, String>) -> Result<Self, StorageError> {
        let get = |name: &str| env.get(name).map(|v| v.trim()).filter(|v| !v.is_empty());
        let dsn = get(ENV_DATABASE_URL).ok_or(StorageError::Config {
            name: ENV_DATABASE_URL,
            reason: "required",
        })?;
        let mut c = Self::with_dsn(dsn);
        if let Some(v) = get("LARIS_SERVER__DATABASE_SCHEMA") {
            c.schema = Some(valid_schema(v)?.to_string());
        }
        if let Some(v) = get("LARIS_SERVER__DB_POOL_MAX") {
            c.pool_max = parse(v, "LARIS_SERVER__DB_POOL_MAX")?;
            if c.pool_max == 0 {
                return Err(bad("LARIS_SERVER__DB_POOL_MAX", "must be at least 1"));
            }
        }
        if let Some(v) = get("LARIS_SERVER__DB_ACQUIRE_TIMEOUT_MS") {
            c.acquire_timeout =
                Duration::from_millis(parse(v, "LARIS_SERVER__DB_ACQUIRE_TIMEOUT_MS")?);
        }
        if let Some(v) = get("LARIS_SERVER__USAGE_RETENTION_DAYS") {
            c.usage_retention_days = days(v, "LARIS_SERVER__USAGE_RETENTION_DAYS")?;
        }
        if let Some(v) = get("LARIS_SERVER__TRACE_RETENTION_DAYS") {
            c.trace_retention_days = days(v, "LARIS_SERVER__TRACE_RETENTION_DAYS")?;
        }
        if let Some(v) = get("LARIS_SERVER__RETENTION_INTERVAL_S") {
            let secs: u64 = parse(v, "LARIS_SERVER__RETENTION_INTERVAL_S")?;
            if secs == 0 {
                return Err(bad(
                    "LARIS_SERVER__RETENTION_INTERVAL_S",
                    "must be at least 1",
                ));
            }
            c.retention_interval = Duration::from_secs(secs);
        }
        Ok(c)
    }
}

fn bad(name: &'static str, reason: &'static str) -> StorageError {
    StorageError::Config { name, reason }
}

fn parse<T: FromStr>(v: &str, name: &'static str) -> Result<T, StorageError> {
    v.parse().map_err(|_| bad(name, "not a number"))
}

fn days(v: &str, name: &'static str) -> Result<f64, StorageError> {
    let d: f64 = parse(v, name)?;
    if d.is_finite() && d > 0.0 {
        Ok(d)
    } else {
        Err(bad(name, "must be greater than zero"))
    }
}

fn valid_schema(name: &str) -> Result<&str, StorageError> {
    let ok = !name.is_empty()
        && name.len() <= 63
        && name
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
        && !name.starts_with(|c: char| c.is_ascii_digit());
    if ok {
        Ok(name)
    } else {
        Err(bad(
            "LARIS_SERVER__DATABASE_SCHEMA",
            "lowercase letters, digits and _ only",
        ))
    }
}

/// The connection pool with the migrated schema.
pub struct Storage {
    pool: PgPool,
    config: StorageConfig,
    /// Month (as a count of months since year 0) whose partitions this process has made sure of.
    ensured: AtomicI64,
    ensure_lock: tokio::sync::Mutex<()>,
    last_error: Mutex<Option<String>>,
}

impl fmt::Debug for Storage {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Storage").finish_non_exhaustive()
    }
}

impl Storage {
    /// Opens the pool, creates the schema when one is configured, applies the pending migrations and makes this
    /// and the next months' partitions.
    pub async fn connect(config: &StorageConfig) -> Result<Self, StorageError> {
        let mut options = PgConnectOptions::from_str(&config.dsn)
            .map_err(|_| StorageError::Unreachable("the connection string cannot be read"))?;
        if let Some(schema) = &config.schema {
            valid_schema(schema)?;
            let once = PgPoolOptions::new()
                .max_connections(1)
                .acquire_timeout(config.acquire_timeout)
                .connect_with(options.clone())
                .await
                .map_err(connect_error)?;
            let create = format!("CREATE SCHEMA IF NOT EXISTS \"{schema}\"");
            sqlx::raw_sql(&create).execute(&once).await?;
            once.close().await;
            options = options.options([("search_path", schema.as_str())]);
        }
        let pool = PgPoolOptions::new()
            .max_connections(config.pool_max)
            .acquire_timeout(config.acquire_timeout)
            .connect_with(options)
            .await
            .map_err(connect_error)?;
        migrate(&pool).await?;
        let storage = Self {
            pool,
            config: config.clone(),
            ensured: AtomicI64::new(i64::MIN),
            ensure_lock: tokio::sync::Mutex::new(()),
            last_error: Mutex::new(None),
        };
        storage.ensure_current_partitions().await?;
        Ok(storage)
    }

    /// The pool, for the stores that read and write rows.
    pub fn pool(&self) -> &PgPool {
        &self.pool
    }

    /// The settings the storage was opened with.
    pub fn config(&self) -> &StorageConfig {
        &self.config
    }

    /// Maintenance (partitions, summary, retention) on this pool.
    pub fn maintenance(&self) -> Maintenance {
        Maintenance::new(
            self.pool.clone(),
            self.config.usage_retention_days,
            self.config.trace_retention_days,
        )
    }

    /// Once per month per process: makes sure the partitions of the previous, this and the next months exist.
    /// Rows of `usage` and `traces` are written "now", so a writer calls this before it begins a transaction.
    pub async fn ensure_current_partitions(&self) -> Result<(), StorageError> {
        let month = maintenance::month_index(maintenance::now_secs());
        if self.ensured.load(Ordering::Acquire) == month {
            return Ok(());
        }
        let _guard = self.ensure_lock.lock().await;
        if self.ensured.load(Ordering::Acquire) == month {
            return Ok(());
        }
        self.maintenance()
            .ensure_partitions(maintenance::now_secs(), 2)
            .await?;
        self.ensured.store(month, Ordering::Release);
        Ok(())
    }

    /// Begins a transaction after the current partitions are known to exist.
    pub async fn begin(&self) -> Result<Transaction<'static, Postgres>, StorageError> {
        self.ensure_current_partitions().await?;
        Ok(self.pool.begin().await?)
    }

    /// The last error of the retention task, if its latest round failed.
    pub fn last_retention_error(&self) -> Option<String> {
        self.last_error.lock().ok().and_then(|g| g.clone())
    }

    pub(crate) fn set_retention_error(&self, error: Option<String>) {
        if let Ok(mut g) = self.last_error.lock() {
            *g = error;
        }
    }

    /// Closes the pool.
    pub async fn close(&self) {
        self.pool.close().await;
    }
}

fn connect_error(e: sqlx::Error) -> StorageError {
    StorageError::Unreachable(match e {
        sqlx::Error::Io(_) => "connection failed",
        sqlx::Error::PoolTimedOut => "timed out",
        sqlx::Error::Database(_) => "login or database refused",
        _ => "connection failed",
    })
}
