//! Text helpers shared by every stage: normalisation for matching, sentences and word overlap.
//!
//! Matching never looks at raw characters. [`normalize`] lower-cases, undoes the PDF ligatures (`ﬁ`, `ﬂ`, ...),
//! joins a word hyphenated at a line break and keeps letters and digits only, one space between words. A quote is
//! *found* in a paper when its normalised form is a substring of the paper's normalised text.

use std::collections::BTreeSet;

fn ligature(c: char) -> Option<&'static str> {
    Some(match c {
        '\u{FB00}' => "ff",
        '\u{FB01}' => "fi",
        '\u{FB02}' => "fl",
        '\u{FB03}' => "ffi",
        '\u{FB04}' => "ffl",
        '\u{FB05}' | '\u{FB06}' => "st",
        _ => return None,
    })
}

/// The normalised text and, for every character of it, the byte offset in `text` it came from.
pub fn normalize_with_map(text: &str) -> (String, Vec<usize>) {
    let mut out = String::with_capacity(text.len());
    let mut map = Vec::with_capacity(text.len());
    let mut pending_space = false;
    let mut chars = text.char_indices().peekable();
    while let Some((at, c)) = chars.next() {
        // a word hyphenated at a line break: "predic-\ntive" -> "predictive"
        if (c == '-' || c == '\u{00AD}')
            && chars.peek().is_some_and(|(_, n)| *n == '\n' || *n == '\r')
        {
            while chars.peek().is_some_and(|(_, n)| n.is_whitespace()) {
                chars.next();
            }
            continue;
        }
        if c == '\u{00AD}' {
            continue;
        }
        // a hyphen inside a word joins it: "orders-of-magnitude" and the reader's "orders-ofmagnitude" agree
        if matches!(c, '-' | '\u{2010}' | '\u{2011}')
            && !pending_space
            && out.chars().last().is_some_and(char::is_alphanumeric)
            && chars.peek().is_some_and(|(_, n)| n.is_alphanumeric())
        {
            continue;
        }
        let push = |piece: &str, at: usize, out: &mut String, map: &mut Vec<usize>| {
            for p in piece.chars() {
                out.push(p);
                map.push(at);
            }
        };
        if let Some(l) = ligature(c) {
            if pending_space && !out.is_empty() {
                push(" ", at, &mut out, &mut map);
            }
            pending_space = false;
            push(l, at, &mut out, &mut map);
        } else if c.is_alphanumeric() {
            if pending_space && !out.is_empty() {
                push(" ", at, &mut out, &mut map);
            }
            pending_space = false;
            let lower: String = c.to_lowercase().collect();
            push(&lower, at, &mut out, &mut map);
        } else {
            pending_space = true;
        }
    }
    (out, map)
}

/// [`normalize_with_map`] without the map.
pub fn normalize(text: &str) -> String {
    normalize_with_map(text).0
}

/// The words of `text` after [`normalize`].
pub fn words(text: &str) -> Vec<String> {
    normalize(text)
        .split(' ')
        .filter(|w| !w.is_empty())
        .map(str::to_owned)
        .collect()
}

/// Sentences of `text`: cut after `.`, `!` or `?` followed by white space and an upper-case letter, a digit or an
/// opening bracket, and at blank lines. Line breaks inside a sentence become spaces.
pub fn sentences(text: &str) -> Vec<String> {
    let flat: String = text
        .split("\n\n")
        .map(|p| p.split_whitespace().collect::<Vec<_>>().join(" "))
        .collect::<Vec<_>>()
        .join("\n");
    let mut out = Vec::new();
    for para in flat.split('\n') {
        let chars: Vec<char> = para.chars().collect();
        let mut start = 0;
        let mut i = 0;
        while i < chars.len() {
            let c = chars[i];
            let before: String = chars[start..i]
                .iter()
                .rev()
                .take_while(|c| !c.is_whitespace())
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect();
            let abbreviation = c == '.'
                && [
                    "al", "e.g", "i.e", "Fig", "Eq", "vs", "Sec", "Tab", "Ref", "cf", "etc", "No",
                ]
                .contains(&before.as_str());
            if (c == '.' || c == '!' || c == '?')
                && !abbreviation
                && chars.get(i + 1) == Some(&' ')
                && chars.get(i + 2).is_some_and(|n| {
                    n.is_uppercase() || n.is_ascii_digit() || *n == '[' || *n == '('
                })
            {
                let s: String = chars[start..=i].iter().collect();
                if !s.trim().is_empty() {
                    out.push(s.trim().to_owned());
                }
                start = i + 2;
                i += 2;
                continue;
            }
            i += 1;
        }
        if start < chars.len() {
            let s: String = chars[start..].iter().collect();
            if !s.trim().is_empty() {
                out.push(s.trim().to_owned());
            }
        }
    }
    out
}

