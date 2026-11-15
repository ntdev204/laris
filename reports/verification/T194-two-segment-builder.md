# T194: two-segment sequence builder (pair-format MLM and sentence-order data)

Measured 2026-11-15 by `scripts/two_segment_dry_run.py`. All figures come from
`reports/verification/T194-two-segment-dry-run-train.json` and `-val.json`. The run used the real
partitioned MLM shards (ten sources, `TASK_DATASET_DIRS["mlm"]`) and the pilot-2 tokenizer
`artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model` for encoding only. It built no model.
Nothing was trained. There was no tokenizer fit, no backward step and no optimizer. The sealed test split was not
read. The foundation model is **NOT QUALIFIED**. This report is about input formatting and says nothing about model
capability.

## 1. What was built

- `src/laris/shared/language/loading/segments.py`: cuts one MLM passage at a sentence or paragraph boundary, chosen
  uniformly, into two consecutive segments `a` and `b` of one document. It also contains the pair layout
  `[CLS] a [SEP] b [SEP]` and the three order classes: 0 in order (`a b`), 1 swapped (`b a`) and 2 other document
  (`a c`, where `c` is a second segment of another document). When the window is too short, `a` keeps its tail and `b`
  its head, so the tokens at the junction survive truncation.
- `StreamingParquetMultiTaskDataLoader` options `mlm_pair_fraction` (default 0), `order_task` (default off) and
  `order_class_shares` (default thirds). Two-segment rows are MLM rows, so their masking is the same 15 % dynamic masking.
  It never masks `[CLS]`, `[SEP]` or padding. With `order_task` the MLM batch carries `order_labels`, with the ignore
  index (-100) on single-segment rows. `two_segment_report()` gives the shares.
- The same three fields are in `TrainingConfig` and go to the train loader and the memory-profile loader. `order_task`
  requires `mlm_pair_fraction > 0`. Until T195 adds the head and loss, `laris train language-encoder` refuses to run
  with `order_task` on. The validation loader keeps single-segment MLM, so validation MLM loss stays comparable with
  earlier runs.

Rules:
- Split. The loader reads only its own split's shards. The other-document segment comes from the same batch first and
  otherwise from a buffer of earlier second segments of the same loader (at most `buffer_size` entries, cleared by
  `reset()`). T193 measured that every document is stored in a single split (`documents_contiguous: true`), so no
  segment crosses train and validation.
- Document. The document of a row is its `id` without the `#k` passage number (`document_id`). An other-document segment
  never shares that document. If no other document is available, the class is drawn again between in order and swapped,
  and the event is counted (`order_other_document_unavailable`).
- Passage. A passage without two sentences or paragraphs stays single-segment (`mlm_pair_without_boundary`).
- Pairs are cut inside one passage. Pairs that join `doc#k` and `doc#k+1` (5.33 M in T193) are not used, because the
  streaming loader interleaves shards and does not see consecutive rows together.
- Default. With `mlm_pair_fraction: 0` the random draws and the batches are identical to the loader before T194 (tested).

## 2. Loader dry run (real shards, seq_len 512, 250 batches of 8, seed 42, fraction 0.5, order task on)

| Measure | Train | Val |
|---|---|---|
| MLM rows drawn | 2,000 | 2,000 |
| Two-segment rows | 971 (0.486) | 978 (0.489) |
| Rows drawn for a pair without a boundary | 4 | 3 |
| Order: in order | 325 (0.335) | 326 (0.333) |
| Order: swapped | 327 (0.337) | 334 (0.342) |
| Order: other document | 319 (0.329) | 318 (0.325) |
| Other document unavailable | 0 | 0 |

The two-segment share is the configured 0.5 minus the rows without a boundary, and is within sampling error of it. The
order classes are within sampling error of the configured thirds.

## 3. Tests

`tests/unit/language/test_two_segment_builder.py` (15 tests, fixtures only): boundaries and the cut, junction-keeping
truncation, the layout, the unchanged default path, consecutive segments of one passage, masking that never touches
special ids, the pair share, the order-class balance and the meaning of each label, ignore labels on single-segment
rows, no cross-split segments, the other-document fallback, seed stability and `reset()`, and option validation.

## 4. Open

- Fractions (pair-format MLM 0.5 proposed, the order share of the pair budget) are proposals. T203 fixes them.
- The order head, its loss and the forward-only chance check on the pilot-2 checkpoint belong to T195. No effect of either
  objective is measured here.
