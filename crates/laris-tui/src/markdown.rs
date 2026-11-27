//! Markdown for the terminal: headings, paragraphs, lists, quotes, rules, tables as rows, fenced code with
//! highlighting, and inline code, bold, italic and links. LaTeX math is kept exactly as written, in its own style.
//!
//! [`render`] turns *complete lines* of Markdown into screen lines. A streamed answer is rendered by cutting it at its
//! last newline ([`split_complete`]): the lines before are final (rendering a longer text never changes them) and the
//! rest waits for its newline. The tests hold the interface to that.

use crate::highlight::highlight;
use crate::style::{Line, Span, Style, Theme};
use crate::width::{hard_wrap, truncate, wrap};

/// Cuts `text` after its last newline: what can be rendered now, and the unfinished line.
pub fn split_complete(text: &str) -> (&str, &str) {
    match text.rfind('\n') {
        Some(at) => (&text[..=at], &text[at + 1..]),
        None => ("", text),
    }
}

/// The inline spans of one paragraph line: `code`, **bold**, *italic*, [text](url) and math (`$…$`, `$$…$$`, `\(…\)`,
/// `\[…\]`, its backslashes untouched). Unmatched markers stay as written. `base` is the style underneath.
pub fn inline(text: &str, base: Style, theme: Theme) -> Vec<Span> {
    let chars: Vec<char> = text.chars().collect();
    let mut spans: Vec<Span> = Vec::new();
    let mut plain = String::new();
    let flush = |spans: &mut Vec<Span>, plain: &mut String| {
        if !plain.is_empty() {
            spans.push(Span::new(std::mem::take(plain), base));
        }
    };
    let find = |from: usize, marker: &[char]| -> Option<usize> {
        let mut j = from;
        while j + marker.len() <= chars.len() {
            if chars[j] == '\\' {
                j += 2;
                continue;
            }
            if chars[j..j + marker.len()] == *marker {
                return Some(j);
            }
            j += 1;
        }
        None
    };
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if let Some((open, close)) = math_at(&chars, i)
            && let Some(end) = math_end(&chars, i + open, close)
        {
            flush(&mut spans, &mut plain);
            let math: String = chars[i..end + close.len()].iter().collect();
            spans.push(Span::new(math, base.on(theme.math())));
            i = end + close.len();
            continue;
        }
        if c == '\\' && i + 1 < chars.len() && "\\`*_[]()#>-+.!$".contains(chars[i + 1]) {
            plain.push(chars[i + 1]);
            i += 2;
            continue;
        }
        if c == '`' {
            let ticks = chars[i..].iter().take_while(|&&x| x == '`').count();
            let marker = vec!['`'; ticks];
            if let Some(end) = find(i + ticks, &marker) {
                flush(&mut spans, &mut plain);
                let code: String = chars[i + ticks..end].iter().collect();
                spans.push(Span::new(code.trim().to_owned(), base.on(theme.code())));
                i = end + ticks;
                continue;
            }
        }
        let doubled = (c == '*' || c == '_') && chars.get(i + 1) == Some(&c);
        if doubled
            && let Some(end) = find(i + 2, &[c, c])
            && end > i + 2
            && !chars[i + 2].is_whitespace()
            && !chars[end - 1].is_whitespace()
        {
            flush(&mut spans, &mut plain);
            let inner: String = chars[i + 2..end].iter().collect();
            spans.extend(inline(&inner, base.on(Style::PLAIN.bold()), theme));
            i = end + 2;
            continue;
        }
        let word_edge = i == 0 || !chars[i - 1].is_alphanumeric();
        if (c == '*' || (c == '_' && word_edge))
            && !doubled
            && chars.get(i + 1).is_some_and(|n| !n.is_whitespace())
            && let Some(end) = find(i + 1, &[c])
            && end > i + 1
            && !chars[end - 1].is_whitespace()
            && (c == '*' || chars.get(end + 1).is_none_or(|n| !n.is_alphanumeric()))
        {
            flush(&mut spans, &mut plain);
            let inner: String = chars[i + 1..end].iter().collect();
            spans.extend(inline(&inner, base.on(Style::PLAIN.italic()), theme));
            i = end + 1;
            continue;
        }
        if c == '['
            && let Some(close) = find(i + 1, &[']'])
            && chars.get(close + 1) == Some(&'(')
            && let Some(end) = find(close + 2, &[')'])
        {
            flush(&mut spans, &mut plain);
            let label: String = chars[i + 1..close].iter().collect();
            let url: String = chars[close + 2..end].iter().collect();
            spans.push(Span::new(label, base.on(theme.link())));
            if !url.is_empty() {
                spans.push(Span::new(format!(" ({url})"), base.on(theme.dim())));
            }
            i = end + 1;
            continue;
        }
        plain.push(c);
        i += 1;
    }
    flush(&mut spans, &mut plain);
    spans
}

