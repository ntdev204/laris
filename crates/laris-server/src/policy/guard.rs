//! The outbound guard (SR-S4): what the model says is checked before the client sees it.
//!
//! * [`SecretRedactor`] hides credentials: values of environment variables whose name marks them as secret, known
//!   token shapes, and the absolute paths of the server's own folders.
//! * [`LeakDetector`] recognises internal text (the system prompt, the rules) in an answer by hashed word shingles
//!   and by a per-session canary token, without keeping the plaintext a second time.
//! * [`StreamGuard`] applies both to streamed text with a small hold-back buffer, so a secret or a leaked passage
//!   is never sent before the guard has seen all of it. Once a leak is found the rest of the answer is dropped.
//!
//! This is a rule over text, not a proof: a model that paraphrases the prompt, or leaks it by translation, passes
//! the shingle test. The confidentiality suite measures what gets through (`tests/policy.rs`), and the limit it
//! sets is the one SR-S4 promises.

use regex::Regex;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::sync::{Arc, LazyLock};

/// Secrets shorter than this are not treated as secrets (they would match ordinary words).
pub const MIN_SECRET_LENGTH: usize = 8;

/// The text put where something was hidden or an answer was stopped.
pub const LEAK_BLOCKED: &str =
    "[Content blocked: the answer contained internal configuration information.]";
/// Put where a credential was.
pub const SECRET_REDACTED: &str = "[SECRET HIDDEN]";

static WORD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\w+").expect("valid"));

/// Settings of the guard.
#[derive(Debug, Clone)]
pub struct GuardSettings {
    /// Environment variables whose name holds one of these (upper-case) are secrets.
    pub secret_env_markers: Vec<String>,
    /// Variables that are secrets whatever their name.
    pub extra_secret_env: Vec<String>,
    /// Shapes of credentials.
    pub secret_patterns: Vec<String>,
    /// Detect internal text in answers.
    pub leak_detection: bool,
    /// Words in one shingle.
    pub leak_shingle_words: usize,
    /// Shingle matches that make a leak.
    pub leak_min_shingles: usize,
    /// Most shingles kept; later text is only partly covered.
    pub leak_max_shingles: usize,
    /// Per-session canary tokens.
    pub canary_enabled: bool,
    /// Characters held back while streaming.
    pub stream_holdback_chars: usize,
    /// Hide the server's own absolute paths.
    pub redact_paths: bool,
}

impl Default for GuardSettings {
    fn default() -> Self {
        Self {
            secret_env_markers: [
                "KEY",
                "TOKEN",
                "SECRET",
                "PASSWORD",
                "CREDENTIAL",
                "AUTH",
                // the server's own secrets are named after what they are, not after a marker
                "MASTER",
                "DSN",
            ]
            .map(str::to_owned)
            .to_vec(),
            extra_secret_env: Vec::new(),
            secret_patterns: [
                r"sk-[A-Za-z0-9_-]{16,}",
                r"hf_[A-Za-z0-9]{20,}",
                r"gh[pousr]_[A-Za-z0-9]{20,}",
                r"AKIA[0-9A-Z]{16}",
                r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}",
                r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
            ]
            .map(str::to_owned)
            .to_vec(),
            leak_detection: true,
            leak_shingle_words: 7,
            leak_min_shingles: 2,
            leak_max_shingles: 200_000,
            canary_enabled: true,
            stream_holdback_chars: 160,
            redact_paths: true,
        }
    }
}

/// Hides credentials and internal paths.
#[derive(Debug, Clone)]
pub struct SecretRedactor {
    values: Vec<String>,
    patterns: Vec<Regex>,
    paths: Vec<(String, &'static str)>,
}

impl SecretRedactor {
    /// Builds the redactor from the settings, the process environment and the folders to hide.
    pub fn new<I>(
        settings: &GuardSettings,
        environ: I,
        project_root: Option<&str>,
        home: Option<&str>,
    ) -> Result<Self, regex::Error>
    where
        I: IntoIterator<Item = (String, String)>,
    {
        let markers: Vec<String> = settings
            .secret_env_markers
            .iter()
            .map(|m| m.to_uppercase())
            .collect();
        let mut values: Vec<String> = environ
            .into_iter()
            .filter(|(name, value)| {
                value.chars().count() >= MIN_SECRET_LENGTH
                    && (settings.extra_secret_env.contains(name)
                        || markers.iter().any(|m| name.to_uppercase().contains(m)))
            })
            .map(|(_, value)| value)
            .collect();
        values.sort_by_key(|v| std::cmp::Reverse(v.len()));
        values.dedup();
        let patterns = settings
            .secret_patterns
            .iter()
            .map(|p| Regex::new(p))
            .collect::<Result<_, _>>()?;
        let mut paths = Vec::new();
        if settings.redact_paths {
            if let Some(root) = project_root.filter(|r| r.len() > 1) {
                paths.push((root.trim_end_matches('/').to_owned(), "."));
            }
            if let Some(home) = home.filter(|h| h.len() > 1) {
                paths.push((home.trim_end_matches('/').to_owned(), "~"));
            }
        }
        Ok(Self {
            values,
            patterns,
            paths,
        })
    }

