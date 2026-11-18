//! Writing properties as YAML, the way generation 1 did (`yaml.safe_dump(props, sort_keys=False, allow_unicode=True,
//! width=1000)`), for the flat shape the vault format allows: a mapping of scalars and lists of scalars.
//!
//! Plain text stays plain; text that would read back as something else (`true`, `42`, `2026-01-01`, `null`, empty) or
//! that holds indicators, edge spaces, tabs or line breaks is quoted, single first, double when it holds characters a
//! single-quoted scalar cannot carry. The result is read back by [`crate::yaml::parse`] to the same values (a test
//! checks it), and by PyYAML to the same values (checked against generation 1 on 40 000 random documents).
//!
//! Differences from PyYAML, all harmless for reading back: a scalar is never folded at column 1000; text with the
//! Unicode line breaks (U+0085, U+2028, U+2029) is double-quoted with escapes, because PyYAML's single-quoted form reads
//! back as `\n`; text with Unicode white space at an edge is single-quoted; nested mappings and lists in lists are
//! refused (format rule 3: no nested objects).

use std::fmt;
use std::sync::LazyLock;

use regex::Regex;

use crate::yaml::{self, Value};

/// Why a property set cannot be written.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmitError(pub String);

impl fmt::Display for EmitError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for EmitError {}

static INT_LIKE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"^[-+]?(0b[01_]+|0[0-7_]+|0|[1-9][0-9_]*|0x[0-9a-fA-F_]+|[1-9][0-9_]*(:[0-5]?[0-9])+)$",
    )
    .expect("static pattern")
});
static FLOAT_SPECIAL: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^([-+]?\.(inf|Inf|INF)|\.(nan|NaN|NAN))$").expect("static pattern")
});

const WHITESPACE: &str = "\0 \t\r\n\u{85}\u{2028}\u{2029}";
const BREAKS: &str = "\n\u{85}\u{2028}\u{2029}";

struct Analysis {
    empty: bool,
    multiline: bool,
    allow_block_plain: bool,
    allow_single_quoted: bool,
}

fn is_ws(c: Option<&char>) -> bool {
    c.is_none_or(|c| WHITESPACE.contains(*c))
}

/// Port of PyYAML's `analyze_scalar` for block context with `allow_unicode`.
fn analyze(text: &str) -> Analysis {
    let chars: Vec<char> = text.chars().collect();
    if chars.is_empty() {
        return Analysis {
            empty: true,
            multiline: false,
            allow_block_plain: true,
            allow_single_quoted: true,
        };
    }
    let (mut block_ind, mut line_breaks, mut special) = (false, false, false);
    let (mut lead_space, mut lead_break, mut trail_space, mut trail_break) =
        (false, false, false, false);
    let (mut break_space, mut space_break) = (false, false);
    let (mut prev_space, mut prev_break) = (false, false);
    if text.starts_with("---") || text.starts_with("...") {
        block_ind = true;
    }
    let mut preceded_ws = true;
    let mut followed_ws = is_ws(chars.get(1));
    for (index, &ch) in chars.iter().enumerate() {
        if index == 0 {
            if "#,[]{}&*!|>'\"%@`".contains(ch) {
                block_ind = true;
            }
            if "?:".contains(ch) && followed_ws {
                block_ind = true;
            }
            if ch == '-' && followed_ws {
                block_ind = true;
            }
        } else {
            if ch == ':' && followed_ws {
                block_ind = true;
            }
            if ch == '#' && preceded_ws {
                block_ind = true;
            }
        }
        if BREAKS.contains(ch) {
            line_breaks = true;
        }
        let printable = ch == '\n' || ('\x20'..='\x7e').contains(&ch);
        if !printable {
            let unicode_ok = (ch == '\u{85}'
                || ('\u{a0}'..='\u{d7ff}').contains(&ch)
                || ('\u{e000}'..='\u{fffd}').contains(&ch)
                || ('\u{10000}'..'\u{10ffff}').contains(&ch))
                && ch != '\u{feff}';
            if !unicode_ok {
                special = true;
            }
        }
        if ch == ' ' {
            if index == 0 {
                lead_space = true;
            }
            if index == chars.len() - 1 {
                trail_space = true;
            }
            if prev_break {
                break_space = true;
            }
            prev_space = true;
            prev_break = false;
        } else if BREAKS.contains(ch) {
            if index == 0 {
                lead_break = true;
            }
            if index == chars.len() - 1 {
                trail_break = true;
            }
            if prev_space {
                space_break = true;
            }
            prev_space = false;
            prev_break = true;
        } else {
            prev_space = false;
            prev_break = false;
        }
        preceded_ws = WHITESPACE.contains(ch);
        followed_ws = chars.get(index + 2).is_none_or(|c| WHITESPACE.contains(*c));
        // `flow_indicators` only matters inside flow collections, which this writer never emits
    }
    let mut allow_block_plain = true;
    let mut allow_single_quoted = true;
    if lead_space || lead_break || trail_space || trail_break {
        allow_block_plain = false;
    }
    if break_space {
        allow_block_plain = false;
        allow_single_quoted = false;
    }
    if space_break || special {
        allow_block_plain = false;
        allow_single_quoted = false;
    }
    if line_breaks {
        allow_block_plain = false;
    }
    if block_ind {
        allow_block_plain = false;
    }
    Analysis {
        empty: false,
        multiline: line_breaks,
        allow_block_plain,
        allow_single_quoted,
    }
}

