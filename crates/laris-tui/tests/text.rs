//! The parts under the screen: columns, wrapping, Markdown (also as it streams), highlighting and the input box.

#![allow(missing_docs)]

use laris_tui::input::{InputBuffer, Key};
use laris_tui::markdown::{inline, render, render_open, split_complete};
use laris_tui::style::{Line, Style, Theme, plain};
use laris_tui::width::{char_width, fit, hard_wrap, str_width, truncate, wrap};

fn theme() -> Theme {
    Theme::mono()
}

fn text_of(lines: &[Line]) -> Vec<String> {
    lines.iter().map(Line::trimmed).collect()
}

// ---------------------------------------------------------------- columns and wrapping

#[test]
fn columns_count_wide_and_combining_characters_the_way_a_terminal_does() {
    assert_eq!(str_width("abc"), 3);
    assert_eq!(str_width("日本語"), 6);
    assert_eq!(str_width("한글"), 4);
    assert_eq!(char_width('😀'), 2);
    // Vietnamese: precomposed letters are one column, a combining accent adds none
    assert_eq!(str_width("Tiếng Việt"), 10);
    assert_eq!(str_width("e\u{0302}\u{0301}"), 1);
    assert_eq!(
        str_width("a\u{200b}b"),
        2,
        "a zero-width space takes no column"
    );
    assert_eq!(char_width('\u{1b}'), 0);
    assert_eq!(fit("日本語", 5), ("日本", 4));
}

#[test]
fn wrapping_keeps_every_line_within_the_width_and_never_loses_a_word() {
    let body = Line::plain("the quick brown fox jumps over the lazy dog");
    for width in 4..60 {
        let lines = wrap(&Line::default(), &Line::default(), &body, width);
        assert!(
            lines.iter().all(|l| l.width() <= width),
            "width {width}: {:?}",
            text_of(&lines)
        );
        let words: Vec<String> = lines
            .iter()
            .flat_map(|l| l.text().split(' ').map(str::to_owned).collect::<Vec<_>>())
            .collect();
        let joined: String = words.concat();
        if width >= 5 {
            assert_eq!(
                joined, "thequickbrownfoxjumpsoverthelazydog",
                "width {width}"
            );
        }
    }
    let lines = wrap(
        &Line::plain("- "),
        &Line::plain("  "),
        &Line::plain("alpha beta gamma delta"),
        12,
    );
    assert_eq!(text_of(&lines), ["- alpha beta", "  gamma", "  delta"]);
}

#[test]
fn a_word_longer_than_the_line_is_cut_by_columns_and_wide_text_is_never_split_in_half() {
    let lines = wrap(
        &Line::default(),
        &Line::default(),
        &Line::plain("abcdefghijkl"),
        5,
    );
    assert_eq!(text_of(&lines), ["abcde", "fghij", "kl"]);
    let lines = wrap(
        &Line::default(),
        &Line::default(),
        &Line::plain("日本語日本語"),
        5,
    );
    assert_eq!(text_of(&lines), ["日本", "語日", "本語"]);
    assert!(lines.iter().all(|l| l.width() <= 5));
    let code = hard_wrap(
        &Line::plain("│ "),
        &Line::plain("│ "),
        &Line::plain("a  b  c  d  e  f"),
        8,
    );
    assert!(code.iter().all(|l| l.width() <= 8), "{:?}", text_of(&code));
    assert_eq!(code[0].text(), "│ a  b  ");
}

#[test]
fn truncating_puts_an_ellipsis_in_the_last_column() {
    let t = truncate(&Line::plain("hello world"), 8);
    assert_eq!((t.text().as_str(), t.width()), ("hello w…", 8));
    assert_eq!(truncate(&Line::plain("short"), 8).text(), "short");
    assert_eq!(truncate(&Line::plain("日本語"), 4).text(), "日…");
    assert_eq!(truncate(&Line::plain("abc"), 0).text(), "");
}

// ---------------------------------------------------------------- Markdown