    /// `text` with credentials and internal paths hidden, and how many credentials were hidden.
    pub fn redact(&self, text: &str) -> (String, usize) {
        let mut out = text.to_owned();
        let mut count = 0;
        for value in &self.values {
            if out.contains(value.as_str()) {
                count += out.matches(value.as_str()).count();
                out = out.replace(value.as_str(), SECRET_REDACTED);
            }
        }
        for pattern in &self.patterns {
            let found = pattern.find_iter(&out).count();
            if found > 0 {
                count += found;
                out = pattern.replace_all(&out, SECRET_REDACTED).into_owned();
            }
        }
        for (path, to) in &self.paths {
            if out.contains(path.as_str()) {
                out = out
                    .replace(
                        &format!("{path}/"),
                        &if *to == "." {
                            String::new()
                        } else {
                            format!("{to}/")
                        },
                    )
                    .replace(path.as_str(), to);
            }
        }
        (out, count)
    }
}

static SPACED: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\b\w(?: \w\b){2,}").expect("valid"));
static DOTTED: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\b\w(?:[-._·•*|/\\,;:]\w\b){2,}").expect("valid"));

/// Characters that show nothing: zero-width and direction marks, soft hyphen, byte order mark.
fn invisible(c: char) -> bool {
    matches!(c, '\u{ad}' | '\u{200b}'..='\u{200f}' | '\u{202a}'..='\u{202e}' | '\u{2060}'..='\u{2064}' | '\u{feff}')
}

/// A letter that looks like a Latin one (Cyrillic, Greek, full-width) as that Latin letter.
fn confusable(c: char) -> char {
    match c {
        'а' | 'α' => 'a',
        'в' => 'b',
        'с' | 'ϲ' => 'c',
        'е' | 'ё' => 'e',
        'һ' => 'h',
        'і' | 'ι' | 'ї' => 'i',
        'ј' => 'j',
        'к' | 'κ' => 'k',
        'м' => 'm',
        'о' | 'ο' => 'o',
        'р' | 'ρ' => 'p',
        'ѕ' => 's',
        'т' | 'τ' => 't',
        'ν' => 'v',
        'х' | 'χ' => 'x',
        'у' | 'υ' => 'y',
        '\u{ff21}'..='\u{ff3a}' => char::from_u32(c as u32 - 0xff21 + 'A' as u32).unwrap_or(c),
        '\u{ff41}'..='\u{ff5a}' => char::from_u32(c as u32 - 0xff41 + 'a' as u32).unwrap_or(c),
        _ => c,
    }
}

/// The text with the tricks that hide a copy from a word match undone: invisible characters dropped, look-alike
/// letters folded to Latin, and letters spread out (`i g n o r e`, `i.g.n.o.r.e`) joined again. `None` when
/// nothing changed, so the common case costs one scan.
fn plain_view(text: &str) -> Option<String> {
    let mut changed = false;
    let mut folded = String::with_capacity(text.len());
    for c in text.chars() {
        if invisible(c) {
            changed = true;
            continue;
        }
        let f = confusable(c);
        changed |= f != c;
        folded.push(f);
    }
    let mut out = folded;
    for pattern in [&*SPACED, &*DOTTED] {
        if pattern.is_match(&out) {
            changed = true;
            out = pattern
                .replace_all(&out, |m: &regex::Captures<'_>| {
                    m[0].chars()
                        .filter(|c| c.is_alphanumeric())
                        .collect::<String>()
                })
                .into_owned();
        }
    }
    changed.then_some(out)
}

