"""Forward-only diagnosis of why the pair tasks sit at chance (no backward, no optimizer).

Usage (inference only; isolated HOME, validation split only, never the sealed test split):
    HOME=$(mktemp -d) .venv/bin/python -I scripts/diagnose_pair_path.py \
        <checkpoint-dir> <tokenizer.model> [N] [--order-only]

Section G (T195) scores the sentence-order head on two-segment cuts of the MLM validation
rows; `--order-only` runs only that section.
"""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
import numpy as np
import pyarrow.parquet as pq
import torch

from laris.model.inference.loader import load_encoder
from laris.research.language.evaluation.sentence_order import score_sentence_order
from laris.shared.language.loading.dataloader import TASK_DATASET_DIRS, build_sequence

ORDER_ONLY = "--order-only" in sys.argv
ARGS = [a for a in sys.argv[1:] if a != "--order-only"]
CKPT = Path(ARGS[0])
TOK = Path(ARGS[1])
N = int(ARGS[2]) if len(ARGS) > 2 else 600
L = 128

enc = load_encoder(CKPT, TOK, device="cuda")
model, tok = enc.model, enc.tokenizer


def rows(dataset, n):
    fs = sorted(glob.glob(f"data/processed/{dataset}/**/*val*.parquet", recursive=True)
                + glob.glob(f"data/processed/{dataset}/val/**/*.parquet", recursive=True))
    out = []
    for f in fs:
        for b in pq.ParquetFile(f).iter_batches(batch_size=2048):
            out.extend(b.to_pylist())
            if len(out) >= n:
                return out[:n]
    return out[:n]


def ids(t):
    return list(tok.encode_as_ids(t)) if t else []


@torch.no_grad()
def run(first, second, task):
    seq, mask = zip(*[build_sequence(a, b, L) for a, b in zip(first, second)])
    t = torch.tensor(seq, device="cuda")
    m = torch.tensor(mask, device="cuda")
    return model(t, attention_mask=m, task=task)


def batched(pairs, task, key, bs=32):
    res = []
    for i in range(0, len(pairs), bs):
        chunk = pairs[i:i + bs]
        out = run([a for a, _ in chunk], [b for _, b in chunk], task)
        res.append(out[key].float().cpu())
    return torch.cat(res)


def rank(x):
    return np.argsort(np.argsort(x)).astype(float)


def spearman(a, b):
    a, b = rank(np.asarray(a)), rank(np.asarray(b))
    return float(np.corrcoef(a, b)[0, 1])


def collapse(x):
    """Mean pairwise cosine between different examples and mean per-dim std / mean norm."""
    x = torch.nn.functional.normalize(x, dim=-1)
    sim = x @ x.T
    n = x.shape[0]
    off = (sim.sum() - sim.diag().sum()) / (n * (n - 1))
    return float(off)


def sentence_order(n):
    """G: order head on two-segment cuts of the MLM validation rows (forward only)."""
    for ds in TASK_DATASET_DIRS["mlm"]:
        files = sorted(Path(f"data/processed/{ds}").glob("val*.parquet"))
        if not files:
            continue
        r = score_sentence_order(enc, files, n, batch_size=32, seed=42)
        print(
            f"G  order {ds}: acc {r['accuracy']:.3f} "
            f"(majority {r['majority_baseline_accuracy']:.3f})  loss {r['loss']:.4f} "
            f"(ln 3 {r['chance_loss']:.4f})  rows {r['rows']}  "
            f"pred share {json.dumps(r['predicted_shares'])}  "
            f"gold share {json.dumps(r['gold_shares'])}"
        )


if ORDER_ONLY:
    sentence_order(N)
    sys.exit(0)

# ---------------- STS-B val ----------------
sts = rows("stsb", N)
a = [ids(r["sentence1"]) for r in sts]
b = [ids(r["sentence2"]) for r in sts]
y = np.array([float(r["score"]) for r in sts])
print(f"STS-B val rows {len(sts)}  label mean {y.mean():.3f} var {y.var():.3f}")

# A: similarity head (cross-encoder on the pair input, or the bi-encoder on two single sentences)
pairs = list(zip(a, b))


@torch.no_grad()
def bi_encoder_scores(first, second, bs=32):
    out = []
    for i in range(0, len(first), bs):
        sides = []
        for chunk in (first[i:i + bs], second[i:i + bs]):
            seq, mask = zip(*[build_sequence(x, None, L) for x in chunk])
            width = max(sum(m) for m in mask)
            sides += [torch.tensor([s[:width] for s in seq], device="cuda"),
                      torch.tensor([m[:width] for m in mask], device="cuda")]
        out.append(model.bi_encoder_similarity(*sides)["similarity_score"].float().cpu())
    return torch.cat(out)


