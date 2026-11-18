//! Store behaviour: migrations, concurrent writers, the event log, paths.

use laris_store::{DEFAULT_BUSY_TIMEOUT, MIGRATIONS, Store, StoreError, slug_of, space_path};
use rusqlite::Connection;
use std::path::{Path, PathBuf};

fn temp_dir(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("laris-store-{name}-{}", std::process::id()));
    std::fs::remove_dir_all(&dir).ok();
    std::fs::create_dir_all(&dir).expect("temp dir");
    dir
}

fn count(conn: &Connection, table: &str) -> i64 {
    conn.query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r.get(0))
        .expect("count")
}

#[test]
fn a_fresh_store_has_every_table_and_the_unique_learning_index() {
    let dir = temp_dir("fresh-tables");
    let store = Store::open(dir.join("fresh.sqlite"), DEFAULT_BUSY_TIMEOUT).expect("open");
    assert_eq!(store.version().expect("version"), 3);
    let conn = store.connect().expect("connect");
    for table in [
        "chunks",
        "embeddings",
        "conversations",
        "learning",
        "vault_index",
        "sessions",
        "events",
    ] {
        assert_eq!(count(&conn, table), 0, "{table}");
    }
    conn.execute(
        "INSERT INTO learning(kind, created, data) VALUES ('example', 1.0, '{\"id\":\"e1\"}')",
        [],
    )
    .expect("first row");
    assert!(
        conn.execute(
            "INSERT INTO learning(kind, created, data) VALUES ('example', 2.0, '{\"id\":\"e1\"}')",
            []
        )
        .is_err()
    );
    assert_eq!(store.migrate().expect("again"), 0);
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn an_empty_file_applies_every_migration_and_a_newer_one_is_refused() {
    let dir = temp_dir("fresh");
    let path = dir.join("projects/p/local.sqlite");
    let store = Store::open(&path, DEFAULT_BUSY_TIMEOUT).expect("open");
    assert_eq!(
        store.version().expect("version"),
        MIGRATIONS.last().expect("last").version
    );
    let conn = Connection::open(&path).expect("raw");
    conn.execute("INSERT INTO schema_version VALUES (99)", [])
        .expect("future");
    drop(conn);
    match Store::open(&path, DEFAULT_BUSY_TIMEOUT) {
        Err(StoreError::TooNew {
            found: 99,
            known: 3,
        }) => {}
        other => panic!("expected TooNew, got {other:?}"),
    }
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn two_writers_lose_nothing() {
    let dir = temp_dir("writers");
    let path = dir.join("shared.sqlite");
    let first = Store::open(&path, DEFAULT_BUSY_TIMEOUT).expect("first");
    // A second store on the same file, as a second process would hold it.
    let second = Store::open(&path, DEFAULT_BUSY_TIMEOUT).expect("second");
    first.create_session("s", "shared", 1.0).expect("session");
    const EACH: usize = 150;
    let writer = |store: Store, tag: &'static str| {
        std::thread::spawn(move || {
            for i in 0..EACH {
                store
                    .append_event("s", tag, 2.0, &format!("{tag}-{i}"))
                    .expect("append");
                store
                    .transaction(|tx| {
                        tx.execute(
                            "INSERT INTO learning(kind, created, data) VALUES (?1, 3.0, ?2)",
                            rusqlite::params![tag, format!("{{\"id\":\"{tag}-{i}\"}}")],
                        )?;
                        Ok(())
                    })
                    .expect("learning");
            }
        })
    };
    let a = writer(first.clone(), "a");
    let b = writer(second.clone(), "b");
    a.join().expect("a");
    b.join().expect("b");
    let events = first.events("s", 0).expect("events");
    assert_eq!(events.len(), 2 * EACH);
    let seqs: Vec<i64> = events.iter().map(|e| e.seq).collect();
    assert_eq!(
        seqs,
        (1..=(2 * EACH) as i64).collect::<Vec<_>>(),
        "gapless, no duplicates"
    );
    for tag in ["a", "b"] {
        let own: Vec<&str> = events
            .iter()
            .filter(|e| e.kind == tag)
            .map(|e| e.data.as_str())
            .collect();
        let want: Vec<String> = (0..EACH).map(|i| format!("{tag}-{i}")).collect();
        assert_eq!(own, want, "each writer's own order is kept");
    }
    assert_eq!(
        count(&second.connect().expect("c"), "learning"),
        (2 * EACH) as i64
    );
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn events_are_appended_in_order_and_cannot_be_changed() {
    let dir = temp_dir("events");
    let store = Store::open(dir.join("e.sqlite"), DEFAULT_BUSY_TIMEOUT).expect("open");
    assert!(matches!(
        store.append_event("missing", "k", 1.0, "{}"),
        Err(StoreError::NoSession(_))
    ));
    store.create_session("s", "t", 1.0).expect("session");
    store
        .create_session("s", "other title", 9.0)
        .expect("again changes nothing");
    let payload = "{\"b\": 1,  \"a\":\"xin chào\"}"; // kept byte for byte
    assert_eq!(store.append_event("s", "user", 2.0, payload).expect("1"), 1);
    assert_eq!(store.append_event("s", "model", 3.0, "{}").expect("2"), 2);
    let all = store.events("s", 0).expect("all");
    assert_eq!(all[0].data, payload);
    assert_eq!(store.events("s", 1).expect("tail").len(), 1);
    let conn = store.connect().expect("c");
    assert!(conn.execute("UPDATE events SET kind = 'x'", []).is_err());
    assert!(conn.execute("DELETE FROM events", []).is_err());
    let title: String = conn
        .query_row("SELECT title FROM sessions WHERE id = 's'", [], |r| {
            r.get(0)
        })
        .expect("title");
    assert_eq!(title, "t");
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn a_failed_transaction_leaves_nothing_behind() {
    let dir = temp_dir("rollback");
    let store = Store::open(dir.join("r.sqlite"), DEFAULT_BUSY_TIMEOUT).expect("open");
    let outcome: Result<(), StoreError> = store.transaction(|tx| {
        tx.execute("INSERT INTO meta VALUES ('k', 'v')", [])?;
        Err(StoreError::NoSession("boom".into()))
    });
    assert!(outcome.is_err());
    assert_eq!(store.get_meta("k").expect("meta"), None);
    store.set_meta("k", "1").expect("set");
    store.set_meta("k", "2").expect("replace");
    assert_eq!(store.get_meta("k").expect("meta").as_deref(), Some("2"));
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn paths_follow_the_documented_layout() {
    let dir = temp_dir("paths");
    let project = dir.join("My Project!");
    std::fs::create_dir_all(&project).expect("project");
    let slug = slug_of(&project);
    assert!(slug.starts_with("my-project-"), "{slug}");
    assert_eq!(slug.len(), "my-project-".len() + 8);
    let home = Path::new("/home/u/.laris");
    assert_eq!(
        space_path(home, &project, Some("AB:cd/12")),
        home.join("projects").join(&slug).join("abcd12.sqlite")
    );
    assert_eq!(
        space_path(home, &project, None)
            .file_name()
            .and_then(|n| n.to_str()),
        Some("local.sqlite")
    );
    assert_eq!(
        space_path(home, &project, Some("::"))
            .file_name()
            .and_then(|n| n.to_str()),
        Some("local.sqlite")
    );
    // The same folder reached another way gets the same slug.
    assert_eq!(slug_of(&project.join("..").join("My Project!")), slug);
    std::fs::remove_dir_all(dir).ok();
}

#[test]
fn slugs_are_the_folder_name_and_a_path_digest() {
    // Recorded values: the folder name plus the first 8 hex digits of the SHA-256 of the
    // resolved path.
    assert_eq!(slug_of(Path::new("/tmp")), "tmp-e9671acd");
    assert_eq!(slug_of(Path::new("/home/vth/ws/laris")), "laris-73ab3b33");
}
