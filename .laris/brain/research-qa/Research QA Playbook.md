---
type: playbook
domain: research-qa
level: 2
summary: Classify the question, search before answering, judge whether the evidence suffices, answer with citations or abstain.
version: 1.0.0
parent: '[[Research QA]]'
requires:
- '[[Evidence Sufficiency]]'
uses:
- '[[Scientific RAG Playbook]]'
- '[[Question Types]]'
---

# Research QA Playbook

Classify the question, search before answering, judge whether the evidence suffices, answer with citations or abstain.


## Decide
- Classify the question (factual, comparative, causal, methodological) and search with terms from the question.
- Search again with changed terms before concluding that nothing is found.
- Compare passages from at least two sources when both exist.

## Verify
- Every claim in the answer carries a citation to a retrieved passage.
- Answers separate what the sources state from your inference.
- Conflicting passages are both reported, with their sources.

## Stop
- Abstain and say what is missing when the evidence does not answer the question.
- Stop after the step limit and give the best supported partial answer, marked partial.
