//! Reader for the YAML subset that note properties use.
//!
//! No YAML crate is approved (ADR-021), so this is a small, strict reader written to give the same values as the
//! generation-1 reader (PyYAML `safe_load`) on everything LARIS writes or a person plausibly types: block mappings
//! and sequences (a sequence may sit at the indent of its key, as the generation-1 writer emits it), flow
//! collections, plain, single- and double-quoted scalars that continue over lines, `|` and `>` block scalars, and
//! comments. Plain scalars resolve as in YAML 1.1 (`yes` and `off` are booleans, `~` is null, `2026-11-13` is a date).
//!
//! What it does not read is an error, never a guess: tags (`!!str`), explicit keys (`? `), merge keys, an explicit
//! block-scalar indent digit, and a flow pair inside a sequence (`[a: 1]`). Three scalar forms differ from PyYAML on
//! purpose and stay text: sexagesimal numbers (`1:30`), `.inf` and `.nan`, and integers beyond 64 bits. Anchors and
//! aliases are refused earlier, by the note parser.

use std::fmt;

/// Deepest nesting the reader follows; deeper input is an error (and `note` limits it far lower).
const MAX_NESTING: usize = 200;

/// One property value.
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    /// `null`, `~` or an empty value.
    Null,
    /// A YAML 1.1 boolean.
    Bool(bool),
    /// An integer that fits 64 bits.
    Int(i64),
    /// A finite float.
    Float(f64),
    /// Text, quoted or plain.
    Str(String),
    /// A calendar date, as `YYYY-MM-DD`.
    Date(String),
    /// A date and time, as the ISO 8601 text `datetime.isoformat` gives (`T` separator, `+00:00` offset).
    DateTime(String),
    /// A sequence.
    List(Vec<Value>),
    /// A mapping, in source order, keys as text.
    Map(Vec<(String, Value)>),
}

/// Why a document could not be read.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct YamlError {
    /// A short description, for tests and logs; the note parser reports its own fixed message.
    pub message: String,
}

impl fmt::Display for YamlError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "invalid YAML: {}", self.message)
    }
}

impl std::error::Error for YamlError {}

type R<T> = Result<T, YamlError>;

fn err<T>(message: &str) -> R<T> {
    Err(YamlError {
        message: message.to_string(),
    })
}

impl Value {
    /// `str(value)` as Python prints it: `True`, `None`, `2026-11-13 10:00:00+00:00`, `['a', 'b']`.
    pub fn py_str(&self) -> String {
        match self {
            Value::Str(s) => s.clone(),
            Value::DateTime(s) => s.replacen('T', " ", 1),
            other => other.py_repr(),
        }
    }

    /// `repr(value)` as Python prints it.
    pub fn py_repr(&self) -> String {
        match self {
            Value::Null => "None".to_string(),
            Value::Bool(true) => "True".to_string(),
            Value::Bool(false) => "False".to_string(),
            Value::Int(n) => n.to_string(),
            Value::Float(x) => format!("{x:?}"),
            Value::Str(s) => py_quote(s),
            Value::Date(s) => s.clone(),
            Value::DateTime(s) => s.replacen('T', " ", 1),
            Value::List(items) => {
                let inner: Vec<String> = items.iter().map(Value::py_repr).collect();
                format!("[{}]", inner.join(", "))
            }
            Value::Map(entries) => {
                let inner: Vec<String> = entries
                    .iter()
                    .map(|(k, v)| format!("{}: {}", py_quote(k), v.py_repr()))
                    .collect();
                format!("{{{}}}", inner.join(", "))
            }
        }
    }
}

