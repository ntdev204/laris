//! System skills chosen by context (SR-S4).
//!
//! `.laris/skills/<name>/SKILL.md` holds task knowledge: when to use it, how to do it. The server does not put the
//! skills, or a list of them, in the prompt. For each turn it reads the user's request, picks the one skill that
//! fits and adds only that skill's text, marked as low authority; when none fits clearly, the prompt carries none.
//!
//! A skill is picked in one of two ways:
//! * the user names it (`/research-gap is this novel?`): that skill, whatever the scores say;
//! * otherwise BM25 over each skill's name and description against the request; the best skill is used when its
//!   score reaches the minimum and beats the runner-up by the margin. Matching is by words, so a request in a
//!   language the descriptions are not written in only reaches a skill by name.
//!
//! Skills are outside `integrity.lock` (generation 1 left them out: they are data, lowest authority, changed
//! without the owner's review). Nothing in a skill can change a rule: the section says so and sits below the policy.

use super::yaml;
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;

const DIR: &str = ".laris/skills";
const MAX_FILE: u64 = 64 * 1024;
const K1: f64 = 1.5;
const B: f64 = 0.75;
/// A word of the skill's name counts as this many words of its description.
const NAME_WEIGHT: usize = 3;

/// One skill.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Skill {
    /// Name, equal to its folder.
    pub name: String,
    /// When to use it.
    pub description: String,
    /// The text after the front matter, cut to the budget.
    pub body: String,
}

/// How a skill was chosen.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Why {
    /// The user named it.
    Named,
    /// Its description matched the request with this score.
    Matched(f64),
}

/// A skill chosen for a turn.
#[derive(Debug, Clone, Copy)]
pub struct Selection<'a> {
    /// The skill.
    pub skill: &'a Skill,
    /// Why.
    pub why: Why,
}

/// Settings of the selection.
#[derive(Debug, Clone, PartialEq)]
pub struct SkillSettings {
    /// Choose skills at all.
    pub enabled: bool,
    /// Lowest BM25 score that selects a skill.
    pub min_score: f64,
    /// The best score must be at least this many times the runner-up's.
    pub margin: f64,
    /// Most characters of one skill added to the prompt.
    pub max_chars: usize,
}

impl Default for SkillSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            min_score: 5.0,
            margin: 1.2,
            max_chars: 12_000,
        }
    }
}

/// The skills of a project.
#[derive(Debug, Clone, Default)]
pub struct Skills {
    settings: SkillSettings,
    list: Vec<Skill>,
    lengths: Vec<usize>,
    postings: BTreeMap<String, Vec<(usize, u32)>>,
    avg: f64,
    /// Folders that were skipped, with the reason (never content).
    pub problems: Vec<String>,
}

fn tokens(text: &str) -> Vec<String> {
    text.split(|c: char| !c.is_alphanumeric())
        .filter(|w| w.chars().count() >= 2)
        .map(str::to_lowercase)
        .collect()
}

