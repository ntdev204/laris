//! Lexical passage retrieval (T230): the rankings and scores below were computed by hand from the formulas in the
//! module documentation (an independent script, not this code), then pinned here.

use laris_retrieval::{PassageError, Scorer, VaultPassages, split_body, verify_passage};
use laris_vault::VaultIndex;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};

static COUNTER: AtomicUsize = AtomicUsize::new(0);

fn vault(name: &str, notes: &[(&str, &str)]) -> (PathBuf, VaultIndex) {
    let n = COUNTER.fetch_add(1, Ordering::Relaxed);
    let dir = std::env::temp_dir().join(format!("laris-lex-{name}-{}-{n}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    for (path, body) in notes {
        let file = dir.join(path);
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(file, format!("---\ntype: concept\n---\n\n{body}")).unwrap();
    }
    let index = VaultIndex::build(&dir, None).unwrap();
    (dir, index)
}

fn four() -> (PathBuf, VaultIndex) {
    vault(
        "four",
        &[
            ("A.md", "perovskite cells degrade with moisture"),
            ("B.md", "silicon cells are textured with etching"),
            ("C.md", "moisture moisture moisture and heat"),
            ("D.md", "graphene sheets conduct heat"),
        ],
    )
}

fn rows(hits: &[laris_retrieval::VaultPassageHit]) -> Vec<(String, f64)> {
    hits.iter()
        .map(|h| (h.passage.path.clone(), h.score))
        .collect()
}

#[test]
fn bm25_matches_the_hand_computed_scores() {
    let (_, index) = four();
    let p = VaultPassages::new(&index);
    assert_eq!(p.len(), 4);
    let hits = p.search("moisture cells", Scorer::Bm25, 10);
    assert_eq!(
        rows(&hits),
        [
            ("A.md".to_owned(), 1.38629436),
            ("C.md".to_owned(), 1.1552453),
            ("B.md".to_owned(), 0.63591484),
        ]
    );
    assert_eq!(hits[0].rank, 1);
}

#[test]
fn tfidf_matches_the_hand_computed_scores() {
    let (_, index) = four();
    let hits = VaultPassages::new(&index).search("moisture cells", Scorer::TfIdf, 10);
    assert_eq!(
        rows(&hits),
        [
            ("C.md".to_owned(), 0.54585744),
            ("A.md".to_owned(), 0.53556687),
            ("B.md".to_owned(), 0.22421917),
        ]
    );
}

#[test]
fn fusion_matches_the_hand_computed_ranks_and_breaks_ties_by_path() {
    let (_, index) = four();
    let hits = VaultPassages::new(&index).search("moisture cells", Scorer::Fused, 10);
    // A is 1st by BM25 and 2nd by tf-idf, C the reverse: equal fused score 1/61 + 1/62, so the path decides
    assert_eq!(
        rows(&hits),
        [
            ("A.md".to_owned(), 0.0325224749),
            ("C.md".to_owned(), 0.0325224749),
            ("B.md".to_owned(), 0.031746031_7),
        ]
    );
    assert_eq!(p_top(&index, Scorer::Fused, 1), ["A.md"]);
}

fn p_top(index: &VaultIndex, scorer: Scorer, k: usize) -> Vec<String> {
    VaultPassages::new(index)
        .search("moisture cells", scorer, k)
        .into_iter()
        .map(|h| h.passage.path)
        .collect()
}

#[test]
fn no_shared_word_means_no_result_and_search_is_deterministic() {
    let (_, index) = four();
    let p = VaultPassages::new(&index);
    for scorer in [Scorer::Bm25, Scorer::TfIdf, Scorer::Fused] {
        assert!(p.search("zeppelin", scorer, 5).is_empty());
        assert!(p.search("", scorer, 5).is_empty());
        assert_eq!(
            format!("{:?}", p.search("heat moisture", scorer, 5)),
            format!("{:?}", p.search("heat moisture", scorer, 5))
        );
    }
    assert!(
        VaultPassages::new(&vault("none", &[]).1)
            .search("x", Scorer::Bm25, 3)
            .is_empty()
    );
}

#[test]
fn spans_are_character_offsets_and_verify() {
    let (_, index) = vault(
        "span",
        &[(
            "Notes/Café.md",
            "intro line about nothing\n\nl'état perovskite dégradé par l'humidité\n\nlast paragraph",
        )],
    );
    let p = VaultPassages::new(&index);
    assert_eq!(p.len(), 3);
    let hit = &p.search("humidité", Scorer::Bm25, 1)[0];
    let body = &index.notes["Notes/Café.md"].body;
    let text: String = body
        .chars()
        .skip(hit.passage.start)
        .take(hit.passage.end - hit.passage.start)
        .collect();
    assert_eq!(text, hit.passage.text);
    assert_eq!(hit.passage.text, "l'état perovskite dégradé par l'humidité");
    assert_eq!(verify_passage(&index, &hit.passage), Ok(()));

    let mut wrong = hit.passage.clone();
    wrong.start += 1;
    assert_eq!(verify_passage(&index, &wrong), Err(PassageError::Mismatch));
    let mut changed = hit.passage.clone();
    changed.note_sha256 = "0".repeat(64);
    assert_eq!(
        verify_passage(&index, &changed),
        Err(PassageError::ChangedNote)
    );
    let mut missing = hit.passage.clone();
    missing.path = "Gone.md".to_owned();
    assert_eq!(
        verify_passage(&index, &missing),
        Err(PassageError::MissingNote)
    );
}

#[test]
fn a_long_paragraph_is_cut_at_whitespace_with_exact_spans() {
    let body = "alpha beta gamma delta epsilon zeta eta theta";
    let parts = split_body(body, 12);
    let texts: Vec<&str> = parts.iter().map(|p| p.2.as_str()).collect();
    assert_eq!(
        texts,
        ["alpha beta", "gamma delta", "epsilon zeta", "eta theta"]
    );
    for (start, end, text) in &parts {
        let cut: String = body.chars().skip(*start).take(end - start).collect();
        assert_eq!(&cut, text);
        assert!(text.chars().count() <= 12 && !text.starts_with(' ') && !text.ends_with(' '));
    }
    // a single word longer than the limit is cut at the limit, never dropped
    let long = split_body("abcdefghijklmnop", 5);
    assert_eq!(
        long.iter().map(|p| p.2.as_str()).collect::<Vec<_>>(),
        ["abcde", "fghij", "klmno", "p"]
    );
}

#[test]
fn the_inbox_is_never_indexed() {
    let (_, index) = vault(
        "inbox",
        &[
            ("Cells.md", "perovskite cells"),
            ("_inbox/Draft.md", "perovskite zeppelin draft"),
        ],
    );
    let p = VaultPassages::new(&index);
    assert_eq!(p.len(), 1);
    assert!(p.search("zeppelin", Scorer::Fused, 5).is_empty());
}
