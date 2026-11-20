//! The main-brain profile on a vault the test writes: a valid vault is clean, and each seeded fault is found by its rule.

use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};

use laris_vault::brain::{Level, SpanError, resolve_span, sha256_hex};
use laris_vault::{VaultIndex, lint_brain};

struct Temp(PathBuf);

impl Temp {
    fn new() -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-brain-{}-{}",
            std::process::id(),
            N.fetch_add(1, Ordering::SeqCst)
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("temp dir");
        Temp(dir)
    }

    fn write(&self, rel: &str, text: &str) {
        let path = self.0.join(rel);
        fs::create_dir_all(path.parent().expect("parent")).expect("dirs");
        fs::write(path, text).expect("write");
    }

    fn codes(&self) -> Vec<(String, String)> {
        let index = VaultIndex::build(&self.0, None).expect("build");
        lint_brain(&index)
            .into_iter()
            .map(|p| (p.path, p.code))
            .collect()
    }
}

impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

const TEXT: &str = "Aspirin reduces fever. It was tested in 2020. Café notes.";

fn source(name: &str, text: &str, extra: &str) -> String {
    format!(
        "---\ntype: source\nkind: document\nidentifier: doi:10.1/{name}\nretrieved: 2026-11-20\nstatus: active\nsha256: {}\ncreated: 2026-11-20\n{extra}---\n\n{text}",
        sha256_hex(text.as_bytes())
    )
}

fn claim(src: &str, text: &str, start: usize, end: usize, level: &str, extra: &str) -> String {
    format!(
        "---\ntype: claim\nlevel: {level}\nsource_ref: \"[[{src}]]\"\nspan_start: {start}\nspan_end: {end}\nspan_sha256: {}\ncreated: 2026-11-20\n{extra}---\n\nAspirin reduces fever.",
        sha256_hex(&text.as_bytes()[start..end])
    )
}

fn base() -> Temp {
    let t = Temp::new();
    t.write("Sources/Paper A.md", &source("a", TEXT, ""));
    t.write(
        "Claims/Fever.md",
        &claim("Paper A", TEXT, 0, 21, "sourced", ""),
    );
    t
}

fn has(codes: &[(String, String)], path: &str, code: &str) -> bool {
    codes.iter().any(|(p, c)| p == path && c == code)
}

#[test]
fn a_valid_vault_has_no_problems() {
    let t = base();
    t.write(
        "Theories/Aspirin view.md",
        &format!(
            "---\ntype: theory\nattributed_to: Dr X\nsource_ref: \"[[Paper A]]\"\nspan_start: 22\nspan_end: 48\nspan_sha256: {}\ncreated: 2026-11-20\n---\n\nX argues it was tested.",
            sha256_hex(&TEXT.as_bytes()[22..48])
        ),
    );
    t.write(
        "Conflicts/Dispute.md",
        "---\ntype: conflict\nstatus: open\nsides:\n  - \"[[Fever]]\"\n  - \"[[Aspirin view]]\"\ncreated: 2026-11-20\n---\n\nBoth kept.",
    );
    t.write(
        "Questions/Why.md",
        "---\ntype: open-question\nstatus: open\nbears_on:\n  - \"[[Fever]]\"\n  - \"[[Dispute]]\"\ncreated: 2026-11-20\n---\n\nWhy?",
    );
    assert_eq!(t.codes(), Vec::<(String, String)>::new());
}

#[test]
fn a_claim_without_a_resolvable_span_fails() {
    let t = base();
    // missing span properties
    t.write(
        "Claims/Bare.md",
        "---\ntype: claim\nlevel: sourced\nsource_ref: \"[[Paper A]]\"\ncreated: 2026-11-20\n---\n\nx",
    );
    // wrong hash
    let mut wrong = claim("Paper A", TEXT, 0, 21, "sourced", "");
    wrong = wrong.replace(&sha256_hex(&TEXT.as_bytes()[0..21]), &sha256_hex(b"other"));
    t.write("Claims/WrongHash.md", &wrong);
    // beyond the text
    t.write(
        "Claims/Beyond.md",
        &format!(
            "---\ntype: claim\nlevel: sourced\nsource_ref: \"[[Paper A]]\"\nspan_start: 0\nspan_end: 9999\nspan_sha256: {}\ncreated: 2026-11-20\n---\n\nx",
            sha256_hex(b"x")
        ),
    );
    // source missing
    t.write(
        "Claims/NoSource.md",
        &claim("Nowhere", TEXT, 0, 21, "sourced", ""),
    );
    let c = t.codes();
    assert!(has(&c, "Claims/Bare.md", "schema-required"));
    assert!(has(&c, "Claims/WrongHash.md", "brain-span"));
    assert!(has(&c, "Claims/Beyond.md", "brain-span"));
    assert!(has(&c, "Claims/NoSource.md", "schema-link"));
    assert!(!c.iter().any(|(p, _)| p == "Claims/Fever.md"));
}

