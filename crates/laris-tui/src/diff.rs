//! A unified diff as lines for the terminal: added lines green, removed lines red, hunk headers dim. Every row is
//! cut to the width with the marker kept, and a long diff is shortened with a count of what was left out.

use crate::style::{Line, Style, Theme};
use crate::width::hard_wrap;

/// Rows of a diff shown before the rest is summarised.
pub const MAX_ROWS: usize = 24;

fn clean(text: &str) -> String {
    text.chars().filter(|c| !c.is_control()).collect()
}

fn style_of(theme: Theme, row: &str) -> Style {
    if row.starts_with("+++") || row.starts_with("---") {
        theme.dim()
    } else if row.starts_with('+') {
        theme.success()
    } else if row.starts_with('-') {
        theme.error()
    } else if row.starts_with("@@") {
        theme.accent()
    } else {
        theme.dim()
    }
}

/// Counts of (added, removed) lines, without the `+++` and `---` file headers.
pub fn counts(diff: &str) -> (usize, usize) {
    let mut added = 0;
    let mut removed = 0;
    for row in diff.lines() {
        if row.starts_with("+++") || row.starts_with("---") {
            continue;
        }
        if row.starts_with('+') {
            added += 1;
        } else if row.starts_with('-') {
            removed += 1;
        }
    }
    (added, removed)
}

/// Draws `diff` at `width` columns after `indent` spaces. Returns the rows and how many diff lines were left out.
pub fn render(diff: &str, width: usize, theme: Theme, indent: usize) -> (Vec<Line>, usize) {
    let lead = " ".repeat(indent);
    let all: Vec<&str> = diff.lines().collect();
    let shown = all.len().min(MAX_ROWS);
    let mut out = Vec::new();
    for row in &all[..shown] {
        let row = clean(row).replace('\t', "    ");
        let style = style_of(theme, &row);
        let body = Line::styled(row, style);
        // a long line wraps by columns; the continuation is indented under the marker
        let first = Line::plain(lead.clone());
        let rest = Line::plain(format!("{lead} "));
        let wrapped = hard_wrap(&first, &rest, &body, width);
        out.extend(wrapped);
    }
    (out, all.len() - shown)
}