/// Python's choice of quote for a string repr (escapes limited to the common ones).
fn py_quote(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// Read a document. Empty or comment-only input is [`Value::Null`].
pub fn parse(text: &str) -> R<Value> {
    let mut lines = Vec::new();
    for raw in text.split('\n') {
        let raw = raw.strip_suffix('\r').unwrap_or(raw);
        if raw.trim().is_empty() {
            lines.push(Line {
                indent: 0,
                text: String::new(),
                blank: true,
                tab: false,
            });
            continue;
        }
        let body = raw.trim_start_matches(' ');
        if body.starts_with('\t') {
            return err("tab in indentation");
        }
        lines.push(Line {
            indent: raw.len() - body.len(),
            text: body.trim_end_matches(' ').to_string(),
            blank: false,
            tab: has_loose_tab(body),
        });
    }
    let mut p = Parser {
        lines,
        pos: 0,
        final_break: text.ends_with('\n'),
    };
    let Some(first) = p.next_sig() else {
        return Ok(Value::Null);
    };
    let indent = p.lines[first].indent;
    let value = p.parse_block(indent, 0)?;
    if p.next_sig().is_some() {
        return err("content after the document");
    }
    Ok(value)
}

struct Line {
    indent: usize,
    text: String,
    blank: bool,
    /// A tab outside quotes and comments: PyYAML refuses it wherever it is not inside a block scalar.
    tab: bool,
}

struct Parser {
    lines: Vec<Line>,
    pos: usize,
    /// The text ended with a line break, so its last line is an empty artifact of the split.
    final_break: bool,
}

/// A tab that is neither inside quotes nor in a comment.
fn has_loose_tab(text: &str) -> bool {
    let bytes = text.as_bytes();
    let mut quote: Option<u8> = None;
    for (i, &c) in bytes.iter().enumerate() {
        match quote {
            Some(q) => {
                if c == q && !(q == b'"' && i > 0 && bytes[i - 1] == b'\\') {
                    quote = None;
                }
            }
            None => match c {
                b'\t' => return true,
                b'#' if i == 0 || bytes[i - 1] == b' ' => return false,
                b'"' | b'\''
                    if i == 0 || matches!(bytes[i - 1], b' ' | b'[' | b'{' | b',' | b':') =>
                {
                    quote = Some(c)
                }
                _ => {}
            },
        }
    }
    false
}

fn is_dash(text: &str) -> bool {
    text == "-" || text.starts_with("- ")
}

fn is_comment_or_empty(rest: &str) -> bool {
    rest.is_empty() || rest.starts_with('#')
}

/// `text` without a trailing ` # comment`, ignoring `#` inside quotes.
fn strip_comment(text: &str) -> &str {
    let bytes = text.as_bytes();
    let mut quote: Option<u8> = None;
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i];
        match quote {
            Some(b'"') => {
                if c == b'\\' {
                    i += 1;
                } else if c == b'"' {
                    quote = None;
                }
            }
            Some(_) => {
                if c == b'\'' {
                    quote = None;
                }
            }
            None => {
                if (c == b'"' || c == b'\'')
                    && (i == 0
                        || bytes[i - 1] == b' '
                        || bytes[i - 1] == b'['
                        || bytes[i - 1] == b'{'
                        || bytes[i - 1] == b',')
                {
                    quote = Some(c);
                } else if c == b'#' && (i == 0 || bytes[i - 1] == b' ') {
                    return text[..i].trim_end();
                }
            }
        }
        i += 1;
    }
    text.trim_end()
}

impl Parser {
    /// Index of the next line that is neither blank nor a comment; blank and comment lines before it are skipped.
    fn next_sig(&mut self) -> Option<usize> {
        while self.pos < self.lines.len() {
            let l = &self.lines[self.pos];
            if l.blank || l.text.starts_with('#') {
                self.pos += 1;
            } else {
                return Some(self.pos);
            }
        }
        None
    }

    fn parse_block(&mut self, indent: usize, depth: usize) -> R<Value> {
        if depth > MAX_NESTING {
            return err("nested too deeply");
        }
        let i = self.next_sig().ok_or(YamlError {
            message: "missing node".into(),
        })?;
        let text = self.lines[i].text.clone();
        if self.lines[i].tab {
            return err("tab outside quotes");
        }
        if is_dash(&text) {
            self.parse_seq(indent, depth)
        } else if split_entry(&text)?.is_some() {
            self.parse_map(indent, depth)
        } else {
            self.pos = i + 1;
            self.parse_value(indent as isize - 1, &text, false, depth + 1)
        }
    }

    fn parse_map(&mut self, indent: usize, depth: usize) -> R<Value> {
        let mut entries: Vec<(String, Value)> = Vec::new();
        while let Some(i) = self.next_sig() {
            let ind = self.lines[i].indent;
            if ind < indent {
                break;
            }
            if ind > indent {
                return err("bad indentation");
            }
            let text = self.lines[i].text.clone();
            if self.lines[i].tab {
                return err("tab outside quotes");
            }
            if is_dash(&text) {
                return err("sequence entry inside a mapping");
            }
            let Some((key, rest)) = split_entry(&text)? else {
                return err("expected a key");
            };
            self.pos = i + 1;
            let value = self.parse_value(indent as isize, &rest, true, depth + 1)?;
            match entries.iter_mut().find(|(k, _)| *k == key) {
                Some(slot) => slot.1 = value, // a repeated key keeps its place, last value wins
                None => entries.push((key, value)),
            }
        }
        Ok(Value::Map(entries))
    }

