---
name: skill-authoring
description: >-
  Turns new knowledge or a new capability taught by the user into a complete, reusable RAG skill.
  Use when the user says they want to add a skill, teach the assistant a procedure, or save a
  recurring way of working with their documents.
---

# Skill authoring

## When to use
- The user describes a new procedure, domain method or recurring task and wants it kept.
- The user explicitly asks for a skill (a repeatable procedure). New facts or definitions are knowledge,
  not a skill: save them with `save_knowledge` instead.

## Steps
1. Ask only for what is missing: the goal, when it should trigger, inputs, the expected output and
   the limits. Do not invent domain facts; mark unknowns as Assumed.
2. Check existing skills first (the Skills list) so you extend instead of duplicating.
3. Draft the skill in chat: a name (lowercase letters, digits, dashes), a description that starts
   with what it does and contains "Use when ...", and a body with these sections: `## When to use`,
   `## Steps` (numbered, using real tools such as `search_corpus`, `read_file`, `extract_discourse`),
   `## Output` and `## Limits`.
4. Show the draft and get the user's agreement. Never put secrets, absolute paths, instructions to
   ignore rules, or references to policy files in a skill.
5. Call `save_skill` (needs approval). If it reports problems, fix exactly those and retry once.
6. Tell the user how to run it: `/<name> request`, and offer to test it on one real example.

## Output
- The saved skill name and path, a two-line summary of what it does, and one suggested test request.

## Limits
- A skill never overrides policy, workflows or the user's message; it only adds task knowledge.
- A skill cannot grant tools, raise limits or skip approval.
- Knowledge from documents belongs in the corpus (ingest it); a skill holds the method, not the facts.
