//! The cognitive evaluation of the main brain (T172, SR-K7, ADR-024 section 8): one command, one report.
//!
//! ```text
//! cargo run --release -p laris-brain --example cognitive_eval -- \
//!     --config configs/cognitive-eval.json --out reports/brain/T172-cognitive-evaluation.json [--advisors FILE]...
//! ```
//!
//! The advisors are **data**: each one is a table of what it replies to each question, how it rewords each claim and
//! which claims it proposes, every entry labelled by construction as supported or not. The built-in advisors of the
//! configuration are scripted profiles. A recorded advisor (for example ResearchLLM, answered offline by the owner) is
//! one more file of the same shape, passed with `--advisors`; nothing else changes. The harness drives the real write
//! gate, the real rule decider behind the loop's `Decider` seam, the real answer assembly with its outside-set check and
//! the real prompt layer, and compares the brain with the programme-2 behaviour in which the advisor decides.
//!
//! The five measures of SR-K7 are system measurements of this harness on these scenarios, not a qualification of any
//! model. The report says what each number does not show. Nothing here trains, fits or tunes.

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::atomic::{AtomicU32, Ordering};

use laris_brain::answer::{
    ABSTENTION, AnswerSettings, Rephraser, assemble, compose, verify_answer,
};
use laris_brain::decide::{Act, Choice, RuleDecider, RuleSettings, Signals};
use laris_brain::seam::{Brain, BrainDecider};
use laris_brain::{ClaimProposal, Gate, GateSettings, MetadataCheck, Proposer, SourceProposal};
use laris_config::Catalogue;
use laris_config::settings::Agent;
use laris_core::prompt::{Budget, Input, Pin, PinKind, assemble as assemble_prompt};
use laris_core::{
    Clock, Decider, Driver, FollowModel, ModelAnswer, Recorder, ScriptedModel, Session, ToolRunner,
};
use laris_protocol::{ChatMessage, Content, Event, Role};
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use laris_vault::VaultIndex;
use laris_vault::brain::Level;
use serde_json::{Map, Value, json};

type Res<T> = Result<T, String>;

struct Temp(PathBuf);

impl Temp {
    fn new() -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-cognition-{}-{}",
            std::process::id(),
            N.fetch_add(1, Ordering::SeqCst)
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("temp dir");
        Temp(dir)
    }
}

impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

// ---------------------------------------------------------------- configuration

fn num(v: &Value, k: &str) -> Res<f64> {
    v.get(k)
        .and_then(Value::as_f64)
        .ok_or(format!("`{k}` is missing or not a number"))
}

fn whole(v: &Value, k: &str) -> Res<u64> {
    v.get(k)
        .and_then(Value::as_u64)
        .ok_or(format!("`{k}` is missing or not a whole number"))
}

fn text<'a>(v: &'a Value, k: &str) -> Res<&'a str> {
    v.get(k)
        .and_then(Value::as_str)
        .ok_or(format!("`{k}` is missing or not text"))
}

fn level(v: &Value, k: &str) -> Res<Level> {
    Level::parse(text(v, k)?).ok_or(format!("`{k}` is not a certainty level"))
}

struct Settings {
    gate: GateSettings,
    answer: AnswerSettings,
    rules: RuleSettings,
    steps: u32,
    seconds: f64,
    budget: Budget,
    turns_after: Vec<u64>,
    filler_words: usize,
}