    fn parse_seq(&mut self, indent: usize, depth: usize) -> R<Value> {
        let mut items = Vec::new();
        while let Some(i) = self.next_sig() {
            let ind = self.lines[i].indent;
            if ind < indent {
                break;
            }
            if ind > indent {
                return err("bad indentation");
            }
            let text = self.lines[i].text.clone();
            if self.lines[i].tab {
                return err("tab outside quotes");
            }
            if !is_dash(&text) {
                break;
            }
            self.pos = i + 1;
            let after = &text[1..];
            let rest = after.trim_start_matches(' ');
            let rest_col = indent + 1 + (after.len() - rest.len());
            if is_comment_or_empty(rest) {
                items.push(self.parse_value(indent as isize, "", false, depth + 1)?);
            } else if is_dash(rest) || split_entry(rest)?.is_some() {
                // `- key: v` and `- - x`: the rest of the line opens a block at its own column
                self.lines[i] = Line {
                    indent: rest_col,
                    text: rest.to_string(),
                    blank: false,
                    tab: false,
                };
                self.pos = i;
                items.push(self.parse_block(rest_col, depth + 1)?);
            } else {
                items.push(self.parse_value(indent as isize, rest, false, depth + 1)?);
            }
        }
        Ok(Value::List(items))
    }

    /// The value written after `key:` or `- ` (`rest`, already cut from its line), or below it when `rest` is empty.
    /// `parent` is the indent of the key or dash; anything deeper belongs to the value.
    fn parse_value(&mut self, parent: isize, rest: &str, in_map: bool, depth: usize) -> R<Value> {
        if depth > MAX_NESTING {
            return err("nested too deeply");
        }
        let rest = rest.trim();
        if is_comment_or_empty(rest) {
            if let Some(i) = self.next_sig() {
                let ind = self.lines[i].indent;
                let text = self.lines[i].text.clone();
                if ind as isize > parent {
                    return self.parse_block(ind, depth + 1);
                }
                if in_map && ind as isize == parent && is_dash(&text) {
                    return self.parse_seq(ind, depth + 1);
                }
            }
            return Ok(Value::Null);
        }
        let first = rest.as_bytes()[0];
        match first {
            b'|' | b'>' => self.block_scalar(parent, rest),
            b'[' | b'{' => {
                let mut buf = strip_comment(rest).to_string();
                while !flow_balanced(&buf) {
                    let Some(line) = self.lines.get(self.pos) else {
                        return err("unterminated flow collection");
                    };
                    self.pos += 1;
                    if line.tab {
                        return err("tab outside quotes");
                    }
                    if !line.blank {
                        buf.push(' ');
                        buf.push_str(strip_comment(&line.text));
                    }
                }
                let mut f = Flow { s: &buf, i: 0 };
                let value = f.value(0)?;
                f.skip_ws();
                if f.i != buf.len() {
                    return err("content after a flow collection");
                }
                Ok(value)
            }
            b'"' | b'\'' => {
                let mut buf = rest.to_string();
                let mut pending = 0usize;
                loop {
                    match parse_quoted(&buf) {
                        Ok((value, used)) => {
                            let tail = buf[used..].trim();
                            if !is_comment_or_empty(tail) {
                                return err("content after a quoted scalar");
                            }
                            return Ok(Value::Str(value));
                        }
                        Err(Quoted::Unterminated) => {
                            let Some(line) = self.lines.get(self.pos) else {
                                return err("unterminated quoted scalar");
                            };
                            self.pos += 1;
                            if line.blank {
                                pending += 1;
                            } else {
                                if pending > 0 {
                                    buf.push_str(&"\n".repeat(pending));
                                } else {
                                    buf.push(' ');
                                }
                                pending = 0;
                                buf.push_str(&line.text);
                            }
                        }
                        Err(Quoted::Bad) => return err("bad escape in a quoted scalar"),
                    }
                }
            }
            b'&' | b'*' | b'!' | b'%' | b'@' | b'`' => err("unsupported scalar indicator"),
            _ => {
                if is_dash(rest)
                    || rest.starts_with("? ")
                    || rest.starts_with(": ")
                    || matches!(first, b',' | b']' | b'}')
                {
                    return err("indicator where a scalar starts");
                }
                let mut text = strip_comment(rest).to_string();
                let mut blanks = 0usize;
                let mut look = self.pos;
                while look < self.lines.len() {
                    let l = &self.lines[look];
                    if l.blank {
                        blanks += 1;
                        look += 1;
                        continue;
                    }
                    if l.text.starts_with('#') || (l.indent as isize) <= parent {
                        break;
                    }
                    if l.tab {
                        return err("tab outside quotes");
                    }
                    if split_entry(&l.text)?.is_some() {
                        return err("mapping value where a scalar continues");
                    }
                    let piece = strip_comment(&l.text);
                    if blanks > 0 {
                        text.push_str(&"\n".repeat(blanks));
                    } else {
                        text.push(' ');
                    }
                    text.push_str(piece);
                    blanks = 0;
                    look += 1;
                    self.pos = look;
                }
                if text.contains(": ") || text.ends_with(':') {
                    return err("mapping value where a scalar is expected");
                }
                resolve_plain(&text)
            }
        }
    }

