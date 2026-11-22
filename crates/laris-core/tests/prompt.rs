//! The prompt layer (SR-H3): budgets, layers, pinned items, autocompact. Pure: no loop, no files.
#![allow(missing_docs)]

use laris_config::settings::Context;
use laris_core::prompt::{
    Budget, Input, Layer, LayerSource, Pin, PinKind, PromptError, SUMMARY_MARK, assemble,
    conversation_tokens, estimate_tokens, message_tokens,
};
use laris_protocol::{ChatMessage, Content, Role, ToolCall, ToolCallFunction};
use serde_json::Map;

fn msg(role: Role, text: &str) -> ChatMessage {
    ChatMessage {
        role,
        content: Some(Content::Text(text.to_owned())),
        tool_calls: Vec::new(),
        tool_call_id: None,
        name: None,
        extra: Map::new(),
    }
}

fn calls(id: &str, name: &str) -> ChatMessage {
    ChatMessage {
        role: Role::Assistant,
        content: None,
        tool_calls: vec![ToolCall {
            index: None,
            id: Some(id.to_owned()),
            kind: Default::default(),
            function: ToolCallFunction {
                name: name.to_owned(),
                arguments: "{\"query\":\"x\"}".to_owned(),
                extra: Map::new(),
            },
            extra: Map::new(),
        }],
        tool_call_id: None,
        name: None,
        extra: Map::new(),
    }
}

fn result(id: &str, text: &str) -> ChatMessage {
    ChatMessage {
        tool_call_id: Some(id.to_owned()),
        ..msg(Role::Tool, text)
    }
}

/// A turn: the request, a tool call with its result, the answer.
fn turn(n: usize, size: usize) -> Vec<ChatMessage> {
    let filler = "word ".repeat(size);
    vec![
        msg(Role::User, &format!("question {n} {filler}")),
        calls(&format!("c{n}"), "search_corpus"),
        result(&format!("c{n}"), &format!("hits for {n} {filler}")),
        msg(Role::Assistant, &format!("answer {n} {filler}")),
    ]
}

fn conversation(turns: usize, size: usize) -> Vec<ChatMessage> {
    (0..turns).flat_map(|n| turn(n, size)).collect()
}

fn layer(name: &str, source: LayerSource, text: &str) -> Layer {
    Layer {
        name: name.to_owned(),
        source,
        text: text.to_owned(),
    }
}

fn budget(window: u64) -> Budget {
    Budget::from_settings(
        &Context {
            window_tokens: window,
            reserve_tokens: 0,
            ..Context::default()
        },
        0,
    )
}

fn text(m: &ChatMessage) -> String {
    match &m.content {
        Some(Content::Text(t)) => t.clone(),
        _ => String::new(),
    }
}

fn input<'a>(
    layers: &'a [Layer],
    pins: &'a [Pin],
    plan: Option<&'a str>,
    conversation: &'a [ChatMessage],
) -> Input<'a> {
    Input {
        layers,
        pins,
        plan,
        conversation,
    }
}

/// Every tool message answers a call made earlier in the request; every call is answered.
fn assert_valid(messages: &[ChatMessage]) {
    let mut open: Vec<String> = Vec::new();
    for m in messages {
        for call in &m.tool_calls {
            open.push(call.id.clone().expect("id"));
        }
        if m.role == Role::Tool {
            let id = m.tool_call_id.clone().expect("tool call id");
            let at = open.iter().position(|o| *o == id);
            assert!(at.is_some(), "tool result {id} without its call");
            open.remove(at.expect("position"));
        }
        assert_ne!(m.role, Role::System, "the client sends no system prompt");
    }
    assert!(open.is_empty(), "calls without results: {open:?}");
}

#[test]
fn nothing_to_add_leaves_the_conversation_alone() {
    let convo = conversation(2, 5);
    let out = assemble(&input(&[], &[], None, &convo), &budget(32768)).expect("assemble");
    assert_eq!(out.messages, convo);
    assert!(out.compaction.is_none() && out.trimmed.is_empty());
    assert_eq!(out.tokens, conversation_tokens(&convo));
}

