# T99 R3a analysis (inference only)

Run `foundation-r3a`: 5,000 steps from `foundation-r2/best`, task alpha 0.4, dataset exponent 0.7. Foundation model: **NOT QUALIFIED**.
Intake (`T99-foundation-r3a-intake.json`): 17 of 18 checks pass; **FAIL: similarity validation loss 0.0135 vs 0.0054 (R2)**, above the 10 % stop rule.

| Measure (val, 2048 samples/group) | R2 | R3a |
|---|---|---|
| MLM acc en / vi | 0.359 / 0.571 | 0.365 / 0.581 |
| NLI macro F1 en / vi | 0.490 / 0.326 | 0.504 / 0.427 |
| Paraphrase AUC en (PAWS+Quora) | 0.640 | 0.672 |
| QA F1 en / vi | 0.250 / 0.289 | 0.274 / 0.289 |
| Similarity Spearman en / vi | 0.322 / 0.384 | 0.404 / 0.230 |
| SciFact dev dense MRR (BM25 0.636) | 0.129 | 0.157 |
| vi-STEM dev dense MRR (LLM gold; BM25 0.989) | 0.391 | 0.555 |

Reading: more exposure helped NLI, paraphrase, QA-en and dense retrieval, as predicted. Similarity-vi regressed (0.384 to 0.230) and
similarity loss rose 2.5x: a regression on a task whose share rose to 5 %, so the cause is open (forgetting or interference with the
contrastive term on QA batches); not tested. No gate is passed: QA-vi, similarity en/vi still FAIL; dense retrieval stays far below BM25.
Gate G01-G12 formal values were not recomputed here. Held-out sets untouched.
