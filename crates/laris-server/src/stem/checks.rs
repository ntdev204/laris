//! The remote tools of the STEM profile on the model service: the solver `solve_stem` (T276) and `stem_check`, the
//! profile's deterministic steps that stay in Python where the reference harness runs them (prompt filter, model-free
//! path, repair, solver answer, answer equivalence, cross-check; `laris.research.stem.checks`).

use super::StemError;
use crate::backend::Backend;
use futures_util::future::BoxFuture;
use laris_protocol::p1::ToolRequest;
use serde_json::{Map, Value};
use std::sync::Arc;
use tokio::sync::Semaphore;

/// The name the model service serves the profile's steps under.
pub const STEM_CHECK: &str = "stem_check";

/// What answers the profile's deterministic calls.
pub trait Checks: Send + Sync {
    /// A solver call: the result, or none, and its status (`verified`, `proposal`, `refused:<code>`).
    fn solve(&self, problem: Map<String, Value>) -> BoxFuture<'static, (Option<Value>, String)>;
    /// One `stem_check` operation (`op` and its arguments in `args`).
    fn check(&self, args: Value) -> BoxFuture<'static, Result<Value, StemError>>;
}

/// The tools of the model service behind `backend`; at most `solver_at_once` solver calls (and model-free paths,
/// which run the solver) at once, as the runner's `solver_check.max_concurrency`.
pub struct RemoteChecks {
    backend: Arc<dyn Backend>,
    solver: Arc<Semaphore>,
}

impl RemoteChecks {
    /// The tools behind `backend`.
    pub fn new(backend: Arc<dyn Backend>, solver_at_once: usize) -> Self {
        Self {
            backend,
            solver: Arc::new(Semaphore::new(solver_at_once.max(1))),
        }
    }
}

fn request(arguments: Map<String, Value>) -> ToolRequest {
    ToolRequest {
        arguments,
        extra: Map::new(),
    }
}

impl Checks for RemoteChecks {
    fn solve(&self, problem: Map<String, Value>) -> BoxFuture<'static, (Option<Value>, String)> {
        let backend = self.backend.clone();
        let gate = self.solver.clone();
        Box::pin(async move {
            let _place = gate.acquire_owned().await.ok();
            match backend
                .tool(
                    laris_protocol::scientific::SOLVE_STEM.to_owned(),
                    request(problem),
                )
                .await
            {
                Ok(answer) => match (answer.result, answer.error) {
                    (Some(result), _) => {
                        let status = result["status"].as_str().unwrap_or("").to_owned();
                        (Some(result), status)
                    }
                    (None, Some(error)) => (
                        None,
                        format!("refused:{}", error.kind.as_deref().unwrap_or("rejected")),
                    ),
                    (None, None) => (None, "refused:tool_failed".to_owned()),
                },
                Err(_) => (None, "refused:unreachable".to_owned()),
            }
        })
    }

    fn check(&self, args: Value) -> BoxFuture<'static, Result<Value, StemError>> {
        let backend = self.backend.clone();
        let gate = self.solver.clone();
        Box::pin(async move {
            let Value::Object(arguments) = args else {
                return Err(StemError::Tool("stem_check takes an object"));
            };
            // the model-free path runs the solver
            let _place = if arguments.get("op").and_then(Value::as_str) == Some("model_free") {
                gate.acquire_owned().await.ok()
            } else {
                None
            };
            let answer = backend
                .tool(STEM_CHECK.to_owned(), request(arguments))
                .await
                .map_err(|_| StemError::Tool("the model service did not answer stem_check"))?;
            match (answer.result, answer.error) {
                (Some(result), _) => Ok(result),
                _ => Err(StemError::Tool("stem_check refused the call")),
            }
        })
    }
}
