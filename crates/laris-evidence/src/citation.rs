//! Citations in an answer: `[source #rank]` (workspace evidence, rule E-2) and `[brain: Title]` (brain evidence).

use crate::text::mask_code;
use regex::Regex;
use std::sync::LazyLock;

/// What a citation points at.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Target {
    /// A retrieved hit: its source and its rank in the tool result.
    Workspace {
        /// The source as written.
        source: String,
        /// The rank as written.
        rank: u32,
    },
    /// A guidance note the server listed in `LarisMeta.brain`.
    Brain {
        /// The title as written.
        title: String,
    },
}

/// One citation found in an answer.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Citation {
    /// What it points at.
    pub target: Target,
    /// Byte offset of its `[`.
    pub start: usize,
    /// Byte offset after its `]`.
    pub end: usize,
    /// The verbatim quote standing right before it, if the answer has one.
    pub quote: Option<String>,
}

static WORKSPACE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\[([^\[\]\n#]{1,200}?)\s+#(\d{1,6})\]").expect("valid citation pattern")
});
static BRAIN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)\[brain:\s*([^\[\]\n]{1,200}?)\s*\]").expect("valid brain pattern")
});

/// The citations of `answer`, in order. Code (fenced or inline) is not read.
pub fn parse(answer: &str) -> Vec<Citation> {
    parse_masked(answer, &mask_code(answer))
}

pub(crate) fn parse_masked(answer: &str, masked: &str) -> Vec<Citation> {
    let mut found = Vec::new();
    for caps in WORKSPACE.captures_iter(masked) {
        let whole = caps.get(0).expect("whole match");
        let Ok(rank) = caps[2].parse::<u32>() else {
            continue;
        };
        found.push(Citation {
            target: Target::Workspace {
                source: caps[1].trim().to_string(),
                rank,
            },
            start: whole.start(),
            end: whole.end(),
            quote: quote_before(answer, whole.start()),
        });
    }
    for caps in BRAIN.captures_iter(masked) {
        let whole = caps.get(0).expect("whole match");
        found.push(Citation {
            target: Target::Brain {
                title: caps[1].trim().to_string(),
            },
            start: whole.start(),
            end: whole.end(),
            quote: quote_before(answer, whole.start()),
        });
    }
    found.sort_by_key(|c| c.start);
    found
}

/// The quoted text that ends right before `start` (`"..." [src #1]`, also with curly or angle quotes).
fn quote_before(text: &str, start: usize) -> Option<String> {
    let before = text[..start]
        .trim_end()
        .trim_end_matches(['.', ',', ';', ':'])
        .trim_end();
    let closer = before.chars().last()?;
    let opener = match closer {
        '"' => '"',
        '\u{201D}' => '\u{201C}',
        '\u{00BB}' => '\u{00AB}',
        _ => return None,
    };
    let body = &before[..before.len() - closer.len_utf8()];
    let open = body.rfind(opener)?;
    let quote = body[open + opener.len_utf8()..].trim();
    (!quote.is_empty() && quote.chars().count() <= 2000).then(|| quote.to_string())
}
