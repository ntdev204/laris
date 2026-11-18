//! Roles and permissions (SR-S2). The table is configuration: defaults in code, replaced as a whole by
//! `LARIS_SERVER__ROLES` (JSON object of role to permission list).

use std::collections::{BTreeMap, BTreeSet};

/// Permissions a route can require.
pub mod perm {
    /// Chat.
    pub const CHAT: &str = "chat";
    /// Embed.
    pub const EMBED: &str = "embed";
    /// List and run the model service's remote tools.
    pub const TOOLS: &str = "tools";
    /// Read the model list.
    pub const MODELS: &str = "models";
    /// Read workflows.
    pub const WORKFLOWS: &str = "workflows";
    /// Read help.
    pub const HELP: &str = "help";
    /// Read one's own account.
    pub const ACCOUNT: &str = "account";
    /// Read usage of every key.
    pub const USAGE_READ: &str = "usage.read";
    /// Read reasoning traces.
    pub const REASONING_READ: &str = "reasoning.read";
    /// Read the per-request traces.
    pub const TRACES_READ: &str = "traces.read";
    /// Create, revoke and limit keys.
    pub const KEYS_MANAGE: &str = "keys.manage";
}

/// A role table that cannot be used.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{0}")]
pub struct RolesError(pub &'static str);

/// Which permissions each role holds.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Roles {
    roles: BTreeMap<String, BTreeSet<String>>,
    privileged_roles: BTreeSet<String>,
    privileged_permissions: BTreeSet<String>,
}

fn set(items: &[&str]) -> BTreeSet<String> {
    items.iter().map(|s| (*s).to_string()).collect()
}

impl Default for Roles {
    fn default() -> Self {
        let user = [
            "chat",
            "embed",
            "tools",
            "models",
            "workflows",
            "help",
            "account",
        ];
        let mut roles = BTreeMap::new();
        roles.insert("user".to_string(), set(&user));
        roles.insert(
            "readonly".to_string(),
            set(&["models", "workflows", "help", "account"]),
        );
        roles.insert(
            "auditor".to_string(),
            set(&["account", "usage.read", "reasoning.read", "traces.read"]),
        );
        let mut admin = set(&user);
        admin.extend(set(&[
            "usage.read",
            "reasoning.read",
            "traces.read",
            "keys.manage",
        ]));
        roles.insert("admin".to_string(), admin);
        Self {
            roles,
            privileged_roles: set(&["admin", "auditor"]),
            privileged_permissions: set(&[
                "usage.read",
                "reasoning.read",
                "traces.read",
                "keys.manage",
            ]),
        }
    }
}

impl Roles {
    /// Reads `{"role": ["permission", ...]}`; the privileged roles and permissions keep their defaults.
    pub fn from_json(text: &str) -> Result<Self, RolesError> {
        let parsed: BTreeMap<String, Vec<String>> = serde_json::from_str(text)
            .map_err(|_| RolesError("not an object of role to permission list"))?;
        if parsed.is_empty() {
            return Err(RolesError("no roles"));
        }
        let defaults = Self::default();
        Ok(Self {
            roles: parsed
                .into_iter()
                .map(|(r, p)| (r, p.into_iter().collect()))
                .collect(),
            ..defaults
        })
    }

    /// Replaces the lists of privileged roles and permissions.
    pub fn with_privileged(
        mut self,
        roles: BTreeSet<String>,
        permissions: BTreeSet<String>,
    ) -> Self {
        self.privileged_roles = roles;
        self.privileged_permissions = permissions;
        self
    }

    /// Whether the role exists.
    pub fn has_role(&self, role: &str) -> bool {
        self.roles.contains_key(role)
    }

    /// Names of the roles.
    pub fn names(&self) -> Vec<&str> {
        self.roles.keys().map(String::as_str).collect()
    }

    /// Every permission any role holds.
    pub fn known_permissions(&self) -> BTreeSet<String> {
        self.roles.values().flatten().cloned().collect()
    }

    /// What a role holds by itself.
    pub fn of(&self, role: &str) -> BTreeSet<String> {
        self.roles.get(role).cloned().unwrap_or_default()
    }

    /// Checks the extra permissions asked for a new key: all known, and the privileged ones only on a privileged
    /// role.
    pub fn check_extras(&self, role: &str, extras: &BTreeSet<String>) -> Result<(), RolesError> {
        if !self.has_role(role) {
            return Err(RolesError("unknown role"));
        }
        let known = self.known_permissions();
        if extras.iter().any(|p| !known.contains(p)) {
            return Err(RolesError("unknown permission"));
        }
        if !self.privileged_roles.contains(role)
            && extras
                .iter()
                .any(|p| self.privileged_permissions.contains(p))
        {
            return Err(RolesError(
                "usage, reasoning and key permissions are for privileged roles only",
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ask_one(p: &str) -> BTreeSet<String> {
        std::iter::once(p.to_owned()).collect()
    }

    #[test]
    fn role_defaults_are_the_documented_ones() {
        let r = Roles::default();
        assert!(r.of("user").contains("chat") && !r.of("user").contains("keys.manage"));
        assert!(r.of("readonly").len() == 4 && !r.of("readonly").contains("chat"));
        assert!(r.of("auditor").contains("reasoning.read") && !r.of("auditor").contains("chat"));
        for role in ["auditor", "admin"] {
            assert!(
                r.of(role).contains(perm::TRACES_READ),
                "{role} reads traces"
            );
        }
        assert!(!r.of("user").contains(perm::TRACES_READ));
        assert!(r.check_extras("user", &ask_one(perm::TRACES_READ)).is_err());
        assert!(r.of("admin").contains("keys.manage") && r.of("admin").contains("chat"));
        for role in ["user", "admin"] {
            assert!(r.of(role).contains(perm::TOOLS), "{role} runs remote tools");
        }
        assert!(!r.of("readonly").contains(perm::TOOLS) && !r.of("auditor").contains(perm::TOOLS));
    }

    #[test]
    fn extras_obey_the_privilege_rule() {
        let r = Roles::default();
        let ask = |p: &[&str]| p.iter().map(|s| s.to_string()).collect::<BTreeSet<_>>();
        assert!(r.check_extras("user", &ask(&["embed"])).is_ok());
        assert!(r.check_extras("user", &ask(&["usage.read"])).is_err());
        assert!(r.check_extras("auditor", &ask(&["usage.read"])).is_ok());
        assert!(r.check_extras("user", &ask(&["made.up"])).is_err());
        assert!(r.check_extras("nobody", &ask(&[])).is_err());
    }

    #[test]
    fn a_json_table_replaces_the_roles() {
        let r = Roles::from_json(r#"{"solo": ["chat"]}"#).unwrap();
        assert_eq!(r.names(), vec!["solo"]);
        assert!(Roles::from_json("[]").is_err());
        assert!(Roles::from_json("{}").is_err());
    }
}
