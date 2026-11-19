# T187 - NER data acquisition and partition

Date: 2026-11-19. Acquisition, conversion and a read-only leakage scan; nothing trained or fitted. The foundation model stays NOT QUALIFIED; NER has no qualification gate.

## Owner decisions (2026-11-19, recorded in T187)
- Sources: Few-NERD (supervised mode; train, validation, test) and WNUT-17 (out-of-domain test); NER is a separate fine-tune, not part of the stage-1 mixture.
- Labels: Few-NERD 8 coarse types, BIO (17 tags). Licence: CC BY-SA 4.0 accepted, `license_approved: true`; data stays outside Git.
- WNUT-17 is mapped to the same set (corporation, group -> ORGANIZATION; creative-work -> ART; person, location, product unchanged). The mapping is my proposal, kept in `configs/data/english_partition.yaml` (`ner`); native BIO labels are kept in `source_labels`.

## Acquired (`laris-model data acquire --ner-all`, SHA-256 in `data/acquisition_manifest.json`)
Few-NERD 188,239 sentences (131,767 / 18,824 / 37,648); WNUT-17 5,690 (3,394 / 1,009 / 1,287). Counts match the publishers' cards. WNUT-17 comes from the Hugging Face parquet conversion branch of `leondz/wnut_17` (the main branch holds only a loading script).

## Partition (`scripts/partition_english.py --only FEW-NERD-EN WNUT-17-EN`)
Official splits kept. Train sentences equal to, or sharing an eight-word window with, any NER validation or test sentence were dropped from train (never from val or test): Few-NERD 7,681 (2,859 val-text, 4,822 test-text), WNUT-17 1.

| Set | train | val | test |
|---|---|---|---|
| Few-NERD sentences | 124,086 | 18,824 | 37,648 |
| Few-NERD entities | 340,180 before drop | 48,741 | 96,842 |
| WNUT-17 sentences | 3,393 | 1,009 | 1,287 |
| WNUT-17 entities | 1,975 before drop | 836 | 1,079 |

Entities per unified type (B- tags, after the drop) are in `data/processed/task_splits_manifest.json` (`english_partition.sources`). Test, Few-NERD: ART 4,064, BUILDING 5,007, EVENT 4,104, LOCATION 27,235, ORGANIZATION 19,078, OTHER 9,558, PERSON 21,565, PRODUCT 6,231. Test, WNUT-17 (mapped): ART 142, LOCATION 150, ORGANIZATION 231, PERSON 429, PRODUCT 127.

Known limits: Few-NERD tags carry no B/I marks, so adjacent entities of one type merge (485,763 entities after conversion against 491,711 in its README, about 1.2 % fewer). Few-NERD supervised-mode train, validation and test are random splits of the same Wikipedia articles.

## Leakage scan against stage 1 (`scripts/check_ner_leakage.py`, report `T187-ner-leakage.json`)
Validation and test sentences against the train split of 42 stage-1 directories (MLM, NLI, paraphrase, similarity, QA, retrieval, relation pairs); six generic names in the loader list have no directory.

| Split | sentences | with a hit | exact | window |
|---|---|---|---|---|
| Few-NERD val | 18,824 | 9,007 (47.9 %) | 137 | 8,964 |
| Few-NERD test | 37,648 | 17,964 (47.7 %) | 273 | 17,880 |
| WNUT-17 val | 1,009 | 27 (2.7 %) | 4 | 23 |
| WNUT-17 test | 1,287 | 77 (6.0 %) | 18 | 67 |

Main sources of Few-NERD hits: `wikipedia_en`, `fineweb_edu_en`, `hotpotqa`, `openwebtext_en`, `c4_en`.

Reading: stage 1 saw the unlabelled text of about half of the Few-NERD test sentences, but it has no entity labels, so no label leaked. The scores of T189 must be worded "measured on Few-NERD test, about 48 % of whose sentences also occur in stage-1 text"; WNUT-17 test is the cleaner out-of-domain number. Test rows were not removed. Whether to remove these text hits from the stage-1 partitions is an owner decision (the stage-1 data is frozen for the finished stage-1 run); I did not touch them.