fn settings(v: &Value) -> Res<Settings> {
    let s = v.get("settings").ok_or("`settings` is missing")?;
    let get = |k: &str| s.get(k).ok_or(format!("`settings.{k}` is missing"));
    let (g, a, r, t, c) = (
        get("gate")?,
        get("answer")?,
        get("rules")?,
        get("turn")?,
        get("context")?,
    );
    Ok(Settings {
        gate: GateSettings {
            min_support: num(g, "min_support")?,
            min_equivalence: num(g, "min_equivalence")?,
            subject_overlap: num(g, "subject_overlap")?,
            search_depth: whole(g, "search_depth")? as usize,
            max_bytes: whole(g, "max_bytes")? as usize,
        },
        answer: AnswerSettings {
            min_cover: num(a, "min_cover")?,
            min_level: level(a, "min_level")?,
            max_notes: whole(a, "max_notes")? as usize,
        },
        rules: RuleSettings {
            required_level: level(r, "required_level")?,
            min_coverage: num(r, "min_coverage")?,
            max_retrievals: whole(r, "max_retrievals")? as u32,
            max_acquisitions: whole(r, "max_acquisitions")? as u32,
            max_advisor_asks: whole(r, "max_advisor_asks")? as u32,
            max_repeats: whole(r, "max_repeats")? as u32,
        },
        steps: whole(t, "steps")? as u32,
        seconds: num(t, "seconds")?,
        budget: Budget {
            window: whole(c, "window")?,
            threshold: num(c, "threshold")?,
            auto_compact: c
                .get("auto_compact")
                .and_then(Value::as_bool)
                .ok_or("`auto_compact` is missing")?,
            output_reserve: whole(c, "reserve")?,
            tools_tokens: whole(c, "tools")?,
            layer_share: num(c, "layer_share")?,
            pinned_share: num(c, "pinned_share")?,
            summary_share: num(c, "summary_share")?,
            target_ratio: num(c, "target_ratio")?,
            line_chars: whole(c, "line_chars")? as usize,
        },
        turns_after: s
            .get("turns_after")
            .and_then(Value::as_array)
            .ok_or("`turns_after` is missing")?
            .iter()
            .filter_map(Value::as_u64)
            .collect(),
        filler_words: whole(s, "filler_words")? as usize,
    })
}

struct Reply {
    text: String,
    supported: bool,
}

struct Proposal {
    statement: String,
    source: Option<String>,
    quote: String,
    supported: bool,
}

struct Advisor {
    name: String,
    kind: String,
    replies: BTreeMap<String, Reply>,
    /// claim statement to (wording, faithful)
    rewordings: BTreeMap<String, (String, bool)>,
    proposals: Vec<Proposal>,
}

struct Question {
    id: String,
    text: String,
    answerable: bool,
}

fn advisor(v: &Value, statements: &BTreeMap<String, String>) -> Res<Advisor> {
    let name = text(v, "name")?.to_owned();
    let replies = v
        .get("replies")
        .and_then(Value::as_object)
        .ok_or(format!("{name}: `replies` is missing"))?
        .iter()
        .map(|(q, r)| {
            Ok((
                q.clone(),
                Reply {
                    text: text(r, "text")?.to_owned(),
                    supported: r
                        .get("supported")
                        .and_then(Value::as_bool)
                        .ok_or("`supported` is missing")?,
                },
            ))
        })
        .collect::<Res<BTreeMap<_, _>>>()?;
    let rewordings = v
        .get("rewordings")
        .and_then(Value::as_object)
        .ok_or(format!("{name}: `rewordings` is missing"))?
        .iter()
        .map(|(c, r)| {
            let statement = statements
                .get(c)
                .ok_or(format!("{name}: no claim {c}"))?
                .clone();
            Ok((
                statement,
                (
                    text(r, "text")?.to_owned(),
                    r.get("faithful")
                        .and_then(Value::as_bool)
                        .ok_or("`faithful` is missing")?,
                ),
            ))
        })
        .collect::<Res<BTreeMap<_, _>>>()?;
    let proposals = v
        .get("proposals")
        .and_then(Value::as_array)
        .ok_or(format!("{name}: `proposals` is missing"))?
        .iter()
        .map(|p| {
            Ok(Proposal {
                statement: text(p, "statement")?.to_owned(),
                source: p.get("source").and_then(Value::as_str).map(str::to_owned),
                quote: text(p, "quote")?.to_owned(),
                supported: p
                    .get("supported")
                    .and_then(Value::as_bool)
                    .ok_or("`supported` is missing")?,
            })
        })
        .collect::<Res<Vec<_>>>()?;
    Ok(Advisor {
        name,
        kind: text(v, "kind")?.to_owned(),
        replies,
        rewordings,
        proposals,
    })
}

// ---------------------------------------------------------------- the vault