    fn block_scalar(&mut self, parent: isize, header: &str) -> R<Value> {
        let folded = header.starts_with('>');
        let mut chomp = '\0';
        let mut tail = &header[1..];
        for _ in 0..2 {
            match tail.chars().next() {
                Some(c @ ('+' | '-')) if chomp == '\0' => {
                    chomp = c;
                    tail = &tail[1..];
                }
                Some('1'..='9') => return err("explicit block scalar indent"),
                _ => {}
            }
        }
        let tail = tail.trim();
        if !is_comment_or_empty(tail) {
            return err("content after a block scalar header");
        }
        let mut content: Vec<(usize, String)> = Vec::new(); // (indent, text); blank lines have empty text
        let mut base: Option<usize> = None;
        while self.pos < self.lines.len() {
            let l = &self.lines[self.pos];
            if l.blank {
                content.push((0, String::new()));
                self.pos += 1;
                continue;
            }
            if (l.indent as isize) <= parent {
                break;
            }
            let b = *base.get_or_insert(l.indent);
            if l.indent < b {
                break;
            }
            content.push((l.indent, l.text.clone()));
            self.pos += 1;
        }
        let base = base.unwrap_or(0);
        let at_end = self.pos >= self.lines.len();
        let mut trailing: usize = 0;
        while content.last().is_some_and(|(_, t)| t.is_empty()) {
            content.pop();
            trailing += 1;
        }
        let lines: Vec<String> = content
            .into_iter()
            .map(|(ind, t)| {
                if t.is_empty() {
                    t
                } else {
                    format!("{}{}", " ".repeat(ind - base), t)
                }
            })
            .collect();
        if at_end && self.final_break {
            trailing = trailing.saturating_sub(1); // the empty last line is only the end of the last break
        }
        let unterminated = at_end && !self.final_break && trailing == 0;
        let mut out = if folded {
            fold(&lines)
        } else {
            lines.join("\n")
        };
        if unterminated {
            // the last line has no line break after it, so there is nothing for clip or keep to keep
        } else if !lines.is_empty() {
            match chomp {
                '-' => {}
                '+' => {
                    out.push('\n');
                    out.push_str(&"\n".repeat(trailing));
                }
                _ => out.push('\n'),
            }
        } else if chomp == '+' {
            out.push_str(&"\n".repeat(trailing));
        }
        Ok(Value::Str(out))
    }
}

/// Folded scalar: single line breaks between ordinary lines become spaces, blank lines become breaks, and lines
/// that start with a space keep their breaks.
fn fold(lines: &[String]) -> String {
    let mut out = String::new();
    let mut previous: Option<&String> = None;
    let mut blanks = 0;
    for line in lines {
        if line.is_empty() {
            blanks += 1;
            continue;
        }
        if let Some(prev) = previous {
            let more = |s: &str| s.starts_with(' ') || s.starts_with('\t');
            if more(prev) || more(line) {
                out.push('\n');
                out.push_str(&"\n".repeat(blanks));
            } else if blanks > 0 {
                out.push_str(&"\n".repeat(blanks));
            } else {
                out.push(' ');
            }
        } else {
            out.push_str(&"\n".repeat(blanks));
        }
        out.push_str(line);
        previous = Some(line);
        blanks = 0;
    }
    out
}

