"""Audit foundation data and score the existing checkpoint on validation only."""

import json
import unicodedata
from collections import Counter
from hashlib import sha256
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import torch
import yaml

from laris.language.evaluation import metrics as m
from laris.language.evaluation.evaluator import DATASET_LANGUAGE, LanguageEncoderEvaluator
from laris.language.inference.loader import load_encoder
from laris.language.training.checkpoint import file_sha256

DATA = Path("data/processed")
MANIFEST = DATA / "task_splits_manifest.json"
TARGETS = {
    "anli": "nli",
    "vinli": "nli",
    "paws": "paraphrase",
    "stsb": "similarity",
    "squad": "qa",
    "viquad_v2": "qa",
}
COLUMNS = {
    "nli": ("premise", "hypothesis", "label"),
    "paraphrase": ("sentence1", "sentence2", "label"),
    "similarity": ("sentence1", "sentence2", "score"),
    "qa": ("context", "question", "answers"),
}
CAP = 512
checkpoint = Path("artifacts/checkpoints/language_encoder/compact-1024-04/best")
tokenizer = Path("artifacts/tokenizer/laris_spm_32k.model")
manifest_rows = {
    Path(row["files"]["train"]).parent.name: row
    for row in json.loads(MANIFEST.read_text())["partitioned_datasets"]
}


