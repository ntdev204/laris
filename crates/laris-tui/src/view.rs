//! Drawing: the banner, the conversation, and the bottom of the screen (spinner, input box, status line, footer).
//!
//! [`App::layout`] returns a [`Layout`]. `committed` lines are final: nothing later changes or moves them, so a
//! terminal driver prints each once into the scrollback. `live` lines are redrawn on every change. Every line is at
//! most `width` columns.

use crate::app::{App, Item, Tone};
use crate::markdown::{render, render_open, split_complete};
use crate::style::{Line, Span, Style, Theme};
use crate::width::{str_width, truncate, wrap};
use serde_json::{Map, Value};

const SPINNER: [&str; 6] = ["✻", "✽", "✶", "✳", "✢", "·"];
const BOX_ROWS: usize = 8;
const BANNER_WIDTH: usize = 64;

/// The screen at one width.
#[derive(Debug, Clone, PartialEq)]
pub struct Layout {
    /// Lines that are final.
    pub committed: Vec<Line>,
    /// Lines that are redrawn: the unfinished answer, the spinner, the input box, the status line, the footer.
    pub live: Vec<Line>,
    /// The cursor, as (row in `live`, column).
    pub cursor: Option<(usize, usize)>,
}

impl Layout {
    /// Everything, top to bottom.
    pub fn all(&self) -> Vec<Line> {
        let mut lines = self.committed.clone();
        lines.extend(self.live.iter().cloned());
        lines
    }
}

/// Removes what could move the cursor or paint outside the interface: control characters, escapes included.
pub fn clean(text: &str) -> String {
    text.chars().filter(|c| !c.is_control()).collect()
}

fn middle(text: &str, columns: usize) -> String {
    if str_width(text) <= columns || columns < 5 {
        return text.to_owned();
    }
    let keep = columns - 1;
    let tail = keep / 2;
    let head = keep - tail;
    let chars: Vec<char> = text.chars().collect();
    let take = |range: &mut dyn Iterator<Item = char>, budget: usize| {
        let mut out = String::new();
        let mut used = 0;
        for c in range {
            let w = crate::width::char_width(c);
            if used + w > budget {
                break;
            }
            used += w;
            out.push(c);
        }
        out
    };
    let front = take(&mut chars.iter().copied(), head);
    let mut back: Vec<char> = Vec::new();
    let mut back_iter = chars.iter().rev().copied();
    let rev = take(&mut back_iter, tail);
    back.extend(rev.chars());
    back.reverse();
    format!("{front}…{}", back.iter().collect::<String>())
}

fn banner(app: &App, width: usize) -> Vec<Line> {
    let Some(info) = &app.info else {
        return Vec::new();
    };
    let theme = app.theme;
    let outer = width.clamp(20, BANNER_WIDTH);
    let inner = outer - 4;
    let row = |content: Line| {
        let mut body = truncate(&content, inner);
        body.pad(inner);
        let mut line = Line::styled("│ ", theme.border());
        line.0.extend(body.0);
        line.push(" │", theme.border());
        line
    };
    let title = {
        let mut l = Line::styled("✻ ", theme.accent());
        l.push("Laris", theme.accent());
        l.push(format!("  v{}", clean(&info.engine)), theme.dim());
        l
    };
    let mut lines = vec![Line::styled(
        format!("╭{}╮", "─".repeat(outer - 2)),
        theme.border(),
    )];
    lines.push(row(title));
    lines.push(row(Line::blank()));
    let cwd = app.text(
        "ui.banner_cwd",
        &[("cwd", &middle(&clean(&info.cwd), inner.saturating_sub(8)))],
    );
    lines.push(row(Line::styled(cwd, theme.dim())));
    let session = clean(&info.session);
    let short: String = session.chars().take(8).collect();
    let session_line = app.text(
        "ui.banner_session",
        &[("session", &short), ("mode", &clean(&info.mode))],
    );
    lines.push(row(Line::styled(session_line, theme.dim())));
    if !info.server.is_empty() {
        let server = app.text(
            "ui.banner_server",
            &[(
                "server",
                &middle(&clean(&info.server), inner.saturating_sub(9)),
            )],
        );
        lines.push(row(Line::styled(server, theme.dim())));
    }
    lines.push(row(Line::styled(
        app.text("ui.hint_help", &[]),
        theme.dim(),
    )));
    lines.push(Line::styled(
        format!("╰{}╯", "─".repeat(outer - 2)),
        theme.border(),
    ));
    lines
}