/// Would the plain text read back as a string (and not as null, bool, number, date, merge or value)?
fn reads_as_text(text: &str) -> bool {
    if text.is_empty() || text == "<<" || text == "=" {
        return false;
    }
    if INT_LIKE.is_match(text) || FLOAT_SPECIAL.is_match(text) {
        return false;
    }
    // Unicode white space at an edge is quoted: readers differ in whether they trim it
    let edge = |c: char| c.is_whitespace() && !c.is_ascii();
    if text.starts_with(edge) || text.ends_with(edge) {
        return false;
    }
    matches!(yaml::parse(text), Ok(Value::Str(s)) if s == text)
}

fn single_quoted(text: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    let mut out = String::from("'");
    let (mut spaces, mut breaks) = (false, false);
    let (mut start, mut end) = (0usize, 0usize);
    while end <= chars.len() {
        let ch = chars.get(end).copied();
        if spaces {
            if ch != Some(' ') {
                out.extend(&chars[start..end]);
                start = end;
            }
        } else if breaks {
            if ch.is_none_or(|c| !BREAKS.contains(c)) {
                if chars[start] == '\n' {
                    out.push('\n');
                }
                for &br in &chars[start..end] {
                    out.push(br);
                }
                out.push_str("  ");
                start = end;
            }
        } else if ch.is_none_or(|c| c == ' ' || BREAKS.contains(c) || c == '\'') {
            if start < end {
                out.extend(&chars[start..end]);
            }
            start = end;
        }
        if ch == Some('\'') {
            out.push_str("''");
            start = end + 1;
        }
        if let Some(c) = ch {
            spaces = c == ' ';
            breaks = BREAKS.contains(c);
        }
        end += 1;
    }
    out.push('\'');
    out
}

fn double_quoted(text: &str) -> String {
    let mut out = String::from("\"");
    for ch in text.chars() {
        let plain = !matches!(
            ch,
            '"' | '\\' | '\u{85}' | '\u{2028}' | '\u{2029}' | '\u{feff}'
        ) && (('\x20'..='\x7e').contains(&ch)
            || ('\u{a0}'..='\u{d7ff}').contains(&ch)
            || ('\u{e000}'..='\u{fffd}').contains(&ch));
        if plain {
            out.push(ch);
            continue;
        }
        let escaped = match ch {
            '\0' => "\\0".to_string(),
            '\x07' => "\\a".to_string(),
            '\x08' => "\\b".to_string(),
            '\t' => "\\t".to_string(),
            '\n' => "\\n".to_string(),
            '\x0b' => "\\v".to_string(),
            '\x0c' => "\\f".to_string(),
            '\r' => "\\r".to_string(),
            '\x1b' => "\\e".to_string(),
            '"' => "\\\"".to_string(),
            '\\' => "\\\\".to_string(),
            '\u{85}' => "\\N".to_string(),
            '\u{2028}' => "\\L".to_string(),
            '\u{2029}' => "\\P".to_string(),
            c if (c as u32) <= 0xff => format!("\\x{:02X}", c as u32),
            c if (c as u32) <= 0xffff => format!("\\u{:04X}", c as u32),
            c => format!("\\U{:08X}", c as u32),
        };
        out.push_str(&escaped);
    }
    out.push('"');
    out
}

