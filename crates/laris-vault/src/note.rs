//! Parse one note: properties (YAML front matter), wikilinks, embeds, Markdown links, tags, headings, block ids and a
//! content hash. The rules are those of `docs/specifications/OBSIDIAN_VAULT_FORMAT.md`.

use std::collections::BTreeSet;
use std::sync::OnceLock;

use regex::{Captures, Regex};
use serde_json::{Map, Number, Value as Json, json};
use sha2::{Digest, Sha256};

use crate::yaml::{self, Value};

/// Longest front matter that is read, in characters.
pub const MAX_FRONT_MATTER_CHARS: usize = 20000;
/// Deepest nesting of properties that is accepted.
pub const MAX_YAML_DEPTH: usize = 12;
/// Characters that break links or file names (`safe_title` in the writer replaces them).
pub const FORBIDDEN_NAME_CHARS: &str = "#|^:%[]\\/\"<>?*";

/// Error texts a note can carry. Fixed strings: the index and the lint compare them.
pub mod errors {
    /// Front matter longer than [`super::MAX_FRONT_MATTER_CHARS`].
    pub const TOO_LARGE: &str = "properties are too large";
    /// YAML anchors or aliases.
    pub const ANCHORS: &str = "properties must not use YAML anchors or aliases";
    /// The front matter does not parse.
    pub const INVALID: &str = "properties are not valid YAML";
    /// Nesting deeper than [`super::MAX_YAML_DEPTH`].
    pub const TOO_DEEP: &str = "properties are nested too deeply";
    /// The front matter is not a mapping.
    pub const NOT_A_MAPPING: &str = "properties must be a mapping";
}

/// Where a link was written.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum LinkSource {
    /// In the text of the note.
    Body,
    /// In a property value.
    Property,
}

impl LinkSource {
    /// `body` or `property`.
    pub fn as_str(self) -> &'static str {
        match self {
            LinkSource::Body => "body",
            LinkSource::Property => "property",
        }
    }
}

/// One link or embed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Link {
    /// Note name or path as written, without heading or alias.
    pub target: String,
    /// Text after `#` (a heading, or `^id` for a block).
    pub heading: String,
    /// Text after `|`.
    pub alias: String,
    /// `![[...]]`.
    pub embed: bool,
    /// Body or property.
    pub source: LinkSource,
    /// The property name when the link sits in a property.
    pub prop: String,
}

impl Link {
    /// A plain link to `target`.
    pub fn to(target: &str) -> Link {
        Link {
            target: target.to_string(),
            heading: String::new(),
            alias: String::new(),
            embed: false,
            source: LinkSource::Body,
            prop: String::new(),
        }
    }
}

/// A parsed note.
#[derive(Debug, Clone, PartialEq)]
pub struct Note {
    /// Vault-relative, forward slashes.
    pub path: String,
    /// The file stem: the note's name in links.
    pub title: String,
    /// Properties in source order; empty when there are none or they could not be read.
    pub props: Vec<(String, Value)>,
    /// The text after the front matter.
    pub body: String,
    /// Property links first, then body links in order of appearance, then Markdown links.
    pub links: Vec<Link>,
    /// Inline tags and the `tags` property, without the leading `#`.
    pub tags: BTreeSet<String>,
    /// Heading texts in order.
    pub headings: Vec<String>,
    /// Block ids (`^id`) defined in the body, sorted.
    pub blocks: Vec<String>,
    /// SHA-256 of the note text (line endings as `\n`).
    pub sha256: String,
    /// Problems with the properties; see [`errors`].
    pub errors: Vec<String>,
}

impl Note {
    /// The value of a property.
    pub fn prop(&self, name: &str) -> Option<&Value> {
        self.props.iter().find(|(k, _)| k == name).map(|(_, v)| v)
    }

    /// A property as a list of text: the items of a list, or the single value; empty when absent or null.
    pub fn prop_list(&self, name: &str) -> Vec<String> {
        match self.prop(name) {
            None | Some(Value::Null) => Vec::new(),
            Some(Value::List(items)) => items.iter().map(Value::py_str).collect(),
            Some(other) => vec![other.py_str()],
        }
    }

