//! Drawing: the banner, the conversation, and the bottom of the screen (spinner, input box, status line, footer).
//!
//! [`App::layout`] returns a [`Layout`]. `committed` lines are final: nothing later changes or moves them, so a
//! terminal driver prints each once into the scrollback. `live` lines are redrawn on every change. Every line is at
//! most `width` columns.

use crate::app::{App, Approval, Item, Stage, Tone};
use crate::diff;
use crate::markdown::{render, render_open, split_complete};
use crate::style::{Line, Span, Style, Theme};
use crate::width::{str_width, truncate, wrap};
use laris_protocol::events::Decision;
use serde_json::{Map, Value};

/// How long one spinner glyph stays, in milliseconds.
pub(crate) const SPINNER_STEP_MS: u64 = 120;
/// Glyphs with no emoji form: ✳ (U+2733) is drawn as a coloured emoji box on Windows, so it is not used.
const SPINNER: [&str; 6] = ["✻", "✽", "✶", "✺", "✢", "·"];
const BOX_ROWS: usize = 8;

/// The screen at one width.
#[derive(Debug, Clone, PartialEq)]
pub struct Layout {
    /// Lines that are final.
    pub committed: Vec<Line>,
    /// Lines that are redrawn: the unfinished answer, the spinner, the input box, the status line, the footer.
    pub live: Vec<Line>,
    /// The cursor, as (row in `live`, column).
    pub cursor: Option<(usize, usize)>,
    /// How many of the first `committed` lines are the header (the banner); a full-screen terminal pins them.
    pub head: usize,
    /// Where in `live` the fixed bottom starts (the input box, the menus, the status line, the footer); what is
    /// above it belongs to the conversation.
    pub fixed: usize,
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
    // three plain lines, as the other terminal assistants show them:
    //   ✻ Laris v1.0.1
    //     server · mode
    //     ~/folder
    let mut title = Line::styled("✻ ", theme.accent());
    title.push("Laris", theme.accent());
    title.push(format!(" v{}", clean(&info.engine)), theme.dim());
    let place = server_host(&clean(&info.server));
    let second = app.text(
        "ui.banner_line",
        &[("server", &place), ("mode", &clean(&info.mode))],
    );
    let second = if place.is_empty() {
        clean(&info.mode)
    } else {
        second
    };
    let cwd = middle(&clean(&info.cwd), width.saturating_sub(2).max(10));
    vec![
        truncate(&title, width),
        truncate(&Line::styled(format!("  {second}"), theme.dim()), width),
        truncate(&Line::styled(format!("  {cwd}"), theme.dim()), width),
    ]
}

