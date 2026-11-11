---
document_id: "DOC-TEST-AGENTIC-001"
title: "Agentic Scenario Suite (harness level)"
document_type: "test"
status: "DRAFT"
version: "1.0.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/adr/ADR-017-layers-and-capability-ladder.md"
  - "docs/testing/TEST_STRATEGY.md"
decision_references:
  - "ADR-017"
change_summary: "Scenarios that show the harness plans, tracks, reflects, completes, resumes and stays inside its limits, using a scripted provider."
---

# Agentic Scenario Suite

`tests/unit/agent/test_agentic_scenarios.py` runs the real loop, tools, guards and conversation store with a
scripted provider that plays the model. It proves what the **harness** does; it says nothing about how well a
trained model plans.

**Model status: NOT QUALIFIED.** The core model is paused and has not passed its formal held-out gates. No
result here is evidence of scientific capability; the suite shows that a capable model can be run
agentically inside the limits.

| Criterion (ADR-017 section 3) | Scenario | What is asserted |
|-------------------------------|----------|------------------|
| 1 Plan | model plans first; harness records a plan when the model acts without one; short questions need none; planning can be turned off | a `plan` event precedes the first tool call; the model is shown its plan every step |
| 2 Track and resume | an interrupted plan is saved with the conversation and continued after resume | statuses persist; finished steps are not repeated |
| 3 Reflect and replan | an empty result triggers a replan that succeeds; a model that never gives up is stopped | `agent.reflect.max_replans` reflections, then one "stop retrying" notice, within `agent.max_steps` |
| 4 Completion check | the model tries to finish with steps open; the model will not finish them | it is asked for the rest; otherwise the answer says "Chưa hoàn thành" and the goal is reported open |
| 5 Memory | a finished goal is written to the project vault with its plan | the note contains the plan lines |
| 6 Bounded autonomy | write refused without approval; a planner that never stops; an invalid plan | typed errors, no file written, the step ceiling holds |

How it works: the model changes the plan through the `update_plan` tool; the loop shows it
(`plan` events), keeps it in the conversation, reflects on each tool result (typed error or empty answer),
and holds a goal open while steps are pending or in progress. Failed steps are reported, not repeated.