fn short_value(value: &Value) -> String {
    match value {
        Value::String(s) => {
            let s = clean(s);
            let shown: String = s.chars().take(40).collect();
            let more = if s.chars().count() > 40 { "…" } else { "" };
            format!("\"{shown}{more}\"")
        }
        other => clean(&other.to_string()),
    }
}

fn arguments_text(arguments: &Map<String, Value>) -> String {
    arguments
        .iter()
        .map(|(k, v)| format!("{}: {}", clean(k), short_value(v)))
        .collect::<Vec<_>>()
        .join(", ")
}

fn result_text(app: &App, result: &Value) -> (String, Tone) {
    if let Some(error) = result.get("error") {
        let code = error.get("code").and_then(Value::as_str).unwrap_or("error");
        let message = error.get("message").and_then(Value::as_str).unwrap_or("");
        let text = if message.is_empty() {
            code.to_owned()
        } else {
            format!("{code}: {message}")
        };
        return (clean(&text), Tone::Error);
    }
    let count = |n: usize| app.text("ui.result_hits", &[("count", &n.to_string())]);
    let text = match result {
        Value::Null => app.text("ui.result_done", &[]),
        Value::Object(map) if map.is_empty() => app.text("ui.result_done", &[]),
        Value::Object(map) => match map.get("hits").and_then(Value::as_array) {
            Some(hits) => count(hits.len()),
            None => clean(&result.to_string()),
        },
        Value::Array(items) => count(items.len()),
        Value::String(s) => clean(s.lines().next().unwrap_or("")),
        other => clean(&other.to_string()),
    };
    (text, Tone::Dim)
}

fn tone_style(theme: Theme, tone: Tone) -> Style {
    match tone {
        Tone::Dim => theme.dim(),
        Tone::Warn => theme.warn(),
        Tone::Error => theme.error(),
    }
}