/// Split `key: rest` on the first `:` that is followed by a space or the end; `None` when the line is not an entry.
fn split_entry(text: &str) -> R<Option<(String, String)>> {
    let first = text.as_bytes()[0];
    if first == b'"' || first == b'\'' {
        return Ok(match parse_quoted(text) {
            Ok((key, used)) => {
                let after = text[used..].trim_start_matches(' ');
                if after == ":" || after.starts_with(": ") {
                    Some((key, after[1..].trim_start().to_string()))
                } else {
                    None
                }
            }
            Err(_) => None,
        });
    }
    if matches!(
        first,
        b'[' | b'{' | b'&' | b'*' | b'!' | b'|' | b'>' | b'%' | b'@' | b'`' | b'#'
    ) {
        return Ok(None);
    }
    if text.starts_with("? ") {
        return err("explicit keys");
    }
    let bytes = text.as_bytes();
    for i in 0..bytes.len() {
        match bytes[i] {
            b'#' if i > 0 && bytes[i - 1] == b' ' => return Ok(None),
            b':' if i + 1 == bytes.len() || bytes[i + 1] == b' ' => {
                let key = text[..i].trim_end();
                if key.is_empty() {
                    return Ok(None);
                }
                let key = key_string(&resolve_plain(key)?);
                return Ok(Some((key, text[i + 1..].trim_start().to_string())));
            }
            _ => {}
        }
    }
    Ok(None)
}

/// `str(key)` for a mapping key that was resolved as a scalar.
fn key_string(v: &Value) -> String {
    v.py_str()
}

fn flow_balanced(s: &str) -> bool {
    let mut depth: i32 = 0;
    let mut quote: Option<u8> = None;
    let bytes = s.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i];
        match quote {
            Some(b'"') => {
                if c == b'\\' {
                    i += 1;
                } else if c == b'"' {
                    quote = None;
                }
            }
            Some(_) => {
                if c == b'\'' {
                    quote = None;
                }
            }
            None => match c {
                b'"' | b'\'' => quote = Some(c),
                b'[' | b'{' => depth += 1,
                b']' | b'}' => depth -= 1,
                _ => {}
            },
        }
        i += 1;
    }
    quote.is_none() && depth <= 0
}

enum Quoted {
    Unterminated,
    Bad,
}

/// Read a quoted scalar at the start of `s`; returns the text and the bytes used.
fn parse_quoted(s: &str) -> Result<(String, usize), Quoted> {
    let quote = s.as_bytes()[0];
    let mut out = String::new();
    let mut chars = s[1..].char_indices().map(|(i, c)| (i + 1, c)).peekable();
    while let Some((i, c)) = chars.next() {
        if quote == b'\'' {
            if c == '\'' {
                if matches!(chars.peek(), Some((_, '\''))) {
                    chars.next();
                    out.push('\'');
                    continue;
                }
                return Ok((out, i + 1));
            }
            out.push(c);
            continue;
        }
        match c {
            '"' => return Ok((out, i + 1)),
            '\\' => {
                let Some((_, e)) = chars.next() else {
                    return Err(Quoted::Unterminated);
                };
                let hex = |chars: &mut dyn Iterator<Item = (usize, char)>, n: usize| {
                    let mut v = 0u32;
                    for _ in 0..n {
                        let (_, h) = chars.next().ok_or(Quoted::Unterminated)?;
                        v = v * 16 + h.to_digit(16).ok_or(Quoted::Bad)?;
                    }
                    char::from_u32(v).ok_or(Quoted::Bad)
                };
                match e {
                    '0' => out.push('\0'),
                    'a' => out.push('\u{7}'),
                    'b' => out.push('\u{8}'),
                    't' | '\t' => out.push('\t'),
                    'n' => out.push('\n'),
                    'v' => out.push('\u{b}'),
                    'f' => out.push('\u{c}'),
                    'r' => out.push('\r'),
                    'e' => out.push('\u{1b}'),
                    ' ' => out.push(' '),
                    '"' => out.push('"'),
                    '/' => out.push('/'),
                    '\\' => out.push('\\'),
                    'N' => out.push('\u{85}'),
                    '_' => out.push('\u{a0}'),
                    'L' => out.push('\u{2028}'),
                    'P' => out.push('\u{2029}'),
                    'x' => out.push(hex(&mut chars, 2)?),
                    'u' => out.push(hex(&mut chars, 4)?),
                    'U' => out.push(hex(&mut chars, 8)?),
                    _ => return Err(Quoted::Bad),
                }
            }
            c => out.push(c),
        }
    }
    Err(Quoted::Unterminated)
}

/// Flow collections: `[a, "b", {c: 1}]`.
struct Flow<'a> {
    s: &'a str,
    i: usize,
}

