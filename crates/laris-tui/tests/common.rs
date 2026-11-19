#![allow(dead_code, missing_docs)]

use laris_config::settings::Ui;
use laris_protocol::scenario::Scenario;
use laris_tui::replay::{Replayed, replay};

pub const SCENARIOS: [&str; 11] = [
    "acceptance_session",
    "approval",
    "basic_chat",
    "completion",
    "interrupt",
    "login",
    "login_trust",
    "mismatch",
    "queued",
    "refusal",
    "slash",
];

pub fn scenario(name: &str) -> Scenario {
    let path = format!(
        "{}/../../tests/golden/ink_scenarios/{name}.json",
        env!("CARGO_MANIFEST_DIR")
    );
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{path}: {e}"));
    Scenario::parse(&text).unwrap_or_else(|e| panic!("{name}: {e}"))
}

pub fn play(name: &str, width: usize, lenient: bool) -> Result<Replayed, String> {
    replay(&scenario(name), &Ui::default(), width, lenient)
}