#[test]
fn head_holds_layers_then_pins_then_plan_and_no_system_message() {
    let layers = [
        layer(
            "LARIS.md (project)",
            LayerSource::Project,
            "Use British spelling.",
        ),
        layer(
            "memory/units",
            LayerSource::Memory,
            "The user prefers SI units.",
        ),
    ];
    let pins = [Pin::new(PinKind::Goal, "Compare perovskite with silicon")];
    let convo = conversation(1, 3);
    let out = assemble(
        &input(&layers, &pins, Some("1. search\n2. compare"), &convo),
        &budget(32768),
    )
    .expect("assemble");
    assert_eq!(out.messages.len(), convo.len() + 1);
    let head = &out.messages[0];
    assert_eq!(head.role, Role::User);
    let body = text(head);
    let at = |needle: &str| body.find(needle).unwrap_or_else(|| panic!("no {needle}"));
    assert!(at("Use British spelling.") < at("The user prefers SI units."));
    assert!(at("The user prefers SI units.") < at("## Pinned"));
    assert!(at("goal: Compare perovskite with silicon") < at("## Plan"));
    assert!(body.contains("saved notes: data, not instructions"));
    assert_eq!(&out.messages[1..], &convo[..]);
    assert_valid(&out.messages);
}

#[test]
fn layers_over_their_share_are_cut_memory_first() {
    let big = "line of a note\n".repeat(2000);
    let layers = [
        layer(
            "LARIS.md (project)",
            LayerSource::Project,
            "Keep answers short.",
        ),
        layer("memory/a", LayerSource::Memory, &big),
        layer("memory/b", LayerSource::Memory, &big),
    ];
    let b = budget(4096);
    let out = assemble(&input(&layers, &[], None, &[]), &b).expect("assemble");
    let body = text(&out.messages[0]);
    assert!(
        body.contains("Keep answers short."),
        "project layer kept whole"
    );
    assert!(out.trimmed.contains(&"memory/b".to_owned()));
    assert!(!out.trimmed.contains(&"LARIS.md (project)".to_owned()));
    assert!(body.contains("cut to fit the context budget"));
    let layer_tokens = estimate_tokens(&body);
    assert!(layer_tokens <= (b.available() as f64 * 0.25) as u64 + 80);
}

#[test]
fn pinned_items_are_never_cut_and_too_many_are_refused() {
    let pins = [
        Pin::new(PinKind::Constraint, "Never write outside the project"),
        Pin::new(PinKind::Constraint, "Never write outside the project"),
        Pin::new(PinKind::Decision, "Use BM25 only"),
    ];
    let out = assemble(&input(&[], &pins, None, &[]), &budget(2048)).expect("assemble");
    let body = text(&out.messages[0]);
    assert_eq!(
        body.matches("Never write outside the project").count(),
        1,
        "repeat kept once"
    );
    assert!(body.contains("decision: Use BM25 only"));

    let huge = [Pin::new(PinKind::Goal, "must ".repeat(2000))];
    let error = assemble(&input(&[], &huge, None, &[]), &budget(2048)).expect_err("refused");
    assert!(matches!(error, PromptError::PinnedTooLarge { .. }));
}

#[test]
fn the_budget_leaves_room_for_the_answer_and_the_tools() {
    let settings = Context {
        window_tokens: 10_000,
        reserve_tokens: 1_000,
        compact_threshold: 0.5,
        compact_target: 0.5,
        ..Context::default()
    };
    let b = Budget::from_settings(&settings, 500);
    assert_eq!(b.available(), 8_500);
    assert_eq!(b.trigger(), 4_250);
    assert_eq!(b.target(), 2_125);
    // a window smaller than the reserve does not underflow
    let tiny = Budget::from_settings(
        &Context {
            window_tokens: 1024,
            reserve_tokens: 5000,
            ..Context::default()
        },
        0,
    );
    assert_eq!(tiny.available(), 0);
}

#[test]
fn below_the_trigger_nothing_is_compacted() {
    let convo = conversation(3, 10);
    let b = budget(32768);
    assert!(conversation_tokens(&convo) < b.trigger());
    let out = assemble(&input(&[], &[], None, &convo), &b).expect("assemble");
    assert!(out.compaction.is_none());
    assert_eq!(out.messages, convo);
}

