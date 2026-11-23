# T285 — Admissible sources and the certainty a brain-only answer needs

Date measured: 2026-11-23. Measured by LARIS on this machine. Development splits only; no sealed file was read, and no
model was called (the brain-only measure is model-free). The model (Qwen3.5-4B) and the system are **NOT QUALIFIED**.
Item text and paper text are not reproduced here; the figures are counts.

## What changed

- **One rule, "certain"** (`laris-brain::certain`, used by the server decider, `laris-server brain retrieve` and
  `brain certify`, and so by the Python harness). A Claim is certain only when, checked each time it is read:
  1. it is a Claim at level `sourced` or higher;
  2. its Source is an active `document` whose text still hashes to its recorded `sha256`;
  3. the Source carries an admission record under a class of `configs/admissible-sources.json`: a registry the
     class accepts with the SHA-256 of its response, a licence the class accepts, a venue on the class's list (papers),
     and a retraction check that found nothing (papers);
  4. the Claim's quote is found again at its byte span with its recorded hash.

  Failures are named: `not-a-claim`, `level`, `no-source`, `retracted`, `source-inactive`, `source-changed`,
  `not-admitted`, `unresolved`, `licence`, `venue`, `retraction-unchecked`, `quote-moved`.
- **The deployed decider** reads the classes from `LARIS_SERVER__DECIDER_ADMISSIBLE_SOURCES` (required; compose mounts
  the file read-only). Only certain Claims count for coverage and for a composed answer; Theories are not composed.
  A Source written through `POST /v1/admin/brain/sources` has no admission record, so its Claims are context for the
  model, never a brain-only answer. This changes the behaviour of the deployed server (`COMPOSE_WITHOUT_MODEL=true`
  in compose): a brain built through the admin routes no longer answers without the model.
- **Source classes** (configuration only): `textbook` (OpenStax at the pinned CC BY 4.0 commits, resolved against the
  openstax.org catalogue), `reference_table` (NIST CODATA 2022, public data; CIAAW abridged atomic weights 2024,
  factual data) and `journal_paper` (Crossref; CC BY 4.0, CC BY 3.0 or CC0; nine venues; retraction check).
- **Papers**: `scripts/acquire_papers.py` (network at acquisition only; the snapshot build and evaluation stay offline).

## The owner's delegation and the choices made

The owner left the venue list and the papers to the agent ("Agent all", 2026-11-23). Chosen:

- **Venues** (ISSN-L): Nature Communications `2041-1723`, Communications Biology `2399-3642`, eLife `2050-084X`, PLOS
  Biology `1544-9173`, PLOS Computational Biology `1553-734X`, Science Advances `2375-2548`, Chemical Science
  `2041-6520`, ACS Central Science `2374-7943`, JACS Au `2691-3704`. Criterion: peer-reviewed venues that publish
  CC BY articles with a JATS full text in Europe PMC. Physics has no such route (Physical Review X: 0 reviews with a
  PMC copy), so physics stays with the OpenStax books.
- **Papers**: per venue, the 10 most cited reviews of 2015-2024 with a CC BY or CC0 open-access copy and a PMCID, not
  retracted per OpenAlex, ordered by citations then DOI (OpenAlex, `candidates.json` SHA-256 `d06810a0…`): 90 DOIs,
  all approved into `papers.approved`. A few are meta-research or policy reviews rather than core STEM (for example on
  replicability or research consent); they were kept so that the selection stays mechanical and reproducible.

## Import: what was admitted and why the rest was refused

| | Count |
|---|---|
| Approved DOIs | 90 |
| Admitted | 79 (10 each: Nature Comms, Comms Biology, eLife, PLOS Biology, Science Advances, JACS Au; 7 PLOS Comp Biol; 7 ACS Central Science; 5 Chemical Science) |
| Refused `licence` | 11 |
| Refused `unresolved`, `retracted`, `venue`, `no-full-text` | 0 |

The 11 licence refusals: 3 PLOS Computational Biology (2015) and 2 Chemical Science state the licence only in prose
with no licence URL; 3 Chemical Science full texts have no licence element; 3 ACS Central Science point to the
publisher's own "AuthorChoice" terms page, not a Creative Commons URL. They are refused rather than guessed from prose.

Two faults in the first acquisition were found and fixed before the build (both in the agent's code, not in the
sources): the JATS reader missed a licence URL inside `<ext-link>` of the licence text (22 false refusals), and the
rule required a licence from Crossref as well, which Crossref does not record for Science Advances, Chemical Science
and ACS Central Science (14 refusals). Now a licence Crossref states must be accepted, and when it states none the
full text's licence decides; each Source records which held. Tests cover both.