if getattr(enc.config, "similarity_head", "cross_encoder") == "bi_encoder":
    sim = bi_encoder_scores(a, b).squeeze(-1).numpy()
else:
    sim = batched(pairs, "similarity", "similarity_score").squeeze(-1).numpy()
print(
    f"A  sim head ({getattr(enc.config, 'similarity_head', 'cross_encoder')}): Spearman {spearman(sim, y):.3f}  pred mean {sim.mean():.3f} "
    f"std {sim.std():.4f}  MSE {((sim - y) ** 2).mean():.3f}  (constant-mean MSE {y.var():.3f})"
)
if getattr(enc.config, "similarity_head", "cross_encoder") != "bi_encoder":
    cls_pair = batched(pairs, "similarity", "cls_embedding")
    print(f"C  CLS of pair input: mean cosine between different examples {collapse(cls_pair):.3f}")

# B: siamese embeddings (the path retrieval trains)
ea = batched([(x, None) for x in a], "embedding", "cls_embedding")
eb = batched([(x, None) for x in b], "embedding", "cls_embedding")
cos = torch.nn.functional.cosine_similarity(ea, eb).numpy()
print(
    f"B  siamese CLS cosine: Spearman {spearman(cos, y):.3f}  "
    f"(mean cosine across unrelated examples {collapse(ea):.3f})"
)

# B2: mean-pooled token states, siamese
@torch.no_grad()
def meanpool(seqs, bs=32):
    out = []
    for i in range(0, len(seqs), bs):
        ch = seqs[i:i + bs]
        s, m = zip(*[build_sequence(x, None, L) for x in ch])
        t = torch.tensor(s, device="cuda")
        mm = torch.tensor(m, device="cuda")
        h = model(t, attention_mask=mm, task="embedding")["hidden_states"].float()
        w = mm.unsqueeze(-1).float()
        out.append(((h * w).sum(1) / w.sum(1)).cpu())
    return torch.cat(out)


pa, pb = meanpool(a), meanpool(b)
cos2 = torch.nn.functional.cosine_similarity(pa, pb).numpy()
print(f"B2 siamese mean-pool cosine: Spearman {spearman(cos2, y):.3f}")

# D: lexical overlap reference
jac = np.array([len(set(x) & set(z)) / max(1, len(set(x) | set(z))) for x, z in zip(a, b)])
print(f"D  token Jaccard (no model): Spearman {spearman(jac, y):.3f}")

# ---------------- NLI ----------------
for ds in ("all_nli", "anli"):
    nl = rows(ds, N)
    lm = {"entailment": 0, "neutral": 1, "contradiction": 2}
    p = [(ids(r["premise"]), ids(r["hypothesis"])) for r in nl]
    g = np.array([lm[r["label"]] for r in nl])
    lg = batched(p, "nli", "nli_logits")
    pred = lg.argmax(-1).numpy()
    prob = torch.softmax(lg, -1)
    share = np.bincount(pred, minlength=3) / len(pred)
    true_share = np.bincount(g, minlength=3) / len(g)
    print(
        f"E  NLI {ds}: acc {(pred == g).mean():.3f}  pred class share {share}  "
        f"max-prob mean {prob.max(-1).values.mean():.3f}  true share {true_share}"
    )

# ---------------- paraphrase ----------------
for ds in ("paws", "quora_duplicates"):
    pr = rows(ds, N)
    keys = list(pr[0])
    s1 = "sentence1" if "sentence1" in keys else keys[0]
    s2 = "sentence2" if "sentence2" in keys else keys[1]
    lab = [c for c in keys if "label" in c][0]
    p = [(ids(r[s1]), ids(r[s2])) for r in pr]
    g = np.array([int(r[lab]) for r in pr])
    pp = batched(p, "paraphrase", "paraphrase_prob").squeeze(-1).numpy()
    pos, neg = pp[g == 1], pp[g == 0]
    auc = float((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean())
    print(
        f"F  paraphrase {ds}: AUC {auc:.3f}  prob mean {pp.mean():.3f} std {pp.std():.4f}  "
        f"positive rate {g.mean():.3f}"
    )

# ---------------- sentence order (T195) ----------------
sentence_order(N)
