//! Client SQLite store (SR-H9, ADR-021 D43).
//!
//! One file per project and API key at `<home>/projects/<slug>/<key-fingerprint>.sqlite`, the same path and the same
//! numbered migrations as generation 1, so a generation-1 database opens without loss. WAL journal, a busy timeout,
//! one short-lived connection per operation and `BEGIN IMMEDIATE` for every write: writers queue on the timeout and
//! none loses its data.
//!
//! Tables: `chunks` (passages with character spans), `embeddings`, `conversations` (generation 1, kept as they are),
//! `learning` (examples), `vault_index` (disposable cache), `meta`, and, from migration 3, `sessions` and the
//! append-only `events` log.

mod migrations;
mod space;

pub use migrations::{MIGRATIONS, Migration};
pub use space::{fingerprint_of, slug_of, space_path};

use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Default wait for a locked database, as in generation 1.
pub const DEFAULT_BUSY_TIMEOUT: Duration = Duration::from_millis(5000);

/// Errors of the store.
#[derive(Debug, thiserror::Error)]
pub enum StoreError {
    /// SQLite refused an operation.
    #[error("database error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    /// The folder of the database could not be created.
    #[error("cannot create {path}: {source}")]
    Folder {
        /// The folder.
        path: PathBuf,
        /// The cause.
        source: std::io::Error,
    },
    /// The database was written by a newer version of Laris.
    #[error("database schema version {found} is newer than this build knows ({known})")]
    TooNew {
        /// Highest version recorded in the file.
        found: i64,
        /// Highest version this build applies.
        known: i64,
    },
    /// A session or an event that was asked for does not exist.
    #[error("no session {0}")]
    NoSession(String),
}

/// Result alias of the store.
pub type Result<T> = std::result::Result<T, StoreError>;

/// One recorded event of a session.
#[derive(Clone, Debug, PartialEq)]
pub struct StoredEvent {
    /// Position in the session, from 1, without gaps.
    pub seq: i64,
    /// Event kind.
    pub kind: String,
    /// Seconds since the epoch, as given by the caller.
    pub created: f64,
    /// The payload exactly as it was appended (the caller serialises it).
    pub data: String,
}

/// A private space: one SQLite file.
#[derive(Clone, Debug)]
pub struct Store {
    path: PathBuf,
    busy_timeout: Duration,
}

