//! The held-out gates N1 to N8 of the decision network (T171, ADR-024 section 8).
//!
//! [`evaluate`] measures a [`NetworkChooser`] against the [`RuleDecider`] on the states of a sealed split. It only
//! scores and chooses: nothing here fits, trains or tunes. A missing measurement is [`Status::NotVerified`], never a
//! pass (ADR-008), and the thresholds come from [`Limits`], which the caller reads from configuration.
//!
//! A *state* is one group of the dataset: the signals, the legal candidates and, for each candidate, whether its
//! outcome was good. A decider is judged by the outcome of the action it chooses in the state.

use std::collections::BTreeMap;
use std::time::Instant;

use serde_json::{Value, json};

use crate::dataset::Example;
use crate::decide::{Act, Chooser, RuleDecider, Signals, legal};
use crate::network::NetworkChooser;

/// The thresholds of the gates and the settings of the measurement. Nothing is defaulted.
#[derive(Debug, Clone, PartialEq)]
pub struct Limits {
    /// N1: the least gain over the rule decider, in points of accuracy.
    pub min_gain_points: f64,
    /// N1: the two-sided confidence level of the bootstrap, in percent (95 gives a 2.5 % lower tail).
    pub confidence_pct: f64,
    /// N1: bootstrap resamples of the states.
    pub bootstrap_resamples: usize,
    /// N1: seed of the resampling (the result is deterministic).
    pub bootstrap_seed: u64,
    /// N2: the largest share of `answer` decisions the accepted set did not support.
    pub max_unsupported_rate: f64,
    /// N3: the largest expected calibration error.
    pub max_ece: f64,
    /// N3: equal-width bins of the error.
    pub ece_bins: usize,
    /// N4: the least share of required abstentions that the decider makes.
    pub min_abstain_recall: f64,
    /// N4: how far above the rule decider the over-abstention may be, in points.
    pub max_overabstain_margin_points: f64,
    /// N6: the largest absolute difference between Python and Rust scores.
    pub max_parity_diff: f64,
    /// N7: the largest 95th-percentile latency of one decision, in milliseconds.
    pub max_p95_ms: f64,
    /// N7: how many times the whole set is timed.
    pub latency_repeats: usize,
}

/// The result of one gate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    /// Measured and within the threshold.
    Pass,
    /// Measured and outside the threshold.
    Fail,
    /// Not measured: no pass.
    NotVerified,
}

impl Status {
    /// The name written in the report.
    pub fn as_str(self) -> &'static str {
        match self {
            Status::Pass => "PASS",
            Status::Fail => "FAIL",
            Status::NotVerified => "NOT VERIFIED",
        }
    }
}

/// One gate with what was measured.
#[derive(Debug, Clone, PartialEq)]
pub struct GateResult {
    /// `N1` to `N8`.
    pub id: &'static str,
    /// The verdict.
    pub status: Status,
    /// The numbers behind it.
    pub measured: Value,
    /// What the verdict means and what it does not.
    pub note: String,
}

impl GateResult {
    fn new(id: &'static str, status: Status, measured: Value, note: &str) -> GateResult {
        GateResult {
            id,
            status,
            measured,
            note: note.to_owned(),
        }
    }

    /// The report entry.
    pub fn to_json(&self) -> Value {
        json!({
            "gate": self.id,
            "status": self.status.as_str(),
            "measured": self.measured,
            "note": self.note,
        })
    }
}

/// One decision situation: the signals, the legal candidates and the label of each candidate.
#[derive(Debug, Clone)]
pub struct State {
    /// The group of the dataset.
    pub group: String,
    /// The signals.
    pub signals: Signals,
    /// The legal actions the examples carried.
    pub candidates: Vec<Act>,
    /// Whether the outcome of each candidate was good.
    pub good: BTreeMap<Act, bool>,
}

/// Groups examples into states. It refuses a group whose examples disagree on the signals or the candidates, and a
/// group that has no label for one of its candidates, so a measurement never rests on a broken state.
pub fn states(examples: &[Example]) -> Result<Vec<State>, String> {
    let mut by_group: BTreeMap<String, State> = BTreeMap::new();
    for e in examples {
        let state = by_group.entry(e.group.clone()).or_insert_with(|| State {
            group: e.group.clone(),
            signals: e.signals.clone(),
            candidates: e.candidates.clone(),
            good: BTreeMap::new(),
        });
        if state.signals != e.signals || state.candidates != e.candidates {
            return Err(format!("group {}: the examples disagree", e.group));
        }
        if state.good.insert(e.action, e.outcome.good).is_some() {
            return Err(format!(
                "group {}: {} is labelled twice",
                e.group,
                e.action.as_str()
            ));
        }
    }
    let out: Vec<State> = by_group.into_values().collect();
    for s in &out {
        if let Some(a) = s.candidates.iter().find(|a| !s.good.contains_key(a)) {
            return Err(format!("group {}: {} has no label", s.group, a.as_str()));
        }
    }
    Ok(out)
}

