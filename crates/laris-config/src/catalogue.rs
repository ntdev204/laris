//! The string catalogue: every message the runtime itself produces, in English and Vietnamese.
//!
//! The two languages live in `catalogue/en.json` and `catalogue/vi.json`, nested as `{group: {name: text}}` and
//! addressed as `group.name`. Placeholders are `{name}`; `{{` and `}}` are literal braces. A test requires the
//! same keys and the same placeholders in both languages. A key missing in the chosen language falls back to
//! English, so a half-translated build still speaks.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::sync::OnceLock;

const EN: &str = include_str!("../catalogue/en.json");
const VI: &str = include_str!("../catalogue/vi.json");

/// Interface language of the catalogue.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "lowercase")]
pub enum Language {
    /// English.
    #[default]
    En,
    /// Vietnamese.
    Vi,
}

impl Language {
    /// Every language, in catalogue order.
    pub const ALL: [Language; 2] = [Language::En, Language::Vi];

    /// Two-letter code, as written in settings.
    pub fn code(self) -> &'static str {
        match self {
            Language::En => "en",
            Language::Vi => "vi",
        }
    }

    /// Reads a code or a locale name (`vi`, `VI`, `vi_VN`, `en-US`); `None` for anything else.
    pub fn parse(text: &str) -> Option<Self> {
        let head = text
            .trim()
            .split(['_', '-', '.'])
            .next()?
            .to_ascii_lowercase();
        Self::ALL.into_iter().find(|l| l.code() == head)
    }
}

/// Failure to produce a message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CatalogueError {
    /// The key is in no language.
    MissingKey(String),
    /// The text uses a placeholder the caller did not supply.
    MissingArg {
        /// Key of the message.
        key: String,
        /// Placeholder name.
        name: String,
    },
    /// The text has an unmatched brace.
    BadTemplate(String),
}

impl fmt::Display for CatalogueError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingKey(k) => write!(f, "missing message: {k}"),
            Self::MissingArg { key, name } => {
                write!(f, "message {key}: missing value for {{{name}}}")
            }
            Self::BadTemplate(k) => write!(f, "message {k}: unmatched brace"),
        }
    }
}

impl std::error::Error for CatalogueError {}

type Table = BTreeMap<String, String>;

fn flatten(prefix: &str, value: &Value, out: &mut Table) {
    match value {
        Value::Object(map) => {
            for (k, v) in map {
                let key = if prefix.is_empty() {
                    k.clone()
                } else {
                    format!("{prefix}.{k}")
                };
                flatten(&key, v, out);
            }
        }
        Value::String(text) => {
            out.insert(prefix.to_owned(), text.clone());
        }
        _ => {}
    }
}

fn parse_table(text: &str) -> Table {
    let mut out = Table::new();
    if let Ok(value) = serde_json::from_str::<Value>(text) {
        flatten("", &value, &mut out);
    }
    out
}

fn table(language: Language) -> &'static Table {
    static EN_TABLE: OnceLock<Table> = OnceLock::new();
    static VI_TABLE: OnceLock<Table> = OnceLock::new();
    match language {
        Language::En => EN_TABLE.get_or_init(|| parse_table(EN)),
        Language::Vi => VI_TABLE.get_or_init(|| parse_table(VI)),
    }
}

/// Names of the `{placeholders}` of a template, without escaped braces.
pub fn placeholders(template: &str) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    let mut chars = template.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '{' if chars.peek() == Some(&'{') => {
                chars.next();
            }
            '{' => {
                let name: String = chars.by_ref().take_while(|&c| c != '}').collect();
                out.insert(name);
            }
            _ => {}
        }
    }
    out
}

fn fill(key: &str, template: &str, args: &[(&str, &str)]) -> Result<String, CatalogueError> {
    let mut out = String::with_capacity(template.len());
    let mut chars = template.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '{' if chars.peek() == Some(&'{') => {
                chars.next();
                out.push('{');
            }
            '}' if chars.peek() == Some(&'}') => {
                chars.next();
                out.push('}');
            }
            '{' => {
                let mut name = String::new();
                loop {
                    match chars.next() {
                        Some('}') => break,
                        Some(ch) => name.push(ch),
                        None => return Err(CatalogueError::BadTemplate(key.to_owned())),
                    }
                }
                match args.iter().find(|(n, _)| *n == name) {
                    Some((_, value)) => out.push_str(value),
                    None => {
                        return Err(CatalogueError::MissingArg {
                            key: key.to_owned(),
                            name,
                        });
                    }
                }
            }
            '}' => return Err(CatalogueError::BadTemplate(key.to_owned())),
            _ => out.push(c),
        }
    }
    Ok(out)
}

/// The catalogue in one language, with English as the fallback.
#[derive(Debug, Clone, Copy)]
pub struct Catalogue {
    language: Language,
}

impl Catalogue {
    /// The catalogue of `language`.
    pub fn new(language: Language) -> Self {
        Self { language }
    }

    /// The English catalogue.
    pub fn english() -> Self {
        Self::new(Language::En)
    }

    /// The chosen language.
    pub fn language(&self) -> Language {
        self.language
    }

    /// Every key of `language`, sorted.
    pub fn keys(language: Language) -> impl Iterator<Item = &'static str> {
        table(language).keys().map(String::as_str)
    }

    /// The template of `key` in the chosen language, else in English.
    pub fn template(&self, key: &str) -> Option<&'static str> {
        table(self.language)
            .get(key)
            .or_else(|| table(Language::En).get(key))
            .map(String::as_str)
    }

    /// The message of `key` with its placeholders filled from `args`.
    pub fn get(&self, key: &str, args: &[(&str, &str)]) -> Result<String, CatalogueError> {
        let template = self
            .template(key)
            .ok_or_else(|| CatalogueError::MissingKey(key.to_owned()))?;
        fill(key, template, args)
    }
}
