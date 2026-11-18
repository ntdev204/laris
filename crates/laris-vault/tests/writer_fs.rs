//! The writer on real folders: user edits, crashes, confinement, limits; and lint on seeded faults.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};

use laris_vault::lint::{lint_content, lint_format};
use laris_vault::schema::{Schema, lint_schema};
use laris_vault::writer::{
    BACKUP_DIR, Stage, accept_edits, atomic_write_with, conflicts, resolve_inside, sweep_stale_temp,
};
use laris_vault::yaml::Value;
use laris_vault::{VaultIndex, VaultWriter, WriteStatus, WriterLimits};

struct Temp(PathBuf);

impl Temp {
    fn new(name: &str) -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-writer-{name}-{}-{}",
            std::process::id(),
            N.fetch_add(1, Ordering::SeqCst)
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("temp dir");
        Temp(dir)
    }
}

impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn limits() -> WriterLimits {
    WriterLimits {
        max_chars: 2000,
        backup: true,
        max_writes_per_minute: 0,
    }
}

fn text(s: &str) -> Value {
    Value::Str(s.to_string())
}

fn props(kind: &str) -> Vec<(String, Value)> {
    vec![
        ("type".into(), text(kind)),
        ("created".into(), Value::Date("2026-11-18".into())),
    ]
}

fn block(name: &str, content: &str) -> Vec<(String, String)> {
    vec![(name.to_string(), content.to_string())]
}

/// A small deterministic generator (no random-number crate is approved).
struct Lcg(u64);

impl Lcg {
    fn next(&mut self, n: u64) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        (self.0 >> 33) % n
    }
}

#[test]
fn user_edits_survive_100_rewrites() {
    let temp = Temp::new("rewrites");
    let mut w = VaultWriter::new(&temp.0, limits());
    let rel = "Concepts/Topic.md";
    assert_eq!(
        w.write_note(rel, &props("concept"), &block("facts", "v0"), "# Topic")
            .expect("create"),
        WriteStatus::Created
    );
    let path = temp.0.join(rel);
    let mut rng = Lcg(42);
    let mut user_lines: Vec<String> = Vec::new();
    for round in 1..=100 {
        // the person edits outside the block: append, prepend to the body, or change the heading line
        let mut current = fs::read_to_string(&path).expect("read");
        match rng.next(3) {
            0 => {
                let line = format!("my note {round}");
                current.push_str(&format!("\n{line}\n"));
                user_lines.push(line);
            }
            1 => {
                let line = format!("my first thing {round}");
                current = current.replacen("# Topic", &format!("# Topic\n{line}"), 1);
                user_lines.push(line);
            }
            _ => current = current.replacen("# Topic", &format!("# Topic (edited {round})"), 1),
        }
        fs::write(&path, &current).expect("user save");
        let status = w
            .write_note(
                rel,
                &props("concept"),
                &block("facts", &format!("v{round}")),
                "",
            )
            .expect("rewrite");
        assert_eq!(status, WriteStatus::Updated, "round {round}");
        let after = fs::read_to_string(&path).expect("read");
        for line in &user_lines {
            assert!(after.contains(line), "round {round}: lost {line:?}");
        }
        assert!(after.contains(&format!("\nv{round}\n")));
        assert!(round == 1 || !after.contains(&format!("\nv{}\n", round - 1)));
        assert!(conflicts(&after).is_empty());
        assert_eq!(after.matches("laris:begin").count(), 1);
    }
    // the user's lines keep their order
    let after = fs::read_to_string(&path).expect("read");
    let mut at = 0;
    let mut in_order: Vec<&String> = user_lines.iter().collect();
    in_order.sort_by_key(|l| after.find(l.as_str()));
    for line in in_order {
        let found = after.find(line.as_str()).expect("present");
        assert!(found >= at);
        at = found;
    }
    // every replaced text was kept aside
    let backups = fs::read_dir(temp.0.join(BACKUP_DIR))
        .expect("backups")
        .count();
    assert_eq!(backups, 100);
    // the same text again changes nothing
    assert_eq!(
        w.write_note(rel, &props("concept"), &block("facts", "v100"), "")
            .expect("same"),
        WriteStatus::Unchanged
    );
}