    /// The JSON form used by the index export and the cache. Dates are `{"__date__": ...}` and
    /// `{"__datetime__": ...}`.
    pub fn to_json(&self) -> Json {
        let mut props = Map::new();
        for (k, v) in &self.props {
            props.insert(k.clone(), value_to_json(v));
        }
        let links: Vec<Json> = self
            .links
            .iter()
            .map(|l| {
                json!([
                    l.target,
                    l.heading,
                    l.alias,
                    l.embed,
                    l.source.as_str(),
                    l.prop
                ])
            })
            .collect();
        json!({
            "path": self.path,
            "title": self.title,
            "props": props,
            "body": self.body,
            "links": links,
            "tags": self.tags.iter().collect::<Vec<_>>(),
            "headings": self.headings,
            "blocks": self.blocks,
            "sha256": self.sha256,
            "errors": self.errors,
        })
    }

    /// The inverse of [`Note::to_json`]; `None` when the shape is wrong.
    pub fn from_json(data: &Json) -> Option<Note> {
        let text = |k: &str| data.get(k)?.as_str().map(str::to_string);
        let strings = |k: &str| -> Option<Vec<String>> {
            data.get(k)?
                .as_array()?
                .iter()
                .map(|v| v.as_str().map(str::to_string))
                .collect()
        };
        let mut props = Vec::new();
        for (k, v) in data.get("props")?.as_object()? {
            props.push((k.clone(), value_from_json(v)?));
        }
        let mut links = Vec::new();
        for row in data.get("links")?.as_array()? {
            let row = row.as_array()?;
            if row.len() != 6 {
                return None;
            }
            links.push(Link {
                target: row[0].as_str()?.to_string(),
                heading: row[1].as_str()?.to_string(),
                alias: row[2].as_str()?.to_string(),
                embed: row[3].as_bool()?,
                source: match row[4].as_str()? {
                    "body" => LinkSource::Body,
                    "property" => LinkSource::Property,
                    _ => return None,
                },
                prop: row[5].as_str()?.to_string(),
            });
        }
        Some(Note {
            path: text("path")?,
            title: text("title")?,
            props,
            body: text("body")?,
            links,
            tags: strings("tags")?.into_iter().collect(),
            headings: strings("headings")?,
            blocks: strings("blocks")?,
            sha256: text("sha256")?,
            errors: strings("errors")?,
        })
    }
}

/// The JSON form of a property value (dates as `{"__date__": ...}`), as the index export writes it.
pub fn value_to_json(v: &Value) -> Json {
    match v {
        Value::Null => Json::Null,
        Value::Bool(b) => Json::Bool(*b),
        Value::Int(n) => Json::Number((*n).into()),
        Value::Float(x) => Number::from_f64(*x).map_or(Json::Null, Json::Number),
        Value::Str(s) => Json::String(s.clone()),
        Value::Date(s) => json!({ "__date__": s }),
        Value::DateTime(s) => json!({ "__datetime__": s }),
        Value::List(items) => Json::Array(items.iter().map(value_to_json).collect()),
        Value::Map(entries) => {
            let mut m = Map::new();
            for (k, v) in entries {
                m.insert(k.clone(), value_to_json(v));
            }
            Json::Object(m)
        }
    }
}

/// The property value a [`value_to_json`] form stands for (`None` for a shape no property has).
pub fn value_from_json(j: &Json) -> Option<Value> {
    Some(match j {
        Json::Null => Value::Null,
        Json::Bool(b) => Value::Bool(*b),
        Json::Number(n) => match n.as_i64() {
            Some(i) => Value::Int(i),
            None => Value::Float(n.as_f64()?),
        },
        Json::String(s) => Value::Str(s.clone()),
        Json::Array(items) => {
            Value::List(items.iter().map(value_from_json).collect::<Option<_>>()?)
        }
        Json::Object(m) => {
            if m.len() == 1 {
                if let Some(s) = m.get("__date__") {
                    return Some(Value::Date(s.as_str()?.to_string()));
                }
                if let Some(s) = m.get("__datetime__") {
                    return Some(Value::DateTime(s.as_str()?.to_string()));
                }
            }
            let mut entries = Vec::new();
            for (k, v) in m {
                entries.push((k.clone(), value_from_json(v)?));
            }
            Value::Map(entries)
        }
    })
}

struct Patterns {
    alias: Regex,
    fence: Regex,
    inline_code: Regex,
    comment: Regex,
    wikilink: Regex,
    tag: Regex,
    md_link: Regex,
    block_id: Regex,
    heading: Regex,
}

