//! Local tools and the remote tool bridge (SR-H4).
//!
//! One [`Registry`] holds the local tools (`Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash`, `save_memory`,
//! `use_skill`) and any [`RemoteTools`] source, and is the [`laris_core::ToolRunner`] the loop drives. Every call is
//! checked against the tool's schema; every result, local or remote, is finished in one place: a failure becomes the
//! typed error `{"error": {"code", "message"}}`, a result over `tools.resultMaxChars` is cut, and a tool whose
//! output carries third-party content marks it `"untrusted": true`.
//!
//! Tools work on the project folder and `permissions.additionalDirectories` only ([`Scope`]): a path is resolved
//! before it is judged, secrets are refused, and `.git` and `.laris` are never written. Every change saves the old
//! content to a checkpoint first ([`Checkpoints`]) and [`Registry::rewind`] restores it. Permissions and hooks are
//! T133, the OS sandbox T135, redaction T136; this crate takes a [`Redactor`] and leaves those to them.

mod args;
mod bash;
mod checkpoints;
mod context;
mod error;
mod files;
mod glob;
mod memory;
mod registry;
mod scope;
mod search;

pub use args::{object_schema, validate};
pub use bash::{kill_tree, shell};
pub use checkpoints::{Checkpoints, Rewound};
pub use context::{Context, Redactor};
pub use error::ToolError;
pub use glob::glob_to_regex;
pub use registry::{LocalTool, Registry, RemoteTools, ToolInfo, function_schema};
pub use scope::Scope;
