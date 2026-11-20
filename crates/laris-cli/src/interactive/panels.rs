//! Plain-text pieces of `/usage`, `/context` and `/config`: a progress bar, the context grid and an aligned table.

/// Columns of the context grid.
const COLS: usize = 10;
/// Rows of the context grid; each cell stands for 2% of the window.
const ROWS: usize = 5;
/// Width of one grid row in characters (cells and the spaces between them).
pub const GRID_WIDTH: usize = COLS * 2 - 1;
const BAR: usize = 30;

/// A bar of `BAR` cells filled to `percent`.
pub fn bar(percent: u64) -> String {
    let filled = usize::try_from(percent.min(100)).unwrap_or(100) * BAR / 100;
    format!("{}{}", "█".repeat(filled), "░".repeat(BAR - filled))
}

/// `12345` as `12.3k`, `2000000` as `2M`.
pub fn compact(n: u64) -> String {
    let scaled = |div: f64, unit: &str| {
        let v = n as f64 / div;
        let text = format!("{v:.1}");
        format!("{}{unit}", text.strip_suffix(".0").unwrap_or(&text))
    };
    match n {
        0..=999 => n.to_string(),
        1_000..=999_999 => scaled(1e3, "k"),
        _ => scaled(1e6, "M"),
    }
}

/// The grid rows: `⛁` for the context in use, `⛝` for the part kept back for compaction (above `threshold`),
/// `⛶` for the free space between.
pub fn grid(context: u64, window: u64, threshold: f64) -> Vec<String> {
    let cells = COLS * ROWS;
    let window = window.max(1);
    let mut used =
        usize::try_from((context.min(window) * cells as u64).div_ceil(window)).unwrap_or(cells);
    used = used.min(cells);
    let reserved =
        (((1.0 - threshold.clamp(0.0, 1.0)) * cells as f64).round() as usize).min(cells - used);
    (0..ROWS)
        .map(|r| {
            (0..COLS)
                .map(|c| {
                    let i = r * COLS + c;
                    if i < used {
                        "⛁"
                    } else if i >= cells - reserved {
                        "⛝"
                    } else {
                        "⛶"
                    }
                })
                .collect::<Vec<_>>()
                .join(" ")
        })
        .collect()
}

/// Rows of `(name, value)` with the values in one column.
pub fn table(rows: &[(String, String)]) -> String {
    let width = rows
        .iter()
        .map(|(k, _)| k.chars().count())
        .max()
        .unwrap_or(0);
    rows.iter()
        .map(|(k, v)| format!("  {k:<width$}  {v}"))
        .collect::<Vec<_>>()
        .join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bar_fills_in_proportion() {
        assert_eq!(bar(0).chars().filter(|c| *c == '█').count(), 0);
        assert_eq!(bar(50).chars().filter(|c| *c == '█').count(), 15);
        assert_eq!(bar(500).chars().filter(|c| *c == '█').count(), BAR);
        assert_eq!(bar(10).chars().count(), BAR);
    }

    #[test]
    fn numbers_are_compact() {
        assert_eq!(compact(999), "999");
        assert_eq!(compact(12_345), "12.3k");
        assert_eq!(compact(200_000), "200k");
        assert_eq!(compact(2_000_000), "2M");
    }

    #[test]
    fn grid_counts_used_free_and_reserved() {
        let g = grid(200, 1000, 0.8).join(" ");
        let n = |s: &str| g.matches(s).count();
        assert_eq!((n("⛁"), n("⛝"), n("⛶")), (10, 10, 30));
        assert_eq!(grid(1, 1000, 1.0).join("").matches('⛁').count(), 1);
    }

    #[test]
    fn table_aligns_values() {
        let t = table(&[("a".into(), "1".into()), ("long".into(), "2".into())]);
        assert_eq!(t, "  a     1\n  long  2");
    }
}