/// Lower-case letters and digits only: the form in which a canary is looked for.
fn bare(text: &str) -> String {
    text.chars()
        .filter(|c| !invisible(*c))
        .map(confusable)
        .filter(|c| c.is_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

fn shingle_hash(words: &[String]) -> u64 {
    let digest = Sha256::digest(words.join(" ").as_bytes());
    u64::from_be_bytes(digest[..8].try_into().expect("a digest has 32 bytes"))
}

fn words_of(text: &str) -> Vec<String> {
    WORD.find_iter(text)
        .map(|m| m.as_str().to_lowercase())
        .collect()
}

/// Recognises internal text in output. Built once from the confidential sources; a per-session canary is added
/// with [`LeakDetector::with_canary`], which shares the shingles.
#[derive(Debug, Clone)]
pub struct LeakDetector {
    shingles: Arc<HashSet<u64>>,
    n: usize,
    min_hits: usize,
    enabled: bool,
    canary: String,
    canary_bare: String,
    /// The budget was reached: later sources are only partly covered.
    pub truncated: bool,
}

impl LeakDetector {
    /// Builds the detector from the texts that must never leave.
    pub fn new<'a>(settings: &GuardSettings, sources: impl IntoIterator<Item = &'a str>) -> Self {
        let n = settings.leak_shingle_words.max(1);
        let mut shingles = HashSet::new();
        let mut truncated = false;
        'sources: for text in sources {
            let words = words_of(text);
            if words.len() < n {
                continue;
            }
            for window in words.windows(n) {
                if shingles.len() >= settings.leak_max_shingles {
                    truncated = true;
                    break 'sources;
                }
                shingles.insert(shingle_hash(window));
            }
        }
        Self {
            shingles: Arc::new(shingles),
            n,
            min_hits: settings.leak_min_shingles.max(1),
            enabled: settings.leak_detection,
            canary: String::new(),
            canary_bare: String::new(),
            truncated,
        }
    }

    /// The same detector with a canary the output must not hold.
    pub fn with_canary(&self, canary: &str) -> Self {
        Self {
            canary: canary.to_owned(),
            canary_bare: bare(canary),
            ..self.clone()
        }
    }

    /// Number of shingles.
    pub fn size(&self) -> usize {
        self.shingles.len()
    }

    /// Whether `text` holds the canary or enough shingles of internal text, also when the copy is spread out,
    /// has invisible characters between its letters or uses look-alike letters.
    pub fn leaked(&self, text: &str) -> bool {
        let plain = plain_view(text);
        if !self.canary.is_empty()
            && (text.contains(&self.canary)
                || bare(plain.as_deref().unwrap_or(text)).contains(&self.canary_bare))
        {
            return true;
        }
        if !self.enabled || self.shingles.is_empty() {
            return false;
        }
        self.shingled(text) || plain.is_some_and(|p| self.shingled(&p))
    }

    fn shingled(&self, text: &str) -> bool {
        let words = words_of(text);
        if words.len() < self.n {
            return false;
        }
        let mut hits = 0;
        for window in words.windows(self.n) {
            if self.shingles.contains(&shingle_hash(window)) {
                hits += 1;
                if hits >= self.min_hits {
                    return true;
                }
            }
        }
        false
    }
}

/// Redactor, detector and counters for one request.
#[derive(Debug, Clone)]
pub struct Guard {
    /// Hides credentials and paths.
    pub redactor: Arc<SecretRedactor>,
    /// Finds internal text.
    pub leak: LeakDetector,
    holdback: usize,
}

impl Guard {
    /// A guard for one request.
    pub fn new(redactor: Arc<SecretRedactor>, leak: LeakDetector, holdback: usize) -> Self {
        Self {
            redactor,
            leak,
            holdback,
        }
    }

    /// Characters the stream guard holds back.
    pub fn holdback(&self) -> usize {
        self.holdback
    }

    /// A stream guard that counts into this guard's request.
    pub fn stream(&self) -> StreamGuard {
        StreamGuard {
            guard: self.clone(),
            buffer: String::new(),
            context: String::new(),
            blocked: false,
            leaks: 0,
            secrets: 0,
        }
    }
}

/// Sanitises streamed text.
#[derive(Debug)]
pub struct StreamGuard {
    guard: Guard,
    buffer: String,
    context: String,
    /// A leak was found: the rest of the answer is dropped.
    pub blocked: bool,
    /// Leaks found (0 or 1).
    pub leaks: usize,
    /// Credentials hidden.
    pub secrets: usize,
}

impl StreamGuard {
    /// Takes more text; returns what is safe to send now.
    pub fn feed(&mut self, delta: &str) -> Vec<String> {
        if self.blocked {
            return Vec::new();
        }
        self.buffer.push_str(delta);
        let mut out = Vec::new();
        loop {
            let chars: Vec<char> = self.buffer.chars().collect();
            if chars.len() <= self.guard.holdback {
                break;
            }
            let mut cut = chars.len() - self.guard.holdback;
            if let Some(space) = chars[..cut].iter().rposition(|c| *c == ' ')
                && space > 0
            {
                cut = space + 1;
            }
            let piece: String = chars[..cut].iter().collect();
            self.buffer = chars[cut..].iter().collect();
            out.extend(self.emit(&piece));
            if self.blocked {
                break;
            }
        }
        out
    }

    /// The end of the text: what was held back.
    pub fn finish(&mut self) -> Vec<String> {
        if self.blocked || self.buffer.is_empty() {
            return Vec::new();
        }
        let piece = std::mem::take(&mut self.buffer);
        self.emit(&piece)
    }

    fn emit(&mut self, piece: &str) -> Vec<String> {
        let window = format!("{}{piece}", self.context);
        if self.guard.leak.leaked(&window) {
            self.blocked = true;
            self.leaks += 1;
            self.buffer.clear();
            return vec![LEAK_BLOCKED.to_owned()];
        }
        let skip = window.chars().count().saturating_sub(400);
        self.context = window.chars().skip(skip).collect();
        let (cleaned, n) = self.guard.redactor.redact(piece);
        self.secrets += n;
        if cleaned.is_empty() {
            Vec::new()
        } else {
            vec![cleaned]
        }
    }
}