/// The math delimiter opening at `i`: its length and the closing marker. A single `$` opens only before a non-space,
/// so a price such as `$5 and $10` stays text.
fn math_at(chars: &[char], i: usize) -> Option<(usize, &'static [char])> {
    let next = chars.get(i + 1).copied();
    match chars[i] {
        '\\' if next == Some('(') => Some((2, &['\\', ')'])),
        '\\' if next == Some('[') => Some((2, &['\\', ']'])),
        '$' if next == Some('$') => Some((2, &['$', '$'])),
        '$' if next.is_some_and(|n| !n.is_whitespace()) => Some((1, &['$'])),
        _ => None,
    }
}

/// Where `close` starts after `from`, skipping escaped characters. A single `$` closes only after a non-space and
/// before a non-digit; an empty span is no math.
fn math_end(chars: &[char], from: usize, close: &[char]) -> Option<usize> {
    let mut j = from;
    while j + close.len() <= chars.len() {
        if chars[j..j + close.len()] == *close && j > from {
            if close != ['$'] {
                return Some(j);
            }
            let after = chars.get(j + 1);
            if !chars[j - 1].is_whitespace() && after.is_none_or(|a| !a.is_ascii_digit()) {
                return Some(j);
            }
        }
        j += if chars[j] == '\\' { 2 } else { 1 };
    }
    None
}

fn clean(text: &str) -> String {
    text.replace('\t', "    ")
        .chars()
        .filter(|c| !c.is_control())
        .collect()
}

fn fence_of(line: &str) -> Option<(char, usize, String)> {
    let t = line.trim_start();
    let c = t.chars().next()?;
    if c != '`' && c != '~' {
        return None;
    }
    let n = t.chars().take_while(|&x| x == c).count();
    (n >= 3).then(|| (c, n, t[n..].trim().to_owned()))
}

fn is_rule(t: &str) -> bool {
    let t: String = t.chars().filter(|c| !c.is_whitespace()).collect();
    t.len() >= 3
        && ["-", "*", "_"]
            .iter()
            .any(|m| t.chars().all(|c| m.starts_with(c)))
}

fn list_marker(line: &str) -> Option<(usize, String, &str)> {
    let indent = line.chars().take_while(|&c| c == ' ').count();
    let t = &line[indent..];
    for m in ["- ", "* ", "+ "] {
        if let Some(rest) = t.strip_prefix(m) {
            return Some((indent, "•".to_owned(), rest));
        }
    }
    let digits = t.chars().take_while(char::is_ascii_digit).count();
    if (1..=9).contains(&digits)
        && let Some(rest) = t[digits..]
            .strip_prefix(". ")
            .or_else(|| t[digits..].strip_prefix(") "))
    {
        return Some((indent, format!("{}.", &t[..digits]), rest));
    }
    None
}

/// Renders complete lines of Markdown at `width` columns. Every line is at most `width` columns.
pub fn render(text: &str, width: usize, theme: Theme) -> Vec<Line> {
    let (mut lines, pending) = render_open(text, width, theme);
    lines.extend(pending);
    while lines.last().is_some_and(|l| l.0.is_empty()) {
        lines.pop();
    }
    lines
}

