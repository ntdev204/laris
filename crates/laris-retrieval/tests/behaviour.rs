//! Behaviour that generation 1 does not pin: folders, span provenance, fusion of channels, the dense interface.

use std::fs;
use std::path::PathBuf;

use laris_retrieval::{
    Channel, DenseChannel, DenseHit, GraphConfig, GraphRetriever, NoDense, NoteSearch, SpanError,
    cite, fuse_ranked, source_title, verify_span,
};
use laris_vault::VaultIndex;

struct Temp(PathBuf);

impl Temp {
    fn new(name: &str) -> Temp {
        let dir =
            std::env::temp_dir().join(format!("laris-retrieval-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        Temp(dir)
    }

    fn write(&self, rel: &str, text: &str) {
        let path = self.0.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text).unwrap();
    }

    fn index(&self) -> VaultIndex {
        VaultIndex::build(&self.0, None).unwrap()
    }
}

impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn vault(name: &str) -> Temp {
    let t = Temp::new(name);
    t.write("A/Alpha.md", "Graphene conductivity is high.\n\nA second paragraph about batteries and graphene sheets.\n");
    t.write("B/Beta.md", "Batteries store energy. See [[Alpha]].\n");
    t.write("B/Gamma.md", "Nothing related here.\n");
    t
}

#[test]
fn folders_restrict_search_and_expansion() {
    let t = vault("folders");
    let index = t.index();
    let only_a = vec!["A".to_string()];
    let search = NoteSearch::new(&index, &only_a);
    assert_eq!(search.len(), 1);
    assert!(
        search
            .search("batteries", 10)
            .iter()
            .all(|h| h.path.starts_with("A/"))
    );
    let graph = GraphRetriever::new(&index, &only_a, GraphConfig::default());
    assert!(
        graph
            .retrieve("batteries", 10)
            .iter()
            .all(|r| r.path.starts_with("A/"))
    );
    let all = GraphRetriever::new(&index, &[], GraphConfig::default());
    let paths: Vec<_> = all
        .retrieve("graphene", 10)
        .into_iter()
        .map(|r| r.path)
        .collect();
    assert_eq!(paths.first().map(String::as_str), Some("A/Alpha.md"));
    assert!(
        paths.contains(&"B/Beta.md".to_string()),
        "the linked note joins: {paths:?}"
    );
}

#[test]
fn empty_vault_and_no_match_give_nothing() {
    let t = Temp::new("empty");
    let index = t.index();
    assert!(NoteSearch::new(&index, &[]).is_empty());
    assert!(
        GraphRetriever::new(&index, &[], GraphConfig::default())
            .retrieve("anything", 5)
            .is_empty()
    );
    let t = vault("nomatch");
    let index = t.index();
    assert!(NoteSearch::new(&index, &[]).search("zzzz", 5).is_empty());
}

#[test]
fn span_is_the_best_paragraph_and_verifies() {
    let t = vault("span");
    let index = t.index();
    let graph = GraphRetriever::new(&index, &[], GraphConfig::default());
    let results = graph.retrieve("batteries graphene", 5);
    let cited = cite(&results, &index, "batteries graphene");
    let alpha = cited
        .iter()
        .find(|c| c.result.path == "A/Alpha.md")
        .unwrap();
    let span = alpha.span.as_ref().expect("span");
    assert!(
        span.snippet.starts_with("A second paragraph"),
        "two words beat one: {}",
        span.snippet
    );
    assert_eq!(verify_span(&index, span), Ok(()));
}

#[test]
fn span_fails_closed_when_the_note_changes_or_the_range_lies() {
    let t = vault("fail");
    let index = t.index();
    let results = GraphRetriever::new(&index, &[], GraphConfig::default()).retrieve("graphene", 5);
    let span = cite(&results, &index, "graphene")
        .into_iter()
        .find_map(|c| c.span)
        .unwrap();

    let mut moved = span.clone();
    moved.start += 1;
    assert_eq!(verify_span(&index, &moved), Err(SpanError::SnippetMismatch));
    let mut far = span.clone();
    far.end = 10_000;
    assert_eq!(verify_span(&index, &far), Err(SpanError::BadRange));
    let mut ghost = span.clone();
    ghost.path = "A/Missing.md".into();
    assert_eq!(verify_span(&index, &ghost), Err(SpanError::MissingNote));

    t.write("A/Alpha.md", "Rewritten after the span was taken.\n");
    assert_eq!(verify_span(&t.index(), &span), Err(SpanError::ChangedNote));
}

#[test]
fn a_note_without_query_words_has_no_span() {
    let t = vault("nospan");
    let index = t.index();
    let results = GraphRetriever::new(&index, &[], GraphConfig::default()).retrieve("graphene", 5);
    let cited = cite(&results, &index, "graphene");
    let beta = cited.iter().find(|c| c.result.path == "B/Beta.md").unwrap();
    assert!(beta.span.is_none());
}

#[test]
fn long_paragraph_is_cut_on_a_character_boundary() {
    let t = Temp::new("long");
    t.write("Long.md", &"é graphene ".repeat(200));
    let index = t.index();
    let results = GraphRetriever::new(&index, &[], GraphConfig::default()).retrieve("graphene", 1);
    let span = cite(&results, &index, "graphene")[0].span.clone().unwrap();
    assert_eq!(span.snippet.chars().count(), 400);
    assert_eq!(verify_span(&index, &span), Ok(()));
}

fn ch(name: &str, qualified: bool, items: &[&str]) -> Channel {
    Channel {
        name: name.into(),
        weight: 1.0,
        qualified,
        items: items.iter().map(|s| s.to_string()).collect(),
    }
}

#[test]
fn fusion_sums_reciprocal_ranks_and_breaks_ties_by_id() {
    let fused = fuse_ranked(
        &[
            ch("bm25", true, &["b", "a", "c"]),
            ch("graph", true, &["a", "b"]),
        ],
        10,
    );
    let ids: Vec<_> = fused.iter().map(|f| f.id.as_str()).collect();
    assert_eq!(ids, ["a", "b", "c"], "a and b tie on score, ids break it");
    assert_eq!(
        fused[0].ranks,
        [("bm25".to_string(), 2), ("graph".to_string(), 1)]
    );
    assert!(fused.iter().all(|f| f.unqualified_channels.is_empty()));
    assert_eq!(
        fuse_ranked(&[ch("bm25", true, &["a", "b", "c"])], 2).len(),
        2
    );
}

#[test]
fn weights_scale_and_zero_weight_silences() {
    let mut loud = ch("graph", true, &["z"]);
    loud.weight = 3.0;
    let fused = fuse_ranked(&[ch("bm25", true, &["a"]), loud], 10);
    assert_eq!(fused[0].id, "z");
    let mut silent = ch("graph", true, &["z"]);
    silent.weight = 0.0;
    assert_eq!(
        fuse_ranked(&[ch("bm25", true, &["a"]), silent], 10).len(),
        1
    );
}

struct Fake;

impl DenseChannel for Fake {
    fn name(&self) -> &str {
        "dense"
    }