/// The conversation as (final lines, unfinished lines).
fn conversation(app: &App, width: usize) -> (Vec<Line>, Vec<Line>) {
    let theme = app.theme;
    let mut out: Vec<Line> = Vec::new();
    let mut tail: Vec<Line> = Vec::new();
    let gap = |out: &mut Vec<Line>| {
        if out.last().is_some_and(|l| !l.0.is_empty()) {
            out.push(Line::blank());
        }
    };
    for (index, item) in app.items.iter().enumerate() {
        match item {
            Item::User(text) => {
                gap(&mut out);
                let lead = Line::styled("> ", theme.dim());
                let hang = Line::plain("  ");
                for (i, part) in clean_lines(text).iter().enumerate() {
                    let body = Line::styled(part.clone(), theme.user());
                    let first = if i == 0 { &lead } else { &hang };
                    out.extend(wrap(first, &hang, &body, width));
                }
            }
            Item::Assistant { text, open } => {
                let (done, rest) = if *open {
                    split_complete(text)
                } else {
                    (text.as_str(), "")
                };
                let inner = width.saturating_sub(2);
                let (lines, pending) = if *open {
                    render_open(done, inner, theme)
                } else {
                    (render(done, inner, theme), Vec::new())
                };
                if !lines.is_empty() {
                    gap(&mut out);
                }
                let bullet = Line::styled("● ", theme.accent());
                let hang = Line::plain("  ");
                let had_lines = !lines.is_empty();
                for (i, line) in lines.into_iter().enumerate() {
                    out.push(if i == 0 {
                        bullet.clone().then(line)
                    } else {
                        hang.clone().then(line)
                    });
                }
                if *open && index + 1 == app.items.len() {
                    let mut live: Vec<Line> =
                        pending.into_iter().map(|l| hang.clone().then(l)).collect();
                    if !rest.is_empty() {
                        let body = Line(inline_plain(rest));
                        live.extend(wrap(&hang, &hang, &body, width));
                    }
                    if !had_lines && let Some(first) = live.first_mut() {
                        first.0.splice(0..1, bullet.0.clone());
                    }
                    tail = live;
                }
            }
            Item::Tool {
                name,
                arguments,
                result,
                ..
            } => {
                if !matches!(
                    app.items.get(index.wrapping_sub(1)),
                    Some(Item::Tool { .. })
                ) {
                    gap(&mut out);
                }
                let head = {
                    let mut l = Line::styled("● ", theme.tool());
                    l.push(clean(name), theme.tool());
                    l.push(format!("({})", arguments_text(arguments)), theme.dim());
                    l
                };
                out.push(truncate(&head, width));
                let (text, tone) = match result {
                    Some(r) => result_text(app, r),
                    None => ("…".to_owned(), Tone::Dim),
                };
                let lead = Line::styled("  ⎿ ", theme.dim());
                let hang = Line::plain("    ");
                let body = Line::styled(text, tone_style(theme, tone));
                let rows = wrap(&lead, &hang, &body, width);
                out.extend(rows.into_iter().take(3));
            }
            Item::Notice { text, tone } => {
                let lead = Line::styled("  ⎿ ", theme.dim());
                let hang = Line::plain("    ");
                let body = Line::styled(clean(text), tone_style(theme, *tone));
                out.extend(wrap(&lead, &hang, &body, width));
            }
            Item::Plan(steps) => {
                gap(&mut out);
                for (text, status) in steps {
                    let (mark, style) = match status.as_str() {
                        "done" | "completed" => ("☒", theme.success()),
                        "failed" => ("☒", theme.error()),
                        "in_progress" | "active" => ("◐", theme.warn()),
                        _ => ("☐", theme.dim()),
                    };
                    let lead = Line::styled(format!("  {mark} "), style);
                    let hang = Line::plain("    ");
                    out.extend(wrap(&lead, &hang, &Line::plain(clean(text)), width));
                }
            }
        }
    }
    (out, tail)
}

fn clean_lines(text: &str) -> Vec<String> {
    text.lines().map(clean).collect()
}

fn inline_plain(rest: &str) -> Vec<Span> {
    vec![Span::new(clean(rest), Style::PLAIN)]
}

fn spinner_line(app: &App, width: usize) -> Line {
    let theme = app.theme;
    let frame = if app.spinner {
        SPINNER[(app.frame as usize) % SPINNER.len()]
    } else {
        "●"
    };
    let seconds = app.elapsed_ms / 1000;
    let mut line = Line::styled(format!("{frame} "), theme.accent());
    line.push(app.text("ui.thinking", &[]), theme.accent());
    line.push(
        format!(" ({seconds}s · {})", app.text("ui.hint_interrupt", &[])),
        theme.dim(),
    );
    truncate(&line, width)
}

fn input_box(app: &App, width: usize) -> (Vec<Line>, (usize, usize)) {
    let theme = app.theme;
    let width = width.max(12);
    let inner = width - 4;
    let text_cols = inner - 2;
    let (rows, (cursor_row, cursor_col)) = app.input.rows(text_cols);
    let first_visible = (cursor_row + 1).saturating_sub(BOX_ROWS);
    let shown: Vec<&String> = rows.iter().skip(first_visible).take(BOX_ROWS).collect();
    let mut lines = vec![Line::styled(
        format!("╭{}╮", "─".repeat(width - 2)),
        theme.border(),
    )];
    for (i, row) in shown.iter().enumerate() {
        let lead = if first_visible + i == 0 { "> " } else { "  " };
        let mut body = if app.input.is_empty() && i == 0 {
            truncate(
                &Line::styled(app.text("ui.placeholder", &[]), theme.dim()),
                text_cols,
            )
        } else {
            Line::plain((*row).clone())
        };
        body.pad(text_cols);
        let mut line = Line::styled("│ ", theme.border());
        line.push(lead, theme.dim());
        line.0.extend(body.0);
        line.push(" │", theme.border());
        lines.push(line);
    }
    lines.push(Line::styled(
        format!("╰{}╯", "─".repeat(width - 2)),
        theme.border(),
    ));
    let col = 2 + 2 + cursor_col;
    (lines, (1 + cursor_row - first_visible, col))
}

