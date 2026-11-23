//! Acquisition and verification tools that feed the write gate (SR-K3, ADR-024 sections 3 and 4).
//!
//! The tools find documents, fetch them, check their identifiers and metadata against a registry, check exact quotes,
//! look for independent corroboration and run checks, and hand every result to the [`Gate`]. They never write the
//! vault themselves: a Source, a Claim or a level exists only because the gate accepted it.
//!
//! The outside world sits behind two traits, [`Scholarly`] (search and fetch) and [`Registry`] (resolve an identifier to
//! its metadata). The server binds them to real services from its configuration; no endpoint, key or default lives
//! here, and the tests bind them to fixtures. A failing provider is an error string, never a verified result.

use std::collections::BTreeSet;

use laris_retrieval::NoteSearch;
use laris_vault::index::VaultIndex;
use laris_vault::note::{Note, link_name};
use serde_json::{Value as Json, json};

use crate::audit;
use crate::gate::{
    ClaimProposal, Decision, Evidence, Gate, GateError, MetadataCheck, Proposer, SourceProposal,
};
use crate::text;
use laris_vault::brain::{Level, sha256_hex};

/// What a registry or a document says about a work.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Metadata {
    /// Title.
    pub title: String,
    /// Authors, "Given Family" or "Family, Given".
    pub authors: Vec<String>,
    /// Year of publication.
    pub year: Option<u32>,
}

/// A document as a provider delivers it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Document {
    /// Identifier it was fetched under (a DOI or URL).
    pub identifier: String,
    /// The full text, kept verbatim.
    pub text: String,
    /// The metadata the document states about itself.
    pub claimed: Metadata,
    /// Identifiers of the documents it cites.
    pub cites: Vec<String>,
    /// The dataset release it reports on, when it names one.
    pub dataset: Option<String>,
}

/// A search result.
#[derive(Debug, Clone, PartialEq)]
pub struct Candidate {
    /// Identifier to fetch.
    pub identifier: String,
    /// Title as the provider lists it.
    pub title: String,
    /// The provider's score; ties are broken by identifier.
    pub score: f64,
}

/// Searches and delivers documents.
pub trait Scholarly {
    /// Documents matching `query`, best first.
    fn search(&self, query: &str, limit: usize) -> Result<Vec<Candidate>, String>;
    /// The document under `identifier`.
    fn fetch(&self, identifier: &str) -> Result<Document, String>;
}

/// Resolves identifiers to metadata (Crossref, DataCite, a library catalogue).
pub trait Registry {
    /// The name recorded as the authority of a verification.
    fn name(&self) -> String;
    /// The metadata of `identifier`; `Ok(None)` when it does not resolve.
    fn resolve(&self, identifier: &str) -> Result<Option<Metadata>, String>;
}

/// What a check run produced.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToolOutput {
    /// The command, recorded in the `tool_run` Source.
    pub command: String,
    /// Hash of the inputs.
    pub inputs_sha256: String,
    /// The output text.
    pub output: String,
}

/// Runs a check (recompute a number, run a script, resolve a DOI) on a statement.
pub trait ToolRunner {
    /// Run the check for `statement`.
    fn run(&self, statement: &str) -> Result<ToolOutput, String>;
}

fn surname(author: &str) -> String {
    let family = match author.split_once(',') {
        Some((family, _)) => family,
        None => author.split_whitespace().last().unwrap_or(""),
    };
    family
        .to_lowercase()
        .chars()
        .filter(|c| c.is_alphabetic())
        .collect()
}

