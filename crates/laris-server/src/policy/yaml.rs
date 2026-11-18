//! A reader for the small YAML subset the policy files use (`manifest.yaml`, `strings.yaml`, workflows).
//!
//! No YAML crate is approved (ADR-021), and the policy files stay as the owner wrote them, so this reads exactly
//! what they use and refuses everything else with an error: block mappings, block sequences (also of mappings),
//! plain, single- and double-quoted scalars, flow sequences of scalars (`[a, "b"]`), folded and literal block
//! scalars (`>`, `>-`, `|`, `|-`) and comments. Anchors, aliases, tags, flow mappings, multi-line plain scalars,
//! several documents and tabs are errors, never guesses: a policy file that is read differently than the owner
//! meant is worse than one that does not load.

use serde_json::{Map, Number, Value};

/// A line the reader cannot take.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("line {line}: {reason}")]
pub struct YamlError {
    /// 1-based line number.
    pub line: usize,
    /// What is wrong.
    pub reason: &'static str,
}

struct Line<'a> {
    number: usize,
    indent: usize,
    text: &'a str,
}

/// Reads a document into JSON values.
pub fn parse(source: &str) -> Result<Value, YamlError> {
    let raw: Vec<&str> = source.lines().collect();
    let mut lines = Vec::new();
    for (i, text) in raw.iter().enumerate() {
        let number = i + 1;
        if text.contains('\t') && text.trim_start_matches(' ').starts_with('\t') {
            return Err(YamlError {
                line: number,
                reason: "tabs are not allowed in indentation",
            });
        }
        let body = text.trim_start_matches(' ');
        if body.trim().is_empty() || body.starts_with('#') {
            continue;
        }
        if body == "---" || body == "..." {
            if lines.is_empty() && body == "---" {
                continue;
            }
            return Err(YamlError {
                line: number,
                reason: "only one document is supported",
            });
        }
        lines.push(Line {
            number,
            indent: text.len() - body.len(),
            text: body.trim_end(),
        });
    }
    if lines.is_empty() {
        return Ok(Value::Null);
    }
    let mut reader = Reader {
        raw: &raw,
        lines,
        at: 0,
    };
    let indent = reader.lines[0].indent;
    let value = reader.block(indent)?;
    if let Some(extra) = reader.lines.get(reader.at) {
        return Err(YamlError {
            line: extra.number,
            reason: "unexpected indentation",
        });
    }
    Ok(value)
}

struct Reader<'a> {
    raw: &'a [&'a str],
    lines: Vec<Line<'a>>,
    at: usize,
}

fn err<T>(line: usize, reason: &'static str) -> Result<T, YamlError> {
    Err(YamlError { line, reason })
}

fn is_item(text: &str) -> bool {
    text == "-" || text.starts_with("- ")
}

impl<'a> Reader<'a> {
    fn block(&mut self, indent: usize) -> Result<Value, YamlError> {
        let line = &self.lines[self.at];
        if is_item(line.text) {
            self.sequence(indent)
        } else {
            self.mapping(indent)
        }
    }

    fn sequence(&mut self, indent: usize) -> Result<Value, YamlError> {
        let mut items = Vec::new();
        while let Some(line) = self.lines.get(self.at) {
            if line.indent != indent || !is_item(line.text) {
                if line.indent > indent {
                    return err(line.number, "unexpected indentation");
                }
                break;
            }
            let number = line.number;
            let rest = line.text[1..].trim_start_matches(' ');
            let offset = line.text.len() - rest.len();
            if rest.is_empty() {
                self.at += 1;
                items.push(self.nested(indent, number)?);
            } else if key_split(rest, number)?.is_some() {
                // `- key: value` opens a mapping whose keys line up after the dash
                let child = indent + offset;
                self.lines[self.at].indent = child;
                self.lines[self.at].text = rest;
                items.push(self.mapping(child)?);
            } else {
                self.at += 1;
                items.push(inline(rest, number)?);
            }
        }
        Ok(Value::Array(items))
    }

    /// The value under a key or a bare dash whose line is already consumed.
    fn nested(&mut self, parent: usize, number: usize) -> Result<Value, YamlError> {
        match self.lines.get(self.at) {
            Some(next) if next.indent > parent => {
                let indent = next.indent;
                self.block(indent)
            }
            Some(next) if next.indent == parent && is_item(next.text) => self.sequence(parent),
            _ => {
                let _ = number;
                Ok(Value::Null)
            }
        }
    }

    fn mapping(&mut self, indent: usize) -> Result<Value, YamlError> {
        let mut map = Map::new();
        while let Some(line) = self.lines.get(self.at) {
            if line.indent != indent {
                if line.indent > indent {
                    return err(line.number, "unexpected indentation");
                }
                break;
            }
            if is_item(line.text) {
                break;
            }
            let number = line.number;
            let Some((key, rest)) = key_split(line.text, number)? else {
                return err(number, "expected `key: value`");
            };
            if map.contains_key(&key) {
                return err(number, "duplicate key");
            }
            self.at += 1;
            let value = if rest.is_empty() {
                self.nested(indent, number)?
            } else if rest.starts_with(['>', '|']) {
                self.block_scalar(rest, indent, number)?
            } else {
                inline(rest, number)?
            };
            map.insert(key, value);
        }
        Ok(Value::Object(map))
    }