#[test]
fn span_resolution_is_byte_exact() {
    let start = TEXT.find("Café").expect("find");
    let end = start + "Café".len();
    let hash = sha256_hex(b"Caf\xc3\xa9");
    assert_eq!(
        resolve_span(TEXT, start as i64, end as i64, &hash),
        Ok("Café")
    );
    assert_eq!(
        resolve_span(TEXT, start as i64, end as i64 - 1, &hash),
        Err(SpanError::NotOnBoundary)
    );
    assert_eq!(resolve_span(TEXT, 5, 5, &hash), Err(SpanError::Empty));
    assert_eq!(resolve_span(TEXT, -1, 5, &hash), Err(SpanError::Empty));
    assert_eq!(
        resolve_span(TEXT, 0, 4, &hash),
        Err(SpanError::HashMismatch)
    );
}

#[test]
fn the_ladder_is_ordered_and_a_candidate_is_refused() {
    assert!(Level::Candidate < Level::Sourced);
    assert!(Level::Sourced < Level::Corroborated);
    assert!(Level::Corroborated < Level::Verified);
    assert!(Level::Verified < Level::Reviewed);
    assert_eq!(Level::parse("verified"), Some(Level::Verified));
    assert_eq!(Level::parse("certain"), None);
    let t = base();
    t.write(
        "Claims/Cand.md",
        &claim("Paper A", TEXT, 0, 21, "candidate", ""),
    );
    t.write(
        "Claims/Odd.md",
        &claim("Paper A", TEXT, 0, 21, "certain", ""),
    );
    let c = t.codes();
    assert!(has(&c, "Claims/Cand.md", "brain-level"));
    assert!(has(&c, "Claims/Odd.md", "brain-level"));
}

#[test]
fn levels_above_sourced_need_their_evidence() {
    let t = base();
    t.write(
        "Claims/NoCorr.md",
        &claim("Paper A", TEXT, 0, 21, "corroborated", ""),
    );
    t.write("Sources/Paper B.md", &source("b", TEXT, ""));
    // corroborated by a Claim on the same Source is not independent
    t.write(
        "Claims/SameSource.md",
        &claim(
            "Paper A",
            TEXT,
            0,
            21,
            "corroborated",
            "corroborated_by:\n  - \"[[Fever]]\"\nindependence: different labs\n",
        ),
    );
    t.write(
        "Claims/FeverB.md",
        &claim("Paper B", TEXT, 0, 21, "sourced", ""),
    );
    t.write(
        "Claims/Good.md",
        &claim(
            "Paper A",
            TEXT,
            0,
            21,
            "corroborated",
            "corroborated_by:\n  - \"[[FeverB]]\"\nindependence: different labs and datasets\n",
        ),
    );
    t.write(
        "Claims/NoRun.md",
        &claim("Paper A", TEXT, 0, 21, "verified", ""),
    );
    t.write(
        "Claims/RunIsDoc.md",
        &claim(
            "Paper A",
            TEXT,
            0,
            21,
            "verified",
            "tool_run_ref: \"[[Paper B]]\"\n",
        ),
    );
    t.write(
        "Sources/Run 1.md",
        &source("r", "result: 4", "").replace(
            "kind: document",
            "kind: tool_run\ncommand: calc\ninputs_sha256: abc",
        ),
    );
    t.write(
        "Claims/GoodRun.md",
        &claim(
            "Paper A",
            TEXT,
            0,
            21,
            "verified",
            "tool_run_ref: \"[[Run 1]]\"\n",
        ),
    );
    t.write(
        "Claims/NoReviewer.md",
        &claim("Paper A", TEXT, 0, 21, "reviewed", ""),
    );
    t.write(
        "Claims/Reviewed.md",
        &claim(
            "Paper A",
            TEXT,
            0,
            21,
            "reviewed",
            "reviewer: owner\nreviewed_on: 2026-11-20\n",
        ),
    );
    let c = t.codes();
    for bad in ["NoCorr", "SameSource", "NoRun", "RunIsDoc", "NoReviewer"] {
        assert!(
            has(&c, &format!("Claims/{bad}.md"), "brain-evidence"),
            "{bad}: {c:?}"
        );
    }
    for good in ["Good", "GoodRun", "Reviewed", "FeverB"] {
        assert!(
            !c.iter().any(|(p, _)| p == &format!("Claims/{good}.md")),
            "{good}: {c:?}"
        );
    }
}

