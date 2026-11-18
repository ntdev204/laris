//! Keys in PostgreSQL (SR-S2): create, verify, revoke, limit, list. Only digests are stored; the key text exists
//! once, in the answer to the call that created it. The columns are the generation-1 `keys` table.

use super::master::{Master, legacy_digest, random_bytes, same};
use super::roles::Roles;
use crate::proxy::Cidr;
use crate::storage::{Storage, StorageError};
use sqlx::Row;
use sqlx::postgres::PgRow;
use std::collections::BTreeSet;
use std::net::IpAddr;
use std::sync::Arc;

/// Every key text starts with this.
pub const PREFIX: &str = "lk_";
/// Longest label kept.
pub const LABEL_MAX: usize = 80;
/// The address rule that means "this machine".
pub const SERVER_RULE: &str = "@server";

/// A key request that cannot be met.
#[derive(Debug, thiserror::Error)]
pub enum KeyError {
    /// The request itself is wrong (unknown role, bad limit, bad address rule, no such key).
    #[error("{0}")]
    Invalid(String),
    /// No key has that id.
    #[error("no such key")]
    NotFound,
    /// The database failed.
    #[error(transparent)]
    Storage(#[from] StorageError),
}

impl From<sqlx::Error> for KeyError {
    fn from(e: sqlx::Error) -> Self {
        Self::Storage(e.into())
    }
}

/// What the store knows about a key. Never the text, never the digest.
#[derive(Debug, Clone, PartialEq)]
pub struct KeyRecord {
    /// Eight hex characters, the part of the key text that selects the row.
    pub id: String,
    /// Free text for the operator.
    pub label: String,
    /// Role name.
    pub role: String,
    /// Permissions beyond the role's.
    pub extra_permissions: BTreeSet<String>,
    /// Token limit; `None` is unlimited.
    pub token_limit: Option<i64>,
    /// Tokens settled so far.
    pub tokens_used: i64,
    /// Tokens held by requests in flight.
    pub tokens_reserved: i64,
    /// Creation time, seconds since the epoch.
    pub created_at: f64,
    /// Expiry time.
    pub expires_at: Option<f64>,
    /// Revocation time.
    pub revoked_at: Option<f64>,
    /// Last settled request.
    pub last_used_at: Option<f64>,
    /// Address rules (CIDR blocks or `@server`); empty means any address.
    pub allowed_ips: Vec<String>,
    /// Made by the server at first start.
    pub builtin: bool,
}

impl KeyRecord {
    /// `active`, `revoked`, `expired` or `exhausted`.
    pub fn status(&self, now: f64) -> &'static str {
        if self.revoked_at.is_some() {
            "revoked"
        } else if self.expires_at.is_some_and(|e| e <= now) {
            "expired"
        } else if self.token_limit.is_some_and(|l| self.tokens_used >= l) {
            "exhausted"
        } else {
            "active"
        }
    }

    fn from_row(row: &PgRow) -> Result<Self, sqlx::Error> {
        let list = |column: &str| -> Result<Vec<String>, sqlx::Error> {
            let text: String = row.try_get(column)?;
            Ok(serde_json::from_str(&text).unwrap_or_default())
        };
        Ok(Self {
            id: row.try_get("id")?,
            label: row.try_get("label")?,
            role: row.try_get("role")?,
            extra_permissions: list("extra_permissions")?.into_iter().collect(),
            token_limit: row.try_get("token_limit")?,
            tokens_used: row.try_get("tokens_used")?,
            tokens_reserved: row.try_get("tokens_reserved")?,
            created_at: row.try_get("created_at")?,
            expires_at: row.try_get("expires_at")?,
            revoked_at: row.try_get("revoked_at")?,
            last_used_at: row.try_get("last_used_at")?,
            allowed_ips: list("allowed_ips")?,
            builtin: row.try_get::<i32, _>("builtin")? != 0,
        })
    }
}

/// What a new key is to be.
#[derive(Debug, Clone, Default)]
pub struct NewKey {
    /// Label (cut to [`LABEL_MAX`] characters).
    pub label: String,
    /// Role name.
    pub role: String,
    /// Token limit; `None` is unlimited.
    pub token_limit: Option<i64>,
    /// Extra permissions.
    pub extra_permissions: BTreeSet<String>,
    /// Days until it expires.
    pub expires_in_days: Option<f64>,
    /// Address rules.
    pub allowed_ips: Vec<String>,
    /// Made by the server itself.
    pub builtin: bool,
}

const COLUMNS: &str = "id, label, role, extra_permissions, token_limit, tokens_used, tokens_reserved, created_at, \
     expires_at, revoked_at, last_used_at, allowed_ips, builtin";

/// The keys table with the master secret and the role table.
pub struct KeyStore {
    storage: Arc<Storage>,
    master: Master,
    roles: Roles,
    server_cidrs: Vec<Cidr>,
}

