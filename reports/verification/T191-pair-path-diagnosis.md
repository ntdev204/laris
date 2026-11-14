# T191: why the pair tasks sit at chance (English R1 pilot 2, step 2,000)

Measured 2026-11-14 on `artifacts/checkpoints/language_encoder/english-r1-pilot2/best` (step 2,000 of a stopped run, mean val loss
0.6865), validation split only, forward passes only (no backward step, no optimizer; the sealed test split is untouched).
The foundation model is **NOT QUALIFIED**; this is a diagnosis of a stopped pilot, not a qualification result.

## Evidence

Evaluator (`cli.model evaluate language-encoder`, 512 samples per dataset): MLM masked accuracy 0.238 (unigram 0.041, perplexity
195 to 460), NLI macro F1 0.285 (majority 0.206), paraphrase AUC 0.552, QA F1 0.0735 (below the 0.0786 empty-answer baseline),
similarity Spearman 0.046. Report: `artifacts/evaluations/language_encoder/english-r1-pilot2-val.json` (outside Git).

Diagnostic (`scripts/diagnose_pair_path.py`, 600 rows per set, inputs cut at 128 tokens):

| Probe | Result |
|---|---|
| STS-B, similarity head on the pair input | Spearman 0.026; prediction mean 0.683, std 0.064 (labels: mean 0.470, variance 0.105); MSE 0.154 against 0.105 for a constant |
| STS-B, cosine of two single-sentence CLS embeddings (the input form retrieval trains) | Spearman 0.570 |
| STS-B, cosine of mean-pooled token states | Spearman 0.460 |
| STS-B, token Jaccard overlap, no model | Spearman 0.571 |
| Mean cosine between different examples, CLS of pair input / single sentence | 0.770 / 0.740 (similar, no collapse specific to the pair path) |
| NLI head, all_nli (labels balanced) | accuracy 0.368; predicts neutral for 74 % of rows; mean top probability 0.359 |
| NLI head, ANLI | accuracy 0.303; predicts entailment for 73.5 % of rows |
| Paraphrase head, Quora / PAWS | AUC 0.651 / 0.505 |

## Reading

1. The encoder body has learned language and single-sentence meaning: MLM is far above the unigram baseline and single-sentence
   embeddings rank STS-B pairs (0.570, equal to word overlap).
2. The cross-segment path does not use it: with the two sentences in one `[CLS] a [SEP] b [SEP]` input the head reaches 0.026,
   although even raw word overlap gives 0.571. Reading overlap across `[SEP]` needs attention between the two segments, and that
   circuit has not formed.
3. About 80 % of the steps (MLM 54 %, retrieval 28 %) carry single-segment input. Only NLI, paraphrase, QA and similarity
   (about 20 % in total; about 190 NLI and 60 similarity updates in 2,000 steps) ever show the body a two-segment input.
4. The heads settle on cheap cues: the NLI prediction follows the source (all_nli to neutral, ANLI to entailment, near-uniform
   confidence), the similarity head sits at the training label mean (the training mixture is 72 % `sts_extra_en`, mean 0.624, against
   0.473 on STS-B validation), paraphrase learns only where overlap suffices (Quora 0.651) and not where word order matters (PAWS 0.505).

## Limits

One checkpoint at step 2,000, 600 rows per probe, one seed. The data cannot separate "more steps would fix it" from "the mixture
will never form the circuit" without a training run; the proposals below are therefore tests and designs for the owner, not
proven fixes. Earlier compact runs (14,000 steps, NLI share 21 to 24 %) reached ANLI macro F1 0.447, so the heads can learn with more
exposure; PAWS stayed near 0.50 there as well.