    fn block_scalar(
        &mut self,
        header: &str,
        parent: usize,
        number: usize,
    ) -> Result<Value, YamlError> {
        let folded = header.starts_with('>');
        let strip = match &header[1..] {
            "" => false,
            "-" => true,
            _ => return err(number, "unsupported block scalar header"),
        };
        let first = self.lines.get(self.at).map(|l| l.number).unwrap_or(0);
        let mut collected: Vec<&str> = Vec::new();
        let mut block_indent = None;
        let mut consumed = self.at;
        // raw lines from just after the header line (`number`) up to the first line that is not deeper
        let start = number;
        let mut cursor = start;
        while cursor < self.raw.len() {
            let text = self.raw[cursor];
            if text.trim().is_empty() {
                collected.push("");
                cursor += 1;
                continue;
            }
            let indent = text.len() - text.trim_start_matches(' ').len();
            if indent <= parent {
                break;
            }
            let base = *block_indent.get_or_insert(indent);
            if indent < base {
                return err(
                    cursor + 1,
                    "block scalar is indented less than its first line",
                );
            }
            collected.push(&text[base..]);
            cursor += 1;
        }
        while collected.last() == Some(&"") {
            collected.pop();
        }
        let _ = first;
        while consumed < self.lines.len() && self.lines[consumed].number <= cursor {
            consumed += 1;
        }
        self.at = consumed;
        let mut text = if folded {
            fold(&collected)
        } else {
            collected.join("\n")
        };
        if !strip && !text.is_empty() {
            text.push('\n');
        }
        Ok(Value::String(text))
    }
}

/// Folded scalar: single line breaks become spaces, a blank line is a line break.
fn fold(lines: &[&str]) -> String {
    let mut out = String::new();
    let mut previous_text = false;
    let mut pending_breaks = 0;
    for line in lines {
        if line.is_empty() {
            pending_breaks += 1;
            continue;
        }
        if previous_text {
            if pending_breaks == 0 {
                out.push(' ');
            } else {
                out.push_str(&"\n".repeat(pending_breaks));
            }
        }
        out.push_str(line);
        previous_text = true;
        pending_breaks = 0;
    }
    out
}

/// Splits `key: rest` (the colon followed by a space or the end), reading a quoted key whole.
fn key_split(text: &str, line: usize) -> Result<Option<(String, &str)>, YamlError> {
    if let Some(quote) = text.chars().next().filter(|c| *c == '"' || *c == '\'') {
        let Some(end) = closing_quote(text, quote) else {
            return err(line, "unterminated quoted text");
        };
        let after = &text[end + 1..];
        if after == ":" || after.starts_with(": ") {
            let key = match scalar(&text[..=end], line)? {
                Value::String(s) => s,
                _ => return err(line, "keys must be text"),
            };
            return Ok(Some((key, after[1..].trim_start_matches(' '))));
        }
        return Ok(None);
    }
    if text.starts_with(['[', '{', '&', '*', '!', '%', '@', '`', '?']) {
        return Ok(None);
    }
    let bytes = text.as_bytes();
    for (i, b) in bytes.iter().enumerate() {
        if *b == b':' && (i + 1 == bytes.len() || bytes[i + 1] == b' ') {
            let key = text[..i].trim_end();
            if key.is_empty() {
                return err(line, "empty key");
            }
            return Ok(Some((
                key.to_owned(),
                text[i + 1..].trim_start_matches(' '),
            )));
        }
        if *b == b' ' && bytes.get(i + 1) == Some(&b'#') {
            break;
        }
    }
    Ok(None)
}

/// Index of the quote that closes the one at the start of `text`.
fn closing_quote(text: &str, quote: char) -> Option<usize> {
    let mut chars = text.char_indices().skip(1).peekable();
    while let Some((i, c)) = chars.next() {
        if quote == '"' && c == '\\' {
            chars.next();
        } else if c == quote {
            if quote == '\'' && matches!(chars.peek(), Some((_, '\''))) {
                chars.next();
            } else {
                return Some(i);
            }
        }
    }
    None
}

/// A value on the same line as its key or dash: scalar or flow sequence, then an optional comment.
fn inline(text: &str, line: usize) -> Result<Value, YamlError> {
    if text.starts_with('[') {
        return flow_sequence(text, line);
    }
    scalar(text, line)
}

fn strip_comment(text: &str) -> &str {
    let bytes = text.as_bytes();
    for i in 1..bytes.len() {
        if bytes[i] == b'#' && bytes[i - 1] == b' ' {
            return text[..i - 1].trim_end();
        }
    }
    text
}

