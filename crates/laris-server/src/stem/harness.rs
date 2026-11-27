//! The profile's loop over one item: the counterpart of `Harness.answer` in `laris.research.stem.harness` (T278,
//! with the levers of T279 and T280 the frozen candidate uses). Each step keeps the reference's order, prompts, seeds
//! and token caps, so on the same engine the two give the same answer within the engine's own variance:
//!
//! 1. route (item shape only); 2. brain-only answer from one certain Claim (when on); 3. the model-free path for an
//!    open computable question; 4. notes of the frozen snapshot for the configured classes; 5. the draft: a thinking
//!    call within the class's budget (closed and answered when the budget runs out), or a plain call, a cut reply
//!    concluded in place of the keep-it-short retry, retries otherwise; 6. formalisation for the configured classes
//!    when the draft is uncertain: the model's solver call, its mechanical repair, the solver, the cross-check, then
//!    agreement, self-consistency or review; 7. self-consistency of a retried draft; 8. the notes check.
//!
//! The loop never sees a gold answer. Every step is recorded without item text; `shown` keeps the visible text of the
//! reply the draft was read from, for the chat (it is not part of the record).

use super::StemError;
use super::checks::Checks;
use super::config::{HarnessCfg, Mode, StemConfig};
use super::engine::{Engine, Reply};
use super::text::{self, COMPUTABLE, LETTERS};
use serde::Serialize;
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Instant;

/// One question: the filtered text and its options (none: an open question).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Item {
    /// The question.
    pub question: String,
    /// Its options, in letter order.
    pub options: Vec<String>,
}

/// What the loop did for one item: steps, answers and cost, without item text (`harness.Trace`).
#[derive(Debug, Clone, Default, Serialize)]
pub struct Trace {
    /// Router class.
    pub cls: String,
    /// Router rule.
    pub rule: String,
    /// What the router read.
    pub features: Value,
    /// Every step, in order.
    pub steps: Vec<Value>,
    /// Answered by the model-free path.
    pub model_free: bool,
    /// Answered from one certain Claim.
    pub brain_only: bool,
    /// The draft's answer.
    pub draft: Option<String>,
    /// The final answer.
    #[serde(rename = "final")]
    pub final_answer: Option<String>,
    /// Where the final answer came from.
    pub final_from: String,
    /// The draft was cut with no answer.
    pub truncated: bool,
    /// The draft was retried or concluded.
    pub retried: bool,
    /// Replies concluded into an answer.
    pub concluded: u32,
    /// Votes by answer, when self-consistency ran.
    pub votes: Option<Map<String, Value>>,
    /// The solver's status.
    pub solver_status: String,
    /// The draft agreed with the solver.
    pub agreement: Option<bool>,
    /// Notes shown.
    pub notes: usize,
    /// The cross-check of the formalisation.
    pub crosscheck: Option<Value>,
    /// Prompt tokens.
    pub prompt_tokens: u64,
    /// Generated tokens.
    pub generated_tokens: u64,
    /// Model calls.
    pub model_calls: u64,
    /// Solver calls.
    pub solver_calls: u64,
    /// Seconds in the model.
    pub model_seconds: f64,
    /// Seconds in the solver.
    pub solver_seconds: f64,
    /// The visible text the draft was read from (chat only, not recorded).
    #[serde(skip)]
    pub shown: Option<String>,
}

/// Called with every step as it is recorded.
pub type OnStep = Arc<dyn Fn(&Value) + Send + Sync>;

/// The loop, with its engine and its deterministic tools.
pub struct Harness {
    cfg: Arc<StemConfig>,
    engine: Arc<dyn Engine>,
    checks: Arc<dyn Checks>,
}

/// The visible text of a reply (`split_reasoning`'s answer part).
struct Said {
    answer_text: String,
    truncated: bool,
}

impl Harness {
    /// The loop under `cfg`.
    pub fn new(cfg: Arc<StemConfig>, engine: Arc<dyn Engine>, checks: Arc<dyn Checks>) -> Self {
        Self {
            cfg,
            engine,
            checks,
        }
    }

    /// The configuration it runs.
    pub fn config(&self) -> &StemConfig {
        &self.cfg
    }

