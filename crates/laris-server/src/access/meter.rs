//! Quota: tokens are set aside before the model is called and settled after it (SR-S2).
//!
//! `reserve` is one statement that adds to `tokens_reserved` only when `tokens_used + tokens_reserved + need`
//! still fits the limit, so parallel requests are counted against each other and the limit is never passed by more
//! than the difference between what one request reserved and what it really used. `settle` records the real use and
//! frees the reservation in one transaction; `release` frees it without a charge. A reservation that is dropped
//! without either is released in the background, so a request that ends early never keeps tokens.

use super::keys::KeyError;
use crate::storage::Storage;
use sqlx::Row;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

/// Why a reservation was refused.
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum Refusal {
    /// The key cannot cover the request.
    #[error("token quota used up")]
    Exhausted,
    /// The key is gone, revoked or expired.
    #[error("key no longer valid")]
    Gone,
}

/// What a request used.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Used {
    /// Prompt tokens.
    pub prompt_tokens: i64,
    /// Completion tokens.
    pub completion_tokens: i64,
    /// `chat` or `embed`.
    pub kind: String,
    /// Session id of the request, cut to 64 characters.
    pub session_id: String,
}

/// Tokens set aside for one request.
pub struct Reservation {
    storage: Arc<Storage>,
    key_id: String,
    tokens: i64,
    done: AtomicBool,
}

impl std::fmt::Debug for Reservation {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Reservation")
            .field("key_id", &self.key_id)
            .field("tokens", &self.tokens)
            .finish()
    }
}

/// Sets `need` tokens aside for the key, or says why not.
pub async fn reserve(
    storage: &Arc<Storage>,
    key_id: &str,
    need: i64,
    now: f64,
) -> Result<Reservation, ReserveError> {
    let need = need.max(0);
    let done = sqlx::query(
        "UPDATE keys SET tokens_reserved = tokens_reserved + $1 WHERE id = $2 AND revoked_at IS NULL \
         AND (expires_at IS NULL OR expires_at > $3) \
         AND (token_limit IS NULL OR tokens_used + tokens_reserved + $1 <= token_limit)",
    )
    .bind(need)
    .bind(key_id)
    .bind(now)
    .execute(storage.pool())
    .await
    .map_err(|e| ReserveError::Failed(e.into()))?;
    if done.rows_affected() == 1 {
        return Ok(Reservation {
            storage: storage.clone(),
            key_id: key_id.to_string(),
            tokens: need,
            done: AtomicBool::new(false),
        });
    }
    let row = sqlx::query("SELECT revoked_at IS NOT NULL OR (expires_at IS NOT NULL AND expires_at <= $2) AS dead FROM keys WHERE id = $1")
        .bind(key_id)
        .bind(now)
        .fetch_optional(storage.pool())
        .await
        .map_err(|e| ReserveError::Failed(e.into()))?;
    let dead = match row {
        None => true,
        Some(r) => r.try_get::<bool, _>("dead").unwrap_or(true),
    };
    Err(ReserveError::Refused(if dead {
        Refusal::Gone
    } else {
        Refusal::Exhausted
    }))
}

/// A reservation that did not happen.
#[derive(Debug, thiserror::Error)]
pub enum ReserveError {
    /// The key may not spend this.
    #[error(transparent)]
    Refused(#[from] Refusal),
    /// The database failed.
    #[error(transparent)]
    Failed(#[from] KeyError),
}

impl Reservation {
    /// Tokens set aside.
    pub fn tokens(&self) -> i64 {
        self.tokens
    }

    fn claim(&self) -> bool {
        !self.done.swap(true, Ordering::AcqRel)
    }

    /// Records the real use and frees the reservation, in one transaction. A second call does nothing.
    pub async fn settle(&self, used: &Used, now: f64) -> Result<(), KeyError> {
        if !self.claim() {
            return Ok(());
        }
        let result = self.write(used, now).await;
        if result.is_err() {
            // the use could not be written; free the tokens anyway so the key is not stuck
            let _ = self.free().await;
        }
        result
    }

    async fn write(&self, used: &Used, now: f64) -> Result<(), KeyError> {
        let mut tx = self.storage.begin().await?;
        let session: String = used.session_id.chars().take(64).collect();
        sqlx::query(
            "INSERT INTO usage (key_id, ts, session_id, kind, prompt_tokens, completion_tokens) \
             VALUES ($1, $2, $3, $4, $5, $6)",
        )
        .bind(&self.key_id)
        .bind(now)
        .bind(&session)
        .bind(&used.kind)
        .bind(used.prompt_tokens.max(0))
        .bind(used.completion_tokens.max(0))
        .execute(&mut *tx)
        .await?;
        sqlx::query(
            "UPDATE keys SET tokens_reserved = tokens_reserved - $1, tokens_used = tokens_used + $2, \
             last_used_at = $3 WHERE id = $4",
        )
        .bind(self.tokens)
        .bind(used.prompt_tokens.max(0) + used.completion_tokens.max(0))
        .bind(now)
        .bind(&self.key_id)
        .execute(&mut *tx)
        .await?;
        tx.commit().await?;
        Ok(())
    }

    async fn free(&self) -> Result<(), KeyError> {
        sqlx::query(
            "UPDATE keys SET tokens_reserved = GREATEST(tokens_reserved - $1, 0) WHERE id = $2",
        )
        .bind(self.tokens)
        .bind(&self.key_id)
        .execute(self.storage.pool())
        .await?;
        Ok(())
    }

    /// Frees the reservation without a charge. A second call does nothing.
    pub async fn release(&self) -> Result<(), KeyError> {
        if self.claim() {
            self.free().await
        } else {
            Ok(())
        }
    }

    /// Settles from a place that cannot wait (a `Drop`): the work goes to the runtime.
    pub fn settle_detached(self: Arc<Self>, used: Used, now: f64) {
        if let Ok(handle) = tokio::runtime::Handle::try_current() {
            handle.spawn(async move {
                let _ = self.settle(&used, now).await;
            });
        }
    }
}

impl Drop for Reservation {
    fn drop(&mut self) {
        if self.done.load(Ordering::Acquire) {
            return;
        }
        if let Ok(handle) = tokio::runtime::Handle::try_current() {
            let storage = self.storage.clone();
            let (key_id, tokens) = (self.key_id.clone(), self.tokens);
            handle.spawn(async move {
                let _ = sqlx::query("UPDATE keys SET tokens_reserved = GREATEST(tokens_reserved - $1, 0) WHERE id = $2")
                    .bind(tokens)
                    .bind(key_id)
                    .execute(storage.pool())
                    .await;
            });
        }
    }
}
