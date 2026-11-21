//! Document ingestion (SR-H13): text, Markdown and PDF into passages whose spans point at the exact source characters.
//! The PDF fixtures are built by hand by `tests/fixtures/ingest/make_pdfs.py`; each has one feature.

use laris_tools::ingest::pdf::{PdfError, PdfLimits, extract};
use laris_tools::ingest::{IngestError, Kind, read_document, split};
use std::path::{Path, PathBuf};

fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/ingest")
        .join(name)
}

const LIMITS: PdfLimits = PdfLimits {
    max_stream_bytes: 1 << 24,
    max_pages: 100,
};

fn pdf(name: &str) -> Result<Vec<String>, PdfError> {
    extract(&std::fs::read(fixture(name)).unwrap(), &LIMITS).map(|t| t.pages)
}

fn temp(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("laris-ingest-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

// ---------------------------------------------------------------- PDF

#[test]
fn a_text_pdf_gives_its_pages_with_lines_kerning_and_encoding() {
    let pages = pdf("report.pdf").unwrap();
    assert_eq!(pages.len(), 2);
    assert_eq!(
        pages[0],
        "Perovskite solar cells reach high efficiency.\nStability under heat remains the main limit.\n\n\
         Encapsulation with glass helps"
    );
    // WinAnsi: \351 is é, \222 is the right single quote; a content array of two streams, one stored
    assert_eq!(
        pages[1],
        "Café results: 25’3 percent\n\nSecond paragraph of page two."
    );
}

#[test]
fn a_font_map_turns_codes_into_the_right_letters_for_simple_and_composite_fonts() {
    let pages = pdf("tounicode.pdf").unwrap();
    // bfchar <01><02><03> = V ạ n; bfrange <04>-<06> = a b c; a two-byte range <0010>-<0014> = A B C D E
    assert_eq!(pages[0], "Vạn\nabc\n\nABC DE");
}

#[test]
fn objects_inside_an_object_stream_are_read() {
    assert_eq!(pdf("objstm.pdf").unwrap(), ["Read from an object stream."]);
}

#[test]
fn a_long_compressed_text_layer_comes_out_whole() {
    let pages = pdf("long.pdf").unwrap();
    let lines: Vec<String> = (0..300)
        .map(|i| {
            format!(
                "Line {i}: measurement {} of sample {}{i} is recorded in table {}.",
                i * 7 % 13,
                char::from(b'A' + (i % 26) as u8),
                i % 9
            )
        })
        .collect();
    assert_eq!(pages[0], lines.join("\n"));
}

#[test]
fn a_scan_encryption_an_unmapped_font_and_other_filters_each_say_what_they_are() {
    assert_eq!(pdf("scan.pdf"), Err(PdfError::NoTextLayer));
    assert_eq!(pdf("encrypted.pdf"), Err(PdfError::Encrypted));
    assert!(matches!(pdf("no_map.pdf"), Err(PdfError::Unsupported(m)) if m.contains("ToUnicode")));
    assert!(matches!(pdf("lzw.pdf"), Err(PdfError::Unsupported(m)) if m.contains("LZWDecode")));
    assert!(matches!(pdf("damaged.pdf"), Err(PdfError::Damaged(_))));
    assert_eq!(extract(b"hello", &LIMITS), Err(PdfError::NotPdf));
    let message = PdfError::NoTextLayer.to_string();
    assert!(
        message.contains("scan") && message.contains("OCR"),
        "{message}"
    );
}

#[test]
fn a_decompression_bomb_stops_at_the_limit() {
    let tight = PdfLimits {
        max_stream_bytes: 200,
        max_pages: 100,
    };
    let data = std::fs::read(fixture("long.pdf")).unwrap();
    let error = extract(&data, &tight).unwrap_err();
    assert!(
        matches!(&error, PdfError::Damaged(m) if m.contains("larger than the limit")),
        "{error:?}"
    );
}

#[test]
fn the_page_limit_holds_and_garbage_inside_a_pdf_never_panics() {
    let one = PdfLimits {
        max_stream_bytes: 1 << 20,
        max_pages: 1,
    };
    let pages = extract(&std::fs::read(fixture("report.pdf")).unwrap(), &one)
        .unwrap()
        .pages;
    assert_eq!(pages.len(), 1);
    // every prefix and a few corruptions of a real file: an error or text, never a panic
    let data = std::fs::read(fixture("report.pdf")).unwrap();
    for cut in (0..data.len()).step_by(7) {
        let _ = extract(&data[..cut], &LIMITS);
    }
    for at in (0..data.len()).step_by(11) {
        let mut broken = data.clone();
        broken[at] ^= 0xff;
        let _ = extract(&broken, &LIMITS);
    }
}

// ---------------------------------------------------------------- passages

fn chars_of(text: &str, start: usize, end: usize) -> String {
    text.chars().skip(start).take(end - start).collect()
}

#[test]
fn every_passage_is_exactly_the_characters_it_points_at() {
    let mut text = String::new();
    for i in 0..60 {
        text.push_str(&format!("# Heading {i}\n\n"));
        for j in 0..(i % 5 + 1) {
            text.push_str(&format!(
                "Paragraph {i}.{j}: Việt Nam, naïve café, résumé; α β γ. Second sentence here! Third one? Yes.\n\n"
            ));
        }
    }
    for max in [60, 200, 1200] {
        let passages = split(&text, max);
        assert!(!passages.is_empty());
        let mut last_end = 0;
        for (i, p) in passages.iter().enumerate() {
            assert_eq!(p.ordinal, i);
            assert_eq!(
                p.text,
                chars_of(&text, p.start, p.end),
                "span of passage {i} at {max}"
            );
            assert!(
                p.text.chars().count() <= max,
                "passage {i} is {} long",
                p.text.chars().count()
            );
            assert!(!p.text.trim().is_empty() && p.text == p.text.trim());
            assert!(p.start >= last_end, "passages do not overlap");
            last_end = p.end;
        }
    }
}

#[test]
fn a_heading_starts_a_passage_and_neighbours_join_while_they_fit() {
    let text = "# One\n\nfirst words.\n\nmore words.\n\n# Two\n\nsecond section.";
    let passages = split(text, 1000);
    assert_eq!(
        passages.iter().map(|p| p.text.as_str()).collect::<Vec<_>>(),
        [
            "# One\n\nfirst words.\n\nmore words.",
            "# Two\n\nsecond section."
        ]
    );
    let small = split(text, 20);
    assert!(small.len() > 2);
    assert!(small.iter().all(|p| p.text.chars().count() <= 20));
}

#[test]
fn a_long_paragraph_is_cut_at_a_sentence_then_at_a_space_then_anywhere() {
    let sentences =
        "This is one sentence. This is another sentence. And a third sentence follows here.";
    let p = split(sentences, 50);
    assert_eq!(p[0].text, "This is one sentence. This is another sentence.");
    let words = split(&"word ".repeat(40), 30);
    assert!(
        words
            .iter()
            .all(|p| p.text.chars().count() <= 30 && !p.text.ends_with(' '))
    );
    let solid = split(&"x".repeat(250), 100);
    assert_eq!(
        solid.iter().map(|p| p.text.len()).collect::<Vec<_>>(),
        [100, 100, 50]
    );
    assert!(split("", 100).is_empty() && split("  \n\n \t", 100).is_empty());
}

// ---------------------------------------------------------------- documents

#[test]
fn text_and_markdown_keep_their_characters_and_pdf_gives_its_text() {
    let dir = temp("documents");
    std::fs::write(
        dir.join("notes.txt"),
        "line one\r\nline two\r\n\r\nsecond paragraph",
    )
    .unwrap();
    std::fs::write(
        dir.join("paper.md"),
        "---\ntitle: \"A Study of Cells\"\n---\n# Heading\n\nBody text with *markup* and [[link]].\n",
    )
    .unwrap();
    std::fs::write(dir.join("plain.md"), "# First heading\n\ntext").unwrap();
    std::fs::write(dir.join("bare.markdown"), "just text").unwrap();
    let text = read_document(&dir.join("notes.txt"), 1 << 20, &LIMITS).unwrap();
    assert_eq!((text.kind, text.title.as_str()), (Kind::Text, "notes"));
    assert_eq!(
        text.text, "line one\nline two\n\nsecond paragraph",
        "CRLF becomes LF"
    );
    let md = read_document(&dir.join("paper.md"), 1 << 20, &LIMITS).unwrap();
    assert_eq!(
        (md.kind, md.title.as_str()),
        (Kind::Markdown, "A Study of Cells")
    );
    assert!(
        md.text.starts_with("---\ntitle:"),
        "the text is the whole file, markup and all"
    );
    assert_eq!(
        read_document(&dir.join("plain.md"), 1 << 20, &LIMITS)
            .unwrap()
            .title,
        "First heading"
    );
    assert_eq!(
        read_document(&dir.join("bare.markdown"), 1 << 20, &LIMITS)
            .unwrap()
            .title,
        "bare"
    );
    // the passages of a Markdown file point at its own characters
    let passages = split(&md.text, 40);
    for p in &passages {
        assert_eq!(p.text, chars_of(&md.text, p.start, p.end));
    }
    let report = read_document(&fixture("report.pdf"), 1 << 20, &LIMITS).unwrap();
    assert_eq!((report.kind, report.title.as_str()), (Kind::Pdf, "report"));
    assert!(
        report
            .text
            .contains("Encapsulation with glass helps\n\nCafé results")
    );
    assert_eq!(report.sha256.len(), 64);
}

#[test]
fn files_that_cannot_be_ingested_say_why() {
    let dir = temp("refused");
    std::fs::write(dir.join("big.txt"), "x".repeat(100)).unwrap();
    std::fs::write(dir.join("blank.md"), "  \n\n").unwrap();
    std::fs::write(dir.join("data.csv"), "a,b").unwrap();
    assert_eq!(
        read_document(&dir.join("big.txt"), 50, &LIMITS),
        Err(IngestError::TooLarge(50))
    );
    assert_eq!(
        read_document(&dir.join("blank.md"), 1000, &LIMITS),
        Err(IngestError::Empty)
    );
    assert!(
        matches!(read_document(&dir.join("data.csv"), 1000, &LIMITS), Err(IngestError::Unsupported(e)) if e == "csv")
    );
    assert!(matches!(
        read_document(&dir.join("none.txt"), 1000, &LIMITS),
        Err(IngestError::Unreadable(_))
    ));
    let scan = read_document(&fixture("scan.pdf"), 1 << 20, &LIMITS).unwrap_err();
    assert!(
        scan.to_string().contains("no text layer") && scan.to_string().contains("OCR"),
        "{scan}"
    );
}

fn has(program: &str) -> bool {
    std::process::Command::new(program)
        .arg("-v")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .is_ok()
}

#[test]
fn a_scanned_pdf_is_read_by_ocr_and_says_so() {
    if !(has("pdftoppm") && has("tesseract")) {
        eprintln!("skipped: pdftoppm or tesseract is not installed");
        return;
    }
    let cfg = laris_config::settings::Ocr::default();
    let (doc, method) = laris_tools::ingest::read_document_with(
        &fixture("scanned_text.pdf"),
        1 << 20,
        &LIMITS,
        Some(&cfg),
    )
    .unwrap();
    assert_eq!(method, laris_tools::ingest::Method::Ocr);
    assert!(
        doc.text.contains("perovskite") && doc.text.contains("encapsulation"),
        "{}",
        doc.text
    );
}

#[test]
fn a_clean_text_pdf_stays_with_the_built_in_reader() {
    let cfg = laris_config::settings::Ocr::default();
    let (_, method) = laris_tools::ingest::read_document_with(
        &fixture("report.pdf"),
        1 << 20,
        &LIMITS,
        Some(&cfg),
    )
    .unwrap();
    assert_eq!(method, laris_tools::ingest::Method::TextLayer);
}

#[test]
fn missing_programs_are_named_in_the_error() {
    let cfg = laris_config::settings::Ocr {
        text_command: "laris-no-such-program".into(),
        render_command: "laris-no-such-program".into(),
        ..Default::default()
    };
    let err =
        laris_tools::ingest::read_document_with(&fixture("scan.pdf"), 1 << 20, &LIMITS, Some(&cfg))
            .unwrap_err()
            .to_string();
    assert!(
        err.contains("no text layer") && err.contains("laris-no-such-program"),
        "{err}"
    );
}
