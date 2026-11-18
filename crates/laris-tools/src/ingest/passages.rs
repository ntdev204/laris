//! Cutting a document into passages that point back at it.
//!
//! A passage is a run of characters of the document text: `start` and `end` count Unicode scalar values, and
//! `chars[start..end]` of the document is exactly the passage text. Nothing is rewritten, so a quotation from a
//! passage can be found in the document and a passage can be shown in place.
//!
//! Paragraphs (separated by a blank line) are the unit. Neighbouring paragraphs are joined while they fit in
//! `max_chars`, a Markdown heading starts a new passage, and a paragraph longer than `max_chars` is cut at the last
//! sentence end (or space) that fits.

/// One passage.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Passage {
    /// 0, 1, 2 ... in document order.
    pub ordinal: usize,
    /// Character offset of the first character.
    pub start: usize,
    /// Character offset after the last character.
    pub end: usize,
    /// The text: the characters `start..end` of the document.
    pub text: String,
}

fn is_heading(chars: &[char], start: usize) -> bool {
    let mut i = start;
    let mut hashes = 0;
    while chars.get(i) == Some(&'#') {
        hashes += 1;
        i += 1;
    }
    (1..=6).contains(&hashes) && chars.get(i).is_some_and(|c| *c == ' ' || *c == '\t')
}

/// `(start, end)` of every paragraph: runs of lines up to a blank line, trimmed.
fn paragraphs(chars: &[char]) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut i = 0;
    let n = chars.len();
    while i < n {
        while i < n && chars[i].is_whitespace() {
            i += 1;
        }
        if i >= n {
            break;
        }
        let start = i;
        let mut end = i;
        while i < n {
            if chars[i] == '\n' {
                // a blank line ends the paragraph; so does a heading on the next line
                let mut j = i + 1;
                while j < n && chars[j] != '\n' && chars[j].is_whitespace() {
                    j += 1;
                }
                if j >= n || chars[j] == '\n' || is_heading(chars, i + 1) {
                    break;
                }
            }
            if !chars[i].is_whitespace() {
                end = i + 1;
            }
            i += 1;
        }
        out.push((start, end));
    }
    out
}

/// Where to cut a run that is too long: after the last sentence end or space within `limit`, else at `limit`.
fn cut_at(chars: &[char], start: usize, end: usize, limit: usize) -> usize {
    let hard = (start + limit).min(end);
    if hard == end {
        return end;
    }
    let floor = start + limit / 2;
    let mut best_space = None;
    for i in (floor..hard).rev() {
        let c = chars[i];
        if matches!(c, '.' | '?' | '!' | '。')
            && chars.get(i + 1).is_some_and(|n| n.is_whitespace())
        {
            return i + 1;
        }
        if c.is_whitespace() && best_space.is_none() {
            best_space = Some(i);
        }
    }
    best_space.unwrap_or(hard)
}

/// Cuts `text` into passages of at most `max_chars` characters.
pub fn split(text: &str, max_chars: usize) -> Vec<Passage> {
    let chars: Vec<char> = text.chars().collect();
    let max_chars = max_chars.max(1);
    let mut pieces: Vec<(usize, usize)> = Vec::new();
    for (start, end) in paragraphs(&chars) {
        let mut at = start;
        while end - at > max_chars {
            let cut = cut_at(&chars, at, end, max_chars);
            pieces.push((at, cut));
            at = cut;
            while at < end && chars[at].is_whitespace() {
                at += 1;
            }
        }
        if at < end {
            pieces.push((at, end));
        }
    }
    let mut passages: Vec<(usize, usize)> = Vec::new();
    for (start, end) in pieces {
        let joins = passages.last().is_some_and(|&(s, e)| {
            let _ = e;
            end - s <= max_chars && !is_heading(&chars, start)
        });
        if joins {
            if let Some(last) = passages.last_mut() {
                last.1 = end;
            }
        } else {
            passages.push((start, end));
        }
    }
    passages
        .into_iter()
        .enumerate()
        .map(|(ordinal, (start, end))| Passage {
            ordinal,
            start,
            end,
            text: chars[start..end].iter().collect(),
        })
        .collect()
}
