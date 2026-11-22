//! Step 2, extraction: what the model is shown of a paper and how its answer is read back.
//!
//! The excerpts are taken by rule, not by the model: the gap-bearing sections whole (limitations, future work,
//! conclusion, discussion), then every sentence of the other sections that carries a limitation cue, then the
//! abstract and the start of the introduction, each block headed by its section name, until the budget is spent.
//! The model returns one JSON record; [`parse_record`] reads it leniently (a `<think>` block, prose around the
//! object or a trailing comma are tolerated) and never invents a field it did not give.

use crate::sections::{self, Section};
use crate::text::sentences;
use regex::RegexBuilder;
use serde::{Deserialize, Serialize};

/// A paper as the analysis takes it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Paper {
    /// Register id: `P1`, `P2`, ...
    pub id: String,
    /// Title.
    pub title: String,
    /// Where it came from (a file or an address).
    pub origin: String,
    /// Year of publication, when known.
    #[serde(default)]
    pub year: Option<u32>,
    /// How the text was obtained: `text_layer`, `pdftotext`, `ocr` or `abstract`.
    #[serde(default)]
    pub read_by: String,
    /// The full text.
    pub text: String,
}

/// One limitation or future-work item as the model gave it.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct RawItem {
    /// Short paraphrase.
    #[serde(default)]
    pub text: String,
    /// The phrase the model says it copied.
    #[serde(default)]
    pub quote: String,
}

/// The record the model returns for one paper.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Record {
    /// The problem addressed.
    #[serde(default)]
    pub problem: String,
    /// The method.
    #[serde(default)]
    pub method: String,
    /// Hardware, system, data or setting of the evaluation.
    #[serde(default, alias = "platform", alias = "data")]
    pub setting: String,
    /// Main result.
    #[serde(default)]
    pub result: String,
    /// Limitations the authors state.
    #[serde(default)]
    pub limitations: Vec<RawItem>,
    /// Future work the authors state.
    #[serde(default)]
    pub future_work: Vec<RawItem>,
}

fn clip(text: &str, max: usize) -> &str {
    if text.len() <= max {
        return text;
    }
    let mut end = max;
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    &text[..end]
}

/// The excerpts of `paper` for the extraction prompt, at most `budget` characters, and the list of blocks taken
/// (section name and characters), for the run log.
pub fn excerpts(
    text: &str,
    secs: &[Section],
    cues: &[String],
    budget: usize,
) -> (String, Vec<(String, usize)>) {
    let cue = cues
        .iter()
        .filter_map(|c| RegexBuilder::new(c).case_insensitive(true).build().ok())
        .collect::<Vec<_>>();
    let whole = ["limitations", "future_work", "conclusion", "discussion"];
    let mut blocks: Vec<(String, String)> = Vec::new();
    for name in whole {
        let t = sections::text_of(text, secs, name);
        if !t.trim().is_empty() {
            blocks.push((name.to_owned(), clip(&t, 6000).to_owned()));
        }
    }
    let skip = [
        "references",
        "acknowledgements",
        "limitations",
        "future_work",
        "conclusion",
        "discussion",
    ];
    let mut cue_lines = Vec::new();
    for s in secs.iter().filter(|s| !skip.contains(&s.name.as_str())) {
        let body = text.get(s.start..s.end).unwrap_or("");
        for sentence in sentences(body) {
            if sentence.len() < 600 && cue.iter().any(|r| r.is_match(&sentence)) {
                cue_lines.push(format!("({}) {}", s.name, sentence));
            }
        }
    }
    if !cue_lines.is_empty() {
        blocks.push(("cue sentences".to_owned(), cue_lines.join("\n")));
    }
    let front = {
        let a = sections::text_of(text, secs, "abstract");
        if a.trim().is_empty() {
            sections::text_of(text, secs, "front")
        } else {
            a
        }
    };
    blocks.push(("abstract".to_owned(), clip(&front, 2500).to_owned()));
    let intro = sections::text_of(text, secs, "introduction");
    if !intro.trim().is_empty() {
        blocks.push(("introduction".to_owned(), clip(&intro, 2500).to_owned()));
    }
    let mut out = String::new();
    let mut taken = Vec::new();
    for (name, body) in blocks {
        let room = budget.saturating_sub(out.len());
        if room < 200 {
            break;
        }
        let piece = clip(&body, room.saturating_sub(40));
        out.push_str(&format!("[SECTION: {name}]\n{piece}\n\n"));
        taken.push((name, piece.len()));
    }
    (out, taken)
}

