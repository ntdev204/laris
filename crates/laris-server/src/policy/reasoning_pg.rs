//! Reasoning records in PostgreSQL: the `traces` table, whose `reasoning` column is what SR-S4 keeps
//! for the operator. A row is written when an answer ends, fails or is dropped; it holds the key id, the session,
//! the model, the hash of the prompt and the reasoning, and no answer text. Writing is best effort and never holds
//! up an answer: a failure is counted, not retried (traces and their retention are T150).

use super::reasoning::{ReasoningRecord, ReasoningSink, ReasoningStore};
use crate::storage::Storage;
use futures_util::future::BoxFuture;
use sqlx::Row;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

/// Reasoning in the `traces` table.
pub struct PgReasoning {
    storage: Arc<Storage>,
    failed: Arc<AtomicU64>,
}

impl PgReasoning {
    /// A store over `storage`.
    pub fn new(storage: Arc<Storage>) -> Self {
        Self {
            storage,
            failed: Arc::new(AtomicU64::new(0)),
        }
    }

    /// Records that could not be written since the start.
    pub fn failures(&self) -> u64 {
        self.failed.load(Ordering::Relaxed)
    }
}

impl ReasoningSink for PgReasoning {
    fn record(&self, record: ReasoningRecord) {
        let storage = self.storage.clone();
        let failed = self.failed.clone();
        let Ok(handle) = tokio::runtime::Handle::try_current() else {
            failed.fetch_add(1, Ordering::Relaxed);
            return;
        };
        handle.spawn(async move {
            let write = async {
                let mut tx = storage.begin().await.map_err(|_| ())?;
                sqlx::query(
                    "INSERT INTO traces (key_id, ts, session_id, model, prompt_sha256, reasoning) \
                     VALUES ($1, $2, $3, $4, $5, $6)",
                )
                .bind(&record.key_id)
                .bind(record.at)
                .bind(record.session_id.chars().take(64).collect::<String>())
                .bind(&record.model)
                .bind(&record.prompt_sha256)
                .bind(&record.reasoning)
                .execute(&mut *tx)
                .await
                .map_err(|_| ())?;
                tx.commit().await.map_err(|_| ())
            };
            if write.await.is_err() {
                failed.fetch_add(1, Ordering::Relaxed);
            }
        });
    }
}

impl ReasoningStore for PgReasoning {
    fn recent(&self, limit: usize) -> BoxFuture<'_, Vec<ReasoningRecord>> {
        Box::pin(async move {
            let limit = i64::try_from(limit).unwrap_or(500);
            let rows = sqlx::query(
                "SELECT key_id, ts, session_id, model, prompt_sha256, reasoning FROM traces \
                 WHERE reasoning <> '' ORDER BY ts DESC, id DESC LIMIT $1",
            )
            .bind(limit)
            .fetch_all(self.storage.pool())
            .await
            .unwrap_or_default();
            rows.into_iter()
                .map(|r| ReasoningRecord {
                    key_id: r.get("key_id"),
                    session_id: r.get("session_id"),
                    model: r.get("model"),
                    prompt_sha256: r.get("prompt_sha256"),
                    reasoning: r.get("reasoning"),
                    at: r.get("ts"),
                })
                .collect()
        })
    }
}
