//! `laris replay FILE`: shows a recorded core scenario through the terminal interface, for review (T157). It reads
//! one scenario of `laris-protocol` (the golden ones are in `tests/golden/ink_scenarios/`), types what the scenario
//! expects the user to type, feeds the events, and prints the screen. No server, no model and no key are involved.

use laris_config::Settings;
use laris_protocol::scenario::Scenario;
use laris_tui::replay::replay;
use laris_tui::{ansi, plain};

/// The usage text.
pub const USAGE: &str = "usage: laris replay FILE [--width N] [--color] [--steps]\nplays a recorded core scenario through the terminal interface and prints the screen (the width defaults to $COLUMNS or 80)";

/// Runs `laris replay` with the arguments after `replay`. `columns` is `$COLUMNS` when it is set.
pub fn run(args: &[String], settings: &Settings, columns: Option<&str>) -> Result<String, String> {
    let mut file: Option<&str> = None;
    let mut width: Option<usize> = columns.and_then(|c| c.trim().parse().ok());
    let (mut color, mut steps) = (false, false);
    let mut iter = args.iter();
    while let Some(arg) = iter.next() {
        match arg.as_str() {
            "--width" => {
                let value = iter.next().ok_or("--width needs a number")?;
                width = Some(
                    value
                        .parse()
                        .map_err(|_| format!("{value:?} is not a width"))?,
                );
            }
            "--color" => color = true,
            "--steps" => steps = true,
            flag if flag.starts_with('-') => return Err(format!("unknown option {flag}")),
            path if file.is_none() => file = Some(path),
            _ => return Err("only one scenario file".to_owned()),
        }
    }
    let file = file.ok_or("no scenario file")?;
    let width = width.unwrap_or(80).clamp(20, 400);
    let text = std::fs::read_to_string(file).map_err(|e| format!("cannot read {file}: {e}"))?;
    let scenario = Scenario::parse(&text).map_err(|e| format!("{file}: {e}"))?;
    let played = replay(&scenario, &settings.ui, width, true)?;
    if steps {
        let mut out = String::new();
        for snapshot in &played.snapshots {
            out.push_str(&format!(
                "──── step {} ────\n{}",
                snapshot.step, snapshot.screen
            ));
        }
        return Ok(out.trim_end().to_owned());
    }
    let lines = played.app.layout(width).all();
    let out = if color {
        ansi(&lines, true)
    } else {
        plain(&lines)
    };
    Ok(out.trim_end().to_owned())
}