/// Compare what a document says about itself with the registry's record. Authors are compared by family name, the
/// year exactly and the title by its words.
pub fn verify_metadata(
    registry: &dyn Registry,
    identifier: &str,
    claimed: &Metadata,
) -> MetadataCheck {
    let record = match registry.resolve(identifier) {
        Ok(Some(record)) => record,
        Ok(None) | Err(_) => return MetadataCheck::Unresolved,
    };
    let known: BTreeSet<String> = record.authors.iter().map(|a| surname(a)).collect();
    let stated: BTreeSet<String> = claimed.authors.iter().map(|a| surname(a)).collect();
    if stated.is_empty() || stated != known {
        return MetadataCheck::Mismatch("the authors differ from the registry".into());
    }
    if claimed.year != record.year {
        return MetadataCheck::Mismatch(format!(
            "the year differs from the registry ({:?} against {:?})",
            claimed.year, record.year
        ));
    }
    if text::words(&claimed.title) != text::words(&record.title) {
        return MetadataCheck::Mismatch("the title differs from the registry".into());
    }
    MetadataCheck::Verified(registry.name())
}

/// Where the provenance of a promotion is read from: the notes the gate wrote and the audit.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Provenance {
    /// Path of the Claim.
    pub claim: String,
    /// Level the Claim holds.
    pub level: Level,
    /// Path of its Source.
    pub source: String,
    /// The Source's identifier.
    pub identifier: String,
    /// How the Source's metadata was checked (`verified:<registry>` or `tool-run`).
    pub metadata_check: String,
    /// The date the Source was retrieved.
    pub retrieved: String,
    /// Byte span in the Source text.
    pub span: (usize, usize),
    /// SHA-256 of the span.
    pub span_sha256: String,
    /// Who proposed the Claim.
    pub proposed_by: String,
    /// Sequence number of the last audit record when the provenance was read.
    pub audit_seq: u64,
}

/// What promoting a Claim did.
#[derive(Debug, Clone, PartialEq)]
pub struct Promotion {
    /// The gate's decision on the Claim.
    pub decision: Decision,
    /// The gate's decisions on corroboration found afterwards.
    pub corroborations: Vec<Decision>,
    /// Provenance of the stored Claim; `None` when it was refused.
    pub provenance: Option<Provenance>,
}

/// The result of acquiring a document.
#[derive(Debug, Clone, PartialEq)]
pub struct Acquired {
    /// The gate's decision on the Source.
    pub decision: Decision,
    /// What the registry said.
    pub metadata: MetadataCheck,
}

fn text_prop(note: &Note, name: &str) -> String {
    note.prop(name).map_or(String::new(), |v| v.py_str())
}

fn int_prop(note: &Note, name: &str) -> usize {
    note.prop(name)
        .and_then(|v| v.py_str().parse().ok())
        .unwrap_or(0)
}

/// The tools, bound to a gate and to providers.
pub struct Tools<'a> {
    /// The only writer.
    pub gate: &'a Gate,
    /// Resolves identifiers.
    pub registry: &'a dyn Registry,
    /// Searches and fetches.
    pub scholarly: &'a dyn Scholarly,
}