impl KeyStore {
    /// A store over `storage`. `server_ips` are the blocks `@server` stands for besides loopback.
    pub fn new(storage: Arc<Storage>, master: Master, roles: Roles, server_ips: Vec<Cidr>) -> Self {
        Self {
            storage,
            master,
            roles,
            server_cidrs: server_ips,
        }
    }

    /// The role table.
    pub fn roles(&self) -> &Roles {
        &self.roles
    }

    pub(crate) fn storage(&self) -> &Arc<Storage> {
        &self.storage
    }

    fn rules(rules: &[String]) -> Result<Vec<String>, KeyError> {
        rules
            .iter()
            .map(|r| {
                if r == SERVER_RULE || Cidr::parse(r).is_some() {
                    Ok(r.clone())
                } else {
                    Err(KeyError::Invalid(
                        "an address rule is a CIDR block, an address or @server".into(),
                    ))
                }
            })
            .collect()
    }

    /// Makes a key and returns its record with the key text. The text is not stored and cannot be asked for again.
    pub async fn create(&self, new: &NewKey, now: f64) -> Result<(KeyRecord, String), KeyError> {
        self.roles
            .check_extras(&new.role, &new.extra_permissions)
            .map_err(|e| KeyError::Invalid(e.to_string()))?;
        if new.token_limit.is_some_and(|l| l < 0) {
            return Err(KeyError::Invalid(
                "the token limit must be zero or more, or unlimited".into(),
            ));
        }
        if new
            .expires_in_days
            .is_some_and(|d| !d.is_finite() || d <= 0.0)
        {
            return Err(KeyError::Invalid(
                "expires_in_days must be greater than zero".into(),
            ));
        }
        let allowed = Self::rules(&new.allowed_ips)?;
        let id = hex_of(&random_bytes(4).map_err(|e| KeyError::Invalid(e.to_string()))?);
        let secret = url_safe(&random_bytes(24).map_err(|e| KeyError::Invalid(e.to_string()))?);
        let text = format!("{PREFIX}{id}_{secret}");
        let expires = new.expires_in_days.map(|d| now + d * 86_400.0);
        let label: String = new.label.chars().take(LABEL_MAX).collect();
        sqlx::query(
            "INSERT INTO keys (id, digest, label, role, extra_permissions, token_limit, created_at, expires_at, \
             allowed_ips, builtin) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
        )
        .bind(&id)
        .bind(self.master.digest(&text))
        .bind(&label)
        .bind(&new.role)
        .bind(serde_json::to_string(&new.extra_permissions).unwrap_or_else(|_| "[]".into()))
        .bind(new.token_limit)
        .bind(now)
        .bind(expires)
        .bind(serde_json::to_string(&allowed).unwrap_or_else(|_| "[]".into()))
        .bind(i32::from(new.builtin))
        .execute(self.storage.pool())
        .await?;
        Ok((self.get(&id).await?, text))
    }

    /// One key by id.
    pub async fn get(&self, id: &str) -> Result<KeyRecord, KeyError> {
        let sql = format!("SELECT {COLUMNS} FROM keys WHERE id = $1");
        let row = sqlx::query(&sql)
            .bind(id)
            .fetch_optional(self.storage.pool())
            .await?;
        match row {
            Some(r) => Ok(KeyRecord::from_row(&r)?),
            None => Err(KeyError::NotFound),
        }
    }

    /// Every key, oldest first.
    pub async fn list(&self) -> Result<Vec<KeyRecord>, KeyError> {
        let sql = format!("SELECT {COLUMNS} FROM keys ORDER BY created_at, id");
        let rows = sqlx::query(&sql).fetch_all(self.storage.pool()).await?;
        rows.iter().map(|r| Ok(KeyRecord::from_row(r)?)).collect()
    }

    /// The built-in key, if one was made.
    pub async fn builtin(&self) -> Result<Option<KeyRecord>, KeyError> {
        let sql =
            format!("SELECT {COLUMNS} FROM keys WHERE builtin <> 0 ORDER BY created_at LIMIT 1");
        let row = sqlx::query(&sql)
            .fetch_optional(self.storage.pool())
            .await?;
        Ok(row.as_ref().map(KeyRecord::from_row).transpose()?)
    }

