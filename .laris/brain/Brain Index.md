---
type: root
domain: brain
level: 0
version: 1.0.0
summary: Entry point of the system brain. Pick one domain hub by route, then follow children; never read the whole brain.
children:
- '[[Literature Mining]]'
- '[[Research QA]]'
- '[[Citation Analysis]]'
- '[[Scientific RAG]]'
- '[[Knowledge Graph]]'
- '[[Scientific NLP]]'
- '[[Tools and Workflows]]'
- '[[Policy Boundaries]]'
- '[[Evaluation]]'
- '[[Ontology]]'
relations:
- requires
- uses
- feeds
- contrasts
- validates
---

# Brain Index

Entry point of the system brain. Pick one domain hub by route, then follow children; never read the whole brain.

## Domain hubs
- [[Literature Mining]] — Turn a corpus of papers into structured findings: scope it, deduplicate it, then measure terms, topics and trends. (when: task is about literature mining)
- [[Research QA]] — Answer research questions only from retrieved evidence: classify the question, gather passages, judge sufficiency, cite. (when: task is about research qa)
- [[Citation Analysis]] — Extract references and citation contexts, then compute and interpret citation structure and its limits. (when: task is about citation analysis)
- [[Scientific RAG]] — Retrieve passages from scientific documents and write answers that stay faithful to them, with citations or an abstention. (when: task is about scientific rag)
- [[Knowledge Graph]] — Build a graph of entities and typed relations from documents, keep provenance on every edge, and reason along paths. (when: task is about knowledge graph)
- [[Scientific NLP]] — Extract claims, methods, datasets, metrics, results and limitations from scientific text, and handle numbers and formulas carefully. (when: task is about scientific nlp)
- [[Tools and Workflows]] — Which tool, skill or workflow fits which job, and how they combine under the approval and step limits. (when: task is about tools)
- [[Policy Boundaries]] — What must never be disclosed or trusted: internal files, untrusted content, and the model's qualification. (when: task is about policy)
- [[Evaluation]] — Judge retrieval and answers with stated metrics and rubrics, on a fixed fixture, without training anything. (when: task is about evaluation)
- [[Ontology]] — The shared vocabulary of the brain: relation types, note types and a glossary of terms. (when: task is about ontology)

## Routing table
Machine-read: a workflow name or task type selects one hub.
route: literature-mining -> [[Literature Mining]]
route: research-brief -> [[Literature Mining]]
route: research-qa -> [[Research QA]]
route: grounded-qa -> [[Research QA]]
route: citation-analysis -> [[Citation Analysis]]
route: scientific-rag -> [[Scientific RAG]]
route: document-intake -> [[Scientific RAG]]
route: knowledge-graph -> [[Knowledge Graph]]
route: scientific-nlp -> [[Scientific NLP]]
route: evidence-review -> [[Scientific NLP]]
route: tools -> [[Tools and Workflows]]
route: policy -> [[Policy Boundaries]]
route: evaluation -> [[Evaluation]]
route: ontology -> [[Ontology]]

## Navigation rule
Enter at a hub chosen by route or keyword, open its playbook or topic, then only the leaf the task needs. Prefer summaries; open full text by id when required.