fn vault(cfg: &Value, s: &Settings) -> Res<Temp> {
    let t = Temp::new();
    let gate = Gate::new(&t.0, s.gate, Box::new(|| "2026-11-20".into()));
    let proposer = Proposer("fixture".into());
    for src in cfg["sources"].as_array().ok_or("`sources` is missing")? {
        gate.submit_source(SourceProposal {
            title: text(src, "title")?.to_owned(),
            kind: "document".into(),
            identifier: text(src, "identifier")?.to_owned(),
            text: text(src, "text")?.to_owned(),
            command: None,
            inputs_sha256: None,
            cites: vec![],
            dataset: None,
            metadata: MetadataCheck::Verified("fixture-registry".into()),
            proposer: proposer.clone(),
        })
        .map_err(|e| e.to_string())?;
    }
    for c in cfg["claims"].as_array().ok_or("`claims` is missing")? {
        let statement = text(c, "statement")?.to_owned();
        let decision = gate
            .submit_claim(ClaimProposal {
                statement: statement.clone(),
                source: Some(text(c, "source")?.to_owned()),
                quote: statement.clone(),
                requested: Level::Sourced,
                evidence: vec![],
                solver: None,
                proposer: proposer.clone(),
            })
            .map_err(|e| e.to_string())?;
        if !decision.is_accepted() {
            return Err(format!("fixture claim refused: {statement}"));
        }
    }
    Ok(t)
}

// ---------------------------------------------------------------- measure 1a: the write gate

#[derive(Default)]
struct GateCount {
    unsupported_sent: usize,
    unsupported_accepted: usize,
    supported_sent: usize,
    supported_accepted: usize,
    /// Supported proposals that repeat a claim the brain holds already: the gate refuses a duplicate, so they say
    /// nothing about acceptance and are left out of the rate.
    already_held: usize,
}

fn through_the_gate(cfg: &Value, s: &Settings, a: &Advisor) -> Res<GateCount> {
    let mut n = GateCount::default();
    for p in &a.proposals {
        // a fresh vault each time: one proposal never changes what the next one meets
        let v = vault(cfg, s)?;
        let gate = Gate::new(&v.0, s.gate, Box::new(|| "2026-11-20".into()));
        let decision = gate
            .submit_claim(ClaimProposal {
                statement: p.statement.clone(),
                source: p.source.clone(),
                quote: p.quote.clone(),
                requested: Level::Sourced,
                evidence: vec![],
                solver: None,
                proposer: Proposer(a.name.clone()),
            })
            .map_err(|e| e.to_string())?;
        let accepted = decision.is_accepted();
        let duplicate = matches!(
            decision,
            laris_brain::Decision::Refused {
                reason: laris_brain::Refusal::Duplicate,
                ..
            }
        );
        if p.supported {
            if duplicate {
                n.already_held += 1;
            } else {
                n.supported_sent += 1;
                n.supported_accepted += usize::from(accepted);
            }
        } else {
            n.unsupported_sent += 1;
            n.unsupported_accepted += usize::from(accepted);
        }
    }
    Ok(n)
}

// ---------------------------------------------------------------- measures 1b and 2: rewording

struct Reword<'a>(&'a BTreeMap<String, (String, bool)>);

impl Rephraser for Reword<'_> {
    fn rephrase(&self, _body: &str, cited: &[String]) -> Result<String, String> {
        cited
            .first()
            .and_then(|c| self.0.get(c.trim()))
            .map(|(w, _)| w.clone())
            .ok_or_else(|| "the advisor has no rewording".to_owned())
    }
}

#[derive(Default)]
struct RewordCount {
    offered_faithful: usize,
    offered_unfaithful: usize,
    kept_faithful: usize,
    kept_unfaithful: usize,
    answer_sentences: usize,
    answer_sentences_faithful: usize,
    verify_problems: usize,
}