    /// The answer to `item` on `seed`: `notes` are the passages shown to the model, `certain` the texts of the
    /// certain Claims among them, `quantities` those the prompt filter found (read only by the cross-check).
    pub async fn answer(
        &self,
        item: &Item,
        seed: u64,
        notes: &[String],
        certain: &[String],
        quantities: Option<&Value>,
        on_step: OnStep,
    ) -> Result<Trace, StemError> {
        let h = &self.cfg.harness;
        let decided = text::route(
            &item.question,
            &item.options,
            h.router.numeric_option_share,
            h.router.knowledge_max_question_words,
        );
        let mut run = Run {
            h: self,
            item,
            on_step,
            trace: Trace {
                cls: decided.cls.to_owned(),
                rule: decided.rule.to_owned(),
                features: serde_json::to_value(&decided.features).unwrap_or(Value::Null),
                ..Trace::default()
            },
        };
        run.answer(seed, notes, certain, quantities).await?;
        Ok(run.trace)
    }
}

struct Run<'a> {
    h: &'a Harness,
    item: &'a Item,
    on_step: OnStep,
    trace: Trace,
}

/// Python's `str(value)` of a solver result's text, as the review prompt shows it.
fn py_str(value: Option<&Value>) -> String {
    match value {
        None | Some(Value::Null) => "None".to_owned(),
        Some(Value::String(s)) => s.clone(),
        Some(Value::Bool(b)) => if *b { "True" } else { "False" }.to_owned(),
        Some(other) => other.to_string(),
    }
}

/// The first `cap` characters of a note, trimmed, as a bullet (`n[:cap].strip()`).
fn bullets(notes: &[String], cap: usize) -> String {
    notes
        .iter()
        .map(|n| {
            let head: String = n.chars().take(cap).collect();
            format!("- {}", text::py_strip(&head))
        })
        .collect::<Vec<_>>()
        .join("\n")
}

