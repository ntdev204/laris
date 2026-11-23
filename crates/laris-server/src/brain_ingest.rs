//! Offline ingestion, freezing and retrieval of the main brain (T277, ADR-026 section 5, SR-K3).
//!
//! * `laris-server brain import PROPOSALS --date YYYY-MM-DD`: feeds a file of proposals (JSON lines) to the write gate
//!   of the vault in `LARIS_SERVER__MAIN_BRAIN_DIR`, with the gate's thresholds from the same settings as the server.
//!   Sources first, in file order, then every Claim in one batch ([`Gate::submit_claims`]). The gate decides; this
//!   module only reads the file and counts. The proposer is the build tool named in the file's records, never a key.
//! * `laris-server brain freeze OUT`: writes a manifest of the vault (every file with its SHA-256, the notes by type,
//!   the Claims by level, the lint problems) and one hash over the manifest's file list: the snapshot's identity.
//! * `laris-server brain retrieve QUERIES K`: the passages the request pipeline's retrieval ([`MainBrain::source`])
//!   returns for each query, as JSON lines, for measuring recall offline. Nothing leaves the machine.

use crate::mainbrain::{MainBrain, MainBrainConfig};
use laris_brain::gate::{
    ClaimProposal, Decision, Evidence, Gate, MetadataCheck, Proposer, SourceProposal,
};
use laris_policy::PassageSource;
use laris_vault::brain::{Level, sha256_hex};
use laris_vault::{VaultIndex, lint_brain};
use serde::Deserialize;
use serde_json::{Value as Json, json};
use std::collections::BTreeMap;
use std::fs;
use std::io::{BufRead, Write};
use std::path::Path;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct MetadataLine {
    kind: String,
    #[serde(default)]
    registry: String,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum EvidenceLine {
    Corroborated { with: String, independence: String },
    ToolRun { source: String },
    Reviewed { reviewer: String, on: String },
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
enum Line {
    Source {
        title: String,
        kind: String,
        identifier: String,
        text: String,
        #[serde(default)]
        command: Option<String>,
        #[serde(default)]
        inputs_sha256: Option<String>,
        #[serde(default)]
        cites: Vec<String>,
        #[serde(default)]
        dataset: Option<String>,
        metadata: MetadataLine,
        proposer: String,
    },
    Claim {
        statement: String,
        #[serde(default)]
        source: Option<String>,
        #[serde(default)]
        quote: String,
        requested: String,
        #[serde(default)]
        evidence: Vec<EvidenceLine>,
        #[serde(default)]
        solver: Option<String>,
        proposer: String,
    },
}

fn metadata(line: MetadataLine) -> Result<MetadataCheck, String> {
    match (line.kind.as_str(), line.registry.is_empty()) {
        ("verified", false) => Ok(MetadataCheck::Verified(line.registry)),
        ("mismatch", false) => Ok(MetadataCheck::Mismatch(line.registry)),
        ("unresolved", _) => Ok(MetadataCheck::Unresolved),
        ("not_applicable", _) => Ok(MetadataCheck::NotApplicable),
        _ => Err("metadata: verified and mismatch name a registry".into()),
    }
}

#[derive(Default)]
struct Tally {
    accepted: u64,
    refused: BTreeMap<String, u64>,
    examples: BTreeMap<String, Vec<String>>,
    levels: BTreeMap<String, u64>,
    conflicts: u64,
}

impl Tally {
    fn add(&mut self, decision: &Decision, what: &str) {
        match decision {
            Decision::Accepted {
                level, conflicts, ..
            } => {
                self.accepted += 1;
                self.conflicts += conflicts.len() as u64;
                if let Some(level) = level {
                    *self.levels.entry(level.as_str().to_string()).or_default() += 1;
                }
            }
            Decision::Refused { reason, detail } => {
                let key = reason.as_str().to_string();
                *self.refused.entry(key.clone()).or_default() += 1;
                let examples = self.examples.entry(key).or_default();
                if examples.len() < 5 {
                    let head: String = what.chars().take(80).collect();
                    examples.push(format!("{head}: {detail}"));
                }
            }
        }
    }

    fn json(&self) -> Json {
        json!({"accepted": self.accepted, "refused": self.refused, "levels": self.levels,
               "conflicts": self.conflicts, "refusal_examples": self.examples})
    }
}

/// Feeds the proposals in `path` to the gate of the vault in `config`; `date` is written as the notes' date.
pub fn import(config: &MainBrainConfig, path: &Path, date: &str) -> Result<Json, String> {
    if !is_date(date) {
        return Err("the date must be YYYY-MM-DD".into());
    }
    fs::create_dir_all(&config.dir).map_err(|e| e.to_string())?;
    let today = date.to_string();
    let gate = Gate::new(&config.dir, config.gate, Box::new(move || today.clone()));
    let file = fs::File::open(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let mut sources = Tally::default();
    let mut claims: Vec<ClaimProposal> = Vec::new();
    for (number, line) in std::io::BufReader::new(file).lines().enumerate() {
        let line = line.map_err(|e| e.to_string())?;
        if line.trim().is_empty() {
            continue;
        }
        let parsed: Line =
            serde_json::from_str(&line).map_err(|e| format!("line {}: {e}", number + 1))?;
        match parsed {
            Line::Source {
                title,
                kind,
                identifier,
                text,
                command,
                inputs_sha256,
                cites,
                dataset,
                metadata: check,
                proposer,
            } => {
                let proposal = SourceProposal {
                    title: title.clone(),
                    kind,
                    identifier,
                    text,
                    command,
                    inputs_sha256,
                    cites,
                    dataset,
                    metadata: metadata(check).map_err(|e| format!("line {}: {e}", number + 1))?,
                    proposer: Proposer(proposer),
                };
                let decision = gate.submit_source(proposal).map_err(|e| e.0)?;
                sources.add(&decision, &title);
            }
            Line::Claim {
                statement,
                source,
                quote,
                requested,
                evidence,
                solver,
                proposer,
            } => {
                let requested = Level::parse(&requested)
                    .ok_or_else(|| format!("line {}: unknown level", number + 1))?;
                claims.push(ClaimProposal {
                    statement,
                    source,
                    quote,
                    requested,
                    evidence: evidence
                        .into_iter()
                        .map(|e| match e {
                            EvidenceLine::Corroborated { with, independence } => {
                                Evidence::Corroborated { with, independence }
                            }
                            EvidenceLine::ToolRun { source } => Evidence::ToolRun { source },
                            EvidenceLine::Reviewed { reviewer, on } => {
                                Evidence::Reviewed { reviewer, on }
                            }
                        })
                        .collect(),
                    solver,
                    proposer: Proposer(proposer),
                });
            }
        }
    }
    let statements: Vec<String> = claims.iter().map(|c| c.statement.clone()).collect();
    let decisions = gate.submit_claims(claims).map_err(|e| e.0)?;
    let mut tally = Tally::default();
    for (decision, statement) in decisions.iter().zip(&statements) {
        tally.add(decision, statement);
    }
    Ok(json!({"sources": sources.json(), "claims": tally.json()}))
}

fn is_date(text: &str) -> bool {
    let b = text.as_bytes();
    b.len() == 10
        && b[4] == b'-'
        && b[7] == b'-'
        && b.iter()
            .enumerate()
            .all(|(i, c)| i == 4 || i == 7 || c.is_ascii_digit())
}

fn walk(base: &Path, dir: &Path, out: &mut Vec<String>) -> std::io::Result<()> {
    let mut entries: Vec<_> = fs::read_dir(dir)?.flatten().collect();
    entries.sort_by_key(|e| e.file_name());
    for entry in entries {
        let path = entry.path();
        let kind = entry.file_type()?;
        if kind.is_symlink() {
            continue;
        }
        if kind.is_dir() {
            walk(base, &path, out)?;
        } else if let Ok(rel) = path.strip_prefix(base) {
            out.push(rel.to_string_lossy().replace('\\', "/"));
        }
    }
    Ok(())
}

/// The manifest of the vault at `dir`: files with SHA-256, notes by type, Claims by level, lint problems, and the
/// snapshot hash (SHA-256 over the sorted `path NUL sha256 LF` lines).
pub fn freeze(dir: &Path) -> Result<Json, String> {
    let mut files = Vec::new();
    walk(dir, dir, &mut files).map_err(|e| e.to_string())?;
    let mut hashes = BTreeMap::new();
    let mut listing = String::new();
    for rel in &files {
        let bytes = fs::read(dir.join(rel)).map_err(|e| format!("{rel}: {e}"))?;
        let hash = sha256_hex(&bytes);
        listing.push_str(&format!("{rel}\0{hash}\n"));
        hashes.insert(rel.clone(), hash);
    }
    let index = VaultIndex::build(dir, None).map_err(|e| format!("{e:?}"))?;
    let mut types: BTreeMap<String, u64> = BTreeMap::new();
    let mut levels: BTreeMap<String, u64> = BTreeMap::new();
    let mut solver_links = 0_u64;
    for note in index.notes.values() {
        let kind = note.prop("type").map(|v| v.py_str()).unwrap_or_default();
        if kind == "claim" {
            let level = note.prop("level").map(|v| v.py_str()).unwrap_or_default();
            *levels.entry(level).or_default() += 1;
            if note.prop("solver_ref").is_some() {
                solver_links += 1;
            }
        }
        *types.entry(kind).or_default() += 1;
    }
    let problems = lint_brain(&index);
    let mut by_code: BTreeMap<String, u64> = BTreeMap::new();
    for p in &problems {
        *by_code.entry(p.code.clone()).or_default() += 1;
    }
    Ok(json!({
        "snapshot_sha256": sha256_hex(listing.as_bytes()),
        "files": hashes.len(),
        "notes_by_type": types,
        "claims_by_level": levels,
        "claims_with_solver_ref": solver_links,
        "lint_problems": problems.len(),
        "lint_by_code": by_code,
        "file_sha256": hashes,
    }))
}

#[derive(Debug, Deserialize)]
struct Query {
    id: String,
    query: String,
}

/// For every query in `queries` (JSON lines `{"id", "query"}`), the best `k` passages of the server's retrieval over
/// the vault in `config`, written to `out` as JSON lines `{"id", "hits": [{"source", "start", "end", "text"}]}`.
pub fn retrieve(
    config: &MainBrainConfig,
    queries: &Path,
    k: usize,
    out: &mut dyn Write,
) -> Result<u64, String> {
    let brain = MainBrain::open(config).map_err(|e| e.to_string())?;
    let source = brain
        .source()
        .ok_or_else(|| "the vault cannot be indexed".to_string())?;
    let file = fs::File::open(queries).map_err(|e| format!("{}: {e}", queries.display()))?;
    let mut count = 0;
    for (number, line) in std::io::BufReader::new(file).lines().enumerate() {
        let line = line.map_err(|e| e.to_string())?;
        if line.trim().is_empty() {
            continue;
        }
        let q: Query =
            serde_json::from_str(&line).map_err(|e| format!("line {}: {e}", number + 1))?;
        let hits: Vec<Json> = source
            .passages(&q.query, k)
            .into_iter()
            .map(|p| json!({"source": p.source, "start": p.start, "end": p.end, "text": p.text}))
            .collect();
        writeln!(out, "{}", json!({"id": q.id, "hits": hits})).map_err(|e| e.to_string())?;
        count += 1;
    }
    Ok(count)
}
