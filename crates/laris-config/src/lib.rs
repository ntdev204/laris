//! Settings, environment, packaged defaults and the string catalogue (SR-L1).
//!
//! Every tunable, limit, path, endpoint and message comes from here and from nowhere else. Precedence, highest
//! first: `LARIS_*` environment ([`layers::env_layer`]), the settings file ([`files`]), the defaults packaged at
//! build time ([`packaged`]), then the defaults of [`Settings`]. The settings type is the single source of the
//! JSON Schema ([`settings::schema`]); [`validate`] checks a value against it and names the JSON path of the
//! first problem, as `hooks.PreToolUse[0].hooks[0].timeout`. Messages are keys of the [`catalogue`], in English
//! and Vietnamese with the same keys and placeholders.
//!
//! [`home`] holds the layout of `~/.laris` and the rules of a project's `./.laris/`.
//!
//! The library never reads the process environment or the home directory itself: callers pass them in, so every
//! rule is testable.

pub mod catalogue;
pub mod error;
pub mod files;
pub mod home;
pub mod layers;
pub mod packaged;
pub mod settings;
pub mod validate;

pub use catalogue::{Catalogue, CatalogueError, Language};
pub use error::{ConfigError, ErrorKind};
pub use layers::{LoadOptions, load, resolve};
pub use settings::Settings;