impl Run<'_> {
    fn hc(&self) -> &HarnessCfg {
        &self.h.cfg.harness
    }

    fn mode(&self) -> Mode {
        self.h.cfg.mode.clone()
    }

    fn step(&mut self, entry: Value) {
        (self.on_step)(&entry);
        self.trace.steps.push(entry);
    }

    fn extract(&self, said: &str) -> Option<String> {
        text::extract(said, self.item.options.len())
    }

    fn count(&mut self, reply: &Reply) {
        self.trace.model_calls += 1;
        self.trace.prompt_tokens += reply.prompt_tokens;
        self.trace.generated_tokens += reply.generated_tokens;
        self.trace.model_seconds += reply.seconds;
    }

    /// A plain call (`Harness._call`).
    async fn call(
        &mut self,
        step: &str,
        prompt: &str,
        seed: u64,
        max_tokens: u32,
    ) -> Result<Said, StemError> {
        let out = self
            .h
            .engine
            .chat(prompt.to_owned(), self.mode(), seed, max_tokens)
            .await?;
        self.count(&out);
        let server = &self.h.cfg.server;
        let (_, answer_text) =
            text::split_reasoning(&out.text, &server.think_open, &server.think_close);
        self.step(
            json!({"step": step, "truncated": out.truncated, "tokens": out.generated_tokens}),
        );
        Ok(Said {
            answer_text,
            truncated: out.truncated,
        })
    }

    /// A thinking call within `budget` reasoning tokens, closed and answered in `answer_tokens` when the reasoning
    /// does not close in time (`Harness._think`, budget forcing).
    async fn think(
        &mut self,
        step: &str,
        prompt: &str,
        seed: u64,
        budget: u32,
        answer_tokens: u32,
    ) -> Result<Said, StemError> {
        let cfg = self.h.cfg.clone();
        let raw = self.h.engine.template(prompt.to_owned(), true).await?;
        let first = self
            .h
            .engine
            .complete(raw.clone(), cfg.thinking.clone(), seed, budget)
            .await?;
        let close = &cfg.server.think_close;
        let forced = !first.text.contains(close.as_str());
        let mut calls = vec![first.clone()];
        let (answer_text, truncated) = if forced {
            let again = format!("{raw}{}{}", first.text, cfg.server.force_answer);
            let second = self
                .h
                .engine
                .complete(again, cfg.thinking.clone(), seed + 1, answer_tokens)
                .await?;
            calls.push(second.clone());
            (second.text, second.truncated)
        } else {
            let after = first
                .text
                .split_once(close.as_str())
                .map_or(String::new(), |(_, a)| a.to_owned());
            (after, first.truncated)
        };
        let tokens: u64 = calls.iter().map(|c| c.generated_tokens).sum();
        for c in &calls {
            self.count(c);
        }
        self.step(json!({
            "step": step, "truncated": truncated, "tokens": tokens, "thinking": true, "forced": forced
        }));
        Ok(Said {
            answer_text,
            truncated,
        })
    }

    /// A reply cut at its cap continued from the reply so far by the answer's opening (`Harness._conclude`).
    async fn conclude(
        &mut self,
        of: &str,
        prompt: &str,
        reply: &str,
        seed: u64,
    ) -> Result<Option<String>, StemError> {
        let cfg = self.h.cfg.clone();
        let choice = !self.item.options.is_empty();
        let p = &cfg.harness.prompts;
        let opening = if choice {
            &p.conclude_choice
        } else {
            &p.conclude_math
        };
        let cap = if choice {
            cfg.harness.conclude.max_tokens_choice
        } else {
            cfg.harness.conclude.max_tokens_math
        };
        let raw = self
            .h
            .engine
            .template(prompt.to_owned(), cfg.mode.enable_thinking)
            .await?;
        let out = self
            .h
            .engine
            .complete(
                format!("{raw}{reply}{opening}"),
                cfg.mode.clone(),
                seed,
                cap,
            )
            .await?;
        self.count(&out);
        let said = format!("{opening}{}", out.text);
        let found = self.extract(&said);
        self.step(json!({
            "step": "conclude", "of": of, "tokens": out.generated_tokens, "answered": found.is_some()
        }));
        if found.is_some() {
            self.trace.concluded += 1;
            // the chat shows the draft's text; a concluded sample of a vote is not the draft
            if of != "sample" {
                self.trace.shown = Some(format!("{reply}{said}"));
            }
        }
        Ok(found)
    }

    fn concluding(&self) -> bool {
        self.hc().conclude.enabled
    }

    /// The draft and its retries (`Harness._draft`).
    async fn draft(&mut self, prompt: &str, seed: u64) -> Result<Option<String>, StemError> {
        let cfg = self.h.cfg.clone();
        let d = &cfg.harness.draft;
        let budget = d.thinking.get(&self.trace.cls).copied().unwrap_or(0);
        let max_new = cfg.mode.max_new_tokens;
        let mut out = if budget > 0 {
            self.think("draft", prompt, seed, budget, d.answer_tokens)
                .await?
        } else {
            self.call("draft", prompt, seed, max_new).await?
        };
        let mut answer = self.extract(&out.answer_text);
        if answer.is_some() {
            self.trace.shown = Some(out.answer_text.clone());
        }
        let mut truncated = out.truncated;
        let conclude = cfg.harness.conclude.enabled;
        if conclude && cfg.harness.conclude.replace_retry && truncated {
            self.trace.retried = true; // uncertain as a retried draft: formalised and voted on
            let found = self
                .conclude("draft", prompt, &out.answer_text, seed + 500)
                .await?;
            if found.is_some() {
                answer = found;
            }
            self.trace.truncated = answer.is_none();
            return Ok(answer);
        }
        for attempt in 1..=u64::from(d.max_retries) {
            if answer.is_some() && !truncated {
                break;
            }
            self.trace.retried = true;
            let retry = format!("{prompt}{}", cfg.harness.prompts.retry_suffix);
            out = self
                .call("retry", &retry, seed + 1000 * attempt, max_new)
                .await?;
            let again = self.extract(&out.answer_text);
            if again.is_some() {
                self.trace.shown = Some(out.answer_text.clone());
                answer = again;
                truncated = out.truncated;
            } else if answer.is_none() {
                truncated = out.truncated;
            }
            if answer.is_none() && truncated && conclude {
                answer = self
                    .conclude(
                        "retry",
                        &retry,
                        &out.answer_text,
                        seed + 1000 * attempt + 500,
                    )
                    .await?;
                truncated = answer.is_none();
            }
        }
        if answer.is_none() && truncated && conclude && !self.trace.retried {
            answer = self
                .conclude("draft", prompt, &out.answer_text, seed + 500)
                .await?;
            truncated = answer.is_none();
        }
        self.trace.truncated = truncated && answer.is_none();
        Ok(answer)
    }

    /// The model's solver call and the solver's verified result (`Harness._formalise`): the problem, as the review
    /// prompt shows it, and the result.
    async fn formalise(
        &mut self,
        seed: u64,
        quantities: Option<&Value>,
    ) -> Result<(Option<String>, Option<Value>), StemError> {
        let cfg = self.h.cfg.clone();
        let p = &cfg.harness.prompts;
        let choice = !self.item.options.is_empty();
        let template = if choice {
            &p.formalise_choice
        } else {
            &p.formalise_math
        };
        let mut prompt = template.replace("{question}", &self.item.question);
        if choice {
            prompt = prompt.replace("{options}", &text::options_block(&self.item.options));
        }
        let out = self
            .call("formalise", &prompt, seed, cfg.harness.formalise.max_tokens)
            .await?;
        let problem = text::first_json_object(&out.answer_text);
        let operation = problem
            .as_ref()
            .and_then(|p| p.get("operation"))
            .and_then(Value::as_str)
            .map(|o| text::py_strip(o).to_uppercase());
        let (Some(problem), Some(operation)) = (problem, operation) else {
            self.trace.solver_status = "not_formalised".to_owned();
            return Ok((None, None));
        };
        if operation == "NONE" {
            self.trace.solver_status = "not_formalised".to_owned();
            return Ok((None, None));
        }
        let repaired = self
            .h
            .checks
            .check(json!({"op": "repair", "problem": problem}))
            .await?;
        let problem = repaired["problem"].as_object().cloned().unwrap_or_default();
        let shown = repaired["problem_json"].as_str().map(str::to_owned);
        let fixes: BTreeSet<String> = repaired["fixes"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|f| f.as_str().map(str::to_owned))
                    .collect()
            })
            .unwrap_or_default();
        if !fixes.is_empty() {
            self.step(json!({"step": "repair", "fixes": fixes}));
        }
        let began = Instant::now();
        let (result, status) = self.h.checks.solve(problem.clone()).await;
        self.trace.solver_calls += 1;
        self.trace.solver_seconds += began.elapsed().as_secs_f64();
        self.step(json!({"step": "solver", "status": status}));
        self.trace.solver_status = status.clone();
        let Some(result) = result.filter(|_| status == "verified") else {
            return Ok((shown, None));
        };
        if quantities.is_some() && cfg.harness.formalisation_check.is_some() {
            let mut check = self
                .h
                .checks
                .check(json!({"op": "crosscheck", "problem": problem, "quantities": quantities}))
                .await?;
            let gate = check["action"].as_str() == Some("gate");
            if let Value::Object(m) = &mut check {
                m.remove("checked");
                m.remove("action");
            }
            let ungrounded = check["ungrounded"].as_u64().unwrap_or(0) > 0;
            let mut entry = json!({"step": "crosscheck"});
            if let (Value::Object(e), Value::Object(c)) = (&mut entry, &check) {
                e.extend(c.clone());
            }
            self.trace.crosscheck = Some(check);
            self.step(entry);
            if gate && ungrounded {
                self.trace.solver_status = "verified_ungrounded".to_owned();
                return Ok((shown, None));
            }
        }
        Ok((shown, Some(result)))
    }

    async fn solver_answer(&self, result: &Value) -> Result<Option<String>, StemError> {
        let out = self
            .h
            .checks
            .check(json!({
                "op": "solver_answer", "result": result,
                "question": self.item.question, "options": self.item.options
            }))
            .await?;
        Ok(out["answer"].as_str().map(str::to_owned))
    }

    /// The draft and the solver's answer say the same (`Harness._agrees`).
    async fn agrees(&self, a: &str, b: &str) -> Result<bool, StemError> {
        if !self.item.options.is_empty() {
            return Ok(a == b);
        }
        let out = self
            .h
            .checks
            .check(json!({"op": "equivalent", "a": a, "b": b}))
            .await?;
        Ok(out["equal"].as_bool().unwrap_or(false))
    }

    async fn review(&mut self, prompt: &str, seed: u64) -> Result<Option<String>, StemError> {
        let max_new = self.h.cfg.mode.max_new_tokens;
        let out = self.call("review", prompt, seed, max_new).await?;
        let found = self.extract(&out.answer_text);
        if found.is_some() {
            self.trace.shown = Some(out.answer_text);
        }
        Ok(found)
    }

    /// The one option whose content words all appear in one note (`Harness._supported_option`); with `least` the
    /// fewest words an option needs.
    fn supported(&self, notes: &[String], least: usize) -> Option<usize> {
        let stop = &self.h.cfg.server.stop_words;
        let sets: Vec<BTreeSet<String>> = notes
            .iter()
            .map(|n| text::content_words(n, stop).into_iter().collect())
            .collect();
        let backed: Vec<usize> = self
            .item
            .options
            .iter()
            .enumerate()
            .filter(|(_, o)| {
                let words: BTreeSet<String> = text::content_words(o, stop).into_iter().collect();
                words.len() >= least && sets.iter().any(|s| words.is_subset(s))
            })
            .map(|(i, _)| i)
            .collect();
        (backed.len() == 1).then(|| backed[0])
    }

    fn consistency_on(&self, when: &str) -> bool {
        let sc = &self.hc().self_consistency;
        sc.enabled && sc.when.iter().any(|w| w == when)
    }

    /// Self-consistency (`Harness._vote`): more thinking-off drafts on other seeds; the answer most of them, the
    /// draft and `extra` share wins, a tie going to the earliest of the tied answers.
    async fn vote(&mut self, prompt: &str, seed: u64, extra: Vec<String>) -> Result<(), StemError> {
        let samples = u64::from(self.hc().self_consistency.samples);
        let max_new = self.h.cfg.mode.max_new_tokens;
        let mut seen: Vec<String> = self.trace.draft.iter().cloned().collect();
        for k in 1..=samples {
            let out = self.call("sample", prompt, seed + 31 * k, max_new).await?;
            let mut found = self.extract(&out.answer_text);
            if found.is_none() && out.truncated && self.concluding() && self.hc().conclude.samples {
                found = self
                    .conclude("sample", prompt, &out.answer_text, seed + 31 * k + 500)
                    .await?;
            }
            seen.extend(found);
        }
        seen.extend(extra);
        let mut groups: Vec<Vec<String>> = Vec::new();
        for answer in seen {
            let mut placed = false;
            for group in &mut groups {
                let same = if self.item.options.is_empty() {
                    self.agrees(&group[0], &answer).await?
                } else {
                    group[0] == answer
                };
                if same {
                    group.push(answer.clone());
                    placed = true;
                    break;
                }
            }
            if !placed {
                groups.push(vec![answer]);
            }
        }
        if groups.is_empty() {
            return Ok(());
        }
        // the first of the longest groups
        let mut best = 0;
        for (i, g) in groups.iter().enumerate() {
            if g.len() > groups[best].len() {
                best = i;
            }
        }
        let mut votes = Map::new();
        for g in &groups {
            votes.insert(g[0].clone(), json!(g.len()));
        }
        self.trace.votes = Some(votes);
        let top = groups[best].len();
        self.step(json!({"step": "vote", "groups": groups.len(), "top": top}));
        let winner = groups[best][0].clone();
        if self.trace.final_answer.as_deref() != Some(winner.as_str()) {
            self.trace.final_answer = Some(winner);
            self.trace.final_from = "vote".to_owned();
        } else if self.trace.final_from == "draft" {
            self.trace.final_from = "vote".to_owned();
        }
        Ok(())
    }

    fn prompt_for(&self) -> String {
        let p = &self.h.cfg.baseline.prompts;
        let item = self.item;
        if item.options.is_empty() {
            return p.math.replace("{question}", &item.question);
        }
        let letters: Vec<String> = text::letters(item.options.len())
            .chars()
            .map(String::from)
            .collect();
        p.choice
            .replace("{letters}", &letters.join(", "))
            .replace("{question}", &item.question)
            .replace("{options}", &text::options_block(&item.options))
    }

    fn brain_only(&self, certain: &[String], least: usize) -> Option<usize> {
        // the one option whose content words all appear in one certain Claim (`brain_only_option`)
        self.supported(certain, least)
    }

    async fn answer(
        &mut self,
        seed: u64,
        notes: &[String],
        certain: &[String],
        quantities: Option<&Value>,
    ) -> Result<(), StemError> {
        let cfg = self.h.cfg.clone();
        let h = &cfg.harness;
        let choice = !self.item.options.is_empty();

        if h.brain_only.enabled && choice && !certain.is_empty() {
            let index = self.brain_only(certain, h.brain_only.min_option_words);
            self.step(json!({"step": "brain_only", "answered": index.is_some(), "certain": certain.len()}));
            if let Some(i) = index {
                self.trace.brain_only = true;
                self.trace.final_answer = Some(LETTERS[i..=i].to_owned());
                self.trace.final_from = "brain_only".to_owned();
                return Ok(());
            }
        }

        if self.trace.cls == COMPUTABLE && !choice && h.model_free {
            let began = Instant::now();
            let free = self
                .h
                .checks
                .check(json!({"op": "model_free", "question": self.item.question}))
                .await?;
            self.trace.solver_seconds += began.elapsed().as_secs_f64();
            if free["pattern"].as_str().is_some_and(|p| !p.is_empty()) {
                self.trace.solver_calls += 1;
            }
            self.step(json!({"step": "model_free", "status": free["status"]}));
            if !free["answer"].is_null() {
                self.trace.model_free = true;
                self.trace.final_answer = Some(py_str(free.get("answer")));
                self.trace.final_from = "model_free".to_owned();
                self.trace.solver_status = "verified".to_owned();
                return Ok(());
            }
        }

        let base_prompt = self.prompt_for();
        let mut prompt = base_prompt.clone();
        let cap = h.retrieval.max_chars_per_note;
        if !notes.is_empty() && h.retrieval.classes.contains(&self.trace.cls) {
            prompt = h
                .prompts
                .notes_prefix
                .replace("{notes}", &bullets(notes, cap))
                + &base_prompt;
            self.trace.notes = notes.len();
        }
        self.trace.draft = self.draft(&prompt, seed).await?;
        self.trace.final_answer = self.trace.draft.clone();
        self.trace.final_from = "draft".to_owned();

        let f = &h.formalise;
        let uncertain = self.trace.draft.is_none() || self.trace.retried;
        if f.classes.contains(&self.trace.cls) && (f.when == "always" || uncertain) {
            let (problem, result) = self.formalise(seed + 7, quantities).await?;
            let solved = match &result {
                Some(r) => self.solver_answer(r).await?,
                None => None,
            };
            if let Some(solved) = solved {
                let Some(draft) = self.trace.draft.clone() else {
                    self.trace.final_answer = Some(solved);
                    self.trace.final_from = "solver_fallback".to_owned();
                    return Ok(());
                };
                let agreement = self.agrees(&draft, &solved).await?;
                self.trace.agreement = Some(agreement);
                if agreement {
                    return Ok(());
                }
                if self.consistency_on("disagree") {
                    return self.vote(&prompt, seed, vec![solved]).await;
                }
                if !f.review {
                    return Ok(()); // the draft stands on a disagreement
                }
                let value = py_str(result.as_ref().and_then(|r| r.get("text")));
                let review = base_prompt.clone()
                    + &text::fill(
                        &h.prompts.review_solver,
                        &[
                            ("draft", &draft),
                            ("problem", problem.as_deref().unwrap_or("{}")),
                            ("value", &value),
                        ],
                    );
                if let Some(answer) = self.review(&review, seed + 13).await? {
                    self.trace.final_answer = Some(answer);
                    self.trace.final_from = "review_solver".to_owned();
                }
                return Ok(());
            }
        }

        if self.trace.retried && self.consistency_on("retried") {
            let again = format!("{prompt}{}", h.prompts.retry_suffix);
            return self.vote(&again, seed, Vec::new()).await;
        }

        if choice
            && self.trace.notes > 0
            && h.notes_check.enabled
            && let Some(draft) = self.trace.draft.clone()
            && let Some(i) = self.supported(notes, h.notes_check.min_option_words)
            && LETTERS[i..=i] != draft
        {
            let letter = &LETTERS[i..=i];
            let shown = bullets(notes, cap);
            let review = base_prompt
                + &text::fill(
                    &h.prompts.review_notes,
                    &[("draft", &draft), ("letter", letter), ("notes", &shown)],
                );
            self.step(json!({"step": "notes_check", "supported": letter}));
            if let Some(answer) = self.review(&review, seed + 17).await? {
                self.trace.final_answer = Some(answer);
                self.trace.final_from = "review_notes".to_owned();
            }
        }
        Ok(())
    }
}