impl Flow<'_> {
    fn peek(&self) -> Option<char> {
        self.s[self.i..].chars().next()
    }

    fn skip_ws(&mut self) {
        while self.peek().is_some_and(|c| c == ' ' || c == '\t') {
            self.i += 1;
        }
    }

    fn value(&mut self, depth: usize) -> R<Value> {
        if depth > MAX_NESTING {
            return err("nested too deeply");
        }
        self.skip_ws();
        match self.peek() {
            Some('[') => {
                self.i += 1;
                let mut items = Vec::new();
                loop {
                    self.skip_ws();
                    match self.peek() {
                        Some(']') => {
                            self.i += 1;
                            return Ok(Value::List(items));
                        }
                        Some(_) => {}
                        None => return err("unterminated sequence"),
                    }
                    items.push(self.value(depth + 1)?);
                    self.skip_ws();
                    match self.peek() {
                        Some(',') => self.i += 1,
                        Some(']') => {}
                        _ => return err("expected , or ]"),
                    }
                }
            }
            Some('{') => {
                self.i += 1;
                let mut entries: Vec<(String, Value)> = Vec::new();
                loop {
                    self.skip_ws();
                    match self.peek() {
                        Some('}') => {
                            self.i += 1;
                            return Ok(Value::Map(entries));
                        }
                        Some(_) => {}
                        None => return err("unterminated mapping"),
                    }
                    let key = key_string(&self.scalar(true)?);
                    self.skip_ws();
                    let value = if self.peek() == Some(':') {
                        self.i += 1;
                        self.skip_ws();
                        if matches!(self.peek(), Some(',' | '}')) {
                            Value::Null
                        } else {
                            self.value(depth + 1)?
                        }
                    } else {
                        Value::Null
                    };
                    match entries.iter_mut().find(|(k, _)| *k == key) {
                        Some(slot) => slot.1 = value,
                        None => entries.push((key, value)),
                    }
                    self.skip_ws();
                    match self.peek() {
                        Some(',') => self.i += 1,
                        Some('}') => {}
                        _ => return err("expected , or }"),
                    }
                }
            }
            Some(_) => self.scalar(false),
            None => err("missing value"),
        }
    }

    /// A quoted or plain scalar; a plain one ends at `,`, a closing bracket, or a `:` followed by a space or bracket.
    fn scalar(&mut self, is_key: bool) -> R<Value> {
        self.skip_ws();
        match self.peek() {
            Some('"' | '\'') => {
                let (v, used) = parse_quoted(&self.s[self.i..]).map_err(|_| YamlError {
                    message: "bad quoted scalar".into(),
                })?;
                self.i += used;
                Ok(Value::Str(v))
            }
            Some('&' | '*' | '!' | '|' | '>' | '%' | '@' | '`') => {
                err("unsupported scalar indicator")
            }
            _ => {
                let rest = &self.s[self.i..];
                let bytes = rest.as_bytes();
                let mut end = bytes.len();
                for (k, &b) in bytes.iter().enumerate() {
                    let sep =
                        k + 1 == bytes.len() || matches!(bytes[k + 1], b' ' | b',' | b']' | b'}');
                    if matches!(b, b',' | b']' | b'}')
                        || (b == b':' && sep)
                        || (b == b'[' || b == b'{')
                    {
                        end = k;
                        break;
                    }
                }
                let text = rest[..end].trim();
                if text.is_empty() {
                    return err("empty flow entry");
                }
                if !is_key && text.contains(": ") {
                    return err("mapping value where a scalar is expected");
                }
                self.i += end;
                resolve_plain(text)
            }
        }
    }
}

/// YAML 1.1 resolution of a plain scalar, as PyYAML does it.
fn resolve_plain(s: &str) -> R<Value> {
    match s {
        "" | "~" | "null" | "Null" | "NULL" => return Ok(Value::Null),
        "yes" | "Yes" | "YES" | "true" | "True" | "TRUE" | "on" | "On" | "ON" => {
            return Ok(Value::Bool(true));
        }
        "no" | "No" | "NO" | "false" | "False" | "FALSE" | "off" | "Off" | "OFF" => {
            return Ok(Value::Bool(false));
        }
        _ => {}
    }
    if let Some(v) = resolve_int(s) {
        return Ok(v);
    }
    if let Some(v) = resolve_float(s) {
        return Ok(v);
    }
    if let Some(v) = resolve_timestamp(s)? {
        return Ok(v);
    }
    Ok(Value::Str(s.to_string()))
}

