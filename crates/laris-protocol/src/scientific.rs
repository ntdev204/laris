//! The scientific remote tools (SR-M2, T149): names, arguments and results of the model service's tool routes,
//! served to the client through `POST /v1/laris/tools/{name}`. `solve_stem` (T276) is the deterministic STEM solver.
//!
//! Every tool is deterministic and model-free. Arguments are what the model (or the client) sends in
//! `ToolRequest.arguments`; results are what comes back in `ToolResponse.result`. A refusal (bad arguments, an input
//! over the limit, a domain refusal) is a `ToolResponse.error` whose `type` is one of the `ERR_*` codes.
//!
//! Character offsets (`char_start`, `char_end`) count Unicode scalar values of the text that was sent, not bytes:
//! a client slicing a Rust `str` must convert them.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::BTreeMap;

/// `extract_discourse`: claims, methods, datasets, metrics, results, limitations, assumptions and formulas.
pub const EXTRACT_DISCOURSE: &str = "extract_discourse";
/// `detect_limitations`: limitations, assumptions and negative findings, independent of headings.
pub const DETECT_LIMITATIONS: &str = "detect_limitations";
/// `normalize_quantities`: quantities with their SI value and dimension.
pub const NORMALIZE_QUANTITIES: &str = "normalize_quantities";
/// `parse_bibliography`: title, authors, year, DOI and arXiv id.
pub const PARSE_BIBLIOGRAPHY: &str = "parse_bibliography";
/// `analyse_citations`: the citation graph of a set of documents.
pub const ANALYSE_CITATIONS: &str = "analyse_citations";
/// `mine_literature`: statistics over a set of documents.
pub const MINE_LITERATURE: &str = "mine_literature";
/// `solve_stem`: a structured STEM problem answered without a model, re-checked by an independent route (T276).
pub const SOLVE_STEM: &str = "solve_stem";

/// Every scientific tool, sorted by name (the order of `GET /v1/tools`).
pub const TOOLS: [&str; 7] = [
    ANALYSE_CITATIONS,
    DETECT_LIMITATIONS,
    EXTRACT_DISCOURSE,
    MINE_LITERATURE,
    NORMALIZE_QUANTITIES,
    PARSE_BIBLIOGRAPHY,
    SOLVE_STEM,
];

/// `solve_stem` status: an independent route re-checked the answer.
pub const STATUS_VERIFIED: &str = "verified";
/// `solve_stem` status: the answer was not (or not fully) re-checked; it must not be presented as checked.
pub const STATUS_PROPOSAL: &str = "proposal";

/// The arguments or the input were refused as malformed.
pub const ERR_INVALID_ARGUMENTS: &str = "invalid_arguments";
/// The input is longer than the service allows (`model_service.tool_max_chars`, `tool_max_documents`).
pub const ERR_INPUT_TOO_LARGE: &str = "input_too_large";
/// The library refused the input; the message names the error class, never the input.
pub const ERR_REJECTED: &str = "rejected";
/// The tool failed unexpectedly; nothing of the failure is reported.
pub const ERR_TOOL_FAILED: &str = "tool_failed";
/// The solver's worker ran past `model_service.solver_timeout_s` and was stopped.
pub const ERR_TIMED_OUT: &str = "timed_out";

/// Arguments of `extract_discourse`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ExtractDiscourseArgs {
    /// The text to read.
    pub text: String,
    /// Name used in evidence coordinates (default `doc`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub document_id: Option<String>,
}

/// Arguments of `detect_limitations`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct DetectLimitationsArgs {
    /// The text to read.
    pub text: String,
    /// Name used in evidence coordinates (default `doc`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub document_id: Option<String>,
    /// Ignore heading lines.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub strip_headers: Option<bool>,
}

/// Arguments of `normalize_quantities`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct NormalizeQuantitiesArgs {
    /// The text to read.
    pub text: String,
    /// Name used in evidence coordinates (default `doc`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub document_id: Option<String>,
}

/// Arguments of `parse_bibliography`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct ParseBibliographyArgs {
    /// The head of the paper (only its first 3000 characters are read).
    pub text: String,
    /// File metadata that fills what the text does not say.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub metadata: Option<Map<String, Value>>,
}

/// A document sent to a scholarly tool.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct DocumentInput {
    /// Unique id within the call.
    pub id: String,
    /// The full text; a reference list ends it.
    pub text: String,
}

