//! Extractive autocompact of a conversation.

use super::{conversation_tokens, estimate_tokens, message_tokens, text_message, text_of};
use laris_protocol::{ChatMessage, Content, Role};

/// First words of a summary message, which is how a later pass finds it and carries it forward.
pub const SUMMARY_MARK: &str = "[Earlier in this session, compacted]";

pub(super) struct Outcome {
    pub messages: Vec<ChatMessage>,
    pub summarized_turns: u64,
    pub trimmed: bool,
}

fn is_summary(message: &ChatMessage) -> bool {
    message.role == Role::User && text_of(message).starts_with(SUMMARY_MARK)
}

fn clip(text: &str, keep: usize) -> String {
    let flat: String = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.chars().count() <= keep {
        return flat;
    }
    let head: String = flat.chars().take(keep).collect();
    format!("{head}...")
}

/// Splits a conversation into turns: each starts at a user message (a summary is not a turn of its own). A user
/// message that follows a tool result is the loop speaking to the model inside the running turn (a replan or
/// wrap-up notice), not a new request, so it stays in that turn with the results it is about.
fn turns(messages: &[ChatMessage]) -> Vec<&[ChatMessage]> {
    let mut starts = vec![0];
    for (i, m) in messages.iter().enumerate().skip(1) {
        let inside_tool_work = messages[..i]
            .iter()
            .rev()
            .find(|p| p.role != Role::User)
            .is_some_and(|p| p.role == Role::Tool);
        if m.role == Role::User && !is_summary(m) && !inside_tool_work {
            starts.push(i);
        }
    }
    let mut out = Vec::new();
    for (n, &s) in starts.iter().enumerate() {
        let end = starts.get(n + 1).copied().unwrap_or(messages.len());
        out.push(&messages[s..end]);
    }
    out
}

/// One line of the summary for a turn: the request, the tools that ran, the answer.
fn summarize_turn(turn: &[ChatMessage], keep: usize) -> String {
    let mut line = String::new();
    if let Some(user) = turn.iter().find(|m| m.role == Role::User) {
        line.push_str(&format!("- asked: {}", clip(&text_of(user), keep)));
    }
    let mut tools: Vec<(String, u32)> = Vec::new();
    for call in turn.iter().flat_map(|m| &m.tool_calls) {
        match tools.iter_mut().find(|(n, _)| *n == call.function.name) {
            Some((_, count)) => *count += 1,
            None => tools.push((call.function.name.clone(), 1)),
        }
    }
    if !tools.is_empty() {
        let list: Vec<String> = tools
            .iter()
            .map(|(n, c)| {
                if *c > 1 {
                    format!("{n} x{c}")
                } else {
                    n.clone()
                }
            })
            .collect();
        line.push_str(&format!("; tools: {}", list.join(", ")));
    }
    if let Some(answer) = turn
        .iter()
        .rev()
        .find(|m| m.role == Role::Assistant && m.tool_calls.is_empty() && !text_of(m).is_empty())
    {
        line.push_str(&format!("; answered: {}", clip(&text_of(answer), keep)));
    }
    line
}

/// The summary message for `lines`, the oldest dropped first when they pass `cap` tokens.
fn summary_message(mut lines: Vec<String>, cap: u64) -> ChatMessage {
    let cost = |lines: &[String]| -> u64 { lines.iter().map(|l| estimate_tokens(l) + 1).sum() };
    let mut dropped = 0usize;
    while lines.len() > 1 && cost(&lines) > cap {
        lines.remove(0);
        dropped += 1;
    }
    let mut text = format!("{SUMMARY_MARK}\n");
    if dropped > 0 {
        text.push_str(&format!("- ({dropped} older turns left out)\n"));
    }
    text.push_str(&lines.join("\n"));
    text_message(Role::User, text)
}

/// Replaces the content of tool results, oldest first, by a stub, until the conversation fits `hard`.
fn trim_tool_results(messages: &mut [ChatMessage], hard: u64) -> bool {
    let mut changed = false;
    for i in 0..messages.len() {
        if conversation_tokens(messages) <= hard {
            break;
        }
        if messages[i].role == Role::Tool {
            let chars = text_of(&messages[i]).chars().count();
            if chars > 80 {
                messages[i].content = Some(Content::Text(format!(
                    "[tool result of {chars} characters left out to fit the context]"
                )));
                changed = true;
            }
        }
    }
    changed
}

/// Folds the oldest turns into one summary until the conversation fits `target` tokens (the fewest turns that
/// do), always keeping the latest turn; then, if even that is over `hard`, shortens tool results.
pub(super) fn compact_conversation(
    conversation: &[ChatMessage],
    target: u64,
    hard: u64,
    summary_cap: u64,
    line_chars: usize,
) -> Outcome {
    // a summary from before is a line source of its own
    let (carried, rest) = match conversation.first() {
        Some(first) if is_summary(first) => (
            text_of(first)
                .lines()
                .skip(1)
                .map(str::to_owned)
                .collect::<Vec<_>>(),
            &conversation[1..],
        ),
        _ => (Vec::new(), conversation),
    };
    let parts = turns(rest);
    let sizes: Vec<u64> = parts.iter().map(|t| conversation_tokens(t)).collect();
    let n = parts.len();
    let mut lines = carried;
    let mut chosen = 0usize;
    for k in 1..n {
        lines.push(summarize_turn(parts[k - 1], line_chars));
        chosen = k;
        let summary = message_tokens(&summary_message(lines.clone(), summary_cap));
        if summary + sizes[k..].iter().sum::<u64>() <= target {
            break;
        }
    }
    let mut messages = if chosen > 0 {
        let mut out = vec![summary_message(lines, summary_cap)];
        out.extend(parts[chosen..].iter().flat_map(|t| t.iter().cloned()));
        out
    } else {
        conversation.to_vec()
    };
    let trimmed = conversation_tokens(&messages) > hard && trim_tool_results(&mut messages, hard);
    Outcome {
        messages,
        summarized_turns: chosen as u64,
        trimmed,
    }
}