fn splitmix(state: &mut u64) -> u64 {
    *state = state.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = *state;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

/// The expected calibration error with equal-width bins, the same formula as the Python reference.
pub fn expected_calibration_error(pairs: &[(f64, bool)], bins: usize) -> f64 {
    if pairs.is_empty() || bins == 0 {
        return 0.0;
    }
    let mut count = vec![0usize; bins];
    let mut confidence = vec![0.0f64; bins];
    let mut right = vec![0.0f64; bins];
    for (p, good) in pairs {
        let at = ((p * bins as f64) as usize).min(bins - 1);
        count[at] += 1;
        confidence[at] += p;
        right[at] += f64::from(u8::from(*good));
    }
    let n = pairs.len() as f64;
    (0..bins)
        .filter(|&b| count[b] > 0)
        .map(|b| {
            let c = count[b] as f64;
            c / n * (confidence[b] / c - right[b] / c).abs()
        })
        .sum()
}

/// What one decider chose in every state.
struct Run {
    /// The chosen act per state.
    acts: Vec<Act>,
    /// Whether each chosen act had a good outcome.
    right: Vec<bool>,
}

fn run(states: &[State], mut choose: impl FnMut(&Signals) -> Act) -> Run {
    let acts: Vec<Act> = states.iter().map(|s| choose(&s.signals)).collect();
    let right = states
        .iter()
        .zip(&acts)
        .map(|(s, a)| s.good.get(a).copied().unwrap_or(false))
        .collect();
    Run { acts, right }
}

fn share(flags: impl Iterator<Item = bool>) -> f64 {
    let (mut yes, mut all) = (0usize, 0usize);
    for f in flags {
        all += 1;
        yes += usize::from(f);
    }
    if all == 0 {
        0.0
    } else {
        yes as f64 / all as f64
    }
}

/// Accuracy gain of `net` over `rule` in points, with the lower bound of a paired bootstrap over the states.
fn gain(net: &Run, rule: &Run, limits: &Limits) -> (f64, f64, f64, f64) {
    let n = net.right.len();
    let acc_net = share(net.right.iter().copied());
    let acc_rule = share(rule.right.iter().copied());
    // per state difference in {-1, 0, 1}
    let diff: Vec<i32> = net
        .right
        .iter()
        .zip(&rule.right)
        .map(|(a, b)| i32::from(*a) - i32::from(*b))
        .collect();
    let mut seed = limits.bootstrap_seed;
    let mut means: Vec<f64> = (0..limits.bootstrap_resamples)
        .map(|_| {
            let sum: i64 = (0..n)
                .map(|_| i64::from(diff[(splitmix(&mut seed) % n.max(1) as u64) as usize]))
                .sum();
            sum as f64 / n.max(1) as f64
        })
        .collect();
    means.sort_by(f64::total_cmp);
    let tail = (100.0 - limits.confidence_pct) / 200.0;
    let at = |q: f64| {
        let i = ((means.len() as f64 * q) as usize).min(means.len().saturating_sub(1));
        means.get(i).copied().unwrap_or(0.0) * 100.0
    };
    (acc_net, acc_rule, at(tail), at(1.0 - tail))
}

fn unsupported(states: &[State], run: &Run) -> (usize, usize) {
    let answers = run.acts.iter().filter(|a| **a == Act::Answer).count();
    let wrong = states
        .iter()
        .zip(&run.acts)
        .filter(|(s, a)| **a == Act::Answer && !s.good.get(&Act::Answer).copied().unwrap_or(false))
        .count();
    (wrong, answers)
}

fn n1_n2(
    id1: &'static str,
    id2: &'static str,
    states: &[State],
    net: &Run,
    rule: &Run,
    limits: &Limits,
    what: &str,
) -> [GateResult; 2] {
    let (acc_net, acc_rule, low, high) = gain(net, rule, limits);
    let gain_points = (acc_net - acc_rule) * 100.0;
    let n1 = if gain_points >= limits.min_gain_points && low > 0.0 {
        Status::Pass
    } else {
        Status::Fail
    };
    let (wrong_net, answers_net) = unsupported(states, net);
    let (wrong_rule, answers_rule) = unsupported(states, rule);
    let rate = |w: usize, a: usize| if a == 0 { 0.0 } else { w as f64 / a as f64 };
    let (rate_net, rate_rule) = (rate(wrong_net, answers_net), rate(wrong_rule, answers_rule));
    let n2 = if answers_net == 0 {
        Status::NotVerified
    } else if rate_net <= limits.max_unsupported_rate && rate_net <= rate_rule {
        Status::Pass
    } else {
        Status::Fail
    };
    [
        GateResult::new(
            id1,
            n1,
            json!({
                "states": states.len(),
                "network_accuracy": acc_net,
                "rule_accuracy": acc_rule,
                "gain_points": gain_points,
                "bootstrap_gain_points_lower": low,
                "bootstrap_gain_points_upper": high,
                "required_gain_points": limits.min_gain_points,
                "set": what,
            }),
            "Accuracy is the share of states where the chosen action's outcome was good. The gate needs the gain and a \
             bootstrap lower bound above zero; a rule decider that is already right leaves no room for either.",
        ),
        GateResult::new(
            id2,
            n2,
            json!({
                "network_answers": answers_net,
                "network_unsupported": wrong_net,
                "network_rate": rate_net,
                "rule_answers": answers_rule,
                "rule_unsupported": wrong_rule,
                "rule_rate": rate_rule,
                "limit": limits.max_unsupported_rate,
                "set": what,
            }),
            "An `answer` is unsupported when the outcome label of `answer` in that state is not good (the accepted set \
             did not cover the question).",
        ),
    ]
}

/// The nearest-rank 95th percentile.
fn p95(values: &mut [f64]) -> f64 {
    values.sort_by(f64::total_cmp);
    let rank = ((values.len() as f64) * 0.95).ceil() as usize;
    values
        .get(rank.saturating_sub(1).min(values.len().saturating_sub(1)))
        .copied()
        .unwrap_or(0.0)
}

/// What the measurement needs besides the states.
pub struct Inputs<'a> {
    /// The sealed held-out states.
    pub heldout: &'a [State],
    /// The states of the withheld advisor, when the dataset has that split.
    pub unseen_advisor: Option<&'a [State]>,
    /// The largest absolute difference between the Python float64 reference and the Rust scores, measured on the
    /// same examples by `scripts/decision_net_parity.py`; `None` when it was not run.
    pub parity_max_diff: Option<f64>,
}

