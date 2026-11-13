# T174: English replacement data inventory (proposal, nothing acquired)

Date 2026-11-14 · Owner decision D46 / ADR-022 · The foundation model is **NOT QUALIFIED**. Sizes below marked *local* are measured from
`data/processed`; every external candidate is a **proposal**: its size and licence are from memory, must be verified before acquisition,
and no file was downloaded.

## 1. What leaves, and what it was worth

| Removed (Vietnamese) | Local size | Role |
|---|---|---|
| `cc100_vi_clean` | 9.3 GB | MLM text (about 70 % of all MLM text) |
| `wikipedia_vi` | 682 MB (1.26 M train rows) | MLM text |
| `vinli`, `viquad_v2`, `vists` | 1.7 / 6.0 / 1.4 MB | NLI, QA (28,300 train rows), similarity (19,440 pairs) |
| `gold_vi_stem` | outside Git | G12 pilot; unused after D46 |

English kept: `wikipedia_en` 3.4 GB, `all_nli` 66 MB, `anli` 19 MB, `fever` 11 MB, `squad` 18 MB, `hotpotqa` 284 MB, `paws` 9.2 MB,
`quora_duplicates` 32 MB, `stsb` 688 KB (5,734 train pairs).

Result: the MLM text drops from about 13 GB to 3.4 GB. English MLM text must be raised toward the old volume, or the epoch count rises.

## 2. English MLM text (replaces cc100_vi and wikipedia_vi)

| Candidate | Why | Licence / risk (verify) |
|---|---|---|
| Open web text corpora with permissive filtering (for example OpenWebText-style or C4 en subset) | general register, large | web text: per-document rights unclear; check terms |
| Project Gutenberg books (public domain) | long coherent text | public domain; archaic register |
| English Wikipedia already local, with more passes | no new licence | repetition, limited gain |
| arXiv and PubMed open-access abstracts | scientific register, supports stage 2 | licence differs per paper; S2ORC is reserved for stage 2 (T101), keep it out of stage 1 |

Proposed first choice: one permissive general web subset plus Gutenberg, deduplicated against Wikipedia, 5 to 8 GB, because that fills the
loss with the least rights risk. Decision belongs to the owner.

## 3. English similarity (STS-B has only 5,734 train pairs)

| Candidate | Pairs (approx., verify) | Leakage and licence |
|---|---|---|
| SICK-R | about 4,500 train | licence is non-commercial (CC BY-NC-SA); fine only if the project stays research-only; check |
| STS 2012-2016 training sets | few thousand each | **STS-B was built from STS 2012-2017: dedupe every sentence pair against the STS-B val and test splits before use, or G05 is contaminated**; licences vary |
| MRPC, QQP-derived graded pairs | binary labels | convert to similarity only with a stated, weak mapping; not graded |
| NLI-derived pairs (entail, neutral, contradict from `all_nli`, already local) | 500k+ | weak labels (three levels), usable for the contrastive term, not for Spearman regression |
| Pseudo-labels from the project's own model | unlimited | circular, not for the held-out gate |

Proposed: SICK-R and STS12-16 after dedupe against STS-B val/test (licence check first), plus `all_nli` triplets for the contrastive term. The
dedupe is a test (leakage check), not an assumption. Expected gain is **not measured**; with about 3 times the labelled pairs, one pass
is more than the 0.5 pass of R2.

## 4. English NLI, paraphrase, QA

Local data are adequate in size (NLI 1.2 M, paraphrase 380 k, QA 168 k English). Gaps are task-specific:
- PAWS is adversarial; the exposure change (R3a) helped AUC 0.640 to 0.672 only; adding PAWS-Wiki duplicates would not add information.
- G06/G07 (SQuAD) rely on 87,599 train questions; more extractive QA (for example NewsQA, TriviaQA) is optional, licences to verify.

## 5. English STEM gold for G12

`gold_vi_stem` cannot be used. The English set needs its own D05 guideline, units and labels (agent labels are allowed as `label_source: llm`
under the 2026-11-13 instruction, not human gold). SciFact (already local, CC BY) stays a development set, not a gate.

## 6. Order

1. Owner confirms or edits section 2 and 3 choices and licences.
2. Agent verifies sizes and licences, builds `scripts` for acquisition and the leakage check, adds the data to the manifests.
3. Owner fits the new tokenizer and retrains (T175).