fn rewording(cfg: &Value, s: &Settings, a: &Advisor, questions: &[Question]) -> Res<RewordCount> {
    let v = vault(cfg, s)?;
    let index = VaultIndex::build(&v.0, None).map_err(|e| e.to_string())?;
    let mut n = RewordCount::default();
    let own: BTreeMap<String, (String, bool)> = a.rewordings.clone();
    for q in questions.iter().filter(|q| q.answerable) {
        let plain = compose(&index, &q.text, &s.answer);
        let done = assemble(&index, &q.text, &s.answer, &Reword(&own), None);
        n.verify_problems += verify_answer(&index, &done.answer, &s.answer).len();
        for (before, after) in plain.sentences.iter().zip(&done.answer.sentences) {
            let Some((wording, faithful)) = own.get(before.body.trim()) else {
                continue;
            };
            if *faithful {
                n.offered_faithful += 1;
            } else {
                n.offered_unfaithful += 1;
            }
            let kept = after.body.trim() == wording.trim() && wording.trim() != before.body.trim();
            // a rewording equal to the claim's own words is neither a gain nor a risk
            let same = wording.trim() == before.body.trim();
            n.answer_sentences += 1;
            if kept && !*faithful {
                n.kept_unfaithful += 1;
            } else if kept && *faithful {
                n.kept_faithful += 1;
            }
            // faithful when the sentence the user reads is the claim's own words or a labelled-faithful rewording
            if after.body.trim() == before.body.trim() || (kept && *faithful) || (same && *faithful)
            {
                n.answer_sentences_faithful += 1;
            }
        }
    }
    Ok(n)
}

// ---------------------------------------------------------------- measures 3 and 4: the loop

struct Tools;

impl ToolRunner for Tools {
    fn run(&mut self, name: &str, _arguments: &Map<String, Value>) -> Value {
        panic!("no tool may run in this evaluation: {name}");
    }
}

struct EvalBrain {
    vault: PathBuf,
    answer: AnswerSettings,
    rules: RuleSettings,
    steps: u32,
    seconds: f64,
    log: Rc<RefCell<Vec<Act>>>,
}

impl Brain for EvalBrain {
    fn signals(&mut self, session: &Session, clock: &Clock) -> Signals {
        let index = VaultIndex::build(&self.vault, None).expect("index");
        let mut s = Signals::empty(
            self.steps.saturating_sub(session.turn().steps()),
            self.seconds - clock.elapsed.as_secs_f64(),
        );
        s.advisor_asks = session.turn().steps();
        s.measure(
            &index,
            session.last_user_text(),
            &self.answer,
            self.rules.required_level,
        )
    }

    fn closing_text(&mut self, act: Act, _choice: &Choice, session: &Session) -> String {
        let index = VaultIndex::build(&self.vault, None).expect("index");
        match act {
            Act::Answer => compose(&index, session.last_user_text(), &self.answer).render(&index),
            Act::Abstain => ABSTENTION.to_owned(),
            Act::AskUser => "Which one do you mean?".to_owned(),
            _ => "The turn was stopped by a limit.".to_owned(),
        }
    }

    fn log(&mut self, choice: &Choice) {
        self.log.borrow_mut().push(choice.act);
    }
}

fn reply(text: &str) -> ModelAnswer {
    ModelAnswer {
        text: text.to_owned(),
        tool_calls: Vec::new(),
        usage: None,
    }
}

/// How a turn ended: the status and what the user read.
struct Ended {
    status: String,
    answer: String,
}

fn ended(events: &[Event]) -> Res<Ended> {
    match events.last() {
        Some(Event::Done { status, answer }) => Ok(Ended {
            status: status.clone(),
            answer: answer.clone(),
        }),
        other => Err(format!("a turn must end with done, ended with {other:?}")),
    }
}

fn run_turn<D: Decider>(
    dir: &Path,
    decider: D,
    script: Vec<ModelAnswer>,
    question: &str,
) -> Res<Ended> {
    let store =
        Store::open(dir.join("space.sqlite"), DEFAULT_BUSY_TIMEOUT).map_err(|e| e.to_string())?;
    let recorder = Recorder::open(store, "s1", "t", 1.0)
        .map_err(|e| e.to_string())?
        .0;
    let mut driver = Driver::new(
        recorder,
        ScriptedModel::new(script),
        Tools,
        decider,
        Vec::new(),
        || 1.0,
    );
    let events = driver.send(question).map_err(|e| e.to_string())?;
    ended(&events)
}

fn normal(s: &str) -> String {
    s.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}

#[derive(Default)]
struct LoopCount {
    runs: usize,
    should_abstain: usize,
    abstained_right: usize,
    abstained_total: usize,
    should_answer: usize,
    completed_with_content: usize,
    false_completions: usize,
    reply_unsupported: usize,
    reply_reached_user: usize,
}

