//! Who may call and how much (SR-S2): digest-only keys with a master secret outside the database, roles, quotas
//! reserved atomically and settled in one transaction, expiry, revocation, and the account and admin views.
//!
//! The routes ask [`Access`] three things in order: *who is this* (401 when the key is missing, unknown, revoked,
//! expired or used from a forbidden address, all with the same answer), *may they do this* (403), *can they afford
//! it* (429, a reservation). Nothing here prints a key; the text of a new key is in the answer to the call that made
//! it and nowhere else.

mod keys;
mod master;
mod meter;
mod roles;

pub use keys::{KeyError, KeyRecord, LABEL_MAX, NewKey, PREFIX, SERVER_RULE};
pub use master::{MIN_MASTER_CHARS, Master, MasterError};
pub use meter::{Refusal, Reservation, ReserveError, Used};
pub use roles::{Roles, RolesError, perm};

use crate::error::ApiError;
use crate::proxy::Cidr;
use crate::storage::Storage;
use keys::KeyStore;
use sqlx::Row;
use std::collections::{BTreeSet, HashMap};
use std::net::IpAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

/// Seconds since the epoch now.
pub fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |d| d.as_secs_f64())
}

/// A setting of the access layer that cannot be used. The message names the variable, never its value.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{name} is invalid: {reason}")]
pub struct AccessConfigError {
    /// Variable name.
    pub name: &'static str,
    /// What is wrong.
    pub reason: &'static str,
}

/// Settings of the access layer.
#[derive(Clone, PartialEq)]
pub struct AccessConfig {
    /// The master secret itself (`LARIS_SERVER__MASTER`); a file is preferred in deployment.
    master: Option<String>,
    /// File holding the master secret (`LARIS_SERVER__MASTER_FILE`, a Docker secret).
    pub master_file: Option<PathBuf>,
    /// Role table (`LARIS_SERVER__ROLES`, JSON), privileged roles (`LARIS_SERVER__PRIVILEGED_ROLES`) and
    /// permissions (`LARIS_SERVER__PRIVILEGED_PERMISSIONS`), comma-separated.
    pub roles: Roles,
    /// Blocks `@server` stands for besides loopback (`LARIS_SERVER__SERVER_IPS`, comma-separated).
    pub server_ips: Vec<Cidr>,
    /// Where the key of the first start is written (`LARIS_SERVER__FIRST_ADMIN_FILE`).
    pub first_admin_file: Option<PathBuf>,
    /// Characters counted as one token when the backend reports none (`LARIS_SERVER__CHARS_PER_TOKEN`).
    pub chars_per_token: f64,
}

impl std::fmt::Debug for AccessConfig {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AccessConfig")
            .field("master", &self.master.as_ref().map(|_| "<redacted>"))
            .field("master_file", &self.master_file)
            .field("first_admin_file", &self.first_admin_file)
            .finish_non_exhaustive()
    }
}

impl AccessConfig {
    /// Reads the settings from `env`.
    pub fn from_env(env: &HashMap<String, String>) -> Result<Self, AccessConfigError> {
        let get = |name: &str| env.get(name).map(|v| v.trim()).filter(|v| !v.is_empty());
        let bad = |name: &'static str, reason: &'static str| AccessConfigError { name, reason };
        let master = get("LARIS_SERVER__MASTER").map(str::to_string);
        let master_file = get("LARIS_SERVER__MASTER_FILE").map(PathBuf::from);
        if master.is_none() && master_file.is_none() {
            return Err(bad(
                "LARIS_SERVER__MASTER_FILE",
                "required (or LARIS_SERVER__MASTER)",
            ));
        }
        let mut roles = match get("LARIS_SERVER__ROLES") {
            Some(text) => Roles::from_json(text).map_err(|e| bad("LARIS_SERVER__ROLES", e.0))?,
            None => Roles::default(),
        };
        let list = |name: &str| -> Option<BTreeSet<String>> {
            get(name).map(|v| {
                v.split(',')
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect()
            })
        };
        if let (Some(r), Some(p)) = (
            list("LARIS_SERVER__PRIVILEGED_ROLES"),
            list("LARIS_SERVER__PRIVILEGED_PERMISSIONS"),
        ) {
            roles = roles.with_privileged(r, p);
        } else if list("LARIS_SERVER__PRIVILEGED_ROLES").is_some()
            || list("LARIS_SERVER__PRIVILEGED_PERMISSIONS").is_some()
        {
            return Err(bad(
                "LARIS_SERVER__PRIVILEGED_ROLES",
                "set it together with LARIS_SERVER__PRIVILEGED_PERMISSIONS",
            ));
        }
        let mut server_ips = Vec::new();
        if let Some(v) = get("LARIS_SERVER__SERVER_IPS") {
            for item in v.split(',').map(str::trim).filter(|s| !s.is_empty()) {
                server_ips.push(Cidr::parse(item).ok_or(bad(
                    "LARIS_SERVER__SERVER_IPS",
                    "not an address or CIDR block",
                ))?);
            }
        }
        let chars_per_token = match get("LARIS_SERVER__CHARS_PER_TOKEN") {
            Some(v) => v
                .parse::<f64>()
                .ok()
                .filter(|c| c.is_finite() && *c > 0.0)
                .ok_or(bad(
                    "LARIS_SERVER__CHARS_PER_TOKEN",
                    "must be a number greater than zero",
                ))?,
            None => 4.0,
        };
        Ok(Self {
            master,
            master_file,
            roles,
            server_ips,
            first_admin_file: get("LARIS_SERVER__FIRST_ADMIN_FILE").map(PathBuf::from),
            chars_per_token,
        })
    }