fn valid_name(name: &str) -> bool {
    (2..=63).contains(&name.len())
        && name.as_bytes()[0].is_ascii_alphanumeric()
        && name
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

/// `(front matter, body)` of a `---` fenced document.
fn split_front_matter(text: &str) -> Option<(&str, &str)> {
    let rest = text.strip_prefix("---\n")?;
    let end = rest.find("\n---")?;
    let after = &rest[end + 4..];
    Some((&rest[..end], after.strip_prefix('\n').unwrap_or(after)))
}

fn read_skill(dir: &Path, name: &str, max_chars: usize) -> Result<Skill, String> {
    let path = dir.join("SKILL.md");
    let meta = fs::symlink_metadata(&path).map_err(|_| "no SKILL.md".to_owned())?;
    if !meta.is_file() || meta.len() > MAX_FILE {
        return Err("SKILL.md is not a regular file of reasonable size".into());
    }
    let text = fs::read_to_string(&path).map_err(|_| "SKILL.md is not text".to_owned())?;
    let (front, body) = split_front_matter(&text).ok_or("no front matter")?;
    let value = yaml::parse(front).map_err(|e| format!("front matter: {e}"))?;
    if value.get("name").and_then(|v| v.as_str()) != Some(name) {
        return Err("name differs from the folder".into());
    }
    let description = value
        .get("description")
        .and_then(|v| v.as_str())
        .map(|d| d.split_whitespace().collect::<Vec<_>>().join(" "))
        .filter(|d| d.chars().count() >= 10)
        .ok_or("description is missing or too short")?;
    let mut body = body.trim().to_owned();
    if body.chars().count() > max_chars {
        body = body.chars().take(max_chars).collect::<String>()
            + "\n[... cut to fit the skill budget]";
    }
    Ok(Skill {
        name: name.to_owned(),
        description,
        body,
    })
}

impl Skills {
    /// Reads the skills under `root`. A folder that does not load is skipped and listed in `problems`.
    pub fn load(root: &Path, settings: SkillSettings) -> Self {
        let mut problems = Vec::new();
        let mut list = Vec::new();
        let dir = root.join(DIR);
        let mut folders: Vec<_> = fs::read_dir(&dir)
            .map(|d| d.filter_map(Result::ok).collect())
            .unwrap_or_default();
        folders.sort_by_key(fs::DirEntry::file_name);
        for entry in folders {
            let name = entry.file_name().to_string_lossy().into_owned();
            if !entry.file_type().is_ok_and(|t| t.is_dir()) {
                continue;
            }
            if !valid_name(&name) {
                problems.push(format!("{name}: not a skill name"));
                continue;
            }
            match read_skill(&entry.path(), &name, settings.max_chars) {
                Ok(skill) => list.push(skill),
                Err(why) => problems.push(format!("{name}: {why}")),
            }
        }
        let mut lengths = Vec::new();
        let mut postings: BTreeMap<String, Vec<(usize, u32)>> = BTreeMap::new();
        for (doc, skill) in list.iter().enumerate() {
            let mut words = tokens(&skill.description);
            let name_words = tokens(&skill.name);
            for _ in 0..NAME_WEIGHT {
                words.extend(name_words.iter().cloned());
            }
            let mut counts: BTreeMap<&str, u32> = BTreeMap::new();
            for w in &words {
                *counts.entry(w).or_insert(0) += 1;
            }
            for (w, tf) in counts {
                postings.entry(w.to_owned()).or_default().push((doc, tf));
            }
            lengths.push(words.len());
        }
        let avg = if lengths.is_empty() {
            1.0
        } else {
            lengths.iter().sum::<usize>() as f64 / lengths.len() as f64
        };
        Self {
            settings,
            list,
            lengths,
            postings,
            avg,
            problems,
        }
    }

    /// The skills, by name.
    pub fn names(&self) -> Vec<&str> {
        self.list.iter().map(|s| s.name.as_str()).collect()
    }

    /// Number of skills.
    pub fn len(&self) -> usize {
        self.list.len()
    }

    /// Whether there are none.
    pub fn is_empty(&self) -> bool {
        self.list.is_empty()
    }

    /// BM25 score of every skill for `query`, best first (ties by name).
    pub fn scores(&self, query: &str) -> Vec<(&str, f64)> {
        let terms: BTreeSet<String> = tokens(query).into_iter().collect();
        let n = self.list.len() as f64;
        let mut score = vec![0.0_f64; self.list.len()];
        for term in &terms {
            let Some(posting) = self.postings.get(term) else {
                continue;
            };
            let df = posting.len() as f64;
            let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
            for &(doc, tf) in posting {
                let tf = f64::from(tf);
                let norm = tf + K1 * (1.0 - B + B * self.lengths[doc] as f64 / self.avg);
                score[doc] += idf * tf * (K1 + 1.0) / norm;
            }
        }
        let mut out: Vec<(&str, f64)> = self
            .list
            .iter()
            .zip(score)
            .map(|(s, v)| (s.name.as_str(), v))
            .collect();
        out.sort_by(|a, b| b.1.total_cmp(&a.1).then_with(|| a.0.cmp(b.0)));
        out
    }

    /// The skill for a request, or none. `request` is what the user asked (their message and the task line).
    pub fn select(&self, request: &str) -> Option<Selection<'_>> {
        if !self.settings.enabled || self.list.is_empty() {
            return None;
        }
        // a skill the user names wins
        for word in request.split_whitespace() {
            let name = word
                .strip_prefix('/')
                .map(|w| w.trim_end_matches(|c: char| !c.is_ascii_alphanumeric()));
            if let Some(skill) = name.and_then(|n| self.list.iter().find(|s| s.name == n)) {
                return Some(Selection {
                    skill,
                    why: Why::Named,
                });
            }
        }
        let ranked = self.scores(request);
        let (best, top) = *ranked.first()?;
        let second = ranked.get(1).map_or(0.0, |r| r.1);
        if top < self.settings.min_score || top < second * self.settings.margin {
            return None;
        }
        let skill = self.list.iter().find(|s| s.name == best)?;
        Some(Selection {
            skill,
            why: Why::Matched(top),
        })
    }
}