/// The shape of the report: the gates and whether every one passed.
pub struct Report {
    /// N1 to N8.
    pub gates: Vec<GateResult>,
}

impl Report {
    /// True when every gate passed. A gate not verified is not a pass.
    pub fn all_pass(&self) -> bool {
        self.gates.iter().all(|g| g.status == Status::Pass)
    }
}

/// Measures the gates. `chooser` is the deployed network chooser, fallback included; `rules` is the baseline.
pub fn evaluate(
    inputs: &Inputs<'_>,
    chooser: &mut NetworkChooser,
    rules: &RuleDecider,
    limits: &Limits,
) -> Report {
    let states = inputs.heldout;
    let mut net_choices: Vec<crate::decide::Choice> = Vec::with_capacity(states.len());
    for s in states {
        net_choices.push(chooser.choose(&s.signals));
    }
    let mut at = 0usize;
    let net = run(states, |_| {
        let act = net_choices[at].act;
        at += 1;
        act
    });
    let rule = run(states, |s| rules.decide(s).act);
    let mut gates = Vec::new();
    gates.extend(n1_n2("N1", "N2", states, &net, &rule, limits, "heldout"));

    // N3: every (state, candidate) pair is one probability against one label
    let pairs: Vec<(f64, bool)> = states
        .iter()
        .flat_map(|s| {
            chooser
                .scores(&s.signals)
                .into_iter()
                .map(|(a, p)| (p, s.good.get(&a).copied().unwrap_or(false)))
                .collect::<Vec<_>>()
        })
        .collect();
    let chosen: Vec<(f64, bool)> = net_choices
        .iter()
        .zip(states)
        .map(|(c, s)| {
            (
                c.confidence.unwrap_or(0.0),
                s.good.get(&c.act).copied().unwrap_or(false),
            )
        })
        .collect();
    let ece = expected_calibration_error(&pairs, limits.ece_bins);
    let fell_back = net_choices.iter().filter(|c| c.rule == "fallback").count();
    gates.push(GateResult::new(
        "N3",
        if ece <= limits.max_ece {
            Status::Pass
        } else {
            Status::Fail
        },
        json!({
            "pair_ece": ece,
            "pairs": pairs.len(),
            "chosen_ece": expected_calibration_error(&chosen, limits.ece_bins),
            "fell_back_to_rules": fell_back,
            "limit": limits.max_ece,
        }),
        "The gate is the error over every (state, legal candidate) probability against its outcome label.",
    ));

    // N4
    let required: Vec<usize> = (0..states.len())
        .filter(|&i| states[i].good.get(&Act::Abstain).copied().unwrap_or(false))
        .collect();
    let recall = |r: &Run| share(required.iter().map(|&i| r.acts[i] == Act::Abstain));
    let over = |r: &Run| {
        share(states.iter().zip(&r.acts).map(|(s, a)| {
            *a == Act::Abstain && !s.good.get(&Act::Abstain).copied().unwrap_or(false)
        }))
    };
    let (recall_net, over_net, over_rule) = (recall(&net), over(&net), over(&rule));
    let n4 = if required.is_empty() {
        Status::NotVerified
    } else if recall_net >= limits.min_abstain_recall
        && (over_net - over_rule) * 100.0 <= limits.max_overabstain_margin_points
    {
        Status::Pass
    } else {
        Status::Fail
    };
    gates.push(GateResult::new(
        "N4",
        n4,
        json!({
            "required_abstentions": required.len(),
            "network_recall": recall_net,
            "rule_recall": recall(&rule),
            "network_over_abstention": over_net,
            "rule_over_abstention": over_rule,
            "min_recall": limits.min_abstain_recall,
            "max_margin_points": limits.max_overabstain_margin_points,
        }),
        "Required abstentions are the states where `abstain` was labelled good. Over-abstention is the share of all \
         states where the decider abstained although `abstain` was not good.",
    ));

    // N5
    match inputs.unseen_advisor {
        Some(unseen) if !unseen.is_empty() => {
            let mut c = chooser.clone();
            let n = run(unseen, |s| c.choose(s).act);
            let r = run(unseen, |s| rules.decide(s).act);
            let [a, b] = n1_n2("N1", "N2", unseen, &n, &r, limits, "unseen advisor");
            let status = if a.status == Status::Pass && b.status == Status::Pass {
                Status::Pass
            } else if a.status == Status::NotVerified || b.status == Status::NotVerified {
                Status::NotVerified
            } else {
                Status::Fail
            };
            gates.push(GateResult::new(
                "N5",
                status,
                json!({"n1": a.measured, "n2": b.measured}),
                "N1 and N2 on the examples of the advisor withheld from training and validation.",
            ));
        }
        _ => gates.push(GateResult::new(
            "N5",
            Status::NotVerified,
            json!({"states": 0}),
            "The dataset has no withheld advisor: every example is a scenario example with no advisor, so there is \
             nothing unseen to measure.",
        )),
    }

    // N6
    gates.push(match inputs.parity_max_diff {
        Some(d) if d.is_finite() => GateResult::new(
            "N6",
            if d <= limits.max_parity_diff {
                Status::Pass
            } else {
                Status::Fail
            },
            json!({"max_abs_diff": d, "limit": limits.max_parity_diff}),
            "Python float64 reference against the Rust forward pass, on every (state, candidate) of the held-out set.",
        ),
        _ => GateResult::new(
            "N6",
            Status::NotVerified,
            json!({}),
            "The parity file was not given; run scripts/decision_net_parity.py on the scores this command writes.",
        ),
    });

    // N7: time the decision alone, the signals are already built
    let mut times: Vec<f64> = Vec::with_capacity(states.len() * limits.latency_repeats);
    for _ in 0..limits.latency_repeats {
        for s in states {
            let started = Instant::now();
            let choice = chooser.choose(&s.signals);
            let elapsed = started.elapsed().as_secs_f64() * 1000.0;
            std::hint::black_box(&choice);
            times.push(elapsed);
        }
    }
    let p95_ms = p95(&mut times);
    gates.push(GateResult::new(
        "N7",
        if times.is_empty() {
            Status::NotVerified
        } else if p95_ms <= limits.max_p95_ms {
            Status::Pass
        } else {
            Status::Fail
        },
        json!({
            "decisions_timed": times.len(),
            "p95_ms": p95_ms,
            "max_ms": times.last().copied().unwrap_or(0.0),
            "limit_ms": limits.max_p95_ms,
        }),
        "One `choose` call, measured on the machine that ran the command. The specification does not define the \
         reference CPU: the owner confirms that this machine is it, or repeats the run on it.",
    ));

    // N8
    let settings = rules.settings();
    let mut outside = 0usize;
    for (c, s) in net_choices.iter().zip(states) {
        let allowed = legal(&s.signals, &settings);
        if !allowed.contains(&c.act) || c.candidates != allowed {
            outside += 1;
        }
    }
    gates.push(GateResult::new(
        "N8",
        if outside == 0 {
            Status::Pass
        } else {
            Status::Fail
        },
        json!({
            "decisions": states.len(),
            "outside_legal_list": outside,
        }),
        "Zero decisions outside the legal list is measured here. Zero policy bypass is not a property of the \
         scores: the chooser returns an `Act` only, and the seam runs every act through the same tool gate; \
         `tests/seam.rs::a_chooser_cannot_bypass_the_tool_gate_or_the_composer` checks it with a chooser forced to \
         every legal act.",
    ));
    Report { gates }
}
