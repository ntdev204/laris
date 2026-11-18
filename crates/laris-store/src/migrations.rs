//! Numbered migrations. A database records the ones it has in `schema_version`, so only the later ones run.

/// One numbered migration.
#[derive(Clone, Copy, Debug)]
pub struct Migration {
    /// Number recorded in `schema_version`.
    pub version: i64,
    /// SQL, run in one transaction.
    pub script: &'static str,
}

/// All migrations, in order. Never edit an applied one; add a new one.
pub const MIGRATIONS: &[Migration] = &[
    Migration {
        version: 1,
        script: "
        CREATE TABLE chunks (
            chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, source TEXT NOT NULL,
            title TEXT NOT NULL, text TEXT NOT NULL, start INTEGER NOT NULL, \"end\" INTEGER NOT NULL,
            ordinal INTEGER NOT NULL);
        CREATE INDEX chunks_doc ON chunks(doc_id);
        CREATE TABLE embeddings (
            chunk_id TEXT NOT NULL, model_id TEXT NOT NULL, dim INTEGER NOT NULL,
            vector BLOB NOT NULL, PRIMARY KEY (chunk_id, model_id));
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL,
            updated REAL NOT NULL, data TEXT NOT NULL);
        CREATE TABLE learning (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, created REAL NOT NULL,
            data TEXT NOT NULL);
        CREATE TABLE vault_index (path TEXT PRIMARY KEY, mtime REAL NOT NULL, data TEXT NOT NULL);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ",
    },
    Migration {
        version: 2,
        script: "CREATE UNIQUE INDEX learning_row ON learning(kind, json_extract(data, '$.id'));",
    },
    // The event log (T129): sessions and an append-only, gapless event sequence per session.
    Migration {
        version: 3,
        script: "
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL, title TEXT NOT NULL);
        CREATE TABLE events (
            session_id TEXT NOT NULL REFERENCES sessions(id), seq INTEGER NOT NULL, kind TEXT NOT NULL,
            created REAL NOT NULL, data TEXT NOT NULL, PRIMARY KEY (session_id, seq)) WITHOUT ROWID;
        CREATE TRIGGER events_no_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
        CREATE TRIGGER events_no_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
        ",
    },
];
