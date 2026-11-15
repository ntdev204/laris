# T195: sentence-order head and loss

Measured 2026-11-16 with `scripts/diagnose_pair_path.py ... 2000 --order-only` on
`artifacts/checkpoints/language_encoder/english-r1-pilot2/best` (step 2,000 of the stopped pilot 2), tokenizer
`artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model`. Forward passes only, under `torch.no_grad()`.
There was no training, no backward step, no optimizer and no tokenizer fit. Only the validation split was read; the
sealed test split was not. The foundation model is **NOT QUALIFIED**. The order task has no gate, and nothing here
measures model capability.

## 1. What was built

- Model (`encoder/transformer.py`): `order_head`, a linear map from the CLS state to three logits (in order, swapped,
  other document; the T194 classes). It is created after the random initialisation with `nn.utils.skip_init` and set
  to zero. So it draws nothing from the RNG, every other parameter of a given seed stays the same as before T195, the
  initial logits are uniform and the initial loss is exactly ln 3. `task="order"` runs only this head, and
  `with_order=True` adds `order_logits` to a single-task pass, because order labels ride on MLM batches (T194). The NumPy
  reference model has the same zero head. Head parameters: 2,307 at d = 768 (3,843 at d = 1,280). The documented
  counts change accordingly: compact 109,764,874 with heads (was 109,762,567), large 513,251,594 (was 513,247,751).
- Checkpoint loading: `load_encoder_state` / `load_model_weights` accept a checkpoint without `order_head.*`, and the
  head keeps its zero values. Any other missing key and every unexpected key still fails as a strict load would. This
  loader is used by `load_checkpoint`, the inference loader and `--init-from`. Resuming the *optimizer state* of a
  pre-T195 checkpoint is refused with a clear error (that state has no slots for the new head). A pre-T195 checkpoint
  starts a new run through `--init-from`.
- Loss: `sentence_order_loss` is the fp32 cross-entropy over the labelled rows. Single-segment rows carry -100, and a
  batch without labelled rows gives a zero that keeps the graph. The trainer adds `order_loss_weight × order loss` to
  the MLM loss of a batch with `order_labels` and records the unweighted value in `TrainingMetricsSnapshot.order_loss`.
- Configuration: `TrainingConfig.loss_lambda_order` (default 0). `order_task` and `loss_lambda_order > 0` must be set
  together. `laris train language-encoder` no longer refuses `order_task`, and it passes the weight to the trainer and
  to the memory profile. No shipped YAML enables the task; T203 fixes the fractions and the weight.
- Evaluator: `evaluation/sentence_order.py` cuts every held-out MLM row into two segments (unmasked) and reports
  accuracy, macro F1, recall per class, gold and predicted shares, mean loss against ln 3, and the majority-class
  baseline. `laris evaluate language-encoder --order-samples N` adds it to the report as `diagnostics.sentence_order`
  with `gate: null`. It never changes `passed`. The default is 0, so it is off.
- Diagnostic script: section G of `scripts/diagnose_pair_path.py`. `--order-only` runs only that section.

## 2. Forward-only run on pilot 2 (validation, 2,000 rows drawn per MLM source)

| Source | Scored rows | Accuracy | Majority baseline | Loss | In order / swapped / other (gold) |
|---|---|---|---|---|---|
| wikipedia_en | 1,995 | 0.336 | 0.336 | 1.0986 | 0.336 / 0.335 / 0.329 |
| fineweb_edu_en | 1,994 | 0.331 | 0.339 | 1.0986 | 0.331 / 0.339 / 0.329 |
| openwebtext_en | 1,998 | 0.325 | 0.349 | 1.0986 | 0.325 / 0.325 / 0.349 |
| c4_en | 1,986 | 0.360 | 0.360 | 1.0986 | 0.360 / 0.319 / 0.321 |
| gutenberg_en | 1,999 | 0.405 | 0.423 | 1.0986 | 0.405 / 0.423 / 0.172 |
| cc_news_en | 1,962 | 0.328 | 0.344 | 1.0986 | 0.328 / 0.344 / 0.328 |
| cnn_dailymail_en | 2,000 | 0.339 | 0.339 | 1.0986 | 0.339 / 0.339 / 0.323 |
| xsum_en | 2,000 | 0.328 | 0.347 | 1.0986 | 0.328 / 0.325 / 0.348 |
| wikipedia_simple_en | 1,990 | 0.341 | 0.341 | 1.0986 | 0.341 / 0.325 / 0.334 |

Reading: the checkpoint has no order head, so it loads with the zero head. The loss is ln 3 = 1.0986 on every source,
and the head predicts "in order" for every row. Accuracy is therefore the in-order share (0.325 to 0.405, near 0.33
except Gutenberg). This confirms that loading and the pipeline work. It says nothing about whether the pilot-2 body
separates the classes, which can only be measured after the head is trained (T204). The rows missing from 2,000 are
passages without a sentence or paragraph boundary.

Gutenberg: its validation split holds 12,626 rows from only 106 books, stored book by book. A batch and the loader's
buffer of earlier segments usually contain a single book, so the other-document class often falls back to in order or
swapped (T194 rule). That leaves 17 % other-document labels. Training draws across sources and shards, so the effect
there is unmeasured. T203 should check the class shares per source on the training mixture.

## 3. Tests

`tests/unit/language/test_sentence_order_head.py` (18 tests, fixtures only, no backward step): zero head and shapes,
`with_order`, the parameter count against the instantiated model, the NumPy head, seed stability, the loss value of
ln 3 and ignore rows, the trainer's weighted ln 3 on an MLM batch, the zero weight, weight validation, the config rule,
loading a checkpoint without the head, refusal of other missing and unexpected keys, refusal to resume a pre-T195
optimizer state, the hand-computed metrics, the forward-only score at chance, and the report diagnostic. Updated:
the parameter-count tests (new head) and one T194 config test (`order_task` now needs `loss_lambda_order`).
`scripts/verify_model_block.py` passes.

## 4. Open

- The weight `loss_lambda_order` and the order share of the pair budget are fixed in T203. Their effect is measured
  only in T204 (owner run).
- Validation during training stays single-segment (T194), so in-training validation loss has no order term. Use the
  evaluator diagnostic for order accuracy.