fn patterns() -> &'static Patterns {
    static P: OnceLock<Patterns> = OnceLock::new();
    P.get_or_init(|| {
        let re = |p: &str| Regex::new(p).expect("fixed pattern");
        Patterns {
            alias: re(r"(?m)(?:^|:\s+|-\s+|[\[,{]\s*)[&*][A-Za-z0-9_-]+"),
            fence: re(r"(?s)```.*?```|~~~.*?~~~"),
            inline_code: re(r"`[^`\n]*`"),
            comment: re(r"(?s)%%.*?%%"),
            wikilink: re(r"(!?)\[\[([^\[\]|#^]*)(?:#([^\[\]|]*))?(?:\|([^\[\]]*))?\]\]"),
            tag: re(r"#([A-Za-z][\w/-]*)"),
            md_link: re(r"\[[^\]]*\]\(([^)\s]+\.md)(?:#[^)]*)?\)"),
            block_id: re(r"(?m)(?:^|\s)\^([A-Za-z0-9-]+)\s*$"),
            heading: re(r"(?m)^(#{1,6})\s+(.*?)\s*#*\s*$"),
        }
    })
}

/// Python's `str.strip()` on a front matter line.
fn is_fence(line: &str, closing: bool) -> bool {
    let t = line.trim();
    t == "---" || (closing && t == "...")
}

/// `(properties text or None, body)`. Front matter must open on the first line.
pub fn split_front_matter(text: &str) -> (Option<String>, String) {
    if !text.starts_with("---") {
        return (None, text.to_string());
    }
    let lines: Vec<&str> = text.split('\n').collect();
    if !is_fence(lines[0], false) {
        return (None, text.to_string());
    }
    for i in 1..lines.len() {
        if is_fence(lines[i], true) {
            let raw = lines[1..i].join("\n");
            let body = lines[i + 1..]
                .join("\n")
                .trim_start_matches('\n')
                .to_string();
            return (Some(raw), body);
        }
    }
    (None, text.to_string())
}

/// The text with comments, fenced code and inline code blanked out, in that order.
pub fn strip_code(text: &str) -> String {
    let p = patterns();
    let text = p.comment.replace_all(text, " ");
    let text = p.fence.replace_all(&text, " ");
    p.inline_code.replace_all(&text, " ").into_owned()
}

/// All matches of `re` in `text`, left to right, skipping a match for which `reject(previous char)` is true and
/// retrying one character later (the behaviour of a negative look-behind, which the regex engine does not have).
fn scan<'t>(re: &Regex, text: &'t str, reject: impl Fn(Option<char>) -> bool) -> Vec<Captures<'t>> {
    let mut found = Vec::new();
    let mut pos = 0;
    while pos <= text.len() {
        let Some(c) = re.captures_at(text, pos) else {
            break;
        };
        let m = c.get(0).expect("group 0");
        let step = |at: usize| at + text[at..].chars().next().map_or(1, char::len_utf8);
        if reject(text[..m.start()].chars().next_back()) {
            pos = step(m.start());
            continue;
        }
        pos = if m.end() > m.start() {
            m.end()
        } else {
            step(m.end())
        };
        found.push(c);
    }
    found
}

/// Wikilinks and embeds in `text`.
pub fn wikilinks(text: &str, source: LinkSource, prop: &str) -> Vec<Link> {
    let mut found = Vec::new();
    for c in patterns().wikilink.captures_iter(text) {
        let group = |i: usize| c.get(i).map_or("", |m| m.as_str());
        let target = group(2).trim();
        let heading = group(3).trim();
        if !target.is_empty() || !heading.is_empty() {
            found.push(Link {
                target: target.to_string(),
                heading: heading.to_string(),
                alias: group(4).trim().to_string(),
                embed: !group(1).is_empty(),
                source,
                prop: prop.to_string(),
            });
        }
    }
    found
}

fn property_links(props: &[(String, Value)]) -> Vec<Link> {
    let mut found = Vec::new();
    for (name, value) in props {
        let items: &[Value] = match value {
            Value::List(items) => items,
            other => std::slice::from_ref(other),
        };
        for item in items {
            if let Value::Str(s) = item {
                found.extend(wikilinks(s, LinkSource::Property, name));
            }
        }
    }
    found
}

fn depth(v: &Value, level: usize) -> usize {
    if level > MAX_YAML_DEPTH {
        return level;
    }
    match v {
        Value::Map(entries) => entries
            .iter()
            .map(|(_, v)| depth(v, level + 1))
            .max()
            .unwrap_or(level + 1),
        Value::List(items) => items
            .iter()
            .map(|v| depth(v, level + 1))
            .max()
            .unwrap_or(level + 1),
        _ => level,
    }
}