/// Token F1 of two texts over their sets of normalised words longer than two characters.
pub fn token_f1(a: &str, b: &str) -> f64 {
    let set =
        |t: &str| -> BTreeSet<String> { words(t).into_iter().filter(|w| w.len() > 2).collect() };
    let (x, y) = (set(a), set(b));
    if x.is_empty() || y.is_empty() {
        return 0.0;
    }
    let common = x.intersection(&y).count() as f64;
    if common == 0.0 {
        return 0.0;
    }
    let p = common / x.len() as f64;
    let r = common / y.len() as f64;
    2.0 * p * r / (p + r)
}

/// Whether the normalised `needle` occurs in the normalised `haystack` as whole words.
pub fn contains_words(haystack_normalized: &str, needle: &str) -> bool {
    let n = normalize(needle);
    if n.is_empty() {
        return false;
    }
    let padded = format!(" {haystack_normalized} ");
    padded.contains(&format!(" {n} "))
}

/// Rounds to four places for reports.
pub fn round4(value: f64) -> f64 {
    (value * 10_000.0).round() / 10_000.0
}

/// Where `quote` stands in the normalised text `norm` (byte offset of its start), reading an ellipsis (`...`, `…`)
/// or an editor's insertion in square brackets as a cut: every remaining piece of three words or more must stand in
/// `norm`, in the quotation's order. `None` when a piece is missing or no piece is long enough.
pub fn locate(norm: &str, quote: &str) -> Option<usize> {
    static CUT: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    let cut = CUT.get_or_init(|| {
        regex::Regex::new(r"\.\s*\.\s*\.|…|\[[^\]]*[A-Za-z][^\]]*\]")
            .unwrap_or_else(|_| unreachable!())
    });
    let pieces: Vec<String> = cut
        .split(quote)
        .map(normalize)
        .filter(|p| p.split(' ').count() >= 3)
        .collect();
    let mut from = 0;
    let mut first = None;
    for p in &pieces {
        let at = from + norm.get(from..)?.find(p.as_str())?;
        first.get_or_insert(at);
        from = at + p.len();
    }
    first
}

#[cfg(test)]
mod tests {

    #[test]
    fn a_quotation_is_found_across_cuts_and_hyphens() {
        let norm = normalize(
            "Robots feature orders-of-\nmagnitude less RAM. Many of these solvers are not built for MPC at all.",
        );
        assert!(locate(&norm, "robots feature orders-of-magnitude less RAM").is_some());
        assert!(
            locate(
                &norm,
                "feature orders-of-magnitude less RAM... these solvers are not built"
            )
            .is_some()
        );
        assert!(
            locate(
                &norm,
                "many of these [existing solvers] are not built for MPC"
            )
            .is_some()
        );
        // the pieces must keep their order and each must stand in the text
        assert!(
            locate(
                &norm,
                "these solvers are not built ... robots feature orders-of-magnitude"
            )
            .is_none()
        );
        assert!(
            locate(
                &norm,
                "feature orders-of-magnitude less RAM ... a sentence nobody wrote"
            )
            .is_none()
        );
    }

    use super::*;

    #[test]
    fn normalisation_undoes_ligatures_and_line_hyphens() {
        assert_eq!(
            normalize("The ﬁrst predic-\ntive  Model!"),
            "the first predictive model"
        );
    }

    #[test]
    fn the_map_points_back_into_the_text() {
        let text = "A ﬁne day";
        let (n, map) = normalize_with_map(text);
        let at = n.find("fine").unwrap();
        assert_eq!(&text[map[at]..map[at] + 3], "ﬁ");
    }

    #[test]
    fn sentences_are_cut_at_full_stops() {
        let s = sentences("We test it. It works on a\nboard. 3 runs were done.");
        assert_eq!(
            s,
            vec!["We test it.", "It works on a board.", "3 runs were done."]
        );
    }

    #[test]
    fn whole_words_only() {
        let hay = normalize("we use online learning here");
        assert!(contains_words(&hay, "online learning"));
        assert!(!contains_words(&hay, "line"));
    }
}
