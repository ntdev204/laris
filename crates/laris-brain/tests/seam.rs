//! The brain behind the loop's `Decider` seam (T167): the loop runs under the rule decider, every choice is logged
//! with its rule, the model is asked only when the chooser says so, and what the user reads comes from the brain.

use std::cell::RefCell;
use std::fs;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::atomic::{AtomicU32, Ordering};

use laris_brain::answer::{ABSTENTION, AnswerSettings, compose};
use laris_brain::decide::{Act, Choice, Chooser, RuleDecider, RuleSettings, Signals, legal};
use laris_brain::seam::{Brain, BrainDecider};
use laris_brain::{ClaimProposal, Gate, GateSettings, MetadataCheck, Proposer, SourceProposal};
use laris_config::Catalogue;
use laris_config::settings::Agent;
use laris_core::{
    Clock, Driver, FollowModel, ModelAnswer, Record, Recorder, ScriptedModel, ToolRunner, replay,
};
use laris_protocol::Event;
use laris_store::{DEFAULT_BUSY_TIMEOUT, Store};
use laris_vault::VaultIndex;
use laris_vault::brain::Level;
use serde_json::{Map, Value};

struct Temp(PathBuf);

impl Temp {
    fn new() -> Temp {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "laris-seam-{}-{}",
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

const GATE: GateSettings = GateSettings {
    min_support: 0.9,
    min_equivalence: 0.6,
    subject_overlap: 0.5,
    search_depth: 10,
    max_bytes: 100_000,
};
const ANSWER: AnswerSettings = AnswerSettings {
    min_cover: 0.8,
    min_level: Level::Sourced,
    max_notes: 8,
};
const RULES: RuleSettings = RuleSettings {
    required_level: Level::Sourced,
    min_coverage: 0.6,
    max_retrievals: 1,
    max_acquisitions: 1,
    max_advisor_asks: 1,
    max_repeats: 3,
};
const C1: &str = "Aspirin reduces fever in adults.";

type ChoiceLog = Rc<RefCell<Vec<(String, Act)>>>;

struct Tools;

impl ToolRunner for Tools {
    fn run(&mut self, name: &str, _arguments: &Map<String, Value>) -> Value {
        panic!("no tool may run in these scenarios: {name}");
    }
}

/// The brain side of the seam: signals measured from a real vault, the composed answer as closing text.
struct TestBrain {
    vault: PathBuf,
    spent: bool,
    log: ChoiceLog,
}

impl Brain for TestBrain {
    fn signals(&mut self, session: &laris_core::Session, clock: &Clock) -> Signals {
        let index = VaultIndex::build(&self.vault, None).expect("index");
        let mut s = Signals::empty(
            10u32.saturating_sub(session.turn().steps()),
            180.0 - clock.elapsed.as_secs_f64(),
        );
        s.advisor_asks = session.turn().steps();
        if self.spent {
            s.budget_left = 0.0;
        }
        s.measure(&index, session.last_user_text(), &ANSWER, Level::Sourced)
    }

    fn closing_text(
        &mut self,
        act: Act,
        _choice: &Choice,
        session: &laris_core::Session,
    ) -> String {
        let index = VaultIndex::build(&self.vault, None).expect("index");
        match act {
            Act::Answer => compose(&index, session.last_user_text(), &ANSWER).render(&index),
            Act::Abstain => ABSTENTION.to_owned(),
            Act::AskUser => "Which drug do you mean?".to_owned(),
            _ => "The turn was stopped by a limit.".to_owned(),
        }
    }

    fn log(&mut self, choice: &Choice) {
        self.log
            .borrow_mut()
            .push((choice.rule.clone(), choice.act));
    }
}

type Rig<C = RuleDecider> = Driver<ScriptedModel, Tools, BrainDecider<C, TestBrain>>;

fn vault() -> Temp {
    let t = Temp::new();
    let gate = Gate::new(&t.0, GATE, Box::new(|| "2026-11-20".into()));
    let proposer = Proposer("placeholder-advisor".into());
    gate.submit_source(SourceProposal {
        title: "Paper".into(),
        kind: "document".into(),
        identifier: "doi:10.1/p".into(),
        text: C1.into(),
        command: None,
        inputs_sha256: None,
        cites: vec![],
        dataset: None,
        metadata: MetadataCheck::Verified("registry-fixture".into()),
        proposer: proposer.clone(),
    })
    .expect("io");
    assert!(
        gate.submit_claim(ClaimProposal {
            statement: C1.into(),
            source: Some("Paper".into()),
            quote: C1.into(),
            requested: Level::Sourced,
            evidence: vec![],
            solver: None,
            proposer,
        })
        .expect("io")
        .is_accepted()
    );
    t
}

fn rig(dir: &Path, vault: &Path, script: Vec<ModelAnswer>, spent: bool) -> (Rig, ChoiceLog) {
    rig_with(dir, vault, script, spent, RuleDecider::new(RULES))
}

fn rig_with<C: Chooser>(
    dir: &Path,
    vault: &Path,
    script: Vec<ModelAnswer>,
    spent: bool,
    chooser: C,
) -> (Rig<C>, ChoiceLog) {
    let log = Rc::new(RefCell::new(Vec::new()));
    let brain = TestBrain {
        vault: vault.to_owned(),
        spent,
        log: Rc::clone(&log),
    };
    let decider = BrainDecider::new(
        FollowModel::new(Agent::default(), Catalogue::english()),
        chooser,
        brain,
    );
    let store = Store::open(dir.join("space.sqlite"), DEFAULT_BUSY_TIMEOUT).expect("store");
    let recorder = Recorder::open(store, "s1", "t", 1.0).expect("open").0;
    let driver = Driver::new(
        recorder,
        ScriptedModel::new(script),
        Tools,
        decider,
        Vec::new(),
        || 1.0,
    );
    (driver, log)
}

fn reply(text: &str) -> ModelAnswer {
    ModelAnswer {
        text: text.to_owned(),
        tool_calls: Vec::new(),
        usage: None,
    }
}

fn done(events: &[Event]) -> (&str, &str) {
    match events.last() {
        Some(Event::Done { status, answer }) => (status, answer),
        other => panic!("the turn must end with done, ended with {other:?}"),
    }
}

fn assert_replays<C: Chooser>(rig: &Rig<C>) {
    let events = rig.recorder().store().events("s1", 0).expect("events");
    let records: Vec<Record> = events
        .iter()
        .map(|e| laris_core::decode_record(&e.data).expect("record"))
        .collect();
    let mut model = ScriptedModel::from_records(records.iter());
    let replayed = replay(&events, Some(&mut model)).expect("replay");
    assert_eq!(&replayed.session, rig.session());
    assert!(replayed.missing.is_empty());
}

#[test]
fn a_covered_question_is_answered_from_the_brain_without_asking_the_model() {
    let (dir, v) = (Temp::new(), vault());
    let (mut rig, log) = rig(&dir.0, &v.0, vec![reply("invented text")], false);
    let events = rig
        .send("does aspirin reduce fever in adults")
        .expect("turn");
    let (status, answer) = done(&events);
    assert_eq!(status, "completed");
    assert!(
        answer.contains(C1) && answer.contains("(level: sourced)"),
        "{answer}"
    );
    assert!(rig.model().seen().is_empty(), "the model was asked");
    assert_eq!(*log.borrow(), [("R3-covered".to_owned(), Act::Answer)]);
    assert_replays(&rig);
}

#[test]
fn the_advisor_proposes_but_the_user_never_reads_its_text() {
    let (dir, v) = (Temp::new(), vault());
    let (mut rig, log) = rig(
        &dir.0,
        &v.0,
        vec![reply("Ibuprofen cures influenza.")],
        false,
    );
    let events = rig.send("does ibuprofen cure influenza").expect("turn");
    let (status, answer) = done(&events);
    assert_eq!((status, answer), ("completed", ABSTENTION));
    let seen = rig.model().seen();
    assert_eq!(seen.len(), 1);
    assert!(
        seen[0]
            .note
            .as_deref()
            .is_some_and(|n| n.contains("Next step chosen by the system: ask_advisor"))
    );
    assert_eq!(
        *log.borrow(),
        [
            ("R7-ask-advisor".to_owned(), Act::AskAdvisor),
            ("R6-abstain".to_owned(), Act::Abstain)
        ]
    );
    assert_replays(&rig);
}

#[test]
fn a_spent_budget_stops_the_turn_with_its_limit() {
    let (dir, v) = (Temp::new(), vault());
    let (mut rig, log) = rig(&dir.0, &v.0, vec![reply("unused")], true);
    let events = rig
        .send("does aspirin reduce fever in adults")
        .expect("turn");
    let (status, _) = done(&events);
    assert_eq!(status, "budget");
    assert!(rig.model().seen().is_empty());
    assert_eq!(*log.borrow(), [("R1-limit".to_owned(), Act::Stop)]);
    assert_replays(&rig);
}

/// A chooser that returns one fixed act whenever it is legal, and the most cautious legal one otherwise. It stands for
/// the worst network: whatever its weights, it can only name an act.
struct Forced(Act);

impl Chooser for Forced {
    fn choose(&mut self, signals: &Signals) -> Choice {
        let candidates = legal(signals, &RULES);
        let act = if candidates.contains(&self.0) {
            self.0
        } else {
            Act::Abstain
        };
        Choice {
            act,
            rule: "network".to_owned(),
            reason: "forced by the test".to_owned(),
            limit: None,
            signals: signals.clone(),
            candidates,
            confidence: Some(1.0),
        }
    }
}

#[test]
fn a_chooser_cannot_bypass_the_tool_gate_or_the_composer() {
    // an uncovered question and an advisor that proposes a false claim: whichever act a chooser forces, the turn ends
    // and the user never reads the advisor's text. `Tools` panics if any tool runs, so a forced act cannot run a tool
    // that the loop did not propose and pass through its own gate.
    for act in Act::ALL {
        let (dir, v) = (Temp::new(), vault());
        let (mut rig, log) = rig_with(
            &dir.0,
            &v.0,
            vec![
                reply("Ibuprofen cures influenza."),
                reply("Ibuprofen cures influenza."),
            ],
            false,
            Forced(act),
        );
        let events = rig.send("does ibuprofen cure influenza").expect("turn");
        let (_, answer) = done(&events);
        assert!(
            !answer.contains("Ibuprofen cures influenza"),
            "forced {act:?}: the advisor's text reached the user: {answer}"
        );
        assert!(
            log.borrow()
                .iter()
                .all(|(rule, a)| rule == "network" && (*a == act || *a == Act::Abstain)),
            "forced {act:?}: {:?}",
            log.borrow()
        );
        assert_replays(&rig);
    }
}