/// The server address as a person says it: no scheme, no `/v1`.
fn server_host(address: &str) -> String {
    let rest = address
        .strip_prefix("https://")
        .or_else(|| address.strip_prefix("http://"))
        .unwrap_or(address);
    rest.trim_end_matches('/')
        .trim_end_matches("/v1")
        .to_owned()
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
            None => match map
                .get("text")
                .or_else(|| map.get("output"))
                .and_then(Value::as_str)
            {
                Some(text) => clean(text.lines().next().unwrap_or("")),
                None => clean(&result.to_string()),
            },
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
fn conversation(app: &App, width: usize) -> (Vec<Line>, Vec<Line>, bool) {
    let theme = app.theme;
    let mut out: Vec<Line> = Vec::new();
    let mut tail: Vec<Line> = Vec::new();
    // Where the first block that may still change begins in `out`. A block that waits for its result (a tool call)
    // or may still be replaced (the last plan) is live, and so is everything after it: the scrollback is written once.
    let mut open_from: Option<usize> = None;
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
                if result.is_none() && open_from.is_none() {
                    open_from = Some(out.len());
                }
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
            Item::Diff(text) => {
                gap(&mut out);
                out.extend(diff_block(app, text, width));
            }
            Item::Plan(steps) => {
                gap(&mut out);
                if index + 1 == app.items.len() && open_from.is_none() {
                    open_from = Some(out.len());
                }
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
    let split = open_from.is_some();
    if let Some(from) = open_from {
        let mut live = out.split_off(from.min(out.len()));
        live.extend(tail);
        tail = live;
    }
    (out, tail, split)
}

fn diff_block(app: &App, text: &str, width: usize) -> Vec<Line> {
    let theme = app.theme;
    let (added, removed) = diff::counts(text);
    let mut head = Line::styled("  ⎿ ", theme.dim());
    head.push(format!("+{added}"), theme.success());
    head.push(" ", theme.dim());
    head.push(format!("−{removed}"), theme.error());
    let mut out = vec![truncate(&head, width)];
    let (rows, left) = diff::render(text, width, theme, 4);
    out.extend(rows);
    if left > 0 {
        out.push(truncate(
            &Line::styled(
                format!(
                    "    {}",
                    app.text("ui.diff_more", &[("count", &left.to_string())])
                ),
                theme.dim(),
            ),
            width,
        ));
    }
    out
}

fn approval_block(app: &App, approval: &Approval, width: usize) -> Vec<Line> {
    let theme = app.theme;
    let mut out = vec![Line::styled(
        format!("╭{}", "─".repeat(width.saturating_sub(1))),
        theme.border(),
    )];
    let mut title = Line::styled(" ", theme.warn());
    title.push(
        app.text("ui.approval_title", &[("tool", &clean(&approval.tool))]),
        theme.warn().on(Style::PLAIN.bold()),
    );
    out.push(truncate(&title, width));
    let args = arguments_text(&approval.arguments);
    if !args.is_empty() {
        out.push(truncate(
            &Line::styled(format!("   {args}"), theme.dim()),
            width,
        ));
    }
    if !approval.reason.is_empty() {
        let body = Line::styled(clean(&approval.reason), theme.dim());
        out.extend(wrap(&Line::plain("   "), &Line::plain("   "), &body, width));
    }
    if !approval.rule.is_empty() {
        out.push(truncate(
            &Line::styled(
                format!(
                    "   {}",
                    app.text("ui.approval_rule", &[("rule", &clean(&approval.rule))])
                ),
                theme.dim(),
            ),
            width,
        ));
    }
    if !approval.diff.trim().is_empty() {
        out.extend(diff_block(app, &approval.diff, width));
    }
    for (i, choice) in approval.choices.iter().enumerate() {
        let label = app.text(choice.label, &[]);
        let selected = i == approval.selected;
        let mark = if selected { "❯" } else { " " };
        let style = if selected {
            if choice.decision == Decision::Deny {
                theme.error()
            } else {
                theme.accent()
            }
        } else {
            Style::PLAIN
        };
        out.push(truncate(
            &Line::styled(format!(" {mark} {}. {label}", i + 1), style),
            width,
        ));
    }
    out
}

fn sign_in_block(app: &App, width: usize) -> Vec<Line> {
    let theme = app.theme;
    let Some(form) = app.sign_in.as_ref() else {
        return Vec::new();
    };
    let server = clean(&form.server);
    let mut out = Vec::new();
    let mut title = Line::styled("✻ ", theme.accent());
    title.push(
        if server.is_empty() {
            app.text("login.title", &[])
        } else {
            app.text("ui.login_title", &[("server", &server)])
        },
        theme.accent(),
    );
    out.push(truncate(&title, width));
    if !form.note.is_empty() {
        let body = Line::styled(clean(&form.note), theme.warn());
        out.extend(wrap(&Line::plain("  "), &Line::plain("  "), &body, width));
    }
    if form.waiting {
        out.push(truncate(
            &Line::styled(
                format!("  {}", app.text("ui.login_checking", &[])),
                theme.dim(),
            ),
            width,
        ));
        return out;
    }
    match form.stage {
        Stage::Trust => {
            let text = app.text(
                "ui.login_trust",
                &[("fingerprint", &clean(&form.fingerprint))],
            );
            let body = Line::styled(text, theme.warn());
            out.extend(wrap(&Line::plain("  "), &Line::plain("  "), &body, width));
        }
        Stage::Server | Stage::Key => {
            let inner = width.saturating_sub(6).max(6);
            let shown = if form.stage == Stage::Key {
                // the key is never drawn: one dot per character, the last ones when it does not fit
                "•".repeat(form.typed().min(inner.saturating_sub(1)))
            } else {
                let typed = clean(&form.field.text());
                let skip = str_width(&typed).saturating_sub(inner.saturating_sub(1));
                typed.chars().skip(skip).collect()
            };
            let label = if form.stage == Stage::Key {
                app.text("ui.login_prompt", &[])
            } else {
                "server".to_owned()
            };
            let mut line = Line::styled(format!("  {label}: "), theme.dim());
            line.push(shown, Style::PLAIN);
            out.push(truncate(&line, width));
        }
    }
    out
}

fn search_block(app: &App, width: usize) -> Vec<Line> {
    let theme = app.theme;
    let Some(search) = app.search.as_ref() else {
        return Vec::new();
    };
    let head = app.text("ui.search_prompt", &[("query", &clean(&search.query))]);
    let mut out = vec![truncate(
        &Line::styled(format!(" {head}"), theme.accent()),
        width,
    )];
    if search.found.is_none() {
        out.push(truncate(
            &Line::styled(
                format!("  {}", app.text("ui.search_none", &[])),
                theme.dim(),
            ),
            width,
        ));
    }
    out
}

fn menu_block(app: &App, width: usize) -> Vec<Line> {
    let theme = app.theme;
    let Some(menu) = app.menu.as_ref() else {
        return Vec::new();
    };
    const SHOWN: usize = 6;
    let first = (menu.selected + 1).saturating_sub(SHOWN);
    menu.items
        .iter()
        .enumerate()
        .skip(first)
        .take(SHOWN)
        .map(|(i, item)| {
            let selected = i == menu.selected;
            let style = if selected {
                theme.accent()
            } else {
                Style::PLAIN
            };
            let mut line = Line::styled(
                format!(
                    " {} {}",
                    if selected { "❯" } else { " " },
                    clean(&item.value)
                ),
                style,
            );
            if !item.description.is_empty() {
                line.push(format!("  {}", clean(&item.description)), theme.dim());
            }
            truncate(&line, width)
        })
        .collect()
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
    let searching = app.search.as_ref().map(|search| {
        let mut shown = crate::input::InputBuffer::new();
        if let Some(entry) = search.found.and_then(|i| app.input.history().get(i)) {
            shown.set(entry);
        }
        shown
    });
    let source = searching.as_ref().unwrap_or(&app.input);
    let (rows, (cursor_row, cursor_col)) = source.rows(text_cols);
    let first_visible = (cursor_row + 1).saturating_sub(BOX_ROWS);
    let shown: Vec<&String> = rows.iter().skip(first_visible).take(BOX_ROWS).collect();
    let mut lines = vec![Line::styled(
        format!("╭{}╮", "─".repeat(width - 2)),
        theme.border(),
    )];
    for (i, row) in shown.iter().enumerate() {
        let lead = if first_visible + i == 0 { "> " } else { "  " };
        let mut body = if source.is_empty() && i == 0 {
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

fn hint_line(app: &App, key: &str, width: usize) -> Line {
    truncate(
        &Line::styled(format!(" {}", app.text(key, &[])), app.theme.dim()),
        width,
    )
}

fn footer(app: &App, width: usize) -> Line {
    let theme = app.theme;
    if app.armed_ms.is_some() {
        return truncate(
            &Line::styled(format!(" {}", app.text("ui.exit_again", &[])), theme.warn()),
            width,
        );
    }
    if let Some(flash) = &app.flash {
        return truncate(
            &Line::styled(format!(" {}", clean(flash)), theme.warn()),
            width,
        );
    }
    if app.search.is_some() {
        return hint_line(app, "ui.search_keys", width);
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
        let head = committed.len();
        let (talk, tail, split) = conversation(self, width);
        if !committed.is_empty() && !talk.is_empty() {
            committed.push(Line::blank());
        }
        committed.extend(talk);

        let mut live: Vec<Line> = Vec::new();
        if (!committed.is_empty() || !tail.is_empty())
            && !tail.first().is_some_and(|l| l.0.is_empty())
        {
            live.push(Line::blank());
        }
        live.extend(tail);
        if split {
            live.push(Line::blank());
        }
        for text in &self.pending {
            let lead = Line::styled("> ", self.theme.dim());
            let hang = Line::plain("  ");
            let mark = self.text("ui.queued_mark", &[]);
            let body = Line::styled(
                format!("{} ({mark})", clean(text.lines().next().unwrap_or(""))),
                self.theme.dim(),
            );
            live.extend(wrap(&lead, &hang, &body, width).into_iter().take(2));
        }
        let waiting = self.approval.is_some() || self.sign_in.is_some();
        if self.running && !waiting {
            live.push(spinner_line(self, width));
        }
        if self.blocked {
            let fixed = live.len();
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
                head,
                fixed,
            };
        }
        if let Some(approval) = &self.approval {
            let fixed = live.len();
            live.extend(approval_block(self, approval, width));
            live.push(hint_line(self, "ui.approval_keys", width));
            return Layout {
                committed,
                live,
                cursor: None,
                head,
                fixed,
            };
        }
        if self.sign_in.is_some() {
            let fixed = live.len();
            let block = sign_in_block(self, width);
            let masked_row = block.len().saturating_sub(1);
            let waiting = self.sign_in.as_ref().is_some_and(|f| f.waiting);
            let asks_text = self
                .sign_in
                .as_ref()
                .is_some_and(|f| f.stage != Stage::Trust && !f.waiting);
            let col = block.last().map_or(0, Line::width);
            let cursor = (asks_text && !waiting).then_some((live.len() + masked_row, col));
            live.extend(block);
            live.push(hint_line(self, "ui.login_keys", width));
            return Layout {
                committed,
                live,
                cursor,
                head,
                fixed,
            };
        }
        let fixed = live.len();
        let (boxed, (row, col)) = input_box(self, width);
        let cursor = Some((live.len() + row, col));
        live.extend(boxed);
        live.extend(search_block(self, width));
        live.extend(menu_block(self, width));
        live.extend(status_line(self, width));
        live.push(footer(self, width));
        Layout {
            committed,
            live,
            cursor,
            head,
            fixed,
        }
    }

    /// The whole screen as text without styles: what a person would read.
    pub fn screen_text(&self, width: usize) -> String {
        crate::style::plain(&self.layout(width).all())
    }
}

#[cfg(test)]
mod tests {
    use super::SPINNER;

    /// Characters that terminals may draw as colour emoji (Unicode `Emoji=Yes` in the Dingbats block).
    const EMOJI: [char; 30] = [
        '\u{2702}', '\u{2705}', '\u{2708}', '\u{2709}', '\u{270A}', '\u{270B}', '\u{270C}',
        '\u{270D}', '\u{270F}', '\u{2712}', '\u{2714}', '\u{2716}', '\u{271D}', '\u{2721}',
        '\u{2728}', '\u{2733}', '\u{2734}', '\u{2744}', '\u{2747}', '\u{274C}', '\u{274E}',
        '\u{2753}', '\u{2754}', '\u{2755}', '\u{2757}', '\u{2763}', '\u{2764}', '\u{2795}',
        '\u{2796}', '\u{2797}',
    ];

    #[test]
    fn no_spinner_glyph_can_turn_into_a_colour_emoji() {
        for glyph in SPINNER {
            assert!(
                glyph.chars().all(|c| !EMOJI.contains(&c)),
                "{glyph} may be drawn as an emoji"
            );
        }
    }
}
