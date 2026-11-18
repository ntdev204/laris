//! Document ingestion (SR-H13): a text, Markdown or PDF file becomes a [`Document`] and its passages.
//!
//! * [`read_document`] reads one file with a size limit and says what it is. Text is read as lossy UTF-8 with
//!   universal newlines (the same as the vault does), so the character offsets of a passage are the same
//!   everywhere. A PDF goes through [`pdf`], which reads the text layer and nothing else.
//! * [`passages::split`] cuts the text into passages with exact character spans.
//!
//! A scanned PDF has no text layer. It is refused with a message that says the stage-3 OCR model is needed, not
//! guessed at.

pub mod inflate;
pub mod passages;
pub mod pdf;

use sha2::{Digest, Sha256};
use std::path::Path;

pub use passages::{Passage, split};
pub use pdf::{PdfError, PdfLimits};

/// What a file is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    /// Plain text.
    Text,
    /// Markdown.
    Markdown,
    /// PDF with a text layer.
    Pdf,
}

impl Kind {
    /// The word written in a Source note.
    pub fn as_str(self) -> &'static str {
        match self {
            Kind::Text => "text",
            Kind::Markdown => "markdown",
            Kind::Pdf => "pdf",
        }
    }
}

/// A document ready to be cut into passages.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Document {
    /// What it was.
    pub kind: Kind,
    /// A title: a Markdown title, or the file name without its extension.
    pub title: String,
    /// The text. For a PDF, the text of the pages joined by a blank line.
    pub text: String,
    /// SHA-256 of the file's bytes.
    pub sha256: String,
}

/// A file that cannot be ingested. The message is for the person and the model.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum IngestError {
    /// The extension is not one of `txt`, `md`, `markdown`, `pdf`.
    #[error("cannot ingest this kind of file ({0}); use .txt, .md or .pdf")]
    Unsupported(String),
    /// The file cannot be read.
    #[error("cannot read the file: {0}")]
    Unreadable(String),
    /// The file is larger than the limit.
    #[error("the file is larger than {0} bytes")]
    TooLarge(u64),
    /// A PDF problem.
    #[error(transparent)]
    Pdf(#[from] PdfError),
    /// The file holds no text.
    #[error("the file holds no text")]
    Empty,
}

/// Reads `path` with at most `max_bytes` bytes.
pub fn read_document(
    path: &Path,
    max_bytes: u64,
    limits: &PdfLimits,
) -> Result<Document, IngestError> {
    let extension = path
        .extension()
        .and_then(|e| e.to_str())
        .map(str::to_lowercase)
        .unwrap_or_default();
    let kind = match extension.as_str() {
        "txt" | "text" => Kind::Text,
        "md" | "markdown" => Kind::Markdown,
        "pdf" => Kind::Pdf,
        other => return Err(IngestError::Unsupported(other.to_owned())),
    };
    let meta =
        std::fs::metadata(path).map_err(|e| IngestError::Unreadable(e.kind().to_string()))?;
    if meta.len() > max_bytes {
        return Err(IngestError::TooLarge(max_bytes));
    }
    let bytes = std::fs::read(path).map_err(|e| IngestError::Unreadable(e.kind().to_string()))?;
    document_from(kind, path, &bytes, limits)
}

/// A document from bytes already read.
pub fn document_from(
    kind: Kind,
    path: &Path,
    bytes: &[u8],
    limits: &PdfLimits,
) -> Result<Document, IngestError> {
    let stem = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("document")
        .to_owned();
    let sha256: String = Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    let (text, title) = match kind {
        Kind::Pdf => (pdf::extract(bytes, limits)?.text(), stem),
        Kind::Text | Kind::Markdown => {
            let raw = String::from_utf8_lossy(bytes)
                .replace("\r\n", "\n")
                .replace('\r', "\n");
            let title = if kind == Kind::Markdown {
                markdown_title(&raw).unwrap_or(stem)
            } else {
                stem
            };
            (raw, title)
        }
    };
    if text.trim().is_empty() {
        return Err(IngestError::Empty);
    }
    Ok(Document {
        kind,
        title,
        text,
        sha256,
    })
}

/// The `title` of the front matter, or the first level-one heading.
fn markdown_title(text: &str) -> Option<String> {
    let mut lines = text.lines();
    if lines.clone().next() == Some("---") {
        lines.next();
        for line in lines.by_ref() {
            if line == "---" {
                break;
            }
            if let Some(v) = line.strip_prefix("title:") {
                let v = v.trim().trim_matches(['"', '\'']).trim();
                if !v.is_empty() {
                    return Some(v.to_owned());
                }
            }
        }
    }
    text.lines()
        .find_map(|l| l.strip_prefix("# "))
        .map(|t| t.trim().to_owned())
        .filter(|t| !t.is_empty())
}