/// Parse one note. `path` is vault-relative with forward slashes; `text` has `\n` line endings.
pub fn parse_note(text: &str, path: &str) -> Note {
    let p = patterns();
    let stem = path.rsplit('/').next().unwrap_or(path);
    let title = if stem.to_lowercase().ends_with(".md") {
        &stem[..stem.len() - 3]
    } else {
        stem
    };
    let (raw, body) = split_front_matter(text);
    let mut props: Vec<(String, Value)> = Vec::new();
    let mut errors: Vec<String> = Vec::new();
    if let Some(raw) = raw {
        let mut loaded = Value::Map(Vec::new());
        if raw.chars().count() > MAX_FRONT_MATTER_CHARS {
            errors.push(errors::TOO_LARGE.into());
        } else if p.alias.is_match(&raw) {
            errors.push(errors::ANCHORS.into());
        } else {
            if !raw.trim().is_empty() {
                match yaml::parse(&raw) {
                    Ok(v) => loaded = v,
                    Err(_) => errors.push(errors::INVALID.into()),
                }
            }
            if errors.is_empty() && depth(&loaded, 0) > MAX_YAML_DEPTH && !is_empty_value(&loaded) {
                loaded = Value::Map(Vec::new());
                errors.push(errors::TOO_DEEP.into());
            }
        }
        if errors.is_empty() {
            match loaded {
                Value::Map(entries) => props = entries,
                _ => errors.push(errors::NOT_A_MAPPING.into()),
            }
        }
    }
    let clean = strip_code(&body);
    let mut links = property_links(&props);
    links.extend(wikilinks(&clean, LinkSource::Body, ""));
    for c in scan(&p.md_link, &clean, |prev| prev == Some('!')) {
        let target = c[1].strip_suffix(".md").unwrap_or(&c[1]);
        links.push(Link::to(target.rsplit('/').next().unwrap_or(target)));
    }
    let mut tags: BTreeSet<String> = scan(&p.tag, &clean, |prev| {
        prev.is_some_and(|c| c.is_alphanumeric() || c == '_' || c == '#' || c == '/' || c == '&')
    })
    .iter()
    .map(|c| c[1].to_string())
    .collect();
    let raw_tags: Vec<&Value> = match props.iter().find(|(k, _)| k == "tags") {
        None => Vec::new(),
        Some((_, Value::List(items))) => items.iter().collect(),
        Some((_, other)) => vec![other],
    };
    for t in raw_tags {
        if let Value::Str(s) = t
            && !s.is_empty()
        {
            tags.insert(s.trim_start_matches('#').to_string());
        }
    }
    let headings = p
        .heading
        .captures_iter(&strip_code(&body))
        .map(|c| c[2].to_string())
        .collect();
    let blocks: BTreeSet<String> = p
        .block_id
        .captures_iter(&clean)
        .map(|c| c[1].to_string())
        .collect();
    Note {
        path: path.to_string(),
        title: title.to_string(),
        props,
        body,
        links,
        tags,
        headings,
        blocks: blocks.into_iter().collect(),
        sha256: sha256_hex(text),
        errors,
    }
}

/// A falsy value (empty, zero, false): it skips the depth check.
fn is_empty_value(v: &Value) -> bool {
    match v {
        Value::Null => true,
        Value::Bool(b) => !b,
        Value::Int(n) => *n == 0,
        Value::Float(x) => *x == 0.0,
        Value::Str(s) => s.is_empty(),
        Value::List(l) => l.is_empty(),
        Value::Map(m) => m.is_empty(),
        _ => false,
    }
}

/// Lower-case hexadecimal SHA-256 of the text as UTF-8.
pub fn sha256_hex(text: &str) -> String {
    let digest = Sha256::digest(text.as_bytes());
    digest.iter().map(|b| format!("{b:02x}")).collect()
}

/// The note name inside a `[[...]]` property value, or the value itself, trimmed.
pub fn link_name(value: &str) -> String {
    match wikilinks(value, LinkSource::Body, "").into_iter().next() {
        Some(l) => l.target,
        None => value.trim().to_string(),
    }
}

/// `[[title]]`.
pub fn wikilink(title: &str) -> String {
    format!("[[{title}]]")
}