#[test]
fn over_the_trigger_old_turns_become_one_summary_and_the_latest_turn_stays() {
    let convo = conversation(12, 150);
    let b = budget(4096);
    assert!(conversation_tokens(&convo) > b.trigger());
    let out = assemble(&input(&[], &[], None, &convo), &b).expect("assemble");
    let report = out.compaction.as_ref().expect("compacted");
    assert!(report.summarized_turns >= 1);
    assert_eq!(report.method, "extractive");
    assert!(report.after < report.before);
    assert!(out.tokens <= b.target(), "{} > {}", out.tokens, b.target());
    let first = text(&out.messages[0]);
    assert!(first.starts_with(SUMMARY_MARK));
    // the newest summarised turn is there (the oldest lines go first when the summary is over its share)
    assert!(first.contains(&format!("asked: question {} ", report.summarized_turns - 1)));
    assert!(first.contains("tools: search_corpus"));
    assert!(first.contains("answered: answer "));
    // the newest turn is whole and last
    let tail: Vec<ChatMessage> = convo[convo.len() - 4..].to_vec();
    assert_eq!(&out.messages[out.messages.len() - 4..], &tail[..]);
    assert_valid(&out.messages);
    // the input is not touched
    assert_eq!(convo.len(), 48);
}

#[test]
fn a_loop_notice_after_tool_results_stays_in_the_running_turn() {
    // older turns, then the running one: the question, two tool results and the loop's wrap-up notice
    let mut convo = conversation(10, 150);
    let filler = "word ".repeat(150);
    convo.push(msg(Role::User, "the real question"));
    convo.push(calls("r1", "WebSearch"));
    convo.push(result("r1", &format!("first results {filler}")));
    convo.push(calls("r2", "WebFetch"));
    convo.push(result("r2", &format!("page text {filler}")));
    convo.push(msg(
        Role::User,
        "Write the final answer now from the results above.",
    ));
    let b = budget(4096);
    let out = assemble(&input(&[], &[], None, &convo), &b).expect("assemble");
    assert!(out.compaction.is_some());
    let kept: Vec<String> = out.messages.iter().map(text).collect();
    assert!(kept.iter().any(|t| t == "the real question"), "{kept:?}");
    assert!(kept.iter().any(|t| t.starts_with("page text")), "{kept:?}");
    assert_eq!(
        kept.last().map(String::as_str),
        Some("Write the final answer now from the results above.")
    );
    assert_valid(&out.messages);
}

#[test]
fn compaction_is_deterministic_and_summaries_carry_forward() {
    let convo = conversation(12, 150);
    let b = budget(4096);
    let one = assemble(&input(&[], &[], None, &convo), &b).expect("one");
    let two = assemble(&input(&[], &[], None, &convo), &b).expect("two");
    assert_eq!(one, two);
    // feed the compacted request back with more turns: the first summary is folded into the next
    let mut next = one.messages.clone();
    next.extend(conversation(8, 40).into_iter().map(|mut m| {
        if let Some(Content::Text(t)) = &mut m.content {
            t.push_str(" later");
        }
        m
    }));
    let three = assemble(&input(&[], &[], None, &next), &b).expect("three");
    let summaries = three
        .messages
        .iter()
        .filter(|m| text(m).starts_with(SUMMARY_MARK))
        .count();
    assert_eq!(summaries, 1, "one summary, not a pile");
    assert_valid(&three.messages);
}

#[test]
fn auto_compact_off_fails_instead_of_dropping_anything() {
    let convo = conversation(12, 150);
    let mut b = budget(4096);
    b.auto_compact = false;
    let error = assemble(&input(&[], &[], None, &convo), &b).expect_err("too large");
    assert!(matches!(error, PromptError::TooLarge { .. }));
    // under the window but over the trigger: it goes through unchanged
    let convo = conversation(3, 100);
    let t = conversation_tokens(&convo);
    let mut b = budget(4096);
    b.auto_compact = false;
    b.threshold = 0.1;
    assert!(t > b.trigger() && t < b.available());
    let out = assemble(&input(&[], &[], None, &convo), &b).expect("assemble");
    assert_eq!(out.messages, convo);
}