fn status_line(app: &App, width: usize) -> Option<Line> {
    if !app.show_status_line {
        return None;
    }
    let get = |k: &str| app.line.get(k);
    let text = |k: &str| {
        get(k)
            .and_then(Value::as_str)
            .map(clean)
            .filter(|s| !s.is_empty())
    };
    let mut parts: Vec<String> = Vec::new();
    if let Some(model) = text("model") {
        parts.push(model);
    }
    if let Some(mode) = text("mode").or_else(|| app.info.as_ref().map(|i| clean(&i.mode))) {
        parts.push(mode);
    }
    let context = app
        .usage
        .filter(|&(_, window)| window > 0)
        .map(|(tokens, window)| tokens * 100 / window)
        .or_else(|| {
            get("context")
                .and_then(|c| c.get("percent"))
                .and_then(Value::as_u64)
        });
    if let Some(percent) = context {
        parts.push(app.text("ui.context", &[("percent", &percent.to_string())]));
    }
    if let Some(branch) = text("branch") {
        parts.push(branch);
    }
    if let Some(left) = get("tokens_left").and_then(Value::as_u64) {
        parts.push(app.text("ui.tokens_left", &[("count", &left.to_string())]));
    }
    if let Some(state) = text("sandbox") {
        parts.push(app.text("ui.sandbox", &[("state", &state)]));
    }
    if app.queued > 0 {
        parts.push(app.text("ui.queued", &[("count", &app.queued.to_string())]));
    }
    if parts.is_empty() {
        return None;
    }
    while parts.len() > 1 && str_width(&format!(" {}", parts.join(" · "))) > width {
        parts.pop();
    }
    Some(truncate(
        &Line::styled(format!(" {}", parts.join(" · ")), app.theme.dim()),
        width,
    ))
}

fn footer(app: &App, width: usize) -> Line {
    let theme = app.theme;
    if app.armed_ms.is_some() {
        return truncate(
            &Line::styled(format!(" {}", app.text("ui.exit_again", &[])), theme.warn()),
            width,
        );
    }
    let mut hints: Vec<String> = Vec::new();
    if app.running {
        hints.push(app.text("ui.hint_interrupt", &[]));
    }
    hints.push(app.text("ui.hint_newline", &[]));
    hints.push(app.text("ui.hint_exit", &[]));
    while hints.len() > 1 && str_width(&format!(" {}", hints.join(" · "))) > width {
        hints.pop();
    }
    truncate(
        &Line::styled(format!(" {}", hints.join(" · ")), theme.dim()),
        width,
    )
}

impl App {
    /// Draws the interface at `width` columns.
    pub fn layout(&self, width: usize) -> Layout {
        let width = width.max(20);
        let mut committed = banner(self, width);
        let (talk, tail) = conversation(self, width);
        if !committed.is_empty() && !talk.is_empty() {
            committed.push(Line::blank());
        }
        committed.extend(talk);

        let mut live: Vec<Line> = Vec::new();
        if !committed.is_empty() || !tail.is_empty() {
            live.push(Line::blank());
        }
        live.extend(tail);
        if self.running {
            live.push(spinner_line(self, width));
        }
        if self.blocked {
            live.push(truncate(
                &Line::styled(
                    format!(" {}", self.text("ui.blocked", &[])),
                    self.theme.warn(),
                ),
                width,
            ));
            return Layout {
                committed,
                live,
                cursor: None,
            };
        }
        let (boxed, (row, col)) = input_box(self, width);
        let cursor = Some((live.len() + row, col));
        live.extend(boxed);
        live.extend(status_line(self, width));
        live.push(footer(self, width));
        Layout {
            committed,
            live,
            cursor,
        }
    }

    /// The whole screen as text without styles: what a person would read.
    pub fn screen_text(&self, width: usize) -> String {
        crate::style::plain(&self.layout(width).all())
    }
}
