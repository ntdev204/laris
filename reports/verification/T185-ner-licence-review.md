# T185 - NER data licence review and source decision

Checked 2026-11-18 by reading the pages linked below. Nothing was downloaded; no data file was opened. This is an engineering reading of publisher statements, not legal advice.
"Not verified" means the page did not load or does not say; it is never read as permission. The foundation model stays NOT QUALIFIED; NER has no qualification gate.

## Summary table

| Candidate | Licence as stated | Text origin | Commercial / redistribution | Share-alike | Labels | Size | Official splits | Status |
|---|---|---|---|---|---|---|---|---|
| Few-NERD | CC BY-SA 4.0 (data), Apache-2.0 (code) | Wikipedia | no NC term found | yes | 8 coarse / 66 fine | 188,200 sentences (README) | supervised / inter / intra, each train/dev/test | usable if owner accepts share-alike |
| WNUT-17 | CC-BY 4.0 (GitHub README, HF card); official page states none | Twitter (train), YouTube (dev), StackExchange + Reddit (test) | no restriction found | no | 6 | train 3,394 / val 1,009 / test 1,287 (HF; unit not stated) | train / dev / test | usable; small, noisy, out-of-domain |
| CoNLL-2003 EN | HF `other`; annotations only | Reuters Corpus (RCV1) | needs NIST agreements | n/a | 4 (PER ORG LOC MISC) | 14,041 / 3,250 / 3,453 (HF) | train / testa / testb | not used without the signed agreements |
| MultiNERD | CC BY-NC-SA 4.0 | Wikipedia, Wikinews (silver labels) | non-commercial research only | yes | 15 | EN 164.1K sentences | multilingual splits; EN-only sizes not stated | not used (NC) |
| WikiANN | not verified (HF page 401) | Wikipedia, silver labels | not verified | not verified | PER/ORG/LOC (not verified here) | not verified | not verified | not used (licence unknown) |
| OntoNotes 5.0 | LDC User Agreement for Non-Members | newswire, broadcast, web, telephone, religious texts | non-commercial only; no redistribution | n/a | 18 | EN ~1.45 M words | train/val/test on HF CoNLL-2012 copy | not used (LDC agreement) |

## Per candidate

