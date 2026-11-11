---
type: playbook
domain: scientific-nlp
level: 2
summary: Extract discourse elements with the extractor, verify each against the text, normalise numbers, and report uncertainty.
version: 1.0.0
parent: '[[Scientific NLP]]'
uses:
- '[[Claims and Results]]'
- '[[Methods Datasets Metrics]]'
- '[[Units and Numbers]]'
- '[[Formula Handling]]'
---

# Scientific NLP Playbook

Extract discourse elements with the extractor, verify each against the text, normalise numbers, and report uncertainty.


## Decide
- Run the extractor on the specific section or document, not on the whole corpus at once.
- Keep each extracted item with its sentence and position.
- Normalise numbers and units only when the text states them.

## Verify
- Check every extracted claim against its sentence; drop items the sentence does not support.
- Distinguish a claim from a result and a result from a limitation.
- Report extraction counts per type and the share that failed verification.

## Stop
- Stop when the extractor returns nothing new for a document.
- Do not present extracted items as findings without their sentences.
