//! Glob patterns as regular expressions: `*` (not `/`), `**`, `?`, `[abc]`, `[!abc]`, `{a,b}`.

use regex::Regex;

/// The expression for `pattern`, anchored at both ends; `None` when the pattern is malformed.
///
/// `**/` matches any number of folders (also none); `**` matches anything; `*` and `?` stop at `/`.
pub fn glob_to_regex(pattern: &str) -> Option<Regex> {
    let chars: Vec<char> = pattern.chars().collect();
    let mut out = String::from("^");
    let mut i = 0;
    let mut braces = 0usize;
    while i < chars.len() {
        match chars[i] {
            '*' if chars.get(i + 1) == Some(&'*') => {
                if chars.get(i + 2) == Some(&'/') {
                    out.push_str("(?:.*/)?");
                    i += 3;
                } else {
                    out.push_str(".*");
                    i += 2;
                }
                continue;
            }
            '*' => out.push_str("[^/]*"),
            '?' => out.push_str("[^/]"),
            '[' => {
                let close = chars[i + 1..].iter().position(|&c| c == ']')? + i + 1;
                if close == i + 1 {
                    return None;
                }
                out.push('[');
                let mut j = i + 1;
                if matches!(chars[j], '!' | '^') {
                    out.push('^');
                    j += 1;
                }
                for &c in &chars[j..close] {
                    if matches!(c, '\\' | '[' | ']' | '&' | '~') {
                        out.push('\\');
                    }
                    out.push(c);
                }
                out.push(']');
                i = close;
            }
            '{' => {
                braces += 1;
                out.push_str("(?:");
            }
            '}' if braces > 0 => {
                braces -= 1;
                out.push(')');
            }
            ',' if braces > 0 => out.push('|'),
            c => out.push_str(&regex::escape(&c.to_string())),
        }
        i += 1;
    }
    if braces > 0 {
        return None;
    }
    out.push('$');
    Regex::new(&out).ok()
}