fn count(c: &mut LoopCount, q: &Question, r: &Reply, end: &Ended) {
    c.runs += 1;
    let completed = end.status == "completed";
    // the system's own abstention: the brain writes it; the advisor-decides mode has no such mechanism
    let abstained = end.answer == ABSTENTION;
    let honest_reply = r.supported && normal(&end.answer).contains(&normal(&r.text));
    if q.answerable {
        c.should_answer += 1;
        c.completed_with_content += usize::from(completed && !abstained);
    } else {
        c.should_abstain += 1;
        c.abstained_right += usize::from(abstained);
        // completing with something when nothing supports an answer is a false completion, unless what the user read
        // is an advisor reply that asserts nothing the brain does not hold
        c.false_completions += usize::from(completed && !abstained && !honest_reply);
    }
    c.abstained_total += usize::from(abstained);
    if !r.supported {
        c.reply_unsupported += 1;
        c.reply_reached_user += usize::from(normal(&end.answer).contains(&normal(&r.text)));
    }
}

struct LoopResult {
    brain: LoopCount,
    advisor_decides: LoopCount,
}

fn through_the_loop(
    cfg: &Value,
    s: &Settings,
    a: &Advisor,
    questions: &[Question],
) -> Res<LoopResult> {
    let mut brain = LoopCount::default();
    let mut baseline = LoopCount::default();
    for q in questions {
        let r = a
            .replies
            .get(&q.id)
            .ok_or(format!("{}: no reply to {}", a.name, q.id))?;
        let script = || (0..4).map(|_| reply(&r.text)).collect::<Vec<_>>();
        // the brain decides, the advisor proposes
        let (dir, v) = (Temp::new(), vault(cfg, s)?);
        let decider = BrainDecider::new(
            FollowModel::new(Agent::default(), Catalogue::english()),
            RuleDecider::new(s.rules),
            EvalBrain {
                vault: v.0.clone(),
                answer: s.answer,
                rules: s.rules,
                steps: s.steps,
                seconds: s.seconds,
                log: Rc::new(RefCell::new(Vec::new())),
            },
        );
        let end = run_turn(&dir.0, decider, script(), &q.text)?;
        count(&mut brain, q, r, &end);
        // the programme-2 behaviour: the loop follows the advisor
        let dir = Temp::new();
        let end = run_turn(
            &dir.0,
            FollowModel::new(Agent::default(), Catalogue::english()),
            script(),
            &q.text,
        )?;
        count(&mut baseline, q, r, &end);
    }
    Ok(LoopResult {
        brain,
        advisor_decides: baseline,
    })
}

// ---------------------------------------------------------------- measure 5: constraints

fn message(role: Role, text: String) -> ChatMessage {
    ChatMessage {
        role,
        content: Some(Content::Text(text)),
        tool_calls: Vec::new(),
        tool_call_id: None,
        name: None,
        extra: Map::new(),
    }
}

fn content(m: &ChatMessage) -> String {
    match &m.content {
        Some(Content::Text(t)) => t.clone(),
        _ => String::new(),
    }
}

/// Share of the pinned constraints still in the request after `turns` turns, and whether it had to compact.
fn constraint_recall(cfg: &Value, s: &Settings, turns: u64) -> Res<Value> {
    let constraints: Vec<String> = cfg["constraints"]
        .as_array()
        .ok_or("`constraints` is missing")?
        .iter()
        .filter_map(|c| c.as_str().map(str::to_owned))
        .collect();
    let pins: Vec<Pin> = constraints
        .iter()
        .map(|c| Pin::new(PinKind::Constraint, c.clone()))
        .collect();
    let filler = "background ".repeat(s.filler_words);
    let mut conversation = Vec::new();
    for n in 0..turns {
        conversation.push(message(Role::User, format!("question {n} {filler}")));
        conversation.push(message(Role::Assistant, format!("answer {n} {filler}")));
    }
    conversation.push(message(Role::User, "and now the last question".to_owned()));
    let built = assemble_prompt(
        &Input {
            layers: &[],
            pins: &pins,
            plan: None,
            conversation: &conversation,
        },
        &s.budget,
    )
    .map_err(|e| e.to_string())?;
    let request: String = built
        .messages
        .iter()
        .map(content)
        .collect::<Vec<_>>()
        .join("\n");
    let kept = constraints
        .iter()
        .filter(|c| request.contains(c.as_str()))
        .count();
    Ok(json!({
        "turns": turns,
        "constraints": constraints.len(),
        "kept_in_request": kept,
        "recall": kept as f64 / constraints.len().max(1) as f64,
        "compacted": built.compaction.is_some(),
        "request_tokens": built.tokens,
    }))
}