#[test]
fn the_blocks_of_markdown_are_drawn() {
    let md = "# Title\n\nA paragraph with **bold**, *italic*, `code` and a [link](https://x.org).\n\n- one\n- two\n  - nested\n1. first\n2) second\n\n> quoted words\n\n---\n\n```python\ndef f(x):\n    return x  # note\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n";
    let lines = render(md, 80, theme());
    let text = text_of(&lines);
    assert_eq!(text[0], "Title");
    assert!(
        text.contains(
            &"A paragraph with bold, italic, code and a link (https://x.org).".to_owned()
        ),
        "{text:#?}"
    );
    for want in [
        "• one",
        "• two",
        "  ◦ nested",
        "1. first",
        "2. second",
        "▎ quoted words",
        "python",
        "│ def f(x):",
        "│     return x  # note",
        "| a | b |",
    ] {
        assert!(text.contains(&want.to_owned()), "{want:?} not in {text:#?}");
    }
    assert!(text.iter().any(|l| l.starts_with("───")));
}

#[test]
fn inline_markers_that_do_not_close_stay_as_written() {
    let t = Style::PLAIN;
    let show = |s: &str| {
        inline(s, t, theme())
            .iter()
            .map(|s| s.text.clone())
            .collect::<String>()
    };
    assert_eq!(
        show("2 * 3 = 6 and snake_case_name"),
        "2 * 3 = 6 and snake_case_name"
    );
    assert_eq!(show("**open"), "**open");
    assert_eq!(show("a `b"), "a `b");
    assert_eq!(show("\\*not italic\\*"), "*not italic*");
    assert_eq!(show("**bold _and italic_**"), "bold and italic");
    assert_eq!(show("``a ` b``"), "a ` b");
}

#[test]
fn bold_and_italic_are_styles_not_characters() {
    let spans = inline(
        "x **b** *i* `c`",
        Style::PLAIN,
        Theme::of(laris_config::settings::Theme::Dark),
    );
    let find = |text: &str| spans.iter().find(|s| s.text == text).unwrap().style;
    assert!(find("b").bold && find("i").italic);
    assert_ne!(find("c"), Style::PLAIN);
}

const DOCS: [&str; 4] = [
    "Intro line one\nthat continues the paragraph and is long enough to wrap around the narrow screen.\n\n- item one that is also long enough to wrap onto a second line\n- item two\n\n## Heading\nText after.\n",
    "```rust\nfn main() {\n    println!(\"hi\"); // greet\n}\n```\nAfter the code.\n\n> a quote\n> goes on\n",
    "Tiếng Việt có dấu: *nhấn mạnh*, **đậm** và `mã`.\n\n1. một\n2. hai\n",
    "A | table\n|---|---|\n| 1 | 2 |\n\n---\n\nEnd",
];

#[test]
fn a_streamed_answer_is_final_line_by_line_and_equals_the_whole_text_rendered_at_once() {
    for width in [20, 40, 60, 100] {
        for doc in DOCS {
            let whole = render(doc, width, theme());
            // cut the text at every character: what is final at one cut stays final at every later cut
            let chars: Vec<(usize, char)> = doc.char_indices().collect();
            let mut previous: Vec<Line> = Vec::new();
            for (at, _) in chars.iter().copied().chain([(doc.len(), ' ')]) {
                let (done, _rest) = split_complete(&doc[..at]);
                let (stable, pending) = render_open(done, width, theme());
                assert!(
                    stable.starts_with(&previous),
                    "width {width}: a final line changed after {at} bytes of {doc:?}\nbefore: {:?}\nnow:    {:?}",
                    text_of(&previous),
                    text_of(&stable)
                );
                previous = stable.clone();
                // what is final plus what is pending is what a later render starts from
                let mut together = stable;
                together.extend(pending);
                assert!(together.iter().all(|l| l.width() <= width));
            }
            let (stable, pending) = render_open(doc, width, theme());
            let mut all = stable;
            all.extend(pending);
            while all.last().is_some_and(|l| l.0.is_empty()) {
                all.pop();
            }
            assert_eq!(plain(&all), plain(&whole), "width {width}: {doc:?}");
        }
    }
}

#[test]
fn a_cut_inside_a_marker_or_a_fence_never_panics_or_overflows() {
    let doc = "**bold `code` _x_ [l](u) ``` ~~~ # h\n> q\n\u{1b}[31mred\n";
    for width in [8, 9, 20] {
        for end in 0..=doc.len() {
            if !doc.is_char_boundary(end) {
                continue;
            }
            let lines = render(&doc[..end], width, theme());
            assert!(lines.iter().all(|l| l.width() <= width));
            assert!(
                lines
                    .iter()
                    .all(|l| !l.text().chars().any(char::is_control))
            );
        }
    }
}

