//! Inference of the decision network (SR-K5, ADR-024 5.4, T169).
//!
//! The network is a small multilayer perceptron over tabular features, exported by `laris.model.decision` as plain JSON
//! weights and evaluated here by a handwritten forward pass in `f64`: no inference library, so no new dependency.
//! [`features`] writes the encoding again, formula for formula, from the Python side; the exported file carries the
//! feature names and [`Network::from_json`] refuses a file whose names differ.
//!
//! [`NetworkChooser`] scores only the legal candidates ([`crate::decide::legal`]), so it cannot choose an action
//! that is not allowed. A confidence below the sealed threshold falls back to the rule decider's choice, never to the
//! advisor's proposal; the decision records both. The network is NOT QUALIFIED until its held-out gates pass (T171),
//! and the rule decider stays in charge until the owner promotes it.

use serde_json::Value;

use crate::decide::{Act, CallState, Choice, Chooser, RuleDecider, Signals, legal};
use laris_vault::brain::Level;

/// The names of the features, in order: the state, then one per action, then the candidate count.
pub const FEATURE_NAMES: [&str; 36] = [
    "coverage",
    "best_level",
    "has_level",
    "accepted",
    "below_required",
    "pending_candidates",
    "open_conflicts",
    "retracted_dependencies",
    "acquisition_allowed",
    "retrievals",
    "acquisitions",
    "advisor_asks",
    "fresh_since_retrieve",
    "call_none",
    "call_legal",
    "call_refused",
    "repeats",
    "advisor_accept_rate_known",
    "advisor_accept_rate",
    "advisor_agreement_known",
    "advisor_agreement",
    "tool_risk",
    "steps_left",
    "time_left",
    "budget_left",
    "missing_slot",
    "candidate_retrieve",
    "candidate_ask_advisor",
    "candidate_run_tool",
    "candidate_acquire",
    "candidate_verify",
    "candidate_answer",
    "candidate_ask_user",
    "candidate_abstain",
    "candidate_stop",
    "candidate_count",
];

fn unit(v: f64) -> f64 {
    v.clamp(0.0, 1.0)
}

fn capped(n: usize, cap: usize) -> f64 {
    n.min(cap) as f64 / cap as f64
}

fn flag(b: bool) -> f64 {
    if b { 1.0 } else { 0.0 }
}

/// The input of the network for `act` among `candidate_count` legal candidates.
pub fn features(s: &Signals, act: Act, candidate_count: usize) -> Vec<f64> {
    let level = s.best_level.map(|l| match l {
        Level::Candidate => 0.0,
        Level::Sourced => 1.0,
        Level::Corroborated => 2.0,
        Level::Verified => 3.0,
        Level::Reviewed => 4.0,
    });
    let mut x = vec![
        unit(s.coverage),
        level.map_or(0.0, |l| l / 4.0),
        flag(level.is_some()),
        capped(s.accepted, 8),
        capped(s.below_required, 4),
        capped(s.pending_candidates, 4),
        capped(s.open_conflicts, 4),
        capped(s.retracted_dependencies, 4),
        flag(s.acquisition_allowed),
        capped(s.retrievals as usize, 4),
        capped(s.acquisitions as usize, 4),
        capped(s.advisor_asks as usize, 8),
        flag(s.fresh_since_retrieve),
        flag(s.call == CallState::None),
        flag(s.call == CallState::Legal),
        flag(s.call == CallState::Refused),
        capped(s.repeats as usize, 8),
        flag(s.advisor_accept_rate.is_some()),
        s.advisor_accept_rate.map_or(0.0, unit),
        flag(s.advisor_agreement.is_some()),
        s.advisor_agreement.map_or(0.0, unit),
        capped(s.tool_risk as usize, 3),
        capped(s.steps_left as usize, 10),
        s.time_left_seconds.clamp(0.0, 300.0) / 300.0,
        unit(s.budget_left),
        flag(s.missing_slot.is_some()),
    ];
    x.extend(Act::ALL.iter().map(|a| flag(*a == act)));
    x.push(capped(candidate_count, Act::ALL.len()));
    debug_assert_eq!(x.len(), FEATURE_NAMES.len());
    x
}

/// A malformed network file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetworkError(pub String);

impl std::fmt::Display for NetworkError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for NetworkError {}

#[derive(Debug, Clone, PartialEq)]
struct Layer {
    weights: Vec<Vec<f64>>,
    bias: Vec<f64>,
    relu: bool,
}

/// An exported network with its calibration and abstention threshold.
#[derive(Debug, Clone, PartialEq)]
pub struct Network {
    layers: Vec<Layer>,
    temperature: f64,
    threshold: f64,
}

fn err<T>(message: &str) -> Result<T, NetworkError> {
    Err(NetworkError(message.to_owned()))
}

fn numbers(v: &Value) -> Result<Vec<f64>, NetworkError> {
    v.as_array()
        .ok_or_else(|| NetworkError("expected a list of numbers".into()))?
        .iter()
        .map(|n| {
            n.as_f64()
                .filter(|x| x.is_finite())
                .ok_or_else(|| NetworkError("a weight is not a finite number".into()))
        })
        .collect()
}

