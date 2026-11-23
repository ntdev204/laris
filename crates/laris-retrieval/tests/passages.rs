//! Passage search and the proposals inbox (SR-H8, SR-H13): ranking is deterministic, a passage with no query word is
//! never returned, and nothing in `_inbox/` is retrieved, by search or by link expansion.

use laris_retrieval::{
    GraphConfig, GraphRetriever, NoteSearch, PassageIndex, PassageRecord, in_inbox,
};
use laris_vault::VaultIndex;
use std::path::PathBuf;

fn passage(id: &str, source: &str, start: usize, text: &str) -> PassageRecord {
    PassageRecord {
        id: id.to_owned(),
        source: source.to_owned(),
        start,
        end: start + text.chars().count(),
        text: text.to_owned(),
    }
}

#[test]
fn passages_are_ranked_by_bm25_with_a_fixed_order_for_ties() {
    let index = PassageIndex::new(vec![
        passage(
            "a#0",
            "B source",
            0,
            "perovskite cells degrade with moisture",
        ),
        passage(
            "a#1",
            "A source",
            40,
            "perovskite cells degrade with moisture",
        ),
        passage(
            "b#0",
            "A source",
            0,
            "silicon wafers are textured with alkaline etching",
        ),
        passage("c#0", "C source", 0, "moisture moisture moisture and heat"),
    ]);
    let hits = index.search("perovskite moisture", 10);
    let ids: Vec<&str> = hits.iter().map(|h| h.passage.id.as_str()).collect();
    // two identical passages tie: source ascending decides; the wafer passage shares no word and is absent
    assert_eq!(ids, ["a#1", "a#0", "c#0"]);
    assert!(hits[0].score == hits[1].score && hits[1].score > hits[2].score);
    assert!(index.search("zeppelin", 5).is_empty());
    assert!(index.search("", 5).is_empty());
    assert_eq!(index.search("perovskite moisture", 1).len(), 1);
    assert!(PassageIndex::new(Vec::new()).search("x", 3).is_empty());
    // the same query twice: byte-identical
    assert_eq!(
        format!("{:?}", index.search("moisture heat", 5)),
        format!("{:?}", index.search("moisture heat", 5))
    );
}

fn vault_with_inbox() -> VaultIndex {
    let dir: PathBuf = std::env::temp_dir().join(format!("laris-inbox-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("_inbox")).unwrap();
    std::fs::write(
        dir.join("Cells.md"),
        "---\ntype: concept\n---\n\nperovskite cells, see [[Draft Idea]]",
    )
    .unwrap();
    std::fs::write(
        dir.join("_inbox/Draft Idea.md"),
        "---\ntype: proposal\n---\n\nperovskite zeppelin draft",
    )
    .unwrap();
    VaultIndex::build(&dir, None).unwrap()
}

#[test]
fn nothing_in_the_inbox_is_found_by_search_or_by_following_a_link() {
    let index = vault_with_inbox();
    assert!(
        in_inbox("_inbox/Draft Idea.md") && !in_inbox("Cells.md") && !in_inbox("Notes/_inbox/x.md")
    );
    let search = NoteSearch::new(&index, &[]);
    assert_eq!(search.len(), 1);
    assert!(search.search("zeppelin", 5).is_empty());
    let graph = GraphRetriever::new(&index, &[], GraphConfig::default());
    let paths: Vec<String> = graph
        .retrieve("perovskite cells", 10)
        .into_iter()
        .map(|r| r.path)
        .collect();
    assert_eq!(paths, ["Cells.md"], "the linked draft is not pulled in");
}

/// T277: notes added one by one score exactly as a fresh index over the same notes.
#[test]
fn notes_added_one_by_one_score_as_a_fresh_index() {
    let dir: PathBuf = std::env::temp_dir().join(format!("laris-add-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("Claims")).unwrap();
    let bodies = [
        ("Claims/a.md", "force equals mass times acceleration"),
        ("Claims/b.md", "the mass of an electron is small"),
        (
            "Claims/c.md",
            "acceleration is the rate of change of velocity",
        ),
        ("Claims/d.md", "a force changes the velocity of a mass"),
    ];
    for (path, body) in &bodies[..2] {
        std::fs::write(dir.join(path), format!("---\ntype: claim\n---\n\n{body}\n")).unwrap();
    }
    let mut grown = NoteSearch::new(&VaultIndex::build(&dir, None).unwrap(), &[]);
    for (path, body) in &bodies[2..] {
        std::fs::write(dir.join(path), format!("---\ntype: claim\n---\n\n{body}\n")).unwrap();
    }
    let full = VaultIndex::build(&dir, None).unwrap();
    for (path, _) in &bodies[2..] {
        grown.add(path, &full.notes[*path]);
    }
    let fresh = NoteSearch::new(&full, &[]);
    assert_eq!(grown.len(), fresh.len());
    for query in [
        "mass acceleration",
        "velocity",
        "force mass velocity",
        "electron",
    ] {
        assert_eq!(grown.search(query, 10), fresh.search(query, 10), "{query}");
    }
    let _ = std::fs::remove_dir_all(&dir);
}