#[test]
fn code_is_highlighted_by_language_and_left_alone_when_the_language_is_unknown() {
    let t = Theme::of(laris_config::settings::Theme::Dark);
    let lines = render(
        "```python\nx = 'a' + 12  # c\n```\n```\nx = 'a'\n```\n",
        60,
        t,
    );
    let spans: Vec<(&str, Style)> = lines[1]
        .0
        .iter()
        .map(|s| (s.text.as_str(), s.style))
        .collect();
    let style_of = |text: &str| {
        spans
            .iter()
            .find(|(t, _)| *t == text)
            .map(|(_, s)| *s)
            .unwrap()
    };
    assert_eq!(style_of("'a'"), t.string());
    assert_eq!(style_of("12"), t.number());
    assert_eq!(style_of("# c"), t.comment());
    let unknown = lines
        .iter()
        .find(|l| {
            l.text().contains("x = 'a'")
                && l.0
                    .iter()
                    .all(|s| s.style == Style::PLAIN || s.style == t.border())
        })
        .is_some();
    assert!(unknown);
}

// ---------------------------------------------------------------- the input box

fn typed(text: &str) -> InputBuffer {
    let mut b = InputBuffer::new();
    for c in text.chars() {
        b.edit(if c == '\n' {
            Key::Newline
        } else {
            Key::Char(c)
        });
    }
    b
}

#[test]
fn the_cursor_moves_and_edits_inside_the_text() {
    let mut b = typed("hello world");
    b.edit(Key::Home);
    b.edit(Key::Right);
    b.edit(Key::Delete);
    assert_eq!(b.text(), "hllo world");
    b.edit(Key::End);
    b.edit(Key::CtrlW);
    assert_eq!(b.text(), "hllo ");
    b.edit(Key::CtrlU);
    assert!(b.is_empty());
    let mut b = typed("ab\ncd");
    b.edit(Key::Up);
    b.edit(Key::End);
    b.edit(Key::CtrlK);
    b.edit(Key::Char('!'));
    assert_eq!(b.text(), "ab!\ncd");
    assert_eq!(b.cursor_line_col(), (0, 3));
    b.edit(Key::Down);
    assert_eq!(b.cursor_line_col().0, 1);
}

#[test]
fn up_and_down_walk_the_history_and_bring_the_unsent_text_back() {
    let mut b = InputBuffer::new();
    for line in ["first", "second"] {
        b.insert(line);
        b.take();
    }
    b.insert("draft");
    b.edit(Key::Up);
    assert_eq!(b.text(), "second");
    b.edit(Key::Up);
    assert_eq!(b.text(), "first");
    b.edit(Key::Up);
    assert_eq!(b.text(), "first", "the oldest stays");
    b.edit(Key::Down);
    assert_eq!(b.text(), "second");
    b.edit(Key::Down);
    assert_eq!(b.text(), "draft", "the draft comes back");
    // the same line twice is kept once, a blank one not at all
    b.take();
    b.insert("second");
    b.take();
    b.insert("  ");
    b.take();
    b.edit(Key::Up);
    assert_eq!(b.text(), "second");
}

#[test]
fn a_trailing_backslash_makes_a_new_line_and_paste_is_cleaned() {
    let mut b = typed("one \\");
    assert!(b.continues());
    b.continue_line();
    b.insert("two");
    assert_eq!(b.text(), "one \ntwo");
    let mut b = InputBuffer::new();
    b.insert("a\tb\r\nc\x1b[31m\rd\u{7}");
    assert_eq!(b.text(), "a b\nc[31m\nd");
}

#[test]
fn rows_wrap_by_columns_and_put_the_cursor_where_the_next_character_goes() {
    let b = typed("abcdef");
    let (rows, cursor) = b.rows(4);
    assert_eq!(rows, ["abcd", "ef"]);
    assert_eq!(cursor, (1, 2));
    let b = typed("abcd");
    let (rows, cursor) = b.rows(4);
    assert_eq!(rows, ["abcd", ""]);
    assert_eq!(cursor, (1, 0), "a full row: the cursor starts the next one");
    let b = typed("日本語");
    let (rows, _) = b.rows(5);
    assert_eq!(rows, ["日本", "語"]);
    let mut b = typed("ab\ncd");
    b.edit(Key::Up);
    assert_eq!(b.rows(10).1, (0, 2));
}
