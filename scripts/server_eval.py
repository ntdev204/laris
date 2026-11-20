#!/usr/bin/env python3
"""The cognitive evaluation of T172 repeated through the server (T243, SR-S8, SR-K7). Standard library only.

    python3 scripts/server_eval.py --base https://localhost:38443 --insecure \\
        --admin-key KEY --user-key KEY --label optional --out reports/server/T243-optional.json

It seeds the main brain of a running stack with the sources and claims of ``configs/cognitive-eval.json`` through the
admin routes (the write gate decides, not this script), then asks the same questions through ``/v1/laris/chat`` and
records, for each one: the decider's action and rule, the stages that ran, whether the model was called, the evidence
entries, the time, and whether every sentence of the answer is one of the accepted claims (a vocabulary check on the
answer text, the same kind of measure as T172).

It measures the system, not a model: the same run with a different backend changes only the free answers. Inference
only; nothing here trains. The stack's grounding mode is set by the caller (``LARIS_PIPELINE_GROUNDING``) and recorded
as ``--label``.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL = "2"


class Client:
    def __init__(self, base: str, insecure: bool, cacert: str | None) -> None:
        self.base = base.rstrip("/")
        context = ssl.create_default_context(cafile=cacert)
        if insecure:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.context = context

    def post(self, path: str, key: str, body: dict, timeout: float = 600.0) -> str:
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "X-Laris-Protocol": PROTOCOL,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout, context=self.context) as reply:
            return reply.read().decode()


def events(raw: str) -> list[dict]:
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
            try:
                out.append(json.loads(line[5:]))
            except ValueError:
                pass
    return out


def sentences(text: str) -> list[str]:
    text = re.sub(r"\[\[[^\]]*\]\]", "", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def read_turn(raw: str) -> dict:
    steps, evidence, text = [], [], ""
    for event in events(raw):
        laris = event.get("laris") or {}
        steps.extend(laris.get("steps") or [])
        evidence.extend(laris.get("evidence") or [])
        for choice in event.get("choices") or []:
            text += (choice.get("delta") or {}).get("content") or ""
    decision = next((s["decision"] for s in steps if s.get("decision")), None)
    return {"steps": steps, "evidence": evidence, "text": text, "decision": decision}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--admin-key", required=True)
    parser.add_argument("--user-key", required=True)
    parser.add_argument("--label", required=True, help="the grounding mode the stack runs (recorded, not set)")
    parser.add_argument("--config", default=str(ROOT / "configs/cognitive-eval.json"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--insecure", action="store_true", help="do not verify the certificate (local stack)")
    parser.add_argument("--cacert")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text())
    client = Client(args.base, args.insecure, args.cacert)
    admin = lambda path, body: json.loads(client.post(path, args.admin_key, body))  # noqa: E731

    seeded = {"sources": [], "claims": []}
    for source in config["sources"]:
        reply = admin(
            "/v1/admin/brain/sources",
            {
                "title": source["title"],
                "kind": "document",
                "identifier": source["identifier"],
                "text": source["text"],
                "metadata": {"kind": "verified", "registry": "server-eval-fixture"},
            },
        )
        seeded["sources"].append(reply.get("decision"))
    for claim in config["claims"]:
        reply = admin(
            "/v1/admin/brain/claims",
            {"statement": claim["statement"], "quote": claim["statement"], "requested": "sourced", "source": claim["source"]},
        )
        seeded["claims"].append(reply.get("decision"))
    accepted = [c["statement"] for c in config["claims"]]
    accepted_words = [words(c) for c in accepted]

    rows = []
    for question in config["questions"]:
        body = {"stream": True, "messages": [{"role": "user", "content": question["text"]}]}
        started = time.monotonic()
        try:
            turn = read_turn(client.post("/v1/laris/chat", args.user_key, body))
            error = None
        except Exception as exc:  # recorded, never hidden
            turn, error = {"steps": [], "evidence": [], "text": "", "decision": None}, str(exc)[:200]
        seconds = round(time.monotonic() - started, 2)
        stages = [s.get("stage") for s in turn["steps"]]
        # a sentence is "inside the accepted set" when its words are all words of one accepted claim
        outside = [s for s in sentences(turn["text"]) if not any(words(s) <= w for w in accepted_words)]
        decision = turn["decision"] or {}
        rows.append(
            {
                "id": question["id"],
                "expect": question["expect"],
                "action": decision.get("action"),
                "rule": decision.get("rule"),
                "stages": stages,
                "model_stage_ran": "model" in stages,
                "server_evidence": sum(1 for e in turn["evidence"] if e.get("origin") == "server"),
                "answer_chars": len(turn["text"]),
                "sentences_outside_accepted_claims": len(outside),
                "seconds": seconds,
                "error": error,
            }
        )

    answerable = [r for r in rows if r["expect"] == "answer"]
    unanswerable = [r for r in rows if r["expect"] == "abstain"]
    abstained = [r for r in rows if r["action"] == "abstain" or "no_evidence" in json.dumps(r["stages"])]
    report = {
        "task": "T243",
        "label": args.label,
        "seeded": seeded,
        "questions": len(rows),
        "answerable": {
            "total": len(answerable),
            "answered_from_brain": sum(1 for r in answerable if r["action"] == "answer" and r["server_evidence"] > 0),
            "model_called": sum(1 for r in answerable if r["model_stage_ran"]),
            "with_sentences_outside_accepted_claims": sum(1 for r in answerable if r["sentences_outside_accepted_claims"]),
        },
        "unanswerable": {
            "total": len(unanswerable),
            "abstained": sum(1 for r in unanswerable if r in abstained),
            "reached_the_model_or_answered": sum(1 for r in unanswerable if r not in abstained),
            "with_sentences_outside_accepted_claims": sum(1 for r in unanswerable if r["sentences_outside_accepted_claims"]),
        },
        "errors": sum(1 for r in rows if r["error"]),
        "rows": rows,
        "does_not_show": [
            "Any capability of the model: the numbers are the pipeline's behaviour on seven hand-made questions.",
            "Meaning: 'outside the accepted claims' compares vocabulary; a rearrangement that keeps every word is not seen.",
            "Free answers (optional grounding) are not checked against any source; they are the model's own text.",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("label", "answerable", "unanswerable", "errors")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