// ---------------------------------------------------------------- the report

fn rate(part: usize, whole: usize) -> Value {
    if whole == 0 {
        Value::Null
    } else {
        json!(part as f64 / whole as f64)
    }
}

fn loop_json(c: &LoopCount) -> Value {
    json!({
        "runs": c.runs,
        "false_completion_rate": rate(c.false_completions, c.should_abstain),
        "false_completions": c.false_completions,
        "should_abstain": c.should_abstain,
        "abstention_recall": rate(c.abstained_right, c.should_abstain),
        "abstention_precision": rate(c.abstained_right, c.abstained_total),
        "completed_with_content_when_answerable": rate(c.completed_with_content, c.should_answer),
        "unsupported_replies": c.reply_unsupported,
        "unsupported_replies_that_reached_the_user": c.reply_reached_user,
        "unsupported_pass_through_rate": rate(c.reply_reached_user, c.reply_unsupported),
    })
}

/// Runs the evaluation for `--config`, `--out` and any `--advisors`, and writes the report.
pub fn run(args: &[String]) -> Res<()> {
    let flag = |name: &str| {
        args.iter()
            .position(|a| a == name)
            .and_then(|i| args.get(i + 1).cloned())
    };
    let config_path = flag("--config").ok_or("--config FILE is required")?;
    let out = flag("--out").ok_or("--out FILE is required")?;
    let config_text =
        fs::read_to_string(&config_path).map_err(|e| format!("{config_path}: {e}"))?;
    let cfg: Value =
        serde_json::from_str(&config_text).map_err(|e| format!("{config_path}: {e}"))?;
    let s = settings(&cfg)?;
    let statements: BTreeMap<String, String> = cfg["claims"]
        .as_array()
        .ok_or("`claims` is missing")?
        .iter()
        .map(|c| Ok((text(c, "id")?.to_owned(), text(c, "statement")?.to_owned())))
        .collect::<Res<_>>()?;
    let questions: Vec<Question> = cfg["questions"]
        .as_array()
        .ok_or("`questions` is missing")?
        .iter()
        .map(|q| {
            Ok(Question {
                id: text(q, "id")?.to_owned(),
                text: text(q, "text")?.to_owned(),
                answerable: text(q, "expect")? == "answer",
            })
        })
        .collect::<Res<_>>()?;
    let mut advisors: Vec<Advisor> = cfg["advisors"]
        .as_array()
        .ok_or("`advisors` is missing")?
        .iter()
        .map(|a| advisor(a, &statements))
        .collect::<Res<_>>()?;
    let mut extra_files = Vec::new();
    for (i, a) in args.iter().enumerate() {
        if a == "--advisors" {
            let path = args.get(i + 1).ok_or("--advisors needs a file")?;
            let body = fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
            let v: Value = serde_json::from_str(&body).map_err(|e| format!("{path}: {e}"))?;
            advisors.push(advisor(&v, &statements)?);
            extra_files.push(
                json!({"path": path, "sha256": laris_vault::brain::sha256_hex(body.as_bytes())}),
            );
        }
    }
    if advisors.len() < 2 {
        return Err("SR-K7 asks for more than one advisor".to_owned());
    }

    let mut per_advisor = Vec::new();
    for a in &advisors {
        let g = through_the_gate(&cfg, &s, a)?;
        let w = rewording(&cfg, &s, a, &questions)?;
        let l = through_the_loop(&cfg, &s, a, &questions)?;
        per_advisor.push(json!({
            "advisor": a.name,
            "kind": a.kind,
            "unsupported_claim_pass_through": {
                "gate": {
                    "unsupported_proposals": g.unsupported_sent,
                    "unsupported_accepted": g.unsupported_accepted,
                    "rate": rate(g.unsupported_accepted, g.unsupported_sent),
                    "supported_proposals": g.supported_sent,
                    "supported_accepted": g.supported_accepted,
                    "supported_accept_rate": rate(g.supported_accepted, g.supported_sent),
                    "supported_already_held": g.already_held,
                },
                "rewording": {
                    "unfaithful_offered": w.offered_unfaithful,
                    "unfaithful_kept": w.kept_unfaithful,
                    "rate": rate(w.kept_unfaithful, w.offered_unfaithful),
                },
                "loop_brain_decides": {
                    "unsupported_replies": l.brain.reply_unsupported,
                    "reached_the_user": l.brain.reply_reached_user,
                    "rate": rate(l.brain.reply_reached_user, l.brain.reply_unsupported),
                },
                "loop_advisor_decides": {
                    "unsupported_replies": l.advisor_decides.reply_unsupported,
                    "reached_the_user": l.advisor_decides.reply_reached_user,
                    "rate": rate(l.advisor_decides.reply_reached_user, l.advisor_decides.reply_unsupported),
                },
            },
            "faithfulness": {
                "answer_sentences": w.answer_sentences,
                "faithful_sentences": w.answer_sentences_faithful,
                "rate": rate(w.answer_sentences_faithful, w.answer_sentences),
                "faithful_rewordings_kept": w.kept_faithful,
                "faithful_rewordings_offered": w.offered_faithful,
                "outside_set_check_problems_in_final_answers": w.verify_problems,
            },
            "abstention_calibration": {
                "brain_decides": loop_json(&l.brain),
                "advisor_decides": loop_json(&l.advisor_decides),
            },
            "false_completion": {
                "brain_decides": rate(l.brain.false_completions, l.brain.should_abstain),
                "advisor_decides": rate(l.advisor_decides.false_completions, l.advisor_decides.should_abstain),
            },
        }));
    }
    let mut recall = Vec::new();
    for turns in &s.turns_after {
        recall.push(constraint_recall(&cfg, &s, *turns)?);
    }
    let document = json!({
        "task": "T172",
        "requirement": "SR-K7",
        "config": {"path": config_path, "sha256": laris_vault::brain::sha256_hex(config_text.as_bytes())},
        "recorded_advisor_files": extra_files,
        "advisors_measured": advisors.iter().map(|a| a.name.clone()).collect::<Vec<_>>(),
        "scenarios": {
            "claims": statements.len(),
            "questions": questions.len(),
            "answerable": questions.iter().filter(|q| q.answerable).count(),
        },
        "per_advisor": per_advisor,
        "constraint_recall": {
            "note": "Share of the pinned constraints still in the request after N turns of filler under a window that forces compaction. It measures that the prompt layer keeps them; it does not measure whether an advisor obeys them.",
            "advisor_independent": true,
            "by_turns": recall,
        },
        "qualified": false,
        "read_this": [
            "These are system measurements of a harness on a small fixed scenario set, not a qualification of any model.",
            "The advisors listed as `scripted` are tables written by hand: their replies, rewordings and proposals are labelled supported or faithful by construction. They show what the brain does with advisors that behave in these ways, not how any real model behaves.",
            if extra_files.is_empty() {
                "ResearchLLM was not loaded for this report: only scripted advisors were measured (the foundation model is NOT QUALIFIED). A recorded run of it is one more advisor file passed with --advisors."
            } else {
                "The advisors under `recorded_advisor_files` are recordings of a real model answered offline and labelled by hand against the accepted claims (a label is a judgement, listed in the file); `unsupported` means outside the accepted claims, not false in the world. One recording of one model is one sample."
            },
            "Unsupported-claim pass-through and the outside-set check compare vocabulary: a sentence that keeps every word of a claim but reverses its meaning is not seen (see reports/brain/outside-set-check.json for the measured miss rate).",
            "In the advisor-decides mode (the programme-2 loop) there is no abstention mechanism: its abstention figures are 0 by construction, and a false completion is counted only when the user read something that is neither the system's abstention nor an advisor reply that asserts nothing unsupported.",
            "Abstention and false completion depend on the question set: four of seven questions cannot be answered and each advisor sees each question once, so rates are coarse and one case moves a rate by 14 to 25 points."
        ]
    });
    fs::write(
        &out,
        serde_json::to_string_pretty(&document).map_err(|e| e.to_string())? + "\n",
    )
    .map_err(|e| format!("{out}: {e}"))?;
    println!("report: {out}");
    Ok(())
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if let Err(message) = run(&args) {
        eprintln!("cognitive_eval: {message}");
        std::process::exit(2);
    }
}