    /// The master secret, from the variable or the file.
    pub fn load_master(&self) -> Result<Master, MasterError> {
        let text = match (&self.master, &self.master_file) {
            (Some(m), _) => m.clone(),
            (None, Some(path)) => std::fs::read_to_string(path)
                .map_err(|_| MasterError("the master secret file cannot be read"))?,
            (None, None) => return Err(MasterError("no master secret")),
        };
        Master::new(&text)
    }
}

/// The caller behind an accepted key.
#[derive(Debug, Clone, PartialEq)]
pub struct Principal {
    /// Key id.
    pub key_id: String,
    /// Role name.
    pub role: String,
    /// Role permissions plus the key's extras.
    pub permissions: BTreeSet<String>,
}

impl Principal {
    /// Whether the key holds the permission.
    pub fn can(&self, permission: &str) -> bool {
        self.permissions.contains(permission)
    }
}

/// What `GET /v1/laris/account` says.
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
pub struct Account {
    /// Role name.
    pub role: String,
    /// Permissions.
    pub permissions: Vec<String>,
    /// Limit; `null` is unlimited.
    pub token_limit: Option<i64>,
    /// Tokens settled.
    pub tokens_used: i64,
    /// Tokens left, `null` when unlimited.
    pub tokens_left: Option<i64>,
}

/// One row of `GET /v1/admin/usage`.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct UsageLine {
    /// Key id.
    pub key_id: String,
    /// Requests.
    pub requests: i64,
    /// Prompt tokens.
    pub prompt: i64,
    /// Completion tokens.
    pub completion: i64,
}

/// Keys, roles and quotas on one storage.
pub struct Access {
    store: KeyStore,
    chars_per_token: f64,
}

impl std::fmt::Debug for Access {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Access").finish_non_exhaustive()
    }
}

impl Access {
    /// Access over `storage` with the master secret loaded from `config`.
    pub fn new(storage: Arc<Storage>, master: Master, config: &AccessConfig) -> Self {
        Self {
            store: KeyStore::new(
                storage,
                master,
                config.roles.clone(),
                config.server_ips.clone(),
            ),
            chars_per_token: config.chars_per_token,
        }
    }

    /// The key store, for admin work.
    pub fn keys(&self) -> &KeyStore {
        &self.store
    }

    /// Tokens a request of `bytes` bytes is expected to use.
    pub fn estimate_tokens(&self, bytes: u64) -> i64 {
        let t = (bytes as f64 / self.chars_per_token).ceil();
        if t >= i64::MAX as f64 {
            i64::MAX
        } else {
            t as i64
        }
    }

