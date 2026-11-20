//! The main brain on the server (T240, ADR-025 D50, SR-K2, SR-K3): one shared vault, written only by the write gate
//! of `laris-brain`, read by the request pipeline for retrieval.
//!
//! * **Writers.** [`MainBrain`] holds the [`Gate`], the only writer. The routes under `/v1/admin/brain/` call it:
//!   `POST sources` (ingestion), `POST claims` and `POST retract`. They need `brain.manage`, a permission of the
//!   admin role only (privileged: it cannot be given to a key of another role). A caller cannot name the proposer: it
//!   is the key's id. Text with no Source is a model-only Claim and the gate refuses it; a Claim needs a quote that is
//!   in a stored Source. Retracting a Source downgrades or retires its Claims. Every proposal is audited by the gate.
//! * **Readers.** The pipeline reads the vault through [`MainBrain::source`] for callers with `brain.read`. After a
//!   write the retrieval index is rebuilt, so a retraction takes effect on the next turn. There is **no route that
//!   returns a note or lists the vault**: what leaves is the cited wording an answer uses.
//! * **Settings.** `LARIS_SERVER__MAIN_BRAIN_DIR` and the five thresholds of the gate
//!   (`LARIS_SERVER__MAIN_BRAIN_MIN_SUPPORT`, `_MIN_EQUIVALENCE`, `_SUBJECT_OVERLAP`, `_SEARCH_DEPTH`,
//!   `_MAX_BYTES`), which have no defaults: set one and every other is required.

use crate::app::{AppState, read_json};
use crate::config::ConfigError;
use crate::error::ApiError;
use crate::log::RequestScope;
use axum::Extension;
use axum::body::Body;
use axum::extract::{Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::Response;
use laris_brain::gate::{
    ClaimProposal, ConsolidationReport, Decision, Evidence, Gate, GateSettings, MetadataCheck,
    Proposer, SourceProposal,
};
use laris_policy::{Passage, PassageSource, VaultSource};
use laris_retrieval::{Scorer, VaultPassages};
use laris_vault::VaultIndex;
use laris_vault::brain::Level;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::sync::{Arc, RwLock};

type Shared = State<Arc<AppState>>;
type Scope = Extension<Arc<RequestScope>>;

/// Where the main brain is and how strict its gate is.
#[derive(Debug, Clone, PartialEq)]
pub struct MainBrainConfig {
    /// The vault folder.
    pub dir: PathBuf,
    /// The thresholds of the gate.
    pub gate: GateSettings,
}

impl MainBrainConfig {
    /// Reads the settings; `None` when `LARIS_SERVER__MAIN_BRAIN_DIR` is not set.
    pub fn from_env(env: &HashMap<String, String>) -> Result<Option<Self>, ConfigError> {
        let get = |name: &str| env.get(name).map(|v| v.trim()).filter(|v| !v.is_empty());
        let Some(dir) = get("LARIS_SERVER__MAIN_BRAIN_DIR") else {
            return Ok(None);
        };
        let ratio = |name: &'static str| -> Result<f64, ConfigError> {
            let text = get(name).ok_or(ConfigError::Missing(name))?;
            match text.parse::<f64>() {
                Ok(v) if (0.0..=1.0).contains(&v) => Ok(v),
                _ => Err(ConfigError::Invalid {
                    name,
                    reason: "expected a number from 0 to 1",
                }),
            }
        };
        let count = |name: &'static str| -> Result<usize, ConfigError> {
            let text = get(name).ok_or(ConfigError::Missing(name))?;
            match text.parse::<usize>() {
                Ok(v) if v >= 1 => Ok(v),
                _ => Err(ConfigError::Invalid {
                    name,
                    reason: "expected a whole number in range",
                }),
            }
        };
        Ok(Some(Self {
            dir: PathBuf::from(dir),
            gate: GateSettings {
                min_support: ratio("LARIS_SERVER__MAIN_BRAIN_MIN_SUPPORT")?,
                min_equivalence: ratio("LARIS_SERVER__MAIN_BRAIN_MIN_EQUIVALENCE")?,
                subject_overlap: ratio("LARIS_SERVER__MAIN_BRAIN_SUBJECT_OVERLAP")?,
                search_depth: count("LARIS_SERVER__MAIN_BRAIN_SEARCH_DEPTH")?,
                max_bytes: count("LARIS_SERVER__MAIN_BRAIN_MAX_BYTES")?,
            },
        }))
    }
}

/// What retrieval reads: the passages of the vault, without those of a Source that was retracted or replaced. A
/// retracted Source keeps its note (the audit needs it) but must never ground an answer again.
pub struct BrainSource {
    inner: VaultSource,
    hidden: HashSet<String>,
}

impl PassageSource for BrainSource {
    fn passages(&self, query: &str, limit: usize) -> Vec<Passage> {
        // ask for more than the limit: the best passages may be the hidden ones
        let wanted = limit.saturating_add(self.hidden.len().min(64));
        self.inner
            .passages(query, wanted)
            .into_iter()
            .filter(|p| !self.hidden.contains(&p.source))
            .take(limit)
            .collect()
    }
}

