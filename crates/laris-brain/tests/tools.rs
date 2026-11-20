//! The acquisition and verification tools on fixture providers: only correctly verified documents and claims reach the
//! brain, and every promotion carries its provenance.

use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};

use laris_brain::tools::{
    Candidate, Document, Metadata, Registry, Scholarly, ToolOutput, ToolRunner, Tools, independent,
    verify_metadata,
};
use laris_brain::{Decision, Gate, GateSettings, MetadataCheck, Proposer, Refusal};
use laris_vault::VaultIndex;
use laris_vault::brain::{Level, resolve_span};

struct Temp(PathBuf);

impl Temp {
    fn new() -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-tools-{}-{}",
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

fn meta(title: &str, authors: &[&str], year: u32) -> Metadata {
    Metadata {
        title: title.into(),
        authors: authors.iter().map(|a| (*a).into()).collect(),
        year: Some(year),
    }
}

struct Fixture {
    docs: BTreeMap<String, Document>,
    registry: BTreeMap<String, Metadata>,
}

impl Registry for Fixture {
    fn name(&self) -> String {
        "registry-fixture".into()
    }
    fn resolve(&self, identifier: &str) -> Result<Option<Metadata>, String> {
        Ok(self.registry.get(identifier).cloned())
    }
}

impl Scholarly for Fixture {
    fn search(&self, query: &str, limit: usize) -> Result<Vec<Candidate>, String> {
        let words: Vec<String> = query
            .to_lowercase()
            .split_whitespace()
            .map(String::from)
            .collect();
        let mut out: Vec<Candidate> = self
            .docs
            .values()
            .map(|d| Candidate {
                identifier: d.identifier.clone(),
                title: d.claimed.title.clone(),
                score: words
                    .iter()
                    .filter(|w| d.text.to_lowercase().contains(w.as_str()))
                    .count() as f64,
            })
            .filter(|c| c.score > 0.0)
            .collect();
        // a provider may return duplicates and any order; the tool must cope
        out.extend(out.clone());
        out.reverse();
        out.truncate(limit * 4);
        Ok(out)
    }
    fn fetch(&self, identifier: &str) -> Result<Document, String> {
        self.docs
            .get(identifier)
            .cloned()
            .ok_or_else(|| format!("{identifier} not found"))
    }
}

fn doc(id: &str, text: &str, claimed: Metadata, cites: &[&str], dataset: Option<&str>) -> Document {
    Document {
        identifier: id.into(),
        text: text.into(),
        claimed,
        cites: cites.iter().map(|c| (*c).into()).collect(),
        dataset: dataset.map(Into::into),
    }
}

fn fixture() -> Fixture {
    let a = meta("Aspirin and fever", &["Anna Smith", "Bo Jones"], 2020);
    let b = meta("A second aspirin trial", &["Lee, Min", "Park, Joo"], 2021);
    let copy = meta("Aspirin review", &["Kim, Sun"], 2022);
    let mut f = Fixture {
        docs: BTreeMap::new(),
        registry: BTreeMap::new(),
    };
    let mut add = |d: Document, registered: Option<Metadata>| {
        if let Some(m) = registered {
            f.registry.insert(d.identifier.clone(), m);
        }
        f.docs.insert(d.identifier.clone(), d);
    };
    add(
        doc(
            "doi:10.1/a",
            "Aspirin reduces fever in adults. A dose of 500 mg was used in 2020.",
            a.clone(),
            &[],
            Some("trial-1"),
        ),
        Some(a),
    );
    add(
        doc(
            "doi:10.1/b",
            "In our trial aspirin reduces fever in adults at 500 mg.",
            b.clone(),
            &[],
            Some("trial-2"),
        ),
        Some(b),
    );
    add(
        doc(
            "doi:10.1/copy",
            "As reported before, aspirin reduces fever in adults.",
            copy.clone(),
            &["doi:10.1/a"],
            Some("trial-1"),
        ),
        Some(copy),
    );
    // the document says 2021, the registry 2019
    add(
        doc(
            "doi:10.1/wrong",
            "Aspirin cures all fever.",
            meta("Aspirin cure", &["Roe, Al"], 2021),
            &[],
            None,
        ),
        Some(meta("Aspirin cure", &["Roe, Al"], 2019)),
    );
    // not in the registry at all
    add(
        doc(
            "doi:10.1/ghost",
            "Aspirin fever fabricated.",
            meta("Ghost", &["Doe, J"], 2020),
            &[],
            None,
        ),
        None,
    );
    f
}

fn who() -> Proposer {
    Proposer("advisor-test".into())
}

const SETTINGS: GateSettings = GateSettings {
    min_support: 0.9,
    min_equivalence: 0.6,
    subject_overlap: 0.5,
    search_depth: 10,
    max_bytes: 100_000,
};

fn gate(t: &Temp) -> Gate {
    Gate::new(&t.0, SETTINGS, Box::new(|| "2026-11-20".to_string()))
}

struct Echo(&'static str);

impl ToolRunner for Echo {
    fn run(&self, _statement: &str) -> Result<ToolOutput, String> {
        Ok(ToolOutput {
            command: "recompute".into(),
            inputs_sha256: "1".repeat(64),
            output: self.0.into(),
        })
    }
}

struct Broken;

impl ToolRunner for Broken {
    fn run(&self, _statement: &str) -> Result<ToolOutput, String> {
        Err("interpreter missing".into())
    }
}

fn level_of(t: &Temp, path: &str) -> String {
    fs::read_to_string(t.0.join(path))
        .expect("claim")
        .lines()
        .find(|l| l.starts_with("level:"))
        .expect("level")
        .to_string()
}

#[test]
fn metadata_is_verified_against_the_registry_or_refused() {
    let f = fixture();
    let check = |id: &str| verify_metadata(&f, id, &f.docs[id].claimed);
    assert_eq!(
        check("doi:10.1/a"),
        MetadataCheck::Verified("registry-fixture".into())
    );
    assert!(matches!(check("doi:10.1/wrong"), MetadataCheck::Mismatch(m) if m.contains("year")));
    assert_eq!(check("doi:10.1/ghost"), MetadataCheck::Unresolved);
    // other authors, other title
    let mut other = f.docs["doi:10.1/a"].claimed.clone();
    other.authors = vec!["Zed Zane".into()];
    assert!(
        matches!(verify_metadata(&f, "doi:10.1/a", &other), MetadataCheck::Mismatch(m) if m.contains("authors"))
    );
    let mut other = f.docs["doi:10.1/a"].claimed.clone();
    other.title = "Something else".into();
    assert!(
        matches!(verify_metadata(&f, "doi:10.1/a", &other), MetadataCheck::Mismatch(m) if m.contains("title"))
    );
}

#[test]
fn only_correctly_verified_claims_are_promoted_and_each_has_provenance() {
    let t = Temp::new();
    let g = gate(&t);
    let f = fixture();
    let tools = Tools {
        gate: &g,
        registry: &f,
        scholarly: &f,
    };

    // search is deterministic, de-duplicated and best first
    let found = tools.search("aspirin fever", 10).expect("search");
    let ids: Vec<&str> = found.iter().map(|c| c.identifier.as_str()).collect();
    assert_eq!(
        found.len(),
        ids.iter().collect::<std::collections::BTreeSet<_>>().len(),
        "one entry per identifier"
    );
    assert_eq!(tools.search("aspirin fever", 10).expect("again"), found);

    // acquisition: only documents whose metadata checks out are stored
    for (id, title, stored) in [
        ("doi:10.1/a", "Paper A", true),
        ("doi:10.1/b", "Paper B", true),
        ("doi:10.1/copy", "Review", true),
        ("doi:10.1/wrong", "Wrong", false),
        ("doi:10.1/ghost", "Ghost", false),
    ] {
        let got = tools.acquire(id, title, &who()).expect("acquire");
        assert_eq!(got.decision.is_accepted(), stored, "{id}: {got:?}");
        if !stored {
            assert!(
                matches!(
                    &got.decision,
                    Decision::Refused {
                        reason: Refusal::Metadata,
                        ..
                    }
                ),
                "{id}"
            );
        }
    }
    assert!(
        tools
            .acquire("doi:10.1/missing", "Missing", &who())
            .is_err(),
        "a provider failure is an error, not a result"
    );
    // what is stored is not offered again
    assert!(
        tools
            .search("aspirin fever", 10)
            .expect("search")
            .iter()
            .all(|c| c.identifier == "doi:10.1/wrong" || c.identifier == "doi:10.1/ghost")
    );

    // a verified quote is promoted, with provenance
    let good = tools
        .promote_claim(
            "Aspirin reduces fever in adults.",
            "Paper A",
            "Aspirin reduces fever in adults.",
            &who(),
        )
        .expect("promote");
    let p = good.provenance.clone().expect("provenance");
    assert_eq!(
        (p.level, p.identifier.as_str(), p.metadata_check.as_str()),
        (Level::Sourced, "doi:10.1/a", "verified:registry-fixture")
    );
    assert_eq!(
        (p.retrieved.as_str(), p.proposed_by.as_str()),
        ("2026-11-20", "advisor-test")
    );
    assert!(p.audit_seq >= 4 && !p.span_sha256.is_empty());
    let index = VaultIndex::build(&t.0, None).expect("index");
    let source = index.notes.get(&p.source).expect("source");
    assert!(
        resolve_span(
            &source.body,
            p.span.0 as i64,
            p.span.1 as i64,
            &p.span_sha256
        )
        .is_ok(),
        "the span reproduces"
    );

    // a fabricated quote and an unsupported statement are refused and carry no provenance
    let fake = tools
        .promote_claim(
            "Aspirin cures cancer.",
            "Paper A",
            "Aspirin cures cancer.",
            &who(),
        )
        .expect("promote");
    assert!(
        matches!(
            fake.decision,
            Decision::Refused {
                reason: Refusal::Span,
                ..
            }
        ) && fake.provenance.is_none()
    );
    let loose = tools
        .promote_claim(
            "Aspirin reduces fever in children.",
            "Paper A",
            "Aspirin reduces fever in adults.",
            &who(),
        )
        .expect("promote");
    assert!(
        matches!(
            loose.decision,
            Decision::Refused {
                reason: Refusal::Unsupported,
                ..
            }
        ) && loose.provenance.is_none()
    );
    assert_eq!(
        tools
            .verify_quote("Paper A", "aspirin  reduces fever")
            .expect("quote"),
        None,
        "case matters"
    );
    assert!(
        tools
            .verify_quote("Paper A", "Aspirin reduces\nfever")
            .expect("quote")
            .is_some()
    );

    // an independent document that says the same corroborates both claims
    let second = tools
        .promote_claim(
            "Aspirin reduces fever in adults.",
            "Paper B",
            "aspirin reduces fever in adults at 500 mg.",
            &who(),
        )
        .expect("promote");
    assert_eq!(second.corroborations.len(), 1, "{second:?}");
    assert_eq!(
        second.provenance.as_ref().expect("provenance").level,
        Level::Corroborated
    );
    assert!(
        level_of(&t, &p.claim).contains("corroborated"),
        "the first claim is raised as well"
    );

    // a document that cites the first, on the same dataset, is not independent of it: it corroborates with the second only
    let review = tools
        .promote_claim(
            "Aspirin reduces fever in adults.",
            "Review",
            "aspirin reduces fever in adults.",
            &who(),
        )
        .expect("promote");
    assert_eq!(review.corroborations.len(), 1, "{review:?}");
    let review_path = review
        .provenance
        .as_ref()
        .expect("provenance")
        .claim
        .clone();
    let text = fs::read_to_string(t.0.join(&review_path)).expect("review claim");
    let first = p
        .claim
        .trim_start_matches("Claims/")
        .trim_end_matches(".md");
    assert!(
        !text.contains(first),
        "the review is not corroborated by the claim on the paper it cites: {text}"
    );
    assert!(text.contains("corroborated_by"));

    // every claim in the brain has complete provenance, and the vault is clean
    let index = VaultIndex::build(&t.0, None).expect("index");
    let claims: Vec<_> = index
        .notes
        .keys()
        .filter(|k| k.starts_with("Claims/"))
        .cloned()
        .collect();
    assert_eq!(
        claims.len(),
        3,
        "only the three verified claims were stored: {claims:?}"
    );
    for path in claims {
        let p = tools.provenance(&path).expect("provenance").expect("some");
        assert!(
            !p.identifier.is_empty()
                && !p.metadata_check.is_empty()
                && !p.retrieved.is_empty()
                && !p.proposed_by.is_empty()
        );
        assert!(p.span.1 > p.span.0);
        assert_eq!(p.to_json()["identifier"], p.identifier);
    }
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
}

#[test]
fn independence_is_checked_on_identifier_citation_and_dataset() {
    let t = Temp::new();
    let g = gate(&t);
    let f = fixture();
    let tools = Tools {
        gate: &g,
        registry: &f,
        scholarly: &f,
    };
    for (id, title) in [
        ("doi:10.1/a", "Paper A"),
        ("doi:10.1/b", "Paper B"),
        ("doi:10.1/copy", "Review"),
    ] {
        tools.acquire(id, title, &who()).expect("acquire");
    }
    let index = g.index().expect("index");
    let (a, b, copy) = (
        &index.notes["Sources/Paper A.md"],
        &index.notes["Sources/Paper B.md"],
        &index.notes["Sources/Review.md"],
    );
    assert!(independent(a, b).is_ok());
    assert_eq!(independent(a, a), Err("the same document".into()));
    assert_eq!(independent(copy, a), Err("one cites the other".into()));
    assert_eq!(independent(a, copy), Err("one cites the other".into()));
    assert!(
        independent(b, copy).is_ok(),
        "different documents, no citation, different datasets"
    );
}

#[test]
fn a_check_raises_a_claim_only_when_its_output_supports_it() {
    let t = Temp::new();
    let g = gate(&t);
    let f = fixture();
    let tools = Tools {
        gate: &g,
        registry: &f,
        scholarly: &f,
    };
    tools
        .acquire("doi:10.1/a", "Paper A", &who())
        .expect("acquire");
    let promoted = tools
        .promote_claim(
            "A dose of 500 mg was used in 2020.",
            "Paper A",
            "A dose of 500 mg was used in 2020.",
            &who(),
        )
        .expect("promote");
    let title = promoted
        .provenance
        .expect("provenance")
        .claim
        .trim_start_matches("Claims/")
        .trim_end_matches(".md")
        .to_string();

    // the check disagrees: refused, the claim stays sourced, the run is kept as a source
    let no = tools
        .verify_with_tool(&title, &Echo("A dose of 900 mg was used in 2020."), &who())
        .expect("run");
    assert!(
        matches!(
            no,
            Decision::Refused {
                reason: Refusal::Evidence,
                ..
            }
        ),
        "{no:?}"
    );
    // the check cannot run: an error, nothing changes
    assert!(tools.verify_with_tool(&title, &Broken, &who()).is_err());
    let path = format!("Claims/{title}.md");
    assert!(level_of(&t, &path).contains("sourced"));
    // the check agrees
    let yes = tools
        .verify_with_tool(&title, &Echo("A dose of 500 mg was used in 2020."), &who())
        .expect("run");
    assert!(
        matches!(
            yes,
            Decision::Accepted {
                level: Some(Level::Verified),
                ..
            }
        ),
        "{yes:?}"
    );
    assert!(level_of(&t, &path).contains("verified"));
    assert_eq!(g.lint().expect("lint"), Vec::<(String, String)>::new());
    assert_eq!(
        tools.provenance(&path).expect("p").expect("some").level,
        Level::Verified
    );
}