impl Tools<'_> {
    /// Search for documents, best first, leaving out the ones already stored. The result is deterministic: score
    /// descending, identifier ascending, one entry per identifier.
    pub fn search(&self, query: &str, limit: usize) -> Result<Vec<Candidate>, GateError> {
        let index = self.gate.index()?;
        let stored: BTreeSet<String> = index
            .notes
            .values()
            .filter(|n| text_prop(n, "type") == "source")
            .map(|n| text_prop(n, "identifier"))
            .collect();
        let mut found = self
            .scholarly
            .search(query, limit.saturating_mul(2).max(limit))
            .map_err(|e| GateError(format!("search failed: {e}")))?;
        found.sort_by(|a, b| {
            b.score
                .total_cmp(&a.score)
                .then_with(|| a.identifier.cmp(&b.identifier))
        });
        let mut seen = BTreeSet::new();
        found.retain(|c| !stored.contains(&c.identifier) && seen.insert(c.identifier.clone()));
        found.truncate(limit);
        Ok(found)
    }

    /// Fetch a document, check its metadata with the registry and offer it to the gate as a Source. A document whose
    /// identifier does not resolve or whose metadata differs is refused by the gate, not stored.
    pub fn acquire(
        &self,
        identifier: &str,
        title: &str,
        who: &Proposer,
    ) -> Result<Acquired, GateError> {
        let document = self
            .scholarly
            .fetch(identifier)
            .map_err(|e| GateError(format!("fetch failed: {e}")))?;
        let metadata = if document.identifier == identifier {
            verify_metadata(self.registry, identifier, &document.claimed)
        } else {
            MetadataCheck::Mismatch("the document answers to another identifier".into())
        };
        let decision = self.gate.submit_source(SourceProposal {
            title: title.to_string(),
            kind: "document".into(),
            identifier: identifier.to_string(),
            text: document.text,
            command: None,
            inputs_sha256: None,
            cites: document.cites,
            dataset: document.dataset,
            metadata: metadata.clone(),
            proposer: who.clone(),
        })?;
        Ok(Acquired { decision, metadata })
    }

    /// Where `quote` stands in the stored Source `source` (byte offsets), or `None` when it is not there.
    pub fn verify_quote(
        &self,
        source: &str,
        quote: &str,
    ) -> Result<Option<(usize, usize)>, GateError> {
        let index = self.gate.index()?;
        Ok(index
            .find(&link_name(source))
            .filter(|n| text_prop(n, "type") == "source")
            .and_then(|n| text::locate(&n.body, quote)))
    }

    /// Offer a Claim to the gate; when it is stored, look for independent corroboration and read its provenance.
    pub fn promote_claim(
        &self,
        statement: &str,
        source: &str,
        quote: &str,
        who: &Proposer,
    ) -> Result<Promotion, GateError> {
        let decision = self.gate.submit_claim(ClaimProposal {
            statement: statement.to_string(),
            source: Some(source.to_string()),
            quote: quote.to_string(),
            requested: Level::Sourced,
            evidence: vec![],
            solver: None,
            proposer: who.clone(),
        })?;
        let Decision::Accepted { path, .. } = &decision else {
            return Ok(Promotion {
                decision,
                corroborations: vec![],
                provenance: None,
            });
        };
        let corroborations = self.corroborate(path, who)?;
        let provenance = self.provenance(path)?;
        Ok(Promotion {
            decision,
            corroborations,
            provenance,
        })
    }

    /// Look for Claims on independent Sources that say the same and offer each pairing to the gate. The tools only
    /// *propose* the pairing; the gate's rule check decides it.
    pub fn corroborate(
        &self,
        claim_path: &str,
        who: &Proposer,
    ) -> Result<Vec<Decision>, GateError> {
        let index = self.gate.index()?;
        let Some(claim) = index.notes.get(claim_path) else {
            return Ok(vec![]);
        };
        let Some(own) = index.find(&link_name(&text_prop(claim, "source_ref"))) else {
            return Ok(vec![]);
        };
        let folders = ["Claims".to_string()];
        let depth = self.gate.settings().search_depth;
        let mut out = Vec::new();
        for hit in NoteSearch::new(&index, &folders).search(&claim.body, depth) {
            if hit.path == claim.path {
                continue;
            }
            let Some(other) = index.notes.get(&hit.path) else {
                continue;
            };
            let Some(other_source) = index.find(&link_name(&text_prop(other, "source_ref"))) else {
                continue;
            };
            let Ok(reason) = independent(own, other_source) else {
                continue;
            };
            if !text::equivalent(
                &text::facts(&claim.body),
                &text::facts(&other.body),
                self.gate.settings().min_equivalence,
            ) {
                continue;
            }
            out.push(self.gate.promote(
                &claim.title,
                Evidence::Corroborated {
                    with: other.title.clone(),
                    independence: reason,
                },
                who.clone(),
            )?);
        }
        Ok(out)
    }

    /// Run a check on a stored Claim and, when its output supports the Claim, raise it to `verified`. The run is stored
    /// as a `tool_run` Source first, so a failed or unsupportive run leaves evidence of what was tried.
    pub fn verify_with_tool(
        &self,
        claim_title: &str,
        runner: &dyn ToolRunner,
        who: &Proposer,
    ) -> Result<Decision, GateError> {
        let index = self.gate.index()?;
        let claim = index
            .find(&link_name(claim_title))
            .filter(|n| text_prop(n, "type") == "claim")
            .ok_or_else(|| GateError(format!("{claim_title} is not a stored claim")))?;
        let output = runner
            .run(&claim.body)
            .map_err(|e| GateError(format!("the check failed to run: {e}")))?;
        let title = format!(
            "Run {}",
            &sha256_hex(format!("{}\0{}", claim.path, output.output).as_bytes())[..8]
        );
        let stored = self.gate.submit_source(SourceProposal {
            title: title.clone(),
            kind: "tool_run".into(),
            identifier: format!("tool:{}", output.command),
            text: output.output,
            command: Some(output.command),
            inputs_sha256: Some(output.inputs_sha256),
            cites: vec![],
            dataset: None,
            metadata: MetadataCheck::NotApplicable,
            proposer: who.clone(),
        })?;
        if !stored.is_accepted() {
            return Ok(stored);
        }
        self.gate.promote(
            &claim.title,
            Evidence::ToolRun { source: title },
            who.clone(),
        )
    }

    /// The provenance of a stored Claim, read from its notes.
    pub fn provenance(&self, claim_path: &str) -> Result<Option<Provenance>, GateError> {
        let index = self.gate.index()?;
        Ok(provenance_of(
            &index,
            claim_path,
            audit::read(self.gate.root()).len() as u64,
        ))
    }
}

