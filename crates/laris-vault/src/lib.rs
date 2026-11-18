//! Obsidian format: parse, index, write, schema, lint (SR-L2).
//!
//! This part reads a vault: [`note::parse_note`] turns one Markdown file into properties, links, tags, headings and
//! block ids; [`index::VaultIndex`] resolves the links of a folder and answers backlinks and orphans, incrementally
//! and deterministically; [`yaml`] is the small reader for the properties, since no YAML crate is approved. The
//! writer, schema registry and lint follow in T127. The format is `docs/specifications/OBSIDIAN_VAULT_FORMAT.md`; the
//! golden fixture under `tests/golden/vault/` is the generation-1 index of a vault that uses every form in it.

pub mod index;
pub mod note;
pub mod yaml;

pub use index::{BuildStats, Resolution, VaultError, VaultIndex};
pub use note::{Link, LinkSource, Note, parse_note};
pub use yaml::Value;