/// The main brain: its gate and the retrieval index over it.
pub struct MainBrain {
    gate: Arc<Gate>,
    source: RwLock<Option<Arc<BrainSource>>>,
    index: RwLock<Option<Arc<VaultIndex>>>,
    /// One writer at a time: the gate reads, decides and rewrites files.
    writing: tokio::sync::Mutex<()>,
}

impl MainBrain {
    /// Opens the vault at `config.dir` (made when it does not exist). A vault that cannot be indexed is not fatal: the
    /// retrieval stage then reports itself skipped.
    pub fn open(config: &MainBrainConfig) -> std::io::Result<Self> {
        std::fs::create_dir_all(&config.dir)?;
        let gate = Gate::new(
            &config.dir,
            config.gate,
            Box::new(crate::policy::gateway::today),
        );
        let brain = Self {
            gate: Arc::new(gate),
            source: RwLock::new(None),
            index: RwLock::new(None),
            writing: tokio::sync::Mutex::new(()),
        };
        brain.reindex();
        Ok(brain)
    }

    /// The retrieval index as of the last write; `None` when the vault cannot be read.
    pub fn source(&self) -> Option<Arc<BrainSource>> {
        self.source
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    /// The vault index as of the last write, for the decider's measurements; `None` when the vault cannot be read.
    pub fn index(&self) -> Option<Arc<VaultIndex>> {
        self.index
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    fn reindex(&self) {
        let built = VaultIndex::build(self.gate.root(), None).ok().map(Arc::new);
        *self
            .index
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = built.clone();
        let fresh = built.map(|index| {
            let hidden = ["retracted", "superseded"]
                .into_iter()
                .flat_map(|status| index.by_prop("status", status))
                .map(|note| note.path.clone())
                .collect();
            Arc::new(BrainSource {
                inner: VaultSource::new(VaultPassages::new(&index), Scorer::Fused),
                hidden,
            })
        });
        *self
            .source
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = fresh;
    }

    /// Runs one write on a blocking thread, alone, and rebuilds the index after it.
    async fn write<T: Send + 'static>(
        self: &Arc<Self>,
        job: impl FnOnce(&Gate) -> Result<T, laris_brain::GateError> + Send + 'static,
    ) -> Result<T, ApiError> {
        let _one = self.writing.lock().await;
        let gate = self.gate.clone();
        let done = tokio::task::spawn_blocking(move || job(&gate))
            .await
            .map_err(|_| ApiError::Internal)?
            .map_err(|e| {
                if e.0.ends_with("is not a stored source") {
                    ApiError::NotFound
                } else {
                    ApiError::Internal
                }
            });
        let this = self.clone();
        tokio::task::spawn_blocking(move || this.reindex())
            .await
            .map_err(|_| ApiError::Internal)?;
        done
    }
}

fn json<T: Serialize>(status: StatusCode, value: &T) -> Result<Response, ApiError> {
    let bytes = serde_json::to_vec(value).map_err(|_| ApiError::Internal)?;
    let mut response = Response::new(Body::from(bytes));
    *response.status_mut() = status;
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/json"),
    );
    Ok(response)
}

fn done(result: Result<Response, ApiError>) -> Response {
    result.unwrap_or_else(ApiError::into_response)
}

fn bad(message: &str) -> ApiError {
    ApiError::BadRequest(format!("invalid request: {message}"))
}

/// The key that asked, as the gate records it. The body never names the proposer.
fn proposer_of(principal: Option<&crate::access::Principal>) -> Proposer {
    Proposer(format!(
        "key:{}",
        principal.map_or("open", |p| p.key_id.as_str())
    ))
}

fn brain_of(state: &AppState) -> Result<Arc<MainBrain>, ApiError> {
    state.main_brain.clone().ok_or(ApiError::NotFound)
}

/// What the gate decided, as the API answers it.
#[derive(Debug, Serialize)]
struct DecisionView {
    decision: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    level: Option<&'static str>,
    conflicts: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    reason: Option<&'static str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    detail: Option<String>,
}