    /// Who the `Authorization` header names, from `client`. Missing, malformed, unknown, revoked, expired and
    /// forbidden-address keys all answer 401 alike.
    pub async fn authenticate(
        &self,
        authorization: Option<&str>,
        client: IpAddr,
    ) -> Result<Principal, ApiError> {
        let deny = || ApiError::Unauthorized("invalid API key".into());
        let supplied = authorization
            .and_then(|h| {
                h.strip_prefix("Bearer ")
                    .or_else(|| h.strip_prefix("bearer "))
            })
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .unwrap_or("");
        let record = self
            .store
            .verify(supplied, now())
            .await
            .map_err(|_| ApiError::Internal)?;
        let record = record.ok_or_else(deny)?;
        if !self.store.address_allowed(&record.allowed_ips, client) {
            return Err(deny());
        }
        let mut permissions = self.store.roles().of(&record.role);
        permissions.extend(record.extra_permissions.iter().cloned());
        Ok(Principal {
            key_id: record.id,
            role: record.role,
            permissions,
        })
    }

    /// 403 unless the principal holds the permission.
    pub fn require(&self, principal: &Principal, permission: &str) -> Result<(), ApiError> {
        if principal.can(permission) {
            Ok(())
        } else {
            Err(ApiError::Forbidden(format!(
                "this key lacks the '{permission}' permission"
            )))
        }
    }

    /// Sets tokens aside for a request; 429 when the key cannot cover it.
    pub async fn reserve(
        &self,
        principal: &Principal,
        tokens: i64,
    ) -> Result<Arc<Reservation>, ApiError> {
        match meter::reserve(self.store.storage(), &principal.key_id, tokens, now()).await {
            Ok(r) => Ok(Arc::new(r)),
            Err(ReserveError::Refused(Refusal::Exhausted)) => Err(ApiError::TooManyRequests {
                retry_after_secs: None,
            }),
            Err(ReserveError::Refused(Refusal::Gone)) => {
                Err(ApiError::Unauthorized("invalid API key".into()))
            }
            Err(ReserveError::Failed(_)) => Err(ApiError::Internal),
        }
    }

    /// The caller's own account, read fresh.
    pub async fn account(&self, principal: &Principal) -> Result<Account, ApiError> {
        let record = self
            .store
            .get(&principal.key_id)
            .await
            .map_err(|_| ApiError::Internal)?;
        Ok(Account {
            role: principal.role.clone(),
            permissions: principal.permissions.iter().cloned().collect(),
            token_limit: record.token_limit,
            tokens_used: record.tokens_used,
            tokens_left: record.token_limit.map(|l| (l - record.tokens_used).max(0)),
        })
    }

    /// Requests and tokens per key over the raw usage rows still kept.
    pub async fn usage_summary(&self) -> Result<Vec<UsageLine>, ApiError> {
        let rows = sqlx::query(
            "SELECT key_id, COUNT(*)::bigint AS requests, COALESCE(SUM(prompt_tokens), 0)::bigint AS prompt, \
             COALESCE(SUM(completion_tokens), 0)::bigint AS completion FROM usage GROUP BY key_id ORDER BY key_id",
        )
        .fetch_all(self.store.storage().pool())
        .await
        .map_err(|_| ApiError::Internal)?;
        rows.iter()
            .map(|r| {
                Ok(UsageLine {
                    key_id: r.try_get("key_id")?,
                    requests: r.try_get("requests")?,
                    prompt: r.try_get("prompt")?,
                    completion: r.try_get("completion")?,
                })
            })
            .collect::<Result<_, sqlx::Error>>()
            .map_err(|_| ApiError::Internal)
    }

    /// On the first start makes the built-in key: role `admin`, every permission, no limit, usable only from this
    /// machine. Returns its text when it was just made.
    pub async fn ensure_builtin_key(&self, label: &str) -> Result<Option<String>, KeyError> {
        if self.store.builtin().await?.is_some() {
            return Ok(None);
        }
        let new = NewKey {
            label: label.to_string(),
            role: "admin".into(),
            token_limit: None,
            extra_permissions: self.store.roles().known_permissions(),
            allowed_ips: vec![SERVER_RULE.into()],
            builtin: true,
            ..NewKey::default()
        };
        let (_, text) = self.store.create(&new, now()).await?;
        Ok(Some(text))
    }
}

/// Writes the text of the built-in key to `path`, readable by the owner only, replacing an older file. The text is
/// never printed or logged.
#[cfg(unix)]
pub fn deliver_key(path: &std::path::Path, text: &str) -> std::io::Result<()> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    if let Some(dir) = path.parent().filter(|d| !d.as_os_str().is_empty()) {
        std::fs::create_dir_all(dir)?;
    }
    match std::fs::remove_file(path) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return Err(e),
    }
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(text.as_bytes())?;
    file.write_all(b"\n")
}