/// What `analyse_citations` reports.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum CitationKind {
    /// Counts and degrees, plus the edges.
    Summary,
    /// The edges only.
    Edges,
    /// Co-citation counts.
    Cocitation,
    /// Bibliographic coupling counts.
    Coupling,
    /// In-degree and PageRank.
    Centrality,
    /// References that did not resolve.
    Unresolved,
}

/// Arguments of `analyse_citations`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct AnalyseCitationsArgs {
    /// The documents to resolve against each other.
    pub documents: Vec<DocumentInput>,
    /// The report (default `summary`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub kind: Option<CitationKind>,
}

/// What `mine_literature` reports.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum MiningKind {
    /// Counts, year range, identifiers.
    Overview,
    /// Terms by year.
    TermTrends,
    /// Pairs above a shingle similarity.
    NearDuplicates,
    /// Single-link similarity groups.
    Groups,
}

/// Arguments of `mine_literature`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct MineLiteratureArgs {
    /// The documents.
    pub documents: Vec<DocumentInput>,
    /// The report (default `overview`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub kind: Option<MiningKind>,
    /// Similarity from 0 to 1 for `near_duplicates` (default 0.8) and `groups` (default 0.25).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub threshold: Option<f64>,
    /// Most terms for `term_trends` (default 10).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub top: Option<u32>,
    /// Fewest documents a term must appear in for `term_trends` (default 2).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub min_docs: Option<u32>,
}

/// Where in the text something was found.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct EvidenceCoordinate {
    /// `<document>:<kind>:<start>-<end>`.
    pub coordinate_id: String,
    /// The document name that was sent.
    pub document_id: String,
    /// SHA-256 of the text, empty where the tool does not compute it.
    #[serde(default)]
    pub document_sha256: String,
    /// First character, counted in Unicode scalar values.
    pub char_start: u64,
    /// One past the last character, counted in Unicode scalar values.
    pub char_end: u64,
    /// The text of the range, verbatim.
    pub verbatim_snippet: String,
    /// How sure the extractor is, from 0 to 1.
    pub extraction_confidence: f64,
    /// Page, section, paragraph and sentence position, and fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One thing found in the text. The fields that differ by kind (`claim_id`, `name`, `latex_source`, ...) are in
/// `fields`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct DiscourseEntity {
    /// How sure the extractor is, from 0 to 1.
    pub confidence: f64,
    /// Where it was found.
    pub coordinate: EvidenceCoordinate,
    /// The rest of the record.
    #[serde(flatten)]
    pub fields: Map<String, Value>,
}

/// Result of `extract_discourse`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct DiscourseExtraction {
    /// The document name.
    pub document_id: String,
    /// `ext-<document>-<hash prefix>`.
    pub extraction_id: String,
    /// When the extraction ran (the only field that differs between two runs on the same text).
    #[serde(default)]
    pub timestamp_iso: String,
    /// Sentences that state a finding or a contribution.
    #[serde(default)]
    pub claims: Vec<DiscourseEntity>,
    /// Methods and procedures.
    #[serde(default)]
    pub methods: Vec<DiscourseEntity>,
    /// Datasets and corpora.
    #[serde(default)]
    pub datasets: Vec<DiscourseEntity>,
    /// Measures with values.
    #[serde(default)]
    pub metrics: Vec<DiscourseEntity>,
    /// Reported results.
    #[serde(default)]
    pub results: Vec<DiscourseEntity>,
    /// Limitations.
    #[serde(default)]
    pub limitations: Vec<DiscourseEntity>,
    /// Assumptions.
    #[serde(default)]
    pub assumptions: Vec<DiscourseEntity>,
    /// Formulas.
    #[serde(default)]
    pub formulas: Vec<DiscourseEntity>,
    /// Digest of the coordinate ids.
    #[serde(default)]
    pub provenance_manifest_sha256: String,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// Result of `detect_limitations`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct LimitationReport {
    /// The document name.
    pub document_id: String,
    /// Limitations.
    #[serde(default)]
    pub limitations: Vec<DiscourseEntity>,
    /// Assumptions.
    #[serde(default)]
    pub assumptions: Vec<DiscourseEntity>,
    /// Negative findings.
    #[serde(default)]
    pub negative_findings: Vec<DiscourseEntity>,
    /// How many were found at each uncertainty level.
    #[serde(default)]
    pub uncertainty_distribution: Map<String, Value>,
    /// How many were found in each category.
    #[serde(default)]
    pub category_counts: Map<String, Value>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One quantity of `normalize_quantities`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct Quantity {
    /// The text as written.
    pub raw_text: String,
    /// The number as written.
    pub numeric_value: f64,
    /// The unit as written.
    pub raw_unit: String,
    /// The value in the canonical (SI) unit.
    pub canonical_value: f64,
    /// The canonical unit.
    pub canonical_unit: String,
    /// Exponent of each base dimension.
    pub dimension: Map<String, Value>,
    /// Uncertainty, in the written unit, when stated.
    #[serde(default)]
    pub uncertainty: Option<f64>,
    /// Where it was found.
    #[serde(default)]
    pub coordinate: Option<EvidenceCoordinate>,
    /// Scale factor, offset and fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// Result of `normalize_quantities`: the quantities found, in text order.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(transparent)]
pub struct Quantities(pub Vec<Quantity>);

/// Result of `parse_bibliography`: a field not stated in the text is empty (`year` is `null`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct BibliographyResult {
    /// The title.
    #[serde(default)]
    pub title: String,
    /// The authors, in order.
    #[serde(default)]
    pub authors: Vec<String>,
    /// The year of publication.
    #[serde(default)]
    pub year: Option<u32>,
    /// The DOI, lower case.
    #[serde(default)]
    pub doi: String,
    /// The arXiv id.
    #[serde(default)]
    pub arxiv: String,
    /// Where each field was read from.
    #[serde(default)]
    pub evidence: BTreeMap<String, String>,
    /// The non-empty fields as note properties.
    #[serde(default)]
    pub properties: Map<String, Value>,
}