fn resolve_int(s: &str) -> Option<Value> {
    let (neg, body) = match s.as_bytes().first()? {
        b'-' => (true, &s[1..]),
        b'+' => (false, &s[1..]),
        _ => (false, s),
    };
    if let Some(n) = sexagesimal(body, false) {
        return Some(match n {
            Some(n) => Value::Int(if neg { -(n as i64) } else { n as i64 }),
            None => Value::Str(s.to_string()),
        });
    }
    let digits_ok =
        |t: &str, radix: u32| !t.is_empty() && t.chars().all(|c| c == '_' || c.is_digit(radix));
    let parsed = if let Some(t) = body.strip_prefix("0b") {
        digits_ok(t, 2).then(|| i64::from_str_radix(&t.replace('_', ""), 2))
    } else if let Some(t) = body.strip_prefix("0x") {
        digits_ok(t, 16).then(|| i64::from_str_radix(&t.replace('_', ""), 16))
    } else if body == "0" {
        Some(Ok(0))
    } else if let Some(t) = body.strip_prefix('0') {
        digits_ok(t, 8).then(|| i64::from_str_radix(&t.replace('_', ""), 8))
    } else if body
        .as_bytes()
        .first()
        .is_some_and(|b| (b'1'..=b'9').contains(b))
        && body.chars().all(|c| c == '_' || c.is_ascii_digit())
    {
        Some(body.replace('_', "").parse::<i64>())
    } else {
        None
    }?;
    // a match that does not fit 64 bits stays text
    Some(match parsed {
        Ok(n) => Value::Int(if neg { -n } else { n }),
        Err(_) => Value::Str(s.to_string()),
    })
}

fn resolve_float(s: &str) -> Option<Value> {
    let body = s.strip_prefix(['-', '+']).unwrap_or(s);
    if body.contains(':') {
        let value = sexagesimal_float(body)?;
        return Some(Value::Float(if s.starts_with('-') {
            -value
        } else {
            value
        }));
    }
    let (mantissa, exponent) = match body.find(['e', 'E']) {
        Some(p) => (&body[..p], Some(&body[p + 1..])),
        None => (body, None),
    };
    if let Some(e) = exponent {
        // the exponent needs an explicit sign and at least one digit
        let digits = e.strip_prefix(['-', '+'])?;
        if digits.is_empty() || !digits.chars().all(|c| c.is_ascii_digit()) {
            return None;
        }
    }
    let dot = mantissa.find('.')?;
    let (whole, frac) = (&mantissa[..dot], &mantissa[dot + 1..]);
    let ok_digits = |t: &str| t.chars().all(|c| c == '_' || c.is_ascii_digit());
    let first_ok = if whole.is_empty() {
        // `.5` needs a digit right after the dot (the sign form of `.5` is not a float)
        s.as_bytes()[0] == b'.' && frac.as_bytes().first().is_some_and(u8::is_ascii_digit)
    } else {
        whole.as_bytes()[0].is_ascii_digit() && ok_digits(whole)
    };
    if !first_ok || !ok_digits(frac) {
        return None;
    }
    let cleaned = s.replace('_', "");
    let cleaned = cleaned.trim_start_matches('+');
    let value: f64 = cleaned.parse().ok()?;
    value.is_finite().then_some(Value::Float(value))
}

/// `1:30:15`: base-60 groups, each `0`-`59`, the first without a leading zero. `Some(None)` when it overflows.
fn sexagesimal(body: &str, allow_leading_zero: bool) -> Option<Option<u64>> {
    let mut parts = body.split(':');
    let head = parts.next()?;
    let head_ok = !head.is_empty()
        && head.chars().all(|c| c == '_' || c.is_ascii_digit())
        && (allow_leading_zero || head.as_bytes()[0] != b'0')
        && head.as_bytes()[0] != b'_';
    if !head_ok {
        return None;
    }
    let mut value: Option<u64> = head.replace('_', "").parse().ok();
    let mut any = false;
    for part in parts {
        any = true;
        if part.is_empty()
            || part.len() > 2
            || !part.bytes().all(|b| b.is_ascii_digit())
            || part.parse::<u32>().ok()? > 59
        {
            return None;
        }
        value = value.and_then(|v| v.checked_mul(60)?.checked_add(part.parse().ok()?));
    }
    any.then_some(value)
}

/// `1:30.5`: base-60 groups with a fraction on the last.
fn sexagesimal_float(body: &str) -> Option<f64> {
    let (whole, frac) = body.split_once('.')?;
    if !frac.chars().all(|c| c == '_' || c.is_ascii_digit()) || frac.contains(':') {
        return None;
    }
    let groups = sexagesimal(whole, true)?;
    let mut value = groups? as f64;
    if !frac.is_empty() {
        let f: f64 = format!("0.{}", frac.replace('_', "")).parse().ok()?;
        value += f;
    }
    Some(value)
}

fn digits(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit())
}