fn scalar(text: &str, line: usize) -> Result<Value, YamlError> {
    let first = text.chars().next().unwrap_or(' ');
    match first {
        '"' => {
            let Some(end) = closing_quote(text, '"') else {
                return err(line, "unterminated quoted text");
            };
            if !strip_comment_after(&text[end + 1..]) {
                return err(line, "text after a quoted value");
            }
            let token = &text[..=end];
            serde_json::from_str::<String>(token)
                .map(Value::String)
                .or_else(|_| err(line, "unsupported escape in a quoted value"))
        }
        '\'' => {
            let Some(end) = closing_quote(text, '\'') else {
                return err(line, "unterminated quoted text");
            };
            if !strip_comment_after(&text[end + 1..]) {
                return err(line, "text after a quoted value");
            }
            Ok(Value::String(text[1..end].replace("''", "'")))
        }
        '&' | '*' | '!' | '{' | '|' | '>' | '%' | '@' | '`' => {
            err(line, "unsupported YAML construct")
        }
        _ => Ok(plain(strip_comment(text))),
    }
}

fn strip_comment_after(rest: &str) -> bool {
    let rest = rest.trim();
    rest.is_empty() || rest.starts_with('#')
}

fn plain(text: &str) -> Value {
    match text {
        "" | "~" | "null" | "Null" | "NULL" => Value::Null,
        "true" | "True" | "TRUE" => Value::Bool(true),
        "false" | "False" | "FALSE" => Value::Bool(false),
        _ => {
            if let Ok(n) = text.parse::<i64>() {
                return Value::Number(n.into());
            }
            if text.contains(['.', 'e', 'E'])
                && text
                    .chars()
                    .all(|c| c.is_ascii_digit() || matches!(c, '.' | 'e' | 'E' | '-' | '+'))
                && let Ok(f) = text.parse::<f64>()
                && let Some(n) = Number::from_f64(f)
            {
                return Value::Number(n);
            }
            Value::String(text.to_owned())
        }
    }
}

fn flow_sequence(text: &str, line: usize) -> Result<Value, YamlError> {
    let text = strip_comment(text);
    let Some(inner) = text.strip_prefix('[').and_then(|t| t.strip_suffix(']')) else {
        return err(line, "a flow sequence must close on its line");
    };
    let mut items = Vec::new();
    let mut rest = inner.trim();
    while !rest.is_empty() {
        let (item, tail) =
            if let Some(quote) = rest.chars().next().filter(|c| *c == '"' || *c == '\'') {
                let Some(end) = closing_quote(rest, quote) else {
                    return err(line, "unterminated quoted text");
                };
                (scalar(&rest[..=end], line)?, rest[end + 1..].trim_start())
            } else {
                if rest.starts_with(['[', '{']) {
                    return err(line, "nested flow collections are not supported");
                }
                let end = rest.find(',').unwrap_or(rest.len());
                (plain(rest[..end].trim()), &rest[end..])
            };
        items.push(item);
        rest = match tail.strip_prefix(',') {
            Some(t) => t.trim_start(),
            None if tail.is_empty() => "",
            None => return err(line, "expected a comma in a flow sequence"),
        };
    }
    Ok(Value::Array(items))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn mappings_sequences_and_scalars() {
        let doc = "\
# comment
name: grounded-qa
version: \"1.2.0\"
count: 5
flag: true
empty:
tools: [a, \"b c\", d]
list:
  - one
  - 'it''s'
  - id: x
    goal: Do it  # trailing
    nested:
      - y
";
        assert_eq!(
            parse(doc).unwrap(),
            json!({
                "name": "grounded-qa",
                "version": "1.2.0",
                "count": 5,
                "flag": true,
                "empty": null,
                "tools": ["a", "b c", "d"],
                "list": ["one", "it's", {"id": "x", "goal": "Do it", "nested": ["y"]}],
            })
        );
    }

    #[test]
    fn block_scalars() {
        let doc = "\
a:
  b: >-
    first line
    second line

    after blank
  c: |
    keep
      this
  d: end
";
        let v = parse(doc).unwrap();
        assert_eq!(v["a"]["b"], "first line second line\nafter blank");
        assert_eq!(v["a"]["c"], "keep\n  this\n");
        assert_eq!(v["a"]["d"], "end");
    }

    #[test]
    fn sequence_beside_its_key_and_colons_in_text() {
        let v = parse("k:\n- a\n- b\npath: \"a/b:c\"\nnote: has: colon\n").unwrap();
        assert_eq!(v["k"], json!(["a", "b"]));
        assert_eq!(v["path"], "a/b:c");
    }

    #[test]
    fn what_is_not_supported_is_an_error() {
        for bad in [
            "a: &anchor 1\n",
            "a: *alias\n",
            "a: !!str x\n",
            "a: {x: 1}\n",
            "\ta: 1\n",
            "a: 1\na: 2\n",
            "a: \"open\n",
            "a: [1, [2]]\n",
            "a: 1\n---\nb: 2\n",
            "a: 1\n  b: 2\n",
        ] {
            assert!(parse(bad).is_err(), "{bad:?} must not load");
        }
    }
}
