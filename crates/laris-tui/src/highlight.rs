//! A small syntax highlighter for fenced code: comments, strings, numbers and keywords, one line at a time.

use crate::style::{Line, Style, Theme};

const PYTHON: &[&str] = &[
    "def", "class", "return", "if", "elif", "else", "for", "while", "in", "import", "from", "as",
    "with", "try", "except", "finally", "raise", "lambda", "yield", "pass", "break", "continue",
    "not", "and", "or", "is", "None", "True", "False", "async", "await",
];
const RUST: &[&str] = &[
    "fn", "let", "mut", "pub", "struct", "enum", "impl", "trait", "use", "mod", "match", "if",
    "else", "for", "while", "loop", "return", "self", "Self", "const", "static", "async", "await",
    "move", "where", "type", "as", "in", "ref", "true", "false", "break", "continue",
];
const JS: &[&str] = &[
    "function",
    "const",
    "let",
    "var",
    "return",
    "if",
    "else",
    "for",
    "while",
    "class",
    "import",
    "export",
    "from",
    "new",
    "async",
    "await",
    "try",
    "catch",
    "throw",
    "switch",
    "case",
    "break",
    "continue",
    "null",
    "undefined",
    "true",
    "false",
    "interface",
    "type",
];
const SHELL: &[&str] = &[
    "if", "then", "else", "elif", "fi", "for", "do", "done", "while", "case", "esac", "function",
    "in", "export", "echo", "cd", "return",
];
const JSON: &[&str] = &["true", "false", "null"];
const TOML: &[&str] = &["true", "false"];

struct Lang {
    keywords: &'static [&'static str],
    comment: &'static str,
}

fn lang_of(name: &str) -> Option<Lang> {
    let name = name.trim().to_ascii_lowercase();
    Some(match name.as_str() {
        "python" | "py" => Lang {
            keywords: PYTHON,
            comment: "#",
        },
        "rust" | "rs" => Lang {
            keywords: RUST,
            comment: "//",
        },
        "javascript" | "js" | "typescript" | "ts" | "tsx" | "jsx" => Lang {
            keywords: JS,
            comment: "//",
        },
        "bash" | "sh" | "shell" | "zsh" | "console" => Lang {
            keywords: SHELL,
            comment: "#",
        },
        "json" | "jsonc" => Lang {
            keywords: JSON,
            comment: "",
        },
        "toml" | "yaml" | "yml" => Lang {
            keywords: TOML,
            comment: "#",
        },
        _ => return None,
    })
}

/// One line of code in `lang`; an unknown language is shown in the code style, unhighlighted.
pub fn highlight(text: &str, lang: &str, theme: Theme) -> Line {
    let base = Style::PLAIN;
    let Some(lang) = lang_of(lang) else {
        return Line::styled(text, base);
    };
    let chars: Vec<char> = text.chars().collect();
    let mut line = Line::default();
    let mut i = 0;
    let mut plain = String::new();
    let flush = |line: &mut Line, plain: &mut String| {
        if !plain.is_empty() {
            line.push(std::mem::take(plain), base);
        }
    };
    while i < chars.len() {
        let c = chars[i];
        let rest: String = chars[i..].iter().collect();
        if !lang.comment.is_empty() && rest.starts_with(lang.comment) {
            flush(&mut line, &mut plain);
            line.push(rest, theme.comment());
            return line;
        }
        if c == '"' || c == '\'' {
            flush(&mut line, &mut plain);
            let mut j = i + 1;
            while j < chars.len() && chars[j] != c {
                if chars[j] == '\\' {
                    j += 1;
                }
                j += 1;
            }
            let end = (j + 1).min(chars.len());
            line.push(chars[i..end].iter().collect::<String>(), theme.string());
            i = end;
            continue;
        }
        if c.is_ascii_digit()
            && (i == 0 || !(chars[i - 1].is_alphanumeric() || chars[i - 1] == '_'))
        {
            flush(&mut line, &mut plain);
            let mut j = i;
            while j < chars.len()
                && (chars[j].is_ascii_alphanumeric() || chars[j] == '.' || chars[j] == '_')
            {
                j += 1;
            }
            line.push(chars[i..j].iter().collect::<String>(), theme.number());
            i = j;
            continue;
        }
        if c.is_alphabetic() || c == '_' {
            let mut j = i;
            while j < chars.len() && (chars[j].is_alphanumeric() || chars[j] == '_') {
                j += 1;
            }
            let word: String = chars[i..j].iter().collect();
            if lang.keywords.contains(&word.as_str()) {
                flush(&mut line, &mut plain);
                line.push(word, theme.keyword());
            } else {
                plain.push_str(&word);
            }
            i = j;
            continue;
        }
        plain.push(c);
        i += 1;
    }
    flush(&mut line, &mut plain);
    line
}