#[test]
fn an_edited_source_and_a_bad_source_are_found() {
    let t = base();
    let edited = source("a", TEXT, "").replace("Aspirin reduces", "Aspirin raises");
    t.write("Sources/Edited.md", &edited);
    t.write(
        "Sources/Odd.md",
        &source("o", "text", "").replace("status: active", "status: gone"),
    );
    t.write(
        "Sources/Run.md",
        &source("r", "out", "").replace("kind: document", "kind: tool_run"),
    );
    t.write(
        "Sources/Old.md",
        &source("old", "old text", "").replace("status: active", "status: superseded"),
    );
    t.write("Notes/Stray.md", "---\ntype: gossip\n---\n\nhi");
    t.write("Notes/Mine.md", "my own note without a type");
    let c = t.codes();
    assert!(has(&c, "Sources/Edited.md", "brain-source-hash"));
    assert!(has(&c, "Sources/Odd.md", "brain-value"));
    assert!(has(&c, "Sources/Run.md", "brain-tool-run"));
    assert!(has(&c, "Sources/Old.md", "brain-superseded"));
    assert!(has(&c, "Notes/Stray.md", "schema-type"));
    assert!(!c.iter().any(|(p, _)| p == "Notes/Mine.md"));
}

#[test]
fn a_retracted_source_flags_its_dependants() {
    let t = base();
    t.write(
        "Sources/Paper A.md",
        &source("a", TEXT, "").replace("status: active", "status: retracted"),
    );
    t.write(
        "Theories/View.md",
        &format!(
            "---\ntype: theory\nattributed_to: Dr X\nsource_ref: \"[[Paper A]]\"\nspan_start: 0\nspan_end: 21\nspan_sha256: {}\ncreated: 2026-11-20\n---\n\nX argues.",
            sha256_hex(&TEXT.as_bytes()[0..21])
        ),
    );
    let c = t.codes();
    assert!(has(&c, "Claims/Fever.md", "brain-retracted"));
    assert!(has(&c, "Theories/View.md", "brain-retracted"));
}

#[test]
fn conflicts_and_questions_are_checked() {
    let t = base();
    t.write(
        "Conflicts/OneSide.md",
        "---\ntype: conflict\nstatus: open\nsides:\n  - \"[[Fever]]\"\ncreated: 2026-11-20\n---\n\nx",
    );
    t.write(
        "Conflicts/TwiceSame.md",
        "---\ntype: conflict\nstatus: open\nsides:\n  - \"[[Fever]]\"\n  - \"[[Fever]]\"\ncreated: 2026-11-20\n---\n\nx",
    );
    t.write(
        "Conflicts/BadSide.md",
        "---\ntype: conflict\nstatus: open\nsides:\n  - \"[[Fever]]\"\n  - \"[[Paper A]]\"\ncreated: 2026-11-20\n---\n\nx",
    );
    t.write(
        "Conflicts/ClosedNoBy.md",
        "---\ntype: conflict\nstatus: closed\nsides:\n  - \"[[Fever]]\"\n  - \"[[FeverB]]\"\ncreated: 2026-11-20\n---\n\nx",
    );
    t.write(
        "Claims/FeverB.md",
        &claim("Paper A", TEXT, 0, 21, "sourced", ""),
    );
    t.write(
        "Questions/Answered.md",
        "---\ntype: open-question\nstatus: answered\ncreated: 2026-11-20\n---\n\nx",
    );
    t.write(
        "Questions/BadLink.md",
        "---\ntype: open-question\nstatus: open\nbears_on:\n  - \"[[Paper A]]\"\ncreated: 2026-11-20\n---\n\nx",
    );
    let c = t.codes();
    for bad in ["OneSide", "TwiceSame", "BadSide", "ClosedNoBy"] {
        assert!(
            has(&c, &format!("Conflicts/{bad}.md"), "brain-conflict"),
            "{bad}: {c:?}"
        );
    }
    assert!(has(&c, "Questions/Answered.md", "brain-question"));
    assert!(has(&c, "Questions/BadLink.md", "brain-question"));
}

#[test]
fn problems_come_in_path_order_and_repeat() {
    let t = base();
    t.write(
        "Claims/Cand.md",
        &claim("Paper A", TEXT, 0, 21, "candidate", ""),
    );
    t.write(
        "Claims/Odd.md",
        &claim("Paper A", TEXT, 0, 21, "certain", ""),
    );
    assert_eq!(t.codes(), t.codes());
    let c = t.codes();
    let paths: Vec<&String> = c.iter().map(|(p, _)| p).collect();
    let mut sorted = paths.clone();
    sorted.sort();
    assert_eq!(paths, sorted);
}
