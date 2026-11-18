//! Numbered SQL migrations, each applied once in the same transaction as its `schema_version` row.
//!
//! A transaction-level advisory lock makes two processes that start together apply them in turn.

use super::StorageError;
use sqlx::postgres::{PgConnection, PgPool};
use sqlx::{Executor, Row};
use std::collections::HashMap;

const LOCK: i64 = 7_260_001;

/// One numbered migration.
#[derive(Debug, Clone, Copy)]
pub struct Migration {
    /// Version, counted from 1 without gaps.
    pub version: i32,
    /// File name, recorded in `schema_version`.
    pub name: &'static str,
    /// The SQL.
    pub sql: &'static str,
}

/// Every migration this build knows, in order.
pub const MIGRATIONS: &[Migration] = &[
    Migration {
        version: 1,
        name: "0001_initial.sql",
        sql: include_str!("../../migrations/0001_initial.sql"),
    },
    Migration {
        version: 2,
        name: "0002_request_traces.sql",
        sql: include_str!("../../migrations/0002_request_traces.sql"),
    },
];

/// Applies the pending migrations and returns how many ran.
///
/// Refuses a database that holds a version this build does not know or whose recorded name differs from the file
/// of that number: the schema was written by something else and is left untouched.
pub async fn migrate(pool: &PgPool) -> Result<usize, StorageError> {
    let mut tx = pool.begin().await?;
    let applied = run(&mut tx).await?;
    tx.commit().await?;
    Ok(applied)
}

async fn run(conn: &mut PgConnection) -> Result<usize, StorageError> {
    lock_and_prepare(conn).await?;
    let done = recorded(conn).await?;
    check(&done)?;
    let mut applied = 0;
    for m in MIGRATIONS {
        if !done.contains_key(&m.version) {
            apply(conn, m).await?;
            applied += 1;
        }
    }
    Ok(applied)
}

async fn lock_and_prepare(conn: &mut PgConnection) -> Result<(), StorageError> {
    sqlx::query("SELECT pg_advisory_xact_lock($1)")
        .bind(LOCK)
        .execute(&mut *conn)
        .await?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version \
         (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TIMESTAMPTZ DEFAULT now())",
    )
    .await?;
    Ok(())
}

async fn recorded(conn: &mut PgConnection) -> Result<HashMap<i32, String>, StorageError> {
    let rows = sqlx::query("SELECT version, name FROM schema_version ORDER BY version")
        .fetch_all(&mut *conn)
        .await?;
    let mut done = HashMap::new();
    for row in &rows {
        done.insert(
            row.try_get::<i32, _>("version")?,
            row.try_get::<String, _>("name")?,
        );
    }
    Ok(done)
}

fn check(done: &HashMap<i32, String>) -> Result<(), StorageError> {
    for (version, name) in done {
        match MIGRATIONS.iter().find(|m| m.version == *version) {
            None => {
                return Err(StorageError::Migration(format!(
                    "the database is at version {version}, newer than this server knows"
                )));
            }
            Some(m) if m.name != name => {
                return Err(StorageError::Migration(format!(
                    "version {version} was applied as another file than this server's"
                )));
            }
            Some(_) => {}
        }
    }
    Ok(())
}

async fn apply(conn: &mut PgConnection, m: &Migration) -> Result<(), StorageError> {
    conn.execute(m.sql).await?;
    sqlx::query("INSERT INTO schema_version (version, name) VALUES ($1, $2)")
        .bind(m.version)
        .bind(m.name)
        .execute(&mut *conn)
        .await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::MIGRATIONS;

    #[test]
    fn numbers_run_without_gaps_and_names_carry_them() {
        for (i, m) in MIGRATIONS.iter().enumerate() {
            assert_eq!(m.version as usize, i + 1);
            assert!(m.name.starts_with(&format!("{:04}_", m.version)));
        }
    }
}