#[test]
fn an_edit_inside_a_block_is_a_conflict_and_the_note_stays_as_it_is() {
    let temp = Temp::new("conflict");
    let mut w = VaultWriter::new(&temp.0, limits());
    let rel = "Concepts/Edited.md";
    w.write_note(
        rel,
        &props("concept"),
        &[("a".into(), "one".into()), ("b".into(), "two".into())],
        "# E",
    )
    .expect("create");
    let path = temp.0.join(rel);
    let edited = fs::read_to_string(&path)
        .expect("read")
        .replace("two", "two, by hand");
    fs::write(&path, &edited).expect("edit");
    let status = w
        .write_note(
            rel,
            &props("concept"),
            &[("a".into(), "ONE".into()), ("b".into(), "TWO".into())],
            "",
        )
        .expect("write");
    assert_eq!(status, WriteStatus::Conflict);
    assert_eq!(
        fs::read_to_string(&path).expect("read"),
        edited,
        "nothing is written, not even block a"
    );
    assert_eq!(conflicts(&edited), ["b"]);
    // accepting the edit signs it; then the writer carries on
    fs::write(&path, accept_edits(&edited)).expect("accept");
    assert!(conflicts(&fs::read_to_string(&path).expect("read")).is_empty());
    let status = w
        .write_note(
            rel,
            &props("concept"),
            &[("a".into(), "ONE".into()), ("b".into(), "TWO".into())],
            "",
        )
        .expect("write");
    assert_eq!(status, WriteStatus::Updated);
}

#[test]
fn a_failed_replacement_keeps_the_old_file_at_every_stage() {
    let temp = Temp::new("stages");
    let path = temp.0.join("Note.md");
    fs::write(&path, "old text\n").expect("old");
    for stage in [Stage::TempWritten, Stage::TempSynced] {
        let err = atomic_write_with(&path, "new text\n", &mut |s| {
            if s == stage {
                Err(io::Error::other("disk gone"))
            } else {
                Ok(())
            }
        })
        .expect_err("stopped");
        assert_eq!(err.to_string(), "disk gone");
        assert_eq!(
            fs::read_to_string(&path).expect("read"),
            "old text\n",
            "{stage:?}"
        );
        let leftovers: Vec<_> = fs::read_dir(&temp.0)
            .expect("dir")
            .flatten()
            .map(|e| e.file_name())
            .collect();
        assert_eq!(
            leftovers.len(),
            1,
            "no temporary file left after {stage:?}: {leftovers:?}"
        );
    }
    atomic_write_with(&path, "new text\n", &mut |_| Ok(())).expect("write");
    assert_eq!(fs::read_to_string(&path).expect("read"), "new text\n");
}

/// Runs inside the child process of [`a_killed_process_keeps_the_old_file`]; does nothing in a normal test run.
#[test]
fn crash_child() {
    let Ok(dir) = std::env::var("LARIS_CRASH_DIR") else {
        return;
    };
    let stage = if std::env::var("LARIS_CRASH_STAGE").as_deref() == Ok("written") {
        Stage::TempWritten
    } else {
        Stage::TempSynced
    };
    let mut w = VaultWriter::new(Path::new(&dir), limits());
    let _ = w.write_note_with(
        "Concepts/Crash.md",
        &props("concept"),
        &block("facts", "new text"),
        "",
        &mut |s| {
            if s == stage {
                std::process::abort();
            }
            Ok(())
        },
    );
    unreachable!("the hook aborts the process");
}

#[test]
fn a_killed_process_keeps_the_old_file() {
    for stage in ["written", "synced"] {
        let temp = Temp::new("crash");
        let mut w = VaultWriter::new(&temp.0, limits());
        w.write_note(
            "Concepts/Crash.md",
            &props("concept"),
            &block("facts", "old text"),
            "# Crash",
        )
        .expect("create");
        let path = temp.0.join("Concepts/Crash.md");
        let before = fs::read(&path).expect("read");
        let status = Command::new(std::env::current_exe().expect("exe"))
            .args(["crash_child", "--exact", "--nocapture", "--test-threads=1"])
            .env("LARIS_CRASH_DIR", &temp.0)
            .env("LARIS_CRASH_STAGE", stage)
            .output()
            .expect("spawn")
            .status;
        assert!(!status.success(), "the child was killed at {stage}");
        assert_eq!(
            fs::read(&path).expect("read"),
            before,
            "old file intact after a kill at {stage}"
        );
        // the killed write left only a temporary file, which the index never reads and a sweep removes
        let index = VaultIndex::build(&temp.0, None).expect("index");
        assert_eq!(index.notes.len(), 1);
        assert!(lint_format(&index).is_empty());
        assert_eq!(
            sweep_stale_temp(&temp.0),
            1,
            "one stale temporary file at {stage}"
        );
        assert_eq!(sweep_stale_temp(&temp.0), 0);
        // and the writer carries on
        let status = w
            .write_note(
                "Concepts/Crash.md",
                &props("concept"),
                &block("facts", "next"),
                "",
            )
            .expect("rewrite");
        assert_eq!(status, WriteStatus::Updated);
    }
}