    /// The record of a valid, unrevoked, unexpired key; `None` for everything else. The same digests are computed
    /// whether or not the key exists, so the time taken does not say which.
    pub async fn verify(&self, supplied: &str, now: f64) -> Result<Option<KeyRecord>, KeyError> {
        let text = supplied.trim();
        let id = text
            .strip_prefix(PREFIX)
            .and_then(|rest| rest.split('_').next())
            .filter(|id| {
                !id.is_empty() && id.len() <= 16 && id.bytes().all(|b| b.is_ascii_hexdigit())
            })
            .unwrap_or("");
        let row = if id.is_empty() {
            None
        } else {
            sqlx::query("SELECT digest FROM keys WHERE id = $1")
                .bind(id)
                .fetch_optional(self.storage.pool())
                .await?
        };
        let stored: String = match &row {
            Some(r) => r.try_get("digest")?,
            None => legacy_digest("no such key"),
        };
        let keyed = same(&self.master.digest(text), &stored);
        let plain = same(&legacy_digest(text), &stored);
        if row.is_none() || !(keyed || plain) {
            return Ok(None);
        }
        if plain && !keyed {
            // a key from before digests were keyed: keep it working and store it keyed from now on
            sqlx::query("UPDATE keys SET digest = $1 WHERE id = $2")
                .bind(self.master.digest(text))
                .bind(id)
                .execute(self.storage.pool())
                .await?;
        }
        let record = self.get(id).await?;
        if record.revoked_at.is_some() || record.expires_at.is_some_and(|e| e <= now) {
            return Ok(None);
        }
        Ok(Some(record))
    }

    /// Whether `ip` may use a key with these rules. No rules means any address.
    pub fn address_allowed(&self, rules: &[String], ip: IpAddr) -> bool {
        if rules.is_empty() {
            return true;
        }
        rules.iter().any(|r| {
            if r == SERVER_RULE {
                ip.is_loopback() || self.server_cidrs.iter().any(|c| c.contains(ip))
            } else {
                Cidr::parse(r).is_some_and(|c| c.contains(ip))
            }
        })
    }

    /// Revokes a key; revoking twice keeps the first time.
    pub async fn revoke(&self, id: &str, now: f64) -> Result<KeyRecord, KeyError> {
        self.get(id).await?;
        sqlx::query("UPDATE keys SET revoked_at = $1 WHERE id = $2 AND revoked_at IS NULL")
            .bind(now)
            .bind(id)
            .execute(self.storage.pool())
            .await?;
        self.get(id).await
    }

    /// Sets the limit (`None` is unlimited), or with `add` adds to a numeric one.
    pub async fn set_limit(
        &self,
        id: &str,
        limit: Option<i64>,
        add: bool,
    ) -> Result<KeyRecord, KeyError> {
        let record = self.get(id).await?;
        if limit.is_some_and(|l| l < 0) {
            return Err(KeyError::Invalid(
                "the token limit must be zero or more, or unlimited".into(),
            ));
        }
        let new = if add {
            match (limit, record.token_limit) {
                (Some(by), Some(now)) => Some(now.saturating_add(by)),
                _ => {
                    return Err(KeyError::Invalid(
                        "add needs an amount and a key that has a limit".into(),
                    ));
                }
            }
        } else {
            limit
        };
        sqlx::query("UPDATE keys SET token_limit = $1 WHERE id = $2")
            .bind(new)
            .bind(id)
            .execute(self.storage.pool())
            .await?;
        self.get(id).await
    }

    /// Replaces the address rules.
    pub async fn set_allowed_ips(&self, id: &str, rules: &[String]) -> Result<KeyRecord, KeyError> {
        self.get(id).await?;
        let rules = Self::rules(rules)?;
        sqlx::query("UPDATE keys SET allowed_ips = $1 WHERE id = $2")
            .bind(serde_json::to_string(&rules).unwrap_or_else(|_| "[]".into()))
            .bind(id)
            .execute(self.storage.pool())
            .await?;
        self.get(id).await
    }
}

fn hex_of(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// URL-safe base64 without padding.
fn url_safe(bytes: &[u8]) -> String {
    const A: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::new();
    for chunk in bytes.chunks(3) {
        let n = chunk
            .iter()
            .enumerate()
            .fold(0u32, |acc, (i, b)| acc | (u32::from(*b) << (16 - 8 * i)));
        let chars = chunk.len() + 1;
        for i in 0..chars {
            out.push(char::from(A[((n >> (18 - 6 * i)) & 63) as usize]));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn url_safe_encodes_like_base64url() {
        assert_eq!(url_safe(b"Man"), "TWFu");
        assert_eq!(url_safe(b"Ma"), "TWE");
        assert_eq!(url_safe(b"M"), "TQ");
        assert_eq!(url_safe(&[0xfb, 0xff]), "-_8");
        assert_eq!(url_safe(&[7u8; 24]).len(), 32);
    }

    #[test]
    fn status_follows_revocation_expiry_and_limit() {
        let mut k = KeyRecord {
            id: "a".into(),
            label: String::new(),
            role: "user".into(),
            extra_permissions: BTreeSet::new(),
            token_limit: Some(10),
            tokens_used: 3,
            tokens_reserved: 0,
            created_at: 0.0,
            expires_at: Some(100.0),
            revoked_at: None,
            last_used_at: None,
            allowed_ips: vec![],
            builtin: false,
        };
        assert_eq!(k.status(50.0), "active");
        assert_eq!(k.status(100.0), "expired");
        k.tokens_used = 10;
        assert_eq!(k.status(50.0), "exhausted");
        k.revoked_at = Some(1.0);
        assert_eq!(k.status(50.0), "revoked");
    }
}
