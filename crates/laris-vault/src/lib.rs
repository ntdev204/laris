//! Obsidian format: parse, index, write, schema, lint (SR-L2).
//!
//! This part reads a vault: [`note::parse_note`] turns one Markdown file into properties, links, tags, headings and
//! block ids; [`index::VaultIndex`] resolves the links of a folder and answers backlinks and orphans, incrementally
//! and deterministically; [`yaml`] is the small reader for the properties, since no YAML crate is approved. The
//! writer ([`writer`]: atomic, managed blocks, conflict detection, properties written by [`emit`]), schema registry
//! ([`schema`]) and lint ([`lint`]: format, hub tree, content) complete SR-L2. The format is `docs/specifications/OBSIDIAN_VAULT_FORMAT.md`; the
//! golden fixture under `tests/golden/vault/` is the generation-1 index of a vault that uses every form in it.

pub mod emit;
pub mod index;
pub mod lint;
pub mod note;
pub mod schema;
pub mod writer;
pub mod yaml;

pub use index::{BuildStats, Resolution, VaultError, VaultIndex};
pub use lint::{HierarchyRules, Problem, lint_content, lint_format, lint_hierarchy};
pub use note::{Link, LinkSource, Note, parse_note};
pub use schema::{Schema, lint_schema};
pub use writer::{VaultWriteError, VaultWriter, WriteStatus, WriterLimits};
pub use yaml::Value;