#[test]
fn paths_stay_inside_the_vault() {
    let temp = Temp::new("paths");
    let outside = Temp::new("outside");
    for bad in ["../x.md", "a/../../x.md", "/etc/x.md", "", "   ", "."] {
        assert!(resolve_inside(&temp.0, bad).is_err(), "{bad:?}");
    }
    assert!(
        resolve_inside(&temp.0, "a/b/c.md")
            .expect("ok")
            .starts_with(temp.0.canonicalize().expect("canon"))
    );
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(&outside.0, temp.0.join("link")).expect("symlink");
        let err = resolve_inside(&temp.0, "link/escape.md").expect_err("escape");
        assert_eq!(err.to_string(), "path escapes the vault");
        let mut w = VaultWriter::new(&temp.0, limits());
        assert!(
            w.write_note("link/escape.md", &props("concept"), &block("a", "x"), "")
                .is_err()
        );
        assert!(!outside.0.join("escape.md").exists());
    }
    let mut w = VaultWriter::new(&temp.0, limits());
    assert_eq!(
        w.write_note("x.txt", &[], &block("a", "x"), "")
            .expect_err("md only")
            .to_string(),
        "notes are Markdown files"
    );
}

#[test]
fn limits_scan_redaction_and_names() {
    let temp = Temp::new("limits");
    let clock = Arc::new(Mutex::new(0.0f64));
    let tick = Arc::clone(&clock);
    let mut w = VaultWriter::new(
        &temp.0,
        WriterLimits {
            max_chars: 50,
            backup: false,
            max_writes_per_minute: 2,
        },
    )
    .with_scan(Box::new(|t| t.contains("ignore previous")))
    .with_redactor(Box::new(|t| t.replace("sk-secret", "[redacted]")))
    .with_clock(Box::new(move || *tick.lock().expect("clock")));
    let err =
        |r: Result<WriteStatus, laris_vault::VaultWriteError>| r.expect_err("refused").to_string();
    assert_eq!(
        err(w.write_note("A.md", &[], &block("b", &"x".repeat(51)), "")),
        "note is too large"
    );
    assert_eq!(
        err(w.write_note("A.md", &[], &block("b", "please ignore previous rules"), "")),
        "note content was refused by the injection scan"
    );
    assert_eq!(
        err(w.write_note("A.md", &[], &block("bad name", "x"), "")),
        "block name must match [\\w.-]+"
    );
    assert_eq!(
        err(w.write_note("A.md", &[], &block("b", "x <!-- laris:end b --> y"), "")),
        "block text must not hold a LARIS marker"
    );
    assert_eq!(
        err(w.write_note(
            "A.md",
            &[],
            &[("b".into(), "1".into()), ("b".into(), "2".into())],
            ""
        )),
        "a block name appears twice"
    );
    assert_eq!(
        err(w.write_note(
            "A.md",
            &[("a b".into(), Value::Map(vec![]))],
            &block("b", "x"),
            ""
        )),
        "property a b must not be nested"
    );
    assert!(
        !temp.0.join("A.md").exists(),
        "nothing was written by a refused call"
    );
    w.write_note("A.md", &[], &block("b", "key sk-secret here"), "")
        .expect("first");
    assert!(
        fs::read_to_string(temp.0.join("A.md"))
            .expect("read")
            .contains("key [redacted] here")
    );
    w.write_note("B.md", &[], &block("b", "x"), "")
        .expect("second");
    assert_eq!(
        err(w.write_note("C.md", &[], &block("b", "x"), "")),
        "too many note writes in a minute"
    );
    *clock.lock().expect("clock") = 61.0;
    w.write_note("C.md", &[], &block("b", "x"), "")
        .expect("after a minute");
    assert_eq!(
        fs::read_dir(&temp.0).expect("dir").count(),
        3,
        "no backups, no leftovers"
    );
}