### Few-NERD
- Licence: README, "License": "Few-NERD dataset is distributed under the CC BY-SA 4.0 license. The code is distributed under the Apache 2.0 license." (https://github.com/thunlp/Few-NERD, checked 2026-11-18). HF card sidebar: `cc-by-sa-4.0` (https://huggingface.co/datasets/DFKI-SLT/few-nerd). I did not open the repository LICENSE file.
- Origin: "188,238 sentences from Wikipedia" (https://arxiv.org/abs/2105.07464, abstract).
- Labels: "8 coarse-grained types, 66 fine-grained types" (README).
- Size: README "188,200 sentences, 491,711 entities and 4,601,223 tokens"; the paper abstract says 188,238 sentences / 4,601,160 words (the two sources differ; the counts must be measured after any download).
- Splits: three modes `supervised`, `inter`, `intra`, each with train/dev/test (README). Supervised sentence counts 131,767 / 18,824 / 37,648 come from the HF card summary and are not verified verbatim.
- Share-alike: CC BY-SA 4.0 requires adaptations of the data to carry the same licence. Whether model weights fine-tuned on it are an adaptation is not settled by the licence text; it is the same open question that keeps the Stack Exchange data at `license_approved: false` (T180).

### WNUT-17
- Licence: "This data is distributed under the CC-BY 4.0 license." (https://github.com/leondz/emerging_entities_17, README). HF card: `cc-by-4.0` (https://huggingface.co/datasets/leondz/wnut_17), its licensing section says only "More Information Needed". The official task page (https://noisy-text.github.io/2017/emerging-rare-entities.html) states no licence, only a request to cite the task paper.
- Origin (official page): train "(Twitter)", dev "(YouTube)", test "(StackExchange and Reddit)". The CC-BY grant covers the annotations and the redistributed text as the publisher states it; the platforms' own terms for the underlying posts are not examined here and remain an owner risk.
- Labels: six: person, location, group, creative work, corporation, product (GitHub README; the official page lists "Consumer good" for product).
- Size: HF table train 3,394 / validation 1,009 / test 1,287 (unit not stated). The GitHub README gives no sizes.
- Splits: official train/dev/test, deliberately from different sources, so the test is out of domain.

### CoNLL-2003 English
- Primary page (https://www.clips.uantwerpen.be/conll2003/ner/) returned 404 and the old cnts host no longer resolves, so the terms below are the HF card quoting it (https://huggingface.co/datasets/eriktks/conll2003): licence `other`; "Because of copyright reasons we only make available the annotations."; the text is the Reuters Corpus, governed by an organisational agreement and an individual agreement filed with NIST. The shared-task paper (https://aclanthology.org/W03-0419/) carries no such terms.
- Not used unless the owner signs both agreements. Commercial and redistribution terms: not verified.
- Labels PER, ORG, LOC, MISC; HF splits 14,041 / 3,250 / 3,453.

### MultiNERD
- Licence: the LICENSE file and HF say CC BY-NC-SA 4.0 ("restricted to only non-commercial research purposes"); the README text says "CC BY-SA-NC 4.0" and its badge "CC BY-NC 4.0" (https://github.com/Babelscape/multinerd, .../blob/master/LICENSE, https://huggingface.co/datasets/Babelscape/multinerd). The wording is inconsistent; the substantive reading is non-commercial plus share-alike.
- Origin: Wikipedia and Wikinews, automatic (silver) annotation. 15 types. English: 164.1K sentences (README).
- Not used: non-commercial.

### WikiANN
- The HF dataset page returned 401 and `huggingface.co/datasets/wikiann` returned 404. The GitHub repository (https://github.com/afshinrahimi/mmner) shows Apache-2.0 for the repository and states no dataset licence. Source paper: https://aclanthology.org/P17-1178/ ("silver-standard" annotations transferred through cross-lingual links).
- Licence of the data: not verified. Labels, English sizes and splits: not verified. Not used.

### OntoNotes 5.0
- Licence: "LDC User Agreement for Non-Members" (https://catalog.ldc.upenn.edu/LDC2013T19); the agreement text (https://catalog.ldc.upenn.edu/license/ldc-non-members-agreement.pdf, read locally) says use is "only for non-commercial linguistic education, research and technology development", that a commercial product requires For-Profit Membership, and that the data may not be redistributed outside the research group. Fees: "Login for the applicable fee" (amount not shown).
- Origin: telephone conversations, newswire, newsgroups, broadcast news and conversation, weblogs, religious texts. English words (catalog table): 625k + 200k + 200k + 300k + 120k.
- Labels: 18 types (HF card of the CoNLL-2012 copy, https://huggingface.co/datasets/ontonotes/conll2012_ontonotesv5, licence field `cc-by-nc-nd-4.0`, which conflicts with the LDC page). Splits exist there; sizes not stated.
- Not used: LDC agreement plus a conflicting redistribution licence.

## Recommendation (not a decision)
1. Only WNUT-17 has a permissive, first-party licence (CC-BY 4.0, no share-alike). It is small and noisy, so it suits a test set or a small fine-tune, not a broad one.
2. Few-NERD is the only large, clean, Wikipedia-based set. Its price is CC BY-SA 4.0. The 2026-11-14 proposal stands: Few-NERD coarse types (8) for training and held-out test, WNUT-17 as a second, out-of-domain test.
3. None of the other four is usable now (agreements, non-commercial, or unknown licence).

## Open owner decisions
1. Accept CC BY-SA 4.0 for Few-NERD (and record it as `license_approved`), or limit NER to WNUT-17.
2. Label set: Few-NERD coarse (8), Few-NERD fine (66), or WNUT-17 (6); the choice sets T187's BIO conversion.
3. NER as a separate fine-tune (proposal) or in the stage-1 mixture (would change T100's protocol; not proposed).
4. Whether the underlying platform terms of WNUT-17's social-media text are acceptable.
Until the owner records these, T187 downloads nothing.
