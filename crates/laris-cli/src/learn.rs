//! `laris learn stats | collect | export | rate | purge`: derive, inspect, export and delete the learning data kept
//! on this machine. Nothing here sends anything or trains a model.

use laris_config::layers::LoadOptions;
use laris_config::packaged::{ENV as PACKAGED_ENV, Packaged};
use laris_config::settings::{ExportRating, Settings};
use laris_policy::Redactor;
use laris_policy::learning::{self, Kind};
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use serde_json::json;
use std::path::PathBuf;

/// Where the command runs.
#[derive(Clone, Debug)]
pub struct Context {
    /// The user's Laris folder (`~/.laris`).
    pub home: PathBuf,
    /// The project folder.
    pub project: PathBuf,
    /// The environment.
    pub env: Vec<(String, String)>,
    /// Seconds since the epoch.
    pub now: f64,
}

fn flag(args: &[String], name: &str) -> Option<String> {
    args.iter()
        .position(|a| a == name)
        .and_then(|i| args.get(i + 1))
        .cloned()
}

fn settings(cx: &Context) -> Result<Settings, String> {
    let path = cx.home.join("settings.json");
    let named = cx
        .env
        .iter()
        .find(|(k, _)| k == PACKAGED_ENV)
        .map(|(_, v)| v.as_str());
    let packaged = Packaged::discover(named, std::env::current_exe().ok().as_deref());
    laris_config::load(&LoadOptions {
        settings_path: Some(&path),
        packaged: &packaged,
        env: &cx.env,
    })
    .map_err(|e| e.to_string())
}

/// Runs `args` (what follows `laris learn`) and returns what to print.
pub fn run(args: &[String], cx: &Context) -> Result<String, String> {
    let settings = settings(cx)?;
    let options = settings.learning;
    let store = Store::open_space(&cx.home, &cx.project, None, DEFAULT_BUSY_TIMEOUT)
        .map_err(|e| e.to_string())?;
    let pretty = |v: serde_json::Value| serde_json::to_string_pretty(&v).unwrap_or_default();
    match args.first().map(String::as_str) {
        Some("stats") => learning::stats(&store, &options)
            .map(pretty)
            .map_err(|e| e.to_string()),
        Some("collect") => {
            let redactor = Redactor::standard().with_env_secrets(cx.env.iter().cloned());
            let sessions = match flag(args, "--session") {
                Some(id) => vec![id],
                None => store.sessions().map_err(|e| e.to_string())?,
            };
            let (mut stored, mut duplicates, mut rejected) = (0, 0, Vec::new());
            for id in &sessions {
                let got = learning::collect(&store, id, &options, &redactor)
                    .map_err(|e| e.to_string())?;
                if !got.enabled {
                    return Ok(pretty(json!({"enabled": false, "stored": 0})));
                }
                stored += got.stored.values().sum::<usize>();
                duplicates += got.duplicates;
                rejected.extend(got.rejected.iter().map(|r| {
                    json!({
                        "session": id, "turn": r.turn, "reason": r.reason,
                    })
                }));
            }
            Ok(pretty(json!({
                "enabled": true, "sessions": sessions.len(), "stored": stored,
                "duplicates": duplicates, "rejected": rejected,
            })))
        }
        Some("export") => {
            let kind = flag(args, "--kind")
                .as_deref()
                .and_then(Kind::parse)
                .ok_or("--kind must be sft, retrieval or preference")?;
            let out = flag(args, "--out").ok_or("--out FILE is required")?;
            let minimum = match flag(args, "--min-rating").as_deref() {
                None => options.export_min_rating,
                Some("none") => ExportRating::None,
                Some("up") => ExportRating::Up,
                Some(_) => return Err("--min-rating must be none or up".to_owned()),
            };
            let exported = learning::export(&store, kind, minimum).map_err(|e| e.to_string())?;
            learning::write_export(&PathBuf::from(out), &exported).map_err(|e| e.to_string())?;
            Ok(pretty(exported.manifest))
        }
        Some("rate") => {
            let (Some(id), Some(rating)) = (args.get(1), args.get(2)) else {
                return Err("usage: rate ID up|down".to_owned());
            };
            let up = match rating.as_str() {
                "up" => true,
                "down" => false,
                _ => return Err("the rating must be up or down".to_owned()),
            };
            learning::rate(&store, id, up, cx.now).map_err(|e| e.to_string())?;
            Ok(pretty(json!({"example_id": id, "rating": rating})))
        }
        Some("purge") => {
            if !args.iter().any(|a| a == "--yes") {
                return Err("refusing to delete collected data without --yes".to_owned());
            }
            let removed = learning::purge(&store).map_err(|e| e.to_string())?;
            Ok(format!("removed {removed} rows"))
        }
        _ => Err("usage: learn <stats | collect | export | rate | purge>".to_owned()),
    }
}