/// Fills the extraction prompt.
pub fn prompt(template: &str, excerpts: &str) -> String {
    template.replace("{excerpts}", excerpts)
}

/// Reads the model's answer: the JSON object in it, or why there is none.
pub fn parse_record(raw: &str) -> Result<Record, String> {
    let mut text = raw.to_owned();
    while let (Some(a), Some(b)) = (text.find("<think>"), text.find("</think>")) {
        if b < a {
            break;
        }
        text.replace_range(a..b + "</think>".len(), "");
    }
    let start = text.find('{').ok_or("the answer holds no JSON object")?;
    let end = text.rfind('}').ok_or("the JSON object is not closed")?;
    if end <= start {
        return Err("the JSON object is not closed".into());
    }
    let body = &text[start..=end];
    let attempt = |s: &str| serde_json::from_str::<serde_json::Value>(s);
    let value = attempt(body)
        .or_else(|_| {
            let fixed = regex::Regex::new(r",\s*([}\]])")
                .map(|r| r.replace_all(body, "$1").into_owned())
                .unwrap_or_else(|_| body.to_owned());
            attempt(&fixed)
        })
        .map_err(|e| format!("the JSON object does not parse: {e}"))?;
    // items may come as plain strings
    let mut value = value;
    for key in ["limitations", "future_work"] {
        // one item given as a plain string instead of a list
        if let Some(v) = value.get_mut(key)
            && v.is_string()
        {
            *v = serde_json::json!([v.clone()]);
        }
        if let Some(list) = value.get_mut(key).and_then(|v| v.as_array_mut()) {
            for item in list.iter_mut() {
                if let Some(s) = item.as_str() {
                    *item = serde_json::json!({"text": s, "quote": ""});
                }
            }
        }
    }
    for key in ["problem", "method", "setting", "platform", "result"] {
        if let Some(v) = value.get_mut(key)
            && !v.is_string()
        {
            *v = serde_json::Value::String(v.to_string());
        }
    }
    serde_json::from_value(value).map_err(|e| format!("the record has the wrong shape: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_record_is_read_around_think_and_prose() {
        let one =
            parse_record("{\"limitations\": \"only one platform\", \"future_work\": \"more\"}")
                .unwrap();
        assert_eq!(one.limitations[0].text, "only one platform");
        let raw = "<think>hm</think>Here: {\"problem\": \"p\", \"platform\": \"MCU\", \"limitations\": [\"slow\", {\"text\": \"t\", \"quote\": \"q\"},], \"future_work\": []}";
        let r = parse_record(raw).unwrap();
        assert_eq!(r.setting, "MCU");
        assert_eq!(r.limitations.len(), 2);
        assert_eq!(r.limitations[0].text, "slow");
    }

    #[test]
    fn no_object_is_an_error() {
        assert!(parse_record("I cannot").is_err());
    }

    #[test]
    fn excerpts_put_limitations_first_and_respect_the_budget() {
        let text = "Abstract—We do X.\nI. INTRODUCTION\nWhy.\nII. METHOD\nWe assume no wind. This is a limitation of our model.\nVI. LIMITATIONS\nOnly one platform.\nREFERENCES\n[1] A.\n";
        let secs = sections::split(text);
        let (e, taken) = excerpts(text, &secs, &["limitation".into()], 10_000);
        assert!(e.starts_with("[SECTION: limitations]"));
        assert!(e.contains("(method) This is a limitation of our model."));
        assert!(taken.iter().any(|(n, _)| n == "abstract"));
        let (small, _) = excerpts(text, &secs, &["limitation".into()], 250);
        assert!(small.len() <= 250);
    }
}
