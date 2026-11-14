# T175: model size against the data on disk (proposal, nothing decided)

The foundation model is **NOT QUALIFIED**. Token counts are estimates (characters divided by 4.2) until the English tokenizer is fitted.

Unique English MLM text: about 11.8 B tokens (FineWeb-Edu 4.2, Wikipedia 2.1, Gutenberg 1.7, C4 1.5, OpenWebText 1.4, CC-News 0.45, CNN/DM 0.28, Simple Wikipedia 0.22).

Rule used: about 20 training tokens per parameter, at most 4 passes over unique data (repeated data past about 4 epochs adds little).

| Parameters | Tokens needed (20/param) | Passes over 11.8 B | Training memory, AdamW (16 B/param) | Time at about 35 TFLOP/s (6·N·D, estimate) |
|---|---|---|---|---|
| 0.11 B (current) | 2.2 B | 0.2 | 1.8 GB | about 5 days at this data volume is not needed |
| 0.35 B | 7 B | 0.6 | 5.6 GB | about 14 days |
| 0.6 B | 12 B | 1.0 | 9.6 GB | about 24 days |
| 1.0 B | 20 B | 1.7 | 16 GB, needs 8-bit state and checkpointing | about 40 days |
| 2.0 B | 40 B | 3.4 | over 16 GB, needs offload | about 160 days |

Reading: the data supports up to about 2 B at 4 passes, but one RTX 5070 Ti (16 GB, 15.0 GB serving limit across all models) makes 0.35 to 1 B the practical range. Proposal: **0.6 B**, re-checked after the tokenizer is fitted and T177 filtering fixes the real token count. Throughput of 35 TFLOP/s is an assumption; the owner measures it first. No configuration was changed.