impl DecisionView {
    fn of(decision: Decision) -> Self {
        match decision {
            Decision::Accepted {
                path,
                level,
                conflicts,
            } => Self {
                decision: "accepted",
                path: Some(path),
                level: level.map(Level::as_str),
                conflicts,
                reason: None,
                detail: None,
            },
            Decision::Refused { reason, detail } => Self {
                decision: "refused",
                path: None,
                level: None,
                conflicts: Vec::new(),
                reason: Some(reason.as_str()),
                detail: Some(detail),
            },
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct MetadataBody {
    /// `verified`, `mismatch`, `unresolved` or `not_applicable`.
    kind: String,
    /// The registry, for `verified` and `mismatch`.
    #[serde(default)]
    registry: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SourceBody {
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
    metadata: MetadataBody,
}

/// `POST /v1/admin/brain/sources`: stores a Source (`brain.manage`).
pub async fn submit_source(
    State(state): Shared,
    Extension(scope): Scope,
    request: Request,
) -> Response {
    scope.set_route("admin_brain_sources");
    done(source_inner(&state, &scope, request).await)
}

async fn source_inner(
    state: &Arc<AppState>,
    scope: &Arc<RequestScope>,
    request: Request,
) -> Result<Response, ApiError> {
    let brain = brain_of(state)?;
    let (body, principal, _) =
        read_json::<SourceBody>(state, scope, request, crate::access::perm::BRAIN_MANAGE).await?;
    let metadata = match body.metadata.kind.as_str() {
        "verified" if !body.metadata.registry.is_empty() => {
            MetadataCheck::Verified(body.metadata.registry)
        }
        "mismatch" if !body.metadata.registry.is_empty() => {
            MetadataCheck::Mismatch(body.metadata.registry)
        }
        "unresolved" => MetadataCheck::Unresolved,
        "not_applicable" => MetadataCheck::NotApplicable,
        _ => return Err(bad("metadata: verified and mismatch name a registry")),
    };
    let proposal = SourceProposal {
        title: body.title,
        kind: body.kind,
        identifier: body.identifier,
        text: body.text,
        command: body.command,
        inputs_sha256: body.inputs_sha256,
        cites: body.cites,
        dataset: body.dataset,
        metadata,
        proposer: proposer_of(principal.as_ref()),
    };
    let decision = brain
        .write(move |gate| gate.submit_source(proposal))
        .await?;
    json(StatusCode::OK, &DecisionView::of(decision))
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum EvidenceBody {
    Corroborated { with: String, independence: String },
    ToolRun { source: String },
    Reviewed { reviewer: String, on: String },
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ClaimBody {
    statement: String,
    /// The Source's note name; absent means model-only text, which the gate refuses.
    #[serde(default)]
    source: Option<String>,
    #[serde(default)]
    quote: String,
    /// The level asked for (`sourced`, `corroborated`, `verified`, `reviewed`).
    requested: String,
    #[serde(default)]
    evidence: Vec<EvidenceBody>,
}

/// `POST /v1/admin/brain/claims`: proposes a Claim to the gate (`brain.manage`). The answer says whether it was
/// accepted or why it was refused; a refusal is not an HTTP error.
pub async fn submit_claim(
    State(state): Shared,
    Extension(scope): Scope,
    request: Request,
) -> Response {
    scope.set_route("admin_brain_claims");
    done(claim_inner(&state, &scope, request).await)
}

async fn claim_inner(
    state: &Arc<AppState>,
    scope: &Arc<RequestScope>,
    request: Request,
) -> Result<Response, ApiError> {
    let brain = brain_of(state)?;
    let (body, principal, _) =
        read_json::<ClaimBody>(state, scope, request, crate::access::perm::BRAIN_MANAGE).await?;
    let requested = Level::parse(&body.requested).ok_or_else(|| bad("requested: unknown level"))?;
    let evidence = body
        .evidence
        .into_iter()
        .map(|e| match e {
            EvidenceBody::Corroborated { with, independence } => {
                Evidence::Corroborated { with, independence }
            }
            EvidenceBody::ToolRun { source } => Evidence::ToolRun { source },
            EvidenceBody::Reviewed { reviewer, on } => Evidence::Reviewed { reviewer, on },
        })
        .collect();
    let proposal = ClaimProposal {
        statement: body.statement,
        source: body.source,
        quote: body.quote,
        requested,
        evidence,
        proposer: proposer_of(principal.as_ref()),
    };
    let decision = brain.write(move |gate| gate.submit_claim(proposal)).await?;
    json(StatusCode::OK, &DecisionView::of(decision))
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RetractBody {
    title: String,
    reason: String,
}

#[derive(Debug, Serialize)]
struct ReportView {
    retired: Vec<(String, String)>,
    downgraded: Vec<(String, &'static str, &'static str)>,
    repointed: Vec<String>,
    pruned: Vec<String>,
}

impl ReportView {
    fn of(r: ConsolidationReport) -> Self {
        Self {
            retired: r.retired,
            downgraded: r
                .downgraded
                .into_iter()
                .map(|(path, from, to)| (path, from.as_str(), to.as_str()))
                .collect(),
            repointed: r.repointed,
            pruned: r.pruned,
        }
    }
}

/// `POST /v1/admin/brain/retract`: retracts a Source; its Claims are downgraded or retired (`brain.manage`).
pub async fn retract_source(
    State(state): Shared,
    Extension(scope): Scope,
    request: Request,
) -> Response {
    scope.set_route("admin_brain_retract");
    done(retract_inner(&state, &scope, request).await)
}

async fn retract_inner(
    state: &Arc<AppState>,
    scope: &Arc<RequestScope>,
    request: Request,
) -> Result<Response, ApiError> {
    let brain = brain_of(state)?;
    let (body, principal, _) =
        read_json::<RetractBody>(state, scope, request, crate::access::perm::BRAIN_MANAGE).await?;
    if body.title.trim().is_empty() || body.reason.trim().is_empty() {
        return Err(bad("title and reason are required"));
    }
    let who = proposer_of(principal.as_ref());
    let report = brain
        .write(move |gate| gate.retract_source(&body.title, &body.reason, who))
        .await?;
    json(StatusCode::OK, &ReportView::of(report))
}