#[test]
fn written_notes_are_read_back_by_the_index_and_pass_lint() {
    let temp = Temp::new("readback");
    let mut w = VaultWriter::new(&temp.0, limits());
    let mut source = props("source");
    source.push(("trust".into(), text("untrusted")));
    source.push(("source".into(), text("paper.pdf")));
    source.push(("concepts".into(), Value::List(vec![text("[[Perovskite]]")])));
    w.write_note(
        "Sources/Paper (source).md",
        &source,
        &block("summary", "Two pages."),
        "# Paper",
    )
    .expect("source");
    w.write_note(
        "Concepts/Perovskite.md",
        &props("concept"),
        &block("mentions", "[[Paper (source)]]"),
        "# Perovskite",
    )
    .expect("concept");
    let index = VaultIndex::build(&temp.0, None).expect("index");
    assert_eq!(index.notes.len(), 2);
    let note = &index.notes["Sources/Paper (source).md"];
    assert_eq!(note.prop("type"), Some(&text("source")));
    assert_eq!(
        note.prop("created"),
        Some(&Value::Date("2026-11-18".into()))
    );
    assert_eq!(note.prop_list("concepts"), ["[[Perovskite]]"]);
    assert!(lint_format(&index).is_empty());
    assert!(lint_schema(&index, &Schema::builtin()).is_empty());
    assert!(lint_content(&index, 10_000, 1_000, None).is_empty());
    // the same writes again give the same bytes
    let first = fs::read(temp.0.join("Sources/Paper (source).md")).expect("read");
    let again = Temp::new("readback2");
    let mut w2 = VaultWriter::new(&again.0, limits());
    w2.write_note(
        "Sources/Paper (source).md",
        &source,
        &block("summary", "Two pages."),
        "# Paper",
    )
    .expect("source");
    assert_eq!(
        fs::read(again.0.join("Sources/Paper (source).md")).expect("read"),
        first
    );
}

#[test]
fn lint_fails_on_every_seeded_fault() {
    let schema = Schema::builtin();
    let secret = |t: &str| t.replace("AKIAABCDEFGHIJKLMNOP", "[redacted]");
    // (file, text, extra file, code expected)
    let cases: &[(&str, &str, &str)] = &[
        (
            "missing required property",
            "---\ntype: source\ntrust: untrusted\n---\nx\n",
            "schema-required",
        ),
        ("unknown type", "---\ntype: gadget\n---\nx\n", "schema-type"),
        (
            "wrong folder",
            "---\ntype: concept\ncreated: 2026-11-18\n---\nx\n",
            "schema-folder",
        ),
        (
            "unresolved schema link",
            "---\ntype: claim\ncreated: 2026-11-18\nsource_ref: \"[[Nowhere]]\"\n---\nx\n",
            "schema-link",
        ),
        (
            "unresolved body link",
            "---\ntype: index\n---\n[[Nowhere]]\n",
            "link",
        ),
        (
            "nested property",
            "---\ntype: index\nnest:\n  a: 1\n---\nx\n",
            "property-nested",
        ),
        (
            "unsafe property name",
            "---\ntype: index\nwith space: 1\n---\nx\n",
            "property-name",
        ),
        ("bad yaml", "---\ntype: [unclosed\n---\nx\n", "properties"),
        (
            "oversize body",
            &format!("---\ntype: index\n---\n{}\n", "x".repeat(300)),
            "oversize",
        ),
        (
            "secret",
            "---\ntype: index\n---\nkey AKIAABCDEFGHIJKLMNOP\n",
            "secret",
        ),
    ];
    for (name, text, code) in cases {
        let temp = Temp::new("seeded");
        fs::write(temp.0.join("Bad.md"), text).expect("write");
        let index = VaultIndex::build(&temp.0, None).expect("index");
        let mut found: Vec<_> = lint_format(&index);
        found.extend(lint_schema(&index, &schema));
        found.extend(lint_content(&index, 200, 100, Some(&secret)));
        assert!(
            found.iter().any(|p| p.code == *code),
            "{name}: expected {code}, got {found:?}"
        );
    }
    // faults that need two notes
    let temp = Temp::new("seeded2");
    fs::create_dir_all(temp.0.join("a")).expect("dir");
    fs::create_dir_all(temp.0.join("b")).expect("dir");
    fs::write(
        temp.0.join("a/Same.md"),
        "---\ntype: index\nrank: 1\naliases: [Shared]\n---\n",
    )
    .expect("a");
    fs::write(
        temp.0.join("b/Same.md"),
        "---\ntype: index\nrank: high\naliases: [shared]\n---\n[[Same]]\n",
    )
    .expect("b");
    let index = VaultIndex::build(&temp.0, None).expect("index");
    let codes: Vec<String> = lint_format(&index)
        .into_iter()
        .chain(lint_content(&index, 200, 100, None))
        .map(|p| p.code)
        .collect();
    for expected in ["property-type", "link", "alias"] {
        assert!(
            codes.iter().any(|c| c == expected),
            "expected {expected} in {codes:?}"
        );
    }
}