impl Store {
    /// Open (creating the folder and the file) and migrate to the latest version.
    pub fn open(path: impl Into<PathBuf>, busy_timeout: Duration) -> Result<Self> {
        let store = Self {
            path: path.into(),
            busy_timeout,
        };
        if let Some(folder) = store.path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(folder).map_err(|source| StoreError::Folder {
                path: folder.to_path_buf(),
                source,
            })?;
        }
        store.migrate()?;
        Ok(store)
    }

    /// Open the space of a project and key under `home` (the `~/.laris` folder).
    pub fn open_space(
        home: &Path,
        project_root: &Path,
        key_fingerprint: Option<&str>,
        busy_timeout: Duration,
    ) -> Result<Self> {
        Self::open(
            space_path(home, project_root, key_fingerprint),
            busy_timeout,
        )
    }

    /// The database file.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// A new connection with WAL, the busy timeout and foreign keys.
    pub fn connect(&self) -> Result<Connection> {
        let conn = Connection::open(&self.path)?;
        conn.busy_timeout(self.busy_timeout)?;
        // The pragma answers with the mode, so it is read as a query.
        conn.query_row("PRAGMA journal_mode = WAL", [], |_| Ok(()))?;
        conn.execute_batch("PRAGMA synchronous = NORMAL; PRAGMA foreign_keys = ON;")?;
        Ok(conn)
    }

    /// Run `work` in a `BEGIN IMMEDIATE` transaction: committed when it returns `Ok`, rolled back otherwise.
    pub fn transaction<T>(
        &self,
        work: impl FnOnce(&rusqlite::Transaction<'_>) -> Result<T>,
    ) -> Result<T> {
        let mut conn = self.connect()?;
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let value = work(&tx)?;
        tx.commit()?;
        Ok(value)
    }

    /// Highest migration applied (0 for an empty file).
    pub fn version(&self) -> Result<i64> {
        let conn = self.connect()?;
        version_of(&conn)
    }

    /// Apply the migrations not yet applied, each in its own transaction; returns how many were applied.
    pub fn migrate(&self) -> Result<usize> {
        self.transaction(|tx| {
            tx.execute_batch(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)",
            )?;
            Ok(())
        })?;
        let known = MIGRATIONS.last().map_or(0, |m| m.version);
        let found = self.version()?;
        if found > known {
            return Err(StoreError::TooNew { found, known });
        }
        let mut applied = 0;
        for migration in MIGRATIONS {
            let done = self.transaction(|tx| {
                let present: Option<i64> = tx
                    .query_row(
                        "SELECT 1 FROM schema_version WHERE version = ?1",
                        [migration.version],
                        |r| r.get(0),
                    )
                    .optional()?;
                if present.is_some() {
                    return Ok(false);
                }
                tx.execute_batch(migration.script)?;
                tx.execute(
                    "INSERT INTO schema_version VALUES (?1)",
                    [migration.version],
                )?;
                Ok(true)
            })?;
            applied += usize::from(done);
        }
        Ok(applied)
    }

    // -- meta -----------------------------------------------------------------------------------

    /// A value of the `meta` table.
    pub fn get_meta(&self, key: &str) -> Result<Option<String>> {
        let conn = self.connect()?;
        Ok(conn
            .query_row("SELECT value FROM meta WHERE key = ?1", [key], |r| r.get(0))
            .optional()?)
    }

    /// Set a value of the `meta` table.
    pub fn set_meta(&self, key: &str, value: &str) -> Result<()> {
        self.transaction(|tx| {
            tx.execute(
                "INSERT INTO meta VALUES (?1, ?2) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                params![key, value],
            )?;
            Ok(())
        })
    }

    // -- sessions and events --------------------------------------------------------------------

    /// Create a session; creating it again changes nothing.
    pub fn create_session(&self, id: &str, title: &str, now: f64) -> Result<()> {
        self.transaction(|tx| {
            tx.execute(
                "INSERT OR IGNORE INTO sessions (id, created, updated, title) VALUES (?1, ?2, ?2, ?3)",
                params![id, now, title],
            )?;
            Ok(())
        })
    }

    /// Append one event to a session and return its position. The position is read and written in one immediate
    /// transaction, so concurrent writers get distinct, consecutive positions.
    pub fn append_event(&self, session: &str, kind: &str, now: f64, data: &str) -> Result<i64> {
        self.transaction(|tx| {
            let exists: Option<i64> = tx
                .query_row("SELECT 1 FROM sessions WHERE id = ?1", [session], |r| {
                    r.get(0)
                })
                .optional()?;
            if exists.is_none() {
                return Err(StoreError::NoSession(session.to_owned()));
            }
            let seq: i64 = tx.query_row(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE session_id = ?1",
                [session],
                |r| r.get(0),
            )?;
            tx.execute(
                "INSERT INTO events (session_id, seq, kind, created, data) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![session, seq, kind, now, data],
            )?;
            tx.execute(
                "UPDATE sessions SET updated = ?2 WHERE id = ?1",
                params![session, now],
            )?;
            Ok(seq)
        })
    }

    /// The events of a session after position `after` (0 for all), in order.
    pub fn events(&self, session: &str, after: i64) -> Result<Vec<StoredEvent>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            "SELECT seq, kind, created, data FROM events WHERE session_id = ?1 AND seq > ?2 ORDER BY seq",
        )?;
        let rows = stmt.query_map(params![session, after], |r| {
            Ok(StoredEvent {
                seq: r.get(0)?,
                kind: r.get(1)?,
                created: r.get(2)?,
                data: r.get(3)?,
            })
        })?;
        Ok(rows.collect::<std::result::Result<_, _>>()?)
    }
}

fn version_of(conn: &Connection) -> Result<i64> {
    let table: Option<i64> = conn
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE name = 'schema_version'",
            [],
            |r| r.get(0),
        )
        .optional()?;
    if table.is_none() {
        return Ok(0);
    }
    let max: Option<i64> =
        conn.query_row("SELECT MAX(version) FROM schema_version", [], |r| r.get(0))?;
    Ok(max.unwrap_or(0))
}