fn provenance_of(index: &VaultIndex, claim_path: &str, audit_seq: u64) -> Option<Provenance> {
    let claim = index.notes.get(claim_path)?;
    let source = index.find(&link_name(&text_prop(claim, "source_ref")))?;
    Some(Provenance {
        claim: claim.path.clone(),
        level: Level::parse(&text_prop(claim, "level"))?,
        source: source.path.clone(),
        identifier: text_prop(source, "identifier"),
        metadata_check: text_prop(source, "metadata_check"),
        retrieved: text_prop(source, "retrieved"),
        span: (int_prop(claim, "span_start"), int_prop(claim, "span_end")),
        span_sha256: text_prop(claim, "span_sha256"),
        proposed_by: text_prop(claim, "proposed_by"),
        audit_seq,
    })
}

impl Provenance {
    /// The record as JSON (for the evidence list and reports).
    pub fn to_json(&self) -> Json {
        json!({"claim": self.claim, "level": self.level.as_str(), "source": self.source,
               "identifier": self.identifier, "metadata_check": self.metadata_check,
               "retrieved": self.retrieved, "span": [self.span.0, self.span.1],
               "span_sha256": self.span_sha256, "proposed_by": self.proposed_by, "audit_seq": self.audit_seq})
    }
}

/// Whether two Sources are independent (ADR-024 3.2): different documents, no mutual citation, not the same dataset
/// release. The reason, or why not.
pub fn independent(a: &Note, b: &Note) -> Result<String, String> {
    let (ida, idb) = (text_prop(a, "identifier"), text_prop(b, "identifier"));
    if a.path == b.path || ida == idb {
        return Err("the same document".into());
    }
    if a.prop_list("cites").contains(&idb) || b.prop_list("cites").contains(&ida) {
        return Err("one cites the other".into());
    }
    let (da, db) = (text_prop(a, "dataset"), text_prop(b, "dataset"));
    if !da.is_empty() && da == db {
        return Err("the same dataset release".into());
    }
    Ok(format!(
        "different documents ({ida}, {idb}), no mutual citation{}",
        if da.is_empty() || db.is_empty() {
            ", dataset not stated"
        } else {
            ", different datasets"
        }
    ))
}
