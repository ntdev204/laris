//! External readers for PDFs the built-in reader cannot use (T261).
//!
//! The built-in reader (`pdf`) handles a clean text layer and refuses the rest. Real papers are often something
//! else: fonts without a Unicode map, filters it does not decode, or pages that are only pictures. For those this
//! module runs programs that are already on the machine and named in `vault.ocr`:
//!
//! 1. `textCommand` (`pdftotext`) prints the text layer with its own, fuller PDF reader;
//! 2. when that gives nothing readable, `renderCommand` (`pdftoppm`) turns the first pages into PNG images and
//!    `ocrCommand` (`tesseract`) reads each one.
//!
//! Nothing is guessed: a step that is missing, fails or times out says so, and the caller reports every reason. The
//! programs get the PDF as a file in a private temporary folder, never a shell line, and are killed at the timeout.

use laris_config::settings::Ocr;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

/// How the text of a document was obtained.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Method {
    /// The built-in reader.
    TextLayer,
    /// `textCommand`.
    Pdftotext,
    /// `renderCommand` and `ocrCommand`.
    Ocr,
}

impl Method {
    /// The word reported with the document.
    pub fn as_str(self) -> &'static str {
        match self {
            Method::TextLayer => "text_layer",
            Method::Pdftotext => "pdftotext",
            Method::Ocr => "ocr",
        }
    }
}

/// Whether `text` looks like language and not like a font that decoded to noise or an empty page.
pub fn readable(text: &str) -> bool {
    let (mut total, mut good, mut bad) = (0usize, 0usize, 0usize);
    for c in text.chars().filter(|c| !c.is_whitespace()) {
        total += 1;
        if c == '\u{FFFD}' || c.is_control() || ('\u{E000}'..='\u{F8FF}').contains(&c) {
            bad += 1;
        } else if c.is_alphanumeric() || ".,;:!?()[]{}'\"%+-=/<>&*_–—’“”".contains(c) {
            good += 1;
        }
    }
    total >= 40 && bad * 50 <= total && good * 10 >= total * 7
}

static COUNTER: AtomicU64 = AtomicU64::new(0);

/// A private temporary folder, removed when dropped.
struct Scratch(PathBuf);

impl Scratch {
    fn new() -> std::io::Result<Self> {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_nanos());
        let dir = std::env::temp_dir().join(format!(
            "laris-ocr-{}-{}-{nanos}",
            std::process::id(),
            COUNTER.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(&dir)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700))?;
        }
        Ok(Self(dir))
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

/// Runs `program` with `args`, at most `limit`; returns its standard output.
fn run(program: &str, args: &[&str], cwd: &Path, limit: Duration) -> Result<Vec<u8>, String> {
    let mut child = Command::new(program)
        .args(args)
        .current_dir(cwd)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("{program} could not start ({})", e.kind()))?;
    let mut out = child.stdout.take();
    let reader = std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(o) = out.as_mut() {
            let _ = std::io::Read::read_to_end(o, &mut buf);
        }
        buf
    });
    let start = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                let buf = reader.join().unwrap_or_default();
                return if status.success() {
                    Ok(buf)
                } else {
                    Err(format!("{program} failed ({status})"))
                };
            }
            Ok(None) if start.elapsed() < limit => std::thread::sleep(Duration::from_millis(20)),
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("{program} took longer than {}s", limit.as_secs()));
            }
            Err(e) => return Err(format!("{program} could not be waited for ({})", e.kind())),
        }
    }
}

/// The text of `bytes` (a PDF) through the external programs, and the method that produced it. Every step that did
/// not work adds its reason to the error.
pub fn read(bytes: &[u8], cfg: &Ocr) -> Result<(String, Method), String> {
    if !cfg.enabled {
        return Err("external PDF readers are off (vault.ocr.enabled)".into());
    }
    let scratch = Scratch::new().map_err(|e| format!("no temporary folder ({})", e.kind()))?;
    let pdf = scratch.0.join("input.pdf");
    std::fs::write(&pdf, bytes)
        .map_err(|e| format!("cannot write a temporary file ({})", e.kind()))?;
    let limit = Duration::from_secs(u64::from(cfg.timeout_seconds));
    let mut reasons: Vec<String> = Vec::new();

    if !cfg.text_command.is_empty() {
        match run(
            &cfg.text_command,
            &["-layout", "-enc", "UTF-8", "input.pdf", "-"],
            &scratch.0,
            limit,
        ) {
            Ok(out) => {
                let text = String::from_utf8_lossy(&out).replace('\u{c}', "\n\n");
                if readable(&text) {
                    return Ok((text, Method::Pdftotext));
                }
                reasons.push(format!("{} found no readable text layer", cfg.text_command));
            }
            Err(e) => reasons.push(e),
        }
    }
    if cfg.render_command.is_empty() || cfg.ocr_command.is_empty() {
        reasons.push("OCR is not configured (vault.ocr.renderCommand, ocrCommand)".into());
        return Err(reasons.join("; "));
    }
    let dpi = cfg.dpi.to_string();
    let last = cfg.max_pages.to_string();
    if let Err(e) = run(
        &cfg.render_command,
        &["-r", &dpi, "-l", &last, "-png", "input.pdf", "page"],
        &scratch.0,
        limit,
    ) {
        reasons.push(e);
        return Err(reasons.join("; "));
    }
    let mut images: Vec<PathBuf> = std::fs::read_dir(&scratch.0)
        .map_err(|e| format!("cannot list the rendered pages ({})", e.kind()))?
        .filter_map(Result::ok)
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == "png"))
        .collect();
    images.sort();
    if images.is_empty() {
        reasons.push(format!("{} produced no page images", cfg.render_command));
        return Err(reasons.join("; "));
    }
    let mut pages = Vec::new();
    let mut failure = None;
    for image in &images {
        let name = image
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or_default();
        match run(
            &cfg.ocr_command,
            &[name, "stdout", "-l", &cfg.languages],
            &scratch.0,
            limit,
        ) {
            Ok(out) => pages.push(String::from_utf8_lossy(&out).trim().to_owned()),
            Err(e) => {
                failure = Some(e);
                break;
            }
        }
    }
    let text = pages.join("\n\n");
    if readable(&text) {
        return Ok((text, Method::Ocr));
    }
    reasons.push(
        failure.unwrap_or_else(|| format!("{} read no text from the pages", cfg.ocr_command)),
    );
    Err(reasons.join("; "))
}