/// Renders the complete lines of an answer that is still streaming: the lines that are final, and the paragraph that
/// may still grow (a later line can join it and move its words). A final line never changes when more text follows.
pub fn render_open(text: &str, width: usize, theme: Theme) -> (Vec<Line>, Vec<Line>) {
    let width = width.max(8);
    let mut out: Vec<Line> = Vec::new();
    let mut paragraph: Vec<String> = Vec::new();
    let mut fence: Option<(char, usize, String)> = None;

    let gutter = Line::styled("│ ", theme.border());
    let flush_paragraph = |out: &mut Vec<Line>, paragraph: &mut Vec<String>| {
        if paragraph.is_empty() {
            return;
        }
        let joined = paragraph.join(" ");
        paragraph.clear();
        let body = Line(inline(&joined, Style::PLAIN, theme));
        out.extend(wrap(&Line::default(), &Line::default(), &body, width));
    };

    for raw in text.lines() {
        let line = clean_keep_indent(raw);
        if let Some((mark, count, lang)) = fence.clone() {
            match fence_of(&line) {
                Some((c, n, rest)) if c == mark && n >= count && rest.is_empty() => {
                    fence = None;
                }
                _ => {
                    let code = highlight(&line, &lang, theme);
                    out.extend(hard_wrap(&gutter, &gutter, &code, width));
                }
            }
            continue;
        }
        if let Some(opened) = fence_of(&line) {
            flush_paragraph(&mut out, &mut paragraph);
            if !opened.2.is_empty() {
                out.push(Line::styled(opened.2.clone(), theme.dim()));
            }
            fence = Some(opened);
            continue;
        }
        let trimmed = line.trim();
        if trimmed.is_empty() {
            flush_paragraph(&mut out, &mut paragraph);
            if out.last().is_some_and(|l| !l.0.is_empty()) {
                out.push(Line::blank());
            }
            continue;
        }
        if let Some(level) = heading_level(trimmed) {
            flush_paragraph(&mut out, &mut paragraph);
            let title = trimmed[level..].trim().trim_end_matches('#').trim();
            let style = if level <= 2 {
                theme.heading()
            } else {
                Style::PLAIN.bold()
            };
            let body = Line(inline(title, style, theme));
            out.extend(wrap(&Line::default(), &Line::default(), &body, width));
            continue;
        }
        if is_rule(trimmed) {
            flush_paragraph(&mut out, &mut paragraph);
            out.push(Line::styled("─".repeat(width.min(40)), theme.border()));
            continue;
        }
        if let Some(quote) = trimmed.strip_prefix('>') {
            flush_paragraph(&mut out, &mut paragraph);
            let bar = Line::styled("▎ ", theme.border());
            let body = Line(inline(
                quote.trim_start(),
                theme.dim().on(Style::PLAIN.italic()),
                theme,
            ));
            out.extend(wrap(&bar, &bar, &body, width));
            continue;
        }
        if let Some((indent, marker, rest)) = list_marker(&line) {
            flush_paragraph(&mut out, &mut paragraph);
            let level = indent / 2;
            let marker = if marker == "•" && level % 2 == 1 {
                "◦".to_owned()
            } else {
                marker
            };
            let lead = format!("{}{marker} ", "  ".repeat(level));
            let hang = " ".repeat(crate::width::str_width(&lead));
            let body = Line(inline(rest.trim(), Style::PLAIN, theme));
            out.extend(wrap(
                &Line::styled(lead, theme.dim()),
                &Line::plain(hang),
                &body,
                width,
            ));
            continue;
        }
        if trimmed.starts_with('|') {
            flush_paragraph(&mut out, &mut paragraph);
            let row = Line(inline(trimmed, Style::PLAIN, theme));
            out.push(truncate(&row, width));
            continue;
        }
        paragraph.push(trimmed.to_owned());
    }
    let mut pending: Vec<Line> = Vec::new();
    flush_paragraph(&mut pending, &mut paragraph);
    if pending.is_empty() {
        while out.last().is_some_and(|l| l.0.is_empty()) {
            out.pop();
        }
    }
    (out, pending)
}

fn clean_keep_indent(raw: &str) -> String {
    let c = clean(raw);
    c.trim_end().to_owned()
}

fn heading_level(t: &str) -> Option<usize> {
    let n = t.chars().take_while(|&c| c == '#').count();
    ((1..=6).contains(&n) && t[n..].starts_with(' ')).then_some(n)
}
