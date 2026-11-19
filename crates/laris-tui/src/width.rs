//! How many terminal columns a character takes, and wrapping by columns.

use crate::style::{Line, Span, Style};

/// Columns of one character: 0 for combining marks and joiners, 2 for East Asian wide characters and emoji, else 1.
pub fn char_width(c: char) -> usize {
    let n = c as u32;
    if n == 0 || (0x1..0x20).contains(&n) || (0x7f..0xa0).contains(&n) {
        return 0;
    }
    const ZERO: &[(u32, u32)] = &[
        (0x0300, 0x036f),
        (0x1ab0, 0x1aff),
        (0x1dc0, 0x1dff),
        (0x200b, 0x200f),
        (0x2028, 0x202e),
        (0x2060, 0x2064),
        (0x20d0, 0x20ff),
        (0xfe00, 0xfe0f),
        (0xfe20, 0xfe2f),
        (0xe0100, 0xe01ef),
    ];
    const WIDE: &[(u32, u32)] = &[
        (0x1100, 0x115f),
        (0x2e80, 0x303e),
        (0x3041, 0x33ff),
        (0x3400, 0x4dbf),
        (0x4e00, 0x9fff),
        (0xa000, 0xa4cf),
        (0xac00, 0xd7a3),
        (0xf900, 0xfaff),
        (0xfe30, 0xfe6f),
        (0xff00, 0xff60),
        (0xffe0, 0xffe6),
        (0x1f300, 0x1f64f),
        (0x1f900, 0x1f9ff),
        (0x20000, 0x3fffd),
    ];
    if ZERO.iter().any(|&(a, b)| (a..=b).contains(&n)) {
        0
    } else if WIDE.iter().any(|&(a, b)| (a..=b).contains(&n)) {
        2
    } else {
        1
    }
}

/// Columns of a text.
pub fn str_width(text: &str) -> usize {
    text.chars().map(char_width).sum()
}

/// The longest prefix of `text` that fits in `columns`, and its width.
pub fn fit(text: &str, columns: usize) -> (&str, usize) {
    let mut used = 0;
    for (at, c) in text.char_indices() {
        let w = char_width(c);
        if used + w > columns {
            return (&text[..at], used);
        }
        used += w;
    }
    (text, used)
}

/// `line` cut to `columns`, with `…` in the last column when something was cut.
pub fn truncate(line: &Line, columns: usize) -> Line {
    if line.width() <= columns {
        return line.clone();
    }
    if columns == 0 {
        return Line::default();
    }
    let mut out = Line::default();
    let mut used = 0;
    let budget = columns - 1;
    'spans: for span in &line.0 {
        let mut kept = String::new();
        for c in span.text.chars() {
            let w = char_width(c);
            if used + w > budget {
                if !kept.is_empty() {
                    out.0.push(Span::new(kept, span.style));
                }
                break 'spans;
            }
            used += w;
            kept.push(c);
        }
        out.0.push(Span::new(kept, span.style));
    }
    let style = line.0.last().map(|s| s.style).unwrap_or_default();
    out.0.push(Span::new("…", style));
    out
}

type Cell = (char, Style);

fn cells(line: &Line) -> Vec<Cell> {
    line.0
        .iter()
        .flat_map(|s| s.text.chars().map(move |c| (c, s.style)))
        .collect()
}

fn line_of(cells: &[Cell]) -> Line {
    let mut line = Line::default();
    for &(c, style) in cells {
        match line.0.last_mut() {
            Some(last) if last.style == style => last.text.push(c),
            _ => line.0.push(Span::new(c.to_string(), style)),
        }
    }
    line
}

fn cells_width(cells: &[Cell]) -> usize {
    cells.iter().map(|&(c, _)| char_width(c)).sum()
}

/// Wraps `body` to `width` columns at spaces; a word longer than a line is cut by columns. `first` leads the first
/// line and `rest` every other one (a hanging indent). Every returned line is at most `width` columns, whatever the
/// prefixes: a prefix that leaves no room is cut.
pub fn wrap(first: &Line, rest: &Line, body: &Line, width: usize) -> Vec<Line> {
    let width = width.max(1);
    let first = truncate(first, width.saturating_sub(1).max(1).min(width));
    let rest = truncate(rest, width.saturating_sub(1).max(1).min(width));
    let room = |prefix: &Line| width.saturating_sub(prefix.width()).max(1);

    let body = cells(body);
    let mut out: Vec<Line> = Vec::new();
    let mut current: Vec<Cell> = Vec::new();
    let mut prefix = first;
    let mut avail = room(&prefix);

    let flush =
        |out: &mut Vec<Line>, current: &mut Vec<Cell>, prefix: &mut Line, avail: &mut usize| {
            while current.last().is_some_and(|&(c, _)| c == ' ') {
                current.pop();
            }
            let mut line = prefix.clone();
            line.0.extend(line_of(current).0);
            out.push(line);
            current.clear();
            *prefix = rest.clone();
            *avail = room(prefix);
        };

    let mut i = 0;
    while i < body.len() {
        let is_space = body[i].0 == ' ';
        let mut j = i;
        while j < body.len() && (body[j].0 == ' ') == is_space {
            j += 1;
        }
        let token = &body[i..j];
        let w = cells_width(token);
        if is_space {
            if !current.is_empty() && cells_width(&current) + w <= avail {
                current.extend_from_slice(token);
            } else if !current.is_empty() {
                // the space would end the line: it is dropped, the next word starts a new one
                flush(&mut out, &mut current, &mut prefix, &mut avail);
            }
        } else if cells_width(&current) + w <= avail {
            current.extend_from_slice(token);
        } else if w <= avail {
            flush(&mut out, &mut current, &mut prefix, &mut avail);
            current.extend_from_slice(token);
        } else {
            if !current.is_empty() {
                flush(&mut out, &mut current, &mut prefix, &mut avail);
            }
            for &(c, style) in token {
                let cw = char_width(c);
                if cells_width(&current) + cw > avail && !current.is_empty() {
                    flush(&mut out, &mut current, &mut prefix, &mut avail);
                }
                current.push((c, style));
            }
        }
        i = j;
    }
    if !current.is_empty() || out.is_empty() {
        flush(&mut out, &mut current, &mut prefix, &mut avail);
    }
    out
}

/// Wraps by columns without regard to words (code, preformatted rows).
pub fn hard_wrap(first: &Line, rest: &Line, body: &Line, width: usize) -> Vec<Line> {
    let width = width.max(1);
    let first = truncate(first, width.saturating_sub(1).max(1).min(width));
    let rest = truncate(rest, width.saturating_sub(1).max(1).min(width));
    let mut out = Vec::new();
    let mut prefix = first;
    let mut avail = width.saturating_sub(prefix.width()).max(1);
    let mut current: Vec<Cell> = Vec::new();
    for (c, style) in cells(body) {
        let cw = char_width(c);
        if cells_width(&current) + cw > avail && !current.is_empty() {
            let mut line = prefix.clone();
            line.0.extend(line_of(&current).0);
            out.push(line);
            current.clear();
            prefix = rest.clone();
            avail = width.saturating_sub(prefix.width()).max(1);
        }
        current.push((c, style));
    }
    let mut line = prefix;
    line.0.extend(line_of(&current).0);
    out.push(line);
    out
}