def norm(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def audit(dataset, task):
    keys, contexts, result = {}, {}, {}
    files = manifest_rows[dataset]
    for split in ("train", "val", "test"):
        path = Path(files["files"][split])
        digest = file_sha256(path)
        if digest != files["sha256"][split]:
            raise ValueError(f"Changed shard {path}")
        counts, invalid = Counter(), Counter()
        keys[split], contexts[split] = set(), set()
        rows = 0
        for batch in pq.ParquetFile(path).iter_batches(columns=list(COLUMNS[task])):
            for row in batch.to_pylist():
                rows += 1
                a, b, label = (row[c] for c in COLUMNS[task])
                if not a or not b:
                    invalid["empty_input"] += 1
                pair = [norm(a or ""), norm(b or "")]
                if task in ("paraphrase", "similarity"):
                    pair.sort()
                keys[split].add(sha256(json.dumps(pair).encode()).digest())
                if task == "qa":
                    contexts[split].add(sha256(pair[0].encode()).digest())
                    texts, starts = label["text"], label["answer_start"]
                    counts["answerable" if texts else "unanswerable"] += 1
                    if len(texts) != len(starts) or any(
                        not t or i is None or i < 0 or (a or "")[i : i + len(t)] != t
                        for t, i in zip(texts, starts)
                    ):
                        invalid["invalid_answer_offsets"] += 1
                elif task == "similarity":
                    if label is None or not np.isfinite(label) or not 0 <= label <= 1:
                        invalid["score_outside_0_to_1"] += 1
                    else:
                        band = min(4, int(label * 5))
                        counts[f"{band / 5:.1f}_to_{(band + 1) / 5:.1f}"] += 1
                else:
                    counts[str(label)] += 1
                    allowed = (
                        ("entailment", "neutral", "contradiction") if task == "nli" else (0, 1)
                    )
                    if label not in allowed:
                        invalid["unknown_label"] += 1
        assert rows == files["counts"][split]
        result[split] = dict(
            path=str(path),
            sha256=digest,
            rows=rows,
            distribution=dict(counts),
            invalid=dict(invalid),
            repeated_normalized_inputs=rows - len(keys[split]),
        )
    pairs = [("train", "val"), ("train", "test"), ("val", "test")]
    return dict(
        splits=result,
        manifest_leakage_verified=files["leakage_verified"],
        normalized_input_overlap={f"{a}_{b}": len(keys[a] & keys[b]) for a, b in pairs},
        normalized_context_overlap={f"{a}_{b}": len(contexts[a] & contexts[b]) for a, b in pairs}
        if task == "qa"
        else None,
    )


def main():
    audit_rows = {ds: audit(ds, task) for ds, task in TARGETS.items()}
    print("Data audit complete", flush=True)
    encoder = load_encoder(checkpoint, tokenizer, device="cuda")
    evaluator = LanguageEncoderEvaluator(encoder, DATA, {}, batch_size=8)
    encoder.model.eval()
    scores = {}
    with torch.inference_mode():
        for ds, task in TARGETS.items():
            files = [Path(manifest_rows[ds]["files"]["val"])]
            n = min(CAP, manifest_rows[ds]["counts"]["val"])
            row = dict(
                language=DATASET_LANGUAGE[ds],
                samples=n,
                split_rows=manifest_rows[ds]["counts"]["val"],
            )
            if task == "qa":
                values, _ = evaluator._score_qa(files, [], n, dataset=ds)
                row.update(metrics=values, details=evaluator._details[ds])
            else:
                pred, gold = [], []
                output, label = {
                    "nli": ("nli_logits", "nli_labels"),
                    "paraphrase": ("paraphrase_prob", "para_labels"),
                    "similarity": ("similarity_score", "sim_labels"),
                }[task]
                for batch, take in evaluator._batches(task, files, n):
                    vals = evaluator._forward(batch)[output][:take].float()
                    vals = vals.argmax(-1) if task == "nli" else vals.reshape(-1)
                    pred.extend(vals.cpu().tolist())
                    gold.extend(batch.labels[label][:take].tolist())
                if task == "similarity":
                    p, g = np.array(pred), np.array(gold)
                    row["metrics"] = {
                        "spearman": m.spearman(p, g),
                        "mae": float(np.mean(abs(p - g))),
                    }
                    row["score_bands"] = [
                        dict(
                            low=i / 5,
                            high=(i + 1) / 5,
                            samples=int(mask.sum()),
                            mean_error=float((p - g)[mask].mean()) if mask.any() else None,
                        )
                        for i in range(5)
                        for mask in [(g >= i / 5) & ((g < (i + 1) / 5) if i < 4 else (g <= 1))]
                    ]
                else:
                    labels = 3 if task == "nli" else 2
                    p = [int(v >= 0.5) for v in pred] if task == "paraphrase" else pred
                    row["metrics"] = {
                        "accuracy": m.accuracy(p, gold),
                        "macro_f1": m.macro_f1(p, gold, labels),
                    }
                    row["confusion_gold_rows_prediction_columns"] = [
                        [
                            sum(int(g) == i and j == v for g, v in zip(gold, p))
                            for j in range(labels)
                        ]
                        for i in range(labels)
                    ]
            scores[ds] = row
            print(ds, row["metrics"], flush=True)
    fertility = {
        r["language"]: r["metrics"]
        for r in json.loads(Path("reports/tokenizer/fertility.json").read_text())["datasets"]
    }
    gates = []
    for gate in yaml.safe_load(Path("configs/evaluation/foundation.yaml").read_text())["gates"]:
        ds, lang, metric, target = (gate[k] for k in ("dataset", "language", "metric", "threshold"))
        value = (
            scores[ds]["metrics"][metric]
            if ds in scores
            else (fertility[lang][metric] if ds == "unseen_text" else None)
        )
        margin = (
            None
            if value is None
            else ((value - target) if gate["operator"] == "ge" else (target - value))
        )
        if margin is None:
            assessment = "Missing independent STEM relevance judgments."
        elif ds == "unseen_text":
            assessment = (
                "Fertility is fixed by the tokenizer and the evaluation text. "
                "Recheck with the same protocol after any tokenizer change."
            )
        elif margin < 0:
            assessment = "Validation gap observed. Training feasibility is unmeasured."
        else:
            assessment = (
                "Validation sample meets the numeric target. "
                "Held-out qualification and training feasibility remain unverified."
            )
        gates.append(
            dict(
                **gate,
                observed=value,
                margin=margin,
                assessment=assessment,
                evidence_split="val" if ds in scores else "test" if value is not None else None,
            )
        )
    report = dict(
        task="F04",
        split="val",
        cap_per_dataset=CAP,
        seed=42,
        batch_size=8,
        sampling="existing evaluator streaming order; QA first rows; descriptive nonrandom sample",
        checkpoint=str(checkpoint),
        model_sha256=file_sha256(checkpoint / "model.pt"),
        tokenizer_sha256=file_sha256(tokenizer),
        dataset_manifest_sha256=file_sha256(MANIFEST),
        evaluator_sha256=file_sha256(Path("src/laris/language/evaluation/evaluator.py")),
        torch_version=torch.__version__,
        validation=scores,
        data_audit=audit_rows,
        data_audit_scope=(
            "Exact normalized pair and context overlap within each target dataset. "
            "The test split was scanned for label and split integrity. "
            "Cross-dataset, near-duplicate and pretraining overlap were outside scope."
        ),
        source_artifacts={
            str(path): file_sha256(path)
            for path in (
                Path("reports/tokenizer/fertility.json"),
                Path("reports/retrieval/foundation.json"),
                Path("configs/evaluation/foundation.yaml"),
                Path(__file__),
            )
        },
        validation_sequence_length=encoder.seq_len,
        class_order={
            "nli": ["entailment", "neutral", "contradiction"],
            "paraphrase": ["not_paraphrase", "paraphrase"],
        },
        gate_assessment=gates,
        training_executed=False,
        weights_or_splits_modified=False,
    )
    Path("reports/language_encoder/foundation-error-analysis.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )


if __name__ == "__main__":
    main()