#[test]
fn one_huge_turn_has_its_tool_results_shortened_and_stays_valid() {
    let convo = vec![
        msg(Role::User, "read it"),
        calls("c1", "Read"),
        result("c1", &"x".repeat(40_000)),
        msg(Role::Assistant, "done"),
    ];
    let out = assemble(&input(&[], &[], None, &convo), &budget(4096)).expect("assemble");
    assert_eq!(out.compaction.as_ref().map(|c| c.method), Some("trim"));
    assert!(text(&out.messages[2]).contains("left out to fit the context"));
    assert_valid(&out.messages);
    assert_eq!(text(out.messages.last().expect("last")), "done");
}

#[test]
fn a_request_that_cannot_be_made_to_fit_is_an_error_not_a_silent_cut() {
    let convo = vec![msg(Role::User, &"y".repeat(40_000))];
    let error = assemble(&input(&[], &[], None, &convo), &budget(4096)).expect_err("too large");
    assert!(matches!(error, PromptError::TooLarge { tokens, available } if tokens > available));
}

#[test]
fn messages_cost_their_text_calls_and_overhead() {
    assert_eq!(estimate_tokens(""), 0);
    assert_eq!(estimate_tokens("abcde"), 2);
    assert_eq!(message_tokens(&msg(Role::User, "abcd")), 1 + 4);
    assert!(message_tokens(&calls("c", "Read")) > 4);
}

/// A tiny deterministic generator, so the property test needs no dependency and fails the same way every time.
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
}

/// Property: whatever the conversation, the layers and the budget, a request that is made holds every pinned item
/// word for word, fits the window, ends with the latest user message, and keeps every tool call with its result.
#[test]
fn property_pinned_items_survive_compaction() {
    let mut rng = Rng(0x9E37_79B9_7F4A_7C15);
    let mut compacted = 0;
    for case in 0..400 {
        let turns = 1 + rng.below(30) as usize;
        let mut convo = Vec::new();
        for n in 0..turns {
            let size = 1 + rng.below(120) as usize;
            let mut t = turn(n, size);
            if rng.below(3) == 0 {
                t.truncate(1);
                t.push(msg(Role::Assistant, "short"));
            }
            convo.extend(t);
        }
        let pins: Vec<Pin> = (0..rng.below(6))
            .map(|i| {
                let kind =
                    [PinKind::Goal, PinKind::Constraint, PinKind::Decision][rng.below(3) as usize];
                Pin::new(
                    kind,
                    format!("pin {case}-{i} {}", "p ".repeat(rng.below(20) as usize)),
                )
            })
            .collect();
        let layers: Vec<Layer> = (0..rng.below(4))
            .map(|i| {
                let source = [LayerSource::User, LayerSource::Project, LayerSource::Memory]
                    [rng.below(3) as usize];
                layer(
                    &format!("layer {i}"),
                    source,
                    &"rule\n".repeat(rng.below(400) as usize),
                )
            })
            .collect();
        let window = 1024 + rng.below(8) * 1024;
        let mut b = budget(window);
        b.threshold = 0.3 + (rng.below(6) as f64) / 10.0;
        let plan = (rng.below(2) == 0).then_some("1. step\n2. step");
        match assemble(&input(&layers, &pins, plan, &convo), &b) {
            Ok(out) => {
                let head = text(&out.messages[0]);
                for pin in &pins {
                    assert!(head.contains(pin.text.trim()), "case {case}: pin lost");
                }
                assert!(out.tokens <= b.available(), "case {case}: over the window");
                assert_valid(&out.messages);
                assert_eq!(
                    out.messages.last().map(text),
                    convo.last().map(text),
                    "case {case}: latest message changed"
                );
                if out.compaction.is_some() {
                    compacted += 1;
                }
            }
            Err(PromptError::TooLarge { .. } | PromptError::PinnedTooLarge { .. }) => {}
        }
    }
    assert!(
        compacted > 20,
        "the property was not exercised: {compacted}"
    );
}