impl Network {
    /// The network of the JSON text `laris.model.decision.network.dumps` wrote. Shapes, names and numbers are
    /// checked; a file that fails is refused whole.
    pub fn from_json(text: &str) -> Result<Network, NetworkError> {
        let v: Value =
            serde_json::from_str(text).map_err(|e| NetworkError(format!("not JSON: {e}")))?;
        if v["format"] != "laris-decision-net" || v["version"] != 1 {
            return err("not a laris-decision-net version 1");
        }
        let names: Vec<&str> = v["features"]
            .as_array()
            .map(|a| a.iter().filter_map(Value::as_str).collect())
            .unwrap_or_default();
        if names != FEATURE_NAMES {
            return err("the feature names differ from this build's");
        }
        let raw = v["layers"]
            .as_array()
            .filter(|l| !l.is_empty())
            .ok_or_else(|| NetworkError("no layers".into()))?;
        let mut layers = Vec::new();
        let mut width = FEATURE_NAMES.len();
        for (i, layer) in raw.iter().enumerate() {
            let weights: Vec<Vec<f64>> = layer["weights"]
                .as_array()
                .ok_or_else(|| NetworkError(format!("layer {i}: no weights")))?
                .iter()
                .map(numbers)
                .collect::<Result<_, _>>()?;
            let bias = numbers(&layer["bias"])?;
            if weights.is_empty() || weights.iter().any(|row| row.len() != width) {
                return err(&format!("layer {i}: expected {width} inputs per row"));
            }
            if bias.len() != weights.len() {
                return err(&format!("layer {i}: bias does not match the output size"));
            }
            let relu = match layer["activation"].as_str() {
                Some("relu") => true,
                Some("none") => false,
                _ => return err(&format!("layer {i}: unknown activation")),
            };
            width = weights.len();
            layers.push(Layer {
                weights,
                bias,
                relu,
            });
        }
        if width != 1 {
            return err("the last layer must have one output");
        }
        let temperature = v["calibration"]["temperature"]
            .as_f64()
            .filter(|t| t.is_finite() && *t > 0.0)
            .ok_or_else(|| NetworkError("temperature must be positive".into()))?;
        let threshold = v["abstention"]["threshold"]
            .as_f64()
            .filter(|t| t.is_finite() && *t >= 0.0)
            .ok_or_else(|| NetworkError("threshold must be a non-negative number".into()))?;
        Ok(Network {
            layers,
            temperature,
            threshold,
        })
    }

    /// The abstention threshold sealed with the network.
    pub fn threshold(&self) -> f64 {
        self.threshold
    }

    /// The number of weights and biases.
    pub fn parameters(&self) -> usize {
        self.layers
            .iter()
            .map(|l| l.weights.iter().map(Vec::len).sum::<usize>() + l.bias.len())
            .sum()
    }

    /// The raw score of an input.
    pub fn logit(&self, x: &[f64]) -> f64 {
        let mut h = x.to_vec();
        for layer in &self.layers {
            h = layer
                .weights
                .iter()
                .zip(&layer.bias)
                .map(|(row, b)| {
                    let z = row.iter().zip(&h).map(|(w, v)| w * v).sum::<f64>() + b;
                    if layer.relu { z.max(0.0) } else { z }
                })
                .collect();
        }
        h[0]
    }

    /// The calibrated probability that the candidate's outcome is good.
    pub fn probability(&self, x: &[f64]) -> f64 {
        let z = self.logit(x) / self.temperature;
        if z >= 0.0 {
            1.0 / (1.0 + (-z).exp())
        } else {
            let e = z.exp();
            e / (1.0 + e)
        }
    }
}

/// Chooses with the network and falls back to the rule decider below the sealed threshold.
#[derive(Debug, Clone)]
pub struct NetworkChooser {
    network: Network,
    rules: RuleDecider,
}

impl NetworkChooser {
    /// A chooser. `rules` supplies the legal candidates and the cautious fallback.
    pub fn new(network: Network, rules: RuleDecider) -> NetworkChooser {
        NetworkChooser { network, rules }
    }

    /// The calibrated probability of every legal candidate, in the order of [`Act::ALL`].
    pub fn scores(&self, signals: &Signals) -> Vec<(Act, f64)> {
        let candidates = legal(signals, &self.rules.settings());
        let n = candidates.len();
        candidates
            .into_iter()
            .map(|act| (act, self.network.probability(&features(signals, act, n))))
            .collect()
    }

    /// The network's pick among the legal candidates and its calibrated confidence. The first of the best wins a tie
    /// (the order of [`Act::ALL`]), so the result is deterministic.
    pub fn pick(&self, signals: &Signals) -> (Act, f64, Vec<Act>) {
        let candidates = legal(signals, &self.rules.settings());
        let n = candidates.len();
        let mut best: Option<(Act, f64)> = None;
        for act in &candidates {
            let p = self.network.probability(&features(signals, *act, n));
            if best.is_none_or(|(_, q)| p > q) {
                best = Some((*act, p));
            }
        }
        // `Stop`, `Abstain` and `AskUser` are always legal, so a candidate always exists
        let (act, confidence) = best.unwrap_or((Act::Abstain, 0.0));
        (act, confidence, candidates)
    }
}

impl Chooser for NetworkChooser {
    fn choose(&mut self, signals: &Signals) -> Choice {
        let (act, confidence, candidates) = self.pick(signals);
        if confidence >= self.network.threshold {
            return Choice {
                act,
                rule: "network".to_owned(),
                reason: format!(
                    "network score {confidence:.3} >= threshold {:.3}",
                    self.network.threshold
                ),
                limit: None,
                signals: signals.clone(),
                candidates,
                confidence: Some(confidence),
            };
        }
        let cautious = self.rules.decide(signals);
        Choice {
            act: cautious.act,
            rule: "fallback".to_owned(),
            reason: format!(
                "network chose {} with confidence {confidence:.3} < threshold {:.3}; the rule decider ({}) chose {}",
                act.as_str(),
                self.network.threshold,
                cautious.rule,
                cautious.act.as_str()
            ),
            limit: cautious.limit,
            signals: signals.clone(),
            candidates: cautious.candidates,
            confidence: Some(confidence),
        }
    }
}