    fn search(&self, _q: &str, k: usize) -> Vec<DenseHit> {
        ["c", "a"]
            .iter()
            .take(k)
            .map(|id| DenseHit {
                id: id.to_string(),
                score: 0.5,
            })
            .collect()
    }
}

#[test]
fn a_dense_channel_is_not_qualified_and_fused_results_say_so() {
    assert!(!NoDense.qualified());
    assert!(NoDense.search("x", 5).is_empty());
    let dense = Fake;
    assert!(
        !dense.qualified(),
        "the default stays false until the gate is passed"
    );
    let items: Vec<String> = dense.search("x", 5).into_iter().map(|h| h.id).collect();
    let channels = [
        ch("bm25", true, &["a", "b"]),
        Channel {
            name: dense.name().into(),
            weight: 1.0,
            qualified: dense.qualified(),
            items,
        },
    ];
    let fused = fuse_ranked(&channels, 10);
    let by_id = |id: &str| fused.iter().find(|f| f.id == id).unwrap();
    assert_eq!(by_id("a").unqualified_channels, ["dense"]);
    assert_eq!(by_id("c").unqualified_channels, ["dense"]);
    assert!(
        by_id("b").unqualified_channels.is_empty(),
        "only dense results carry the label"
    );
}

#[test]
fn source_title_follows_pathlib_stem_and_safe_title() {
    assert_eq!(
        source_title("Papers/Perovskite review.pdf"),
        "Perovskite review (source)"
    );
    assert_eq!(source_title("a.b.c"), "a.b (source)");
    assert_eq!(source_title(".hidden"), "hidden (source)");
    assert_eq!(source_title("dir/"), "dir (source)");
    assert_eq!(source_title("x/we:ird?.md"), "we ird (source)");
}