/// One citation edge: `citing` lists `cited` in its references.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct CitationEdge {
    /// Id of the citing document.
    pub citing: String,
    /// Id of the cited document.
    pub cited: String,
}

/// Result of `analyse_citations`. `scope` says what was computed over; the other fields depend on `kind`: `summary`
/// (with `edges`), `edges`, `cocitation`, `coupling`, `centrality` or `unresolved`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct CitationResult {
    /// Documents, references and how many resolved.
    pub scope: Map<String, Value>,
    /// The edges (`summary` only).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub edges: Option<Vec<CitationEdge>>,
    /// The report of the requested kind.
    #[serde(flatten)]
    pub report: Map<String, Value>,
}

/// Arguments of `solve_stem`: the operation and the fields it reads (`expression`, `variable`, `matrix`, `integers`,
/// `value`, `unit`, `target_unit`, `constant`, `reaction`, ...; the tool list carries the full schema). A field the
/// operation does not read is refused.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct SolveStemArgs {
    /// One of the solver's operations (`evaluate`, `solve`, `integrate`, `determinant`, `gcd`, `convert_unit`,
    /// `constant`, `balance`, ...).
    pub operation: String,
    /// The operation's fields.
    #[serde(flatten)]
    pub fields: Map<String, Value>,
}

/// One independent check of a `solve_stem` answer.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct SolverCheck {
    /// How the answer was re-checked (for example `mpmath identity at seeded points`).
    pub route: String,
    /// Whether it agreed.
    pub passed: bool,
    /// Why it did not, when it did not.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

/// A source of data a `solve_stem` answer used (the CODATA table).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct SolverSource {
    /// Name and release, for example `CODATA 2022 (NIST)`.
    pub name: String,
    /// Where the data was published.
    pub url: String,
    /// SHA-256 of the file the solver read.
    pub sha256: String,
}

/// Result of `solve_stem`. `status` is `verified` only when every check ran and passed; otherwise `proposal`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
pub struct SolveStemResult {
    /// The operation that ran.
    pub operation: String,
    /// Its domain (`algebra`, `calculus`, `linear_algebra`, `number_theory`, `units`, `constants`, `chemistry`).
    pub domain: String,
    /// `verified` or `proposal`.
    pub status: String,
    /// The answer as a JSON value (a string, a list, an object, a number or a boolean).
    pub answer: Value,
    /// The answer as one line.
    pub text: String,
    /// The independent checks.
    pub checks: Vec<SolverCheck>,
    /// Versions of the libraries that computed it.
    pub engine: BTreeMap<String, String>,
    /// The answer in LaTeX, when it is an expression.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub latex: Option<String>,
    /// The numeric value, when the answer is a number.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub numeric: Option<String>,
    /// Remarks (an unchecked completeness, a constant used).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub notes: Vec<String>,
    /// Data sources used.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub sources: Vec<SolverSource>,
    /// Fields of a newer peer.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}