/// One text scalar, in the style PyYAML picks. `key` is true for a mapping key.
fn text_scalar(text: &str, key: bool) -> Result<String, EmitError> {
    let a = analyze(text);
    if key && (a.empty || a.multiline || text.chars().count() >= 128) {
        return Err(EmitError(
            "property name must be one short line of text".to_string(),
        ));
    }
    if a.allow_block_plain && reads_as_text(text) {
        return Ok(text.to_string());
    }
    // the Unicode line breaks are written escaped: a reader folds a raw one into `\n`
    if a.allow_single_quoted && !text.contains(['\u{85}', '\u{2028}', '\u{2029}']) {
        return Ok(single_quoted(text));
    }
    Ok(double_quoted(text))
}

/// `repr(float)` of Python, lower-cased, with PyYAML's `.0` before the exponent.
fn float_scalar(x: f64) -> String {
    if x.is_nan() {
        return ".nan".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { ".inf" } else { "-.inf" }.to_string();
    }
    let sci = format!("{x:e}");
    let (mantissa, exp) = sci.split_once('e').expect("exponent form");
    let exp: i32 = exp.parse().expect("exponent");
    if (-4..16).contains(&exp) {
        let text = format!("{x}");
        return if text.contains('.') {
            text
        } else {
            format!("{text}.0")
        };
    }
    let mantissa = if mantissa.contains('.') {
        mantissa.to_string()
    } else {
        format!("{mantissa}.0")
    };
    format!(
        "{mantissa}e{}{:02}",
        if exp < 0 { '-' } else { '+' },
        exp.abs()
    )
}

fn scalar(value: &Value) -> Result<String, EmitError> {
    Ok(match value {
        Value::Null => "null".to_string(),
        Value::Bool(true) => "true".to_string(),
        Value::Bool(false) => "false".to_string(),
        Value::Int(n) => n.to_string(),
        Value::Float(x) => float_scalar(*x),
        Value::Str(s) => text_scalar(s, false)?,
        Value::Date(s) => s.clone(),
        Value::DateTime(s) => s.replacen('T', " ", 1),
        Value::List(_) | Value::Map(_) => {
            return Err(EmitError(
                "properties must not be nested (lists hold plain values only)".to_string(),
            ));
        }
    })
}

/// The properties as a YAML mapping, in the order given, without a trailing line break. No properties give `{}`.
pub fn dump_properties(props: &[(String, Value)]) -> Result<String, EmitError> {
    if props.is_empty() {
        return Ok("{}".to_string());
    }
    let mut seen = std::collections::BTreeSet::new();
    let mut lines: Vec<String> = Vec::new();
    for (name, value) in props {
        if !seen.insert(name.as_str()) {
            return Err(EmitError(format!("property {name} appears twice")));
        }
        let key = text_scalar(name, true)?;
        match value {
            Value::Map(_) => {
                return Err(EmitError(format!("property {name} must not be nested")));
            }
            Value::List(items) if items.is_empty() => lines.push(format!("{key}: []")),
            Value::List(items) => {
                lines.push(format!("{key}:"));
                for item in items {
                    lines.push(format!("- {}", scalar(item)?));
                }
            }
            other => lines.push(format!("{key}: {}", scalar(other)?)),
        }
    }
    Ok(lines.join("\n"))
}