fn days_in(year: u32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        _ if year.is_multiple_of(4) && (!year.is_multiple_of(100) || year.is_multiple_of(400)) => {
            29
        }
        _ => 28,
    }
}

/// `YYYY-MM-DD` and `YYYY-M-D[T ]h:mm:ss[.f][ ][Z|±h[:mm]]`. An impossible date is an error, as in generation 1.
fn resolve_timestamp(s: &str) -> R<Option<Value>> {
    let bad = || err("impossible date or time");
    let Some((date, time)) = s.split_once(['T', 't', ' ', '\t']) else {
        let parts: Vec<&str> = s.split('-').collect();
        if parts.len() == 3
            && parts[0].len() == 4
            && parts[1].len() == 2
            && parts[2].len() == 2
            && parts.iter().all(|p| digits(p))
        {
            let (y, m, d): (u32, u32, u32) = (
                parts[0].parse().unwrap_or(0),
                parts[1].parse().unwrap_or(0),
                parts[2].parse().unwrap_or(0),
            );
            if y == 0 || !(1..=12).contains(&m) || d < 1 || d > days_in(y, m) {
                return bad();
            }
            return Ok(Some(Value::Date(format!("{y:04}-{m:02}-{d:02}"))));
        }
        return Ok(None);
    };
    let dparts: Vec<&str> = date.split('-').collect();
    if dparts.len() != 3
        || dparts[0].len() != 4
        || !(1..=2).contains(&dparts[1].len())
        || !(1..=2).contains(&dparts[2].len())
        || !dparts.iter().all(|p| digits(p))
    {
        return Ok(None);
    }
    let time = time.trim_start_matches([' ', '\t']);
    // split the clock from the zone: Z, or a sign after the seconds
    let (clock, zone) = match time.find(['Z', '+', '-', ' ', '\t']) {
        Some(p) => (&time[..p], time[p..].trim_start_matches([' ', '\t'])),
        None => (time, ""),
    };
    let (hms, frac) = match clock.split_once('.') {
        Some((a, b)) => (a, Some(b)),
        None => (clock, None),
    };
    let tparts: Vec<&str> = hms.split(':').collect();
    if tparts.len() != 3
        || !(1..=2).contains(&tparts[0].len())
        || tparts[1].len() != 2
        || tparts[2].len() != 2
        || !tparts.iter().all(|p| digits(p))
        || frac.is_some_and(|f| !f.bytes().all(|b| b.is_ascii_digit()))
    {
        return Ok(None);
    }
    let offset = if zone.is_empty() || zone == "Z" {
        zone.is_empty().then_some("").or(Some("+00:00"))
    } else {
        None
    };
    let mut tz = offset.map(str::to_string);
    if tz.is_none() {
        let sign = zone.as_bytes()[0];
        if sign != b'+' && sign != b'-' {
            return Ok(None);
        }
        let (h, m) = match zone[1..].split_once(':') {
            Some((h, m)) => (h, m),
            None => (&zone[1..], "0"),
        };
        if !(1..=2).contains(&h.len()) || !digits(h) || !(1..=2).contains(&m.len()) || !digits(m) {
            return Ok(None);
        }
        let (h, m): (u32, u32) = (h.parse().unwrap_or(99), m.parse().unwrap_or(99));
        if h > 23 || m > 59 {
            return bad();
        }
        tz = Some(format!("{}{h:02}:{m:02}", sign as char));
    }
    let (y, mo, d): (u32, u32, u32) = (
        dparts[0].parse().unwrap_or(0),
        dparts[1].parse().unwrap_or(0),
        dparts[2].parse().unwrap_or(0),
    );
    let (h, mi, sec): (u32, u32, u32) = (
        tparts[0].parse().unwrap_or(99),
        tparts[1].parse().unwrap_or(99),
        tparts[2].parse().unwrap_or(99),
    );
    if y == 0
        || !(1..=12).contains(&mo)
        || d < 1
        || d > days_in(y, mo)
        || h > 23
        || mi > 59
        || sec > 59
    {
        return bad();
    }
    let micro = frac.map_or(0, |f| {
        let mut f6: String = f.chars().take(6).collect();
        while f6.len() < 6 {
            f6.push('0');
        }
        f6.parse::<u32>().unwrap_or(0)
    });
    let mut out = format!("{y:04}-{mo:02}-{d:02}T{h:02}:{mi:02}:{sec:02}");
    if micro != 0 {
        out.push_str(&format!(".{micro:06}"));
    }
    out.push_str(tz.as_deref().unwrap_or(""));
    Ok(Some(Value::DateTime(out)))
}