`provenance.json` (SHA-256 `47152398…`, outside Git) holds every verdict and the SHA-256 of every kept response.

## The new snapshot

`stem-t285-2`, built by `python scripts/build_stem_brain.py build stem-t285-2 --sources configs/admissible-sources.json`
at code revision `2c3012df` (clean tree); SHA-256 `5019e63b76f7a5ae68a0497ba51279f85683266da6e0f2cd4670ba766638a9c4`.
A first build from the uncommitted tree (`stem-t285-1`) gave the same hash. The T277 snapshot `stem-t277-2` is unchanged.

| | Sources | Claims (all `sourced`) |
|---|---|---|
| Textbook (OpenStax, 2,133 modules) | 2,135 | 19,570 |
| Reference table (CODATA 355 constants, CIAAW 84 elements) | 2 | 439 |
| Journal paper (abstract sentences) | 79 | 371 |
| Solver runs (`tool_run`, not admissible: no Claim rests on them) | 606 | — |
| **Total** | **2,822** | **20,380** |

Gate: 0 refused, 668 Conflicts (the false-Conflict issue of T277, owned by T283), lint 0. The papers' Claims are abstract
sentences of 8 to 60 words without first-person or framing words; the Source keeps only title and abstract.

`laris-server brain certify` (`certify.json`): all 2,216 document Sources admitted (2,135 textbook, 2 reference table,
79 journal paper) and all 20,380 Claims certain. The same rule on the frozen T277 snapshot: 0 of 19,925 Claims certain
(`not-admitted`: no admission records), as intended.

**B6 leakage scan**: 0 hits over 14,524 benchmark items (13-gram), after the build left out the same 11 textbook blocks
in 8 modules as T277; no paper paragraph was left out.

## Brain-only answers on development (B5 needs 0 wrong)

Rule (`harness.brain_only_option`): answer a multiple-choice item without the model only when exactly one option's
content words (at least 2) all occur in one certain Claim among the top 5 passages, and no other option's do.

| Development split | Items | With a certain hit | Answered | Right | Wrong | Precision |
|---|---|---|---|---|---|---|
| MMLU-Pro STEM | 1,175 | 384 | 16 | 1 | 15 | 6 % |
| GPQA main minus Diamond | 250 | 113 | 1 | 0 | 1 | 0 % |
| MATH (open answers; not applicable) | 500 | 237 | 0 | — | — | — |

**The rule fails B5** (16 wrong of 17). A certain Claim is faithful to an admitted source; that does not make an option
whose words it contains the answer to the question: the Claim usually states a fact *about* the option's terms, not
the relation the question asks for. Certainty of the source and correctness of the choice are separate, and only the
first is solved here. The brain-only path therefore stays **off** (`harness.brain_only.enabled: false`) and the
harness's numbers of T278 are unchanged. Most retrieved passages are Source text, not Claims (`not-a-claim`: 5,241 /
1,090 / 2,113 hits), so a better route to Claims, and a check that a Claim answers the question rather than mentions
its words, belong to T286 (filter and extracted fields) and T287 (router labels per path).

## Tests

- Rust: `crates/laris-brain/tests/certain.rs` (8: each failure named, including an unresolved DOI, a retracted
  paper, a venue off the list, a closed licence, a moved quote and an edited Source; a model-only Claim stays refused;
  the composer uses only certain Claims), `crates/laris-server/tests/brain_ingest.rs` (admission record stored,
  `certify` and `retrieve` verdicts), `decider.rs` (the setting is required; a Claim without an admission record does
  not answer alone), `deployment.rs` (the file is mounted read-only). Workspace: 1,027 passed; `cargo fmt --check`,
  `cargo clippy -D warnings`, `cargo deny check` ok.
- Python: `tests/unit/knowledge/test_papers.py` (each refusal by name, licence reading, Claims, CIAAW), brain-only
  tests in `tests/unit/stem/test_harness.py`.

## Open for the owner

- ADR-026 section 5 says a model-free answer may rest on "an accepted claim"; T285 makes that "a certain Claim". An
  amendment to ADR-026 is proposed, not made.
- The venue list and the 90 papers were the agent's choice under delegation; the owner may change either in the
  configuration and rebuild.
- CIAAW's table carries no stated licence; it is admitted as factual data (`factual-data`), as already used by the
  solver since T276. Removing that licence from the class removes its 84 Claims from certainty.
