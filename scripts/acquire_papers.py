#!/usr/bin/env python3
"""Propose and fetch the journal papers of T285 and record why each is admitted or refused.

    python scripts/acquire_papers.py propose   # OpenAlex: candidates per configured venue
    python scripts/acquire_papers.py acquire   # Crossref + Europe PMC for the approved DOIs

Settings: section `papers` of `configs/admissible-sources.json` (venues, selection, licences,
claim filter, approved DOIs). `propose` writes `candidates.json` (the most cited CC BY reviews
with a PMC copy, per venue, in the configured years; the order is fixed: citations, then DOI);
the DOIs to take are then written into `papers.approved` of the configuration. `acquire` fetches,
for each approved DOI, Crossref's record and the Europe PMC JATS full text, keeps both responses
byte for byte, checks them (`laris.research.knowledge.papers`) and writes `provenance.json` with
each paper's verdict, the reason when refused, and the SHA-256 of every response.

Network: api.openalex.org (propose), api.crossref.org and www.ebi.ac.uk (acquire), at
acquisition time only. The snapshot build (`scripts/build_stem_brain.py build --sources ...`) and
evaluation runs read the kept files and stay offline. No contact detail is sent.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from laris.research.knowledge import papers  # noqa: E402
from laris.research.knowledge.build import sha256  # noqa: E402


def fetch(url: str, agent: str, kept: Optional[Path] = None) -> Optional[bytes]:
    """The response body, or None on 404/410. A response already kept in `kept` is read back
    instead of fetched again (the same bytes, so the same hash). Timeouts and 429/5xx are
    retried; other failures stop the run."""
    if kept is not None and kept.exists():
        return kept.read_bytes()
    request = urllib.request.Request(url, headers={"User-Agent": agent})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310 (configured https)
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(10 * (attempt + 1))
                continue
            raise
        except (TimeoutError, urllib.error.URLError):
            if attempt < 3:
                time.sleep(10 * (attempt + 1))
                continue
            raise
    return None


def safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in name)


def cmd_propose(config: Dict[str, Any], out: Path) -> int:
    settings = config["papers"]
    choice = settings["proposal"]
    base = settings["registries"]["openalex"]
    agent = settings["user_agent"]
    (out / "openalex").mkdir(parents=True, exist_ok=True)
    families = {name.rsplit("-", 1)[0] for name in config["classes"]["journal_paper"]["licences"]}
    candidates = []
    for venue in settings["venues"]:
        issns = "|".join(venue["issns"])
        query = {
            "filter": (
                f"primary_location.source.issn:{issns},type:{choice['type']},"
                f"publication_year:{choice['from_year']}-{choice['to_year']},"
                "ids.pmcid:!null,is_retracted:false,best_oa_location.license:cc-by|cc0"
            ),
            "sort": "cited_by_count:desc",
            "per-page": str(int(choice["per_venue"]) * 3),
            "select": "doi,title,ids,cited_by_count,publication_year,best_oa_location,is_retracted",
        }
        url = base + "?" + urllib.parse.urlencode(query)
        raw = fetch(url, agent)
        if raw is None:
            raise SystemExit(f"OpenAlex returned nothing for {venue['name']}")
        (out / "openalex" / f"{safe(venue['issn_l'])}.json").write_bytes(raw)
        rows = []
        for work in json.loads(raw)["results"]:
            licence = (work.get("best_oa_location") or {}).get("license") or ""
            pmcid = ((work.get("ids") or {}).get("pmcid") or "").rsplit("/", 1)[-1]
            if not work.get("doi") or not pmcid or work.get("is_retracted"):
                continue
            if licence not in families:  # OpenAlex names the family without a version
                continue
            rows.append(
                {
                    "doi": papers.normalise_doi(work["doi"]),
                    "pmcid": pmcid if pmcid.upper().startswith("PMC") else f"PMC{pmcid}",
                    "title": work.get("title") or "",
                    "venue": venue["issn_l"],
                    "cited_by_count": int(work.get("cited_by_count") or 0),
                    "year": work.get("publication_year"),
                }
            )
        rows.sort(key=lambda r: (-r["cited_by_count"], r["doi"]))
        candidates.extend(rows[: int(choice["per_venue"])])
        print(f"{venue['name']}: {min(len(rows), int(choice['per_venue']))} of {len(rows)}")
        time.sleep(1)
    record = {"proposal": choice, "candidates": candidates}
    (out / "candidates.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {(out / 'candidates.json').relative_to(ROOT)} ({len(candidates)} candidates)")
    return 0


def cmd_acquire(config: Dict[str, Any], out: Path) -> int:
    settings = config["papers"]
    agent = settings["user_agent"]
    classes = config["classes"]
    for sub in ("crossref", "jats"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    record: Dict[str, Any] = {"papers": [], "refused": {}, "files": {}}
    for entry in settings["approved"]:
        doi, pmcid = papers.normalise_doi(entry["doi"]), entry["pmcid"]
        path = out / "crossref" / f"{safe(doi)}.json"
        cr_raw = fetch(settings["registries"]["crossref"] + urllib.parse.quote(doi), agent, path)
        if cr_raw is not None:
            path.write_bytes(cr_raw)
            record["files"][str(path.relative_to(ROOT))] = sha256(cr_raw)
        verdict = papers.check_crossref(doi, cr_raw, settings, classes)
        jats = None
        jats_sha = ""
        if verdict.admitted:
            path = out / "jats" / f"{safe(pmcid)}.xml"
            jats_raw = fetch(settings["registries"]["full_text"].format(pmcid=pmcid), agent, path)
            if jats_raw is not None:
                path.write_bytes(jats_raw)
                jats_sha = sha256(jats_raw)
                record["files"][str(path.relative_to(ROOT))] = jats_sha
                try:
                    jats = papers.parse_jats(jats_raw)
                except (ValueError, SyntaxError):
                    jats = None
            papers.check_full_text(verdict, jats, settings, classes)
        row = {
            "doi": doi,
            "pmcid": pmcid,
            "admitted": verdict.admitted,
            "reason": verdict.reason,
            "detail": verdict.detail,
            "venue": verdict.admission.get("venue"),
            "admission": verdict.admission if verdict.admitted else None,
            "crossref_sha256": sha256(cr_raw) if cr_raw is not None else None,
            "jats_sha256": jats_sha or None,
        }
        record["papers"].append(row)
        if not verdict.admitted:
            record["refused"][verdict.reason] = record["refused"].get(verdict.reason, 0) + 1
        print(f"{'ok' if verdict.admitted else 'refused ' + str(verdict.reason)} {doi}", flush=True)
    admitted = sum(1 for r in record["papers"] if r["admitted"])
    record["counts"] = {"approved": len(settings["approved"]), "admitted": admitted}
    (out / "provenance.json").write_text(
        json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(record["counts"] | {"refused": record["refused"]}))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["propose", "acquire"])
    parser.add_argument("--config", default=str(ROOT / "configs" / "admissible-sources.json"))
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out = ROOT / config["papers"]["data_dir"]
    out.mkdir(parents=True, exist_ok=True)
    if args.command == "propose":
        return cmd_propose(config, out)
    return cmd_acquire(config, out)


if __name__ == "__main__":
    sys.exit(main())
