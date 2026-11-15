"""Bounded, resumable acquisition of open-access scientific PDFs from the PMC Open Access S3 bucket
(stage 3).

For each article the publisher PDF is kept together with the JATS XML and plain text (a *silver*
text reference, not gold) and the article's own metadata. An article is kept only when its metadata
declares one of the licence codes listed in ``configs/data/ocr_sources.yaml``. Sampling is
deterministic (seeded id prefixes) and stops at a hard byte budget. Nothing here trains or fits a
model.
"""

import hashlib
import json
import random
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import yaml

from laris.research.corpus.acquisition.common import (
    RAW_DIR,
    REPO_ROOT,
    DatasetEntry,
    _finalize_entry,
    compute_sha256,
)

PMC_ID = "PMC-OA-PDF"
OCR_CONFIG_PATH = REPO_ROOT / "configs" / "data" / "ocr_sources.yaml"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
SILVER_SUFFIXES = (".txt", ".xml")


def load_pmc_config(path: Optional[Path] = None) -> Dict[str, Any]:
    with open(path or OCR_CONFIG_PATH, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    return {
        "user_agent": config["user_agent"],
        "timeout": config["timeout_seconds"],
        **config["pmc"],
    }


def _get(url: str, config: Dict[str, Any], method: str = "GET") -> Tuple[bytes, Any]:
    request = urllib.request.Request(
        url, method=method, headers={"User-Agent": config["user_agent"]}
    )
    with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
        return (b"" if method == "HEAD" else response.read()), response.headers


def sample_prefixes(config: Dict[str, Any]) -> List[str]:
    """Deterministic shuffled list of 'PMC<digits>' listing prefixes."""
    low, high = int(config["prefix_min"]), int(config["prefix_max"])
    values = list(range(low, high + 1))
    random.Random(int(config["seed"])).shuffle(values)
    width = int(config["prefix_digits"])
    return [f"PMC{v:0{width}d}" for v in values]


def list_articles(prefix: str, config: Dict[str, Any]) -> List[str]:
    """Article folders ('PMC123.1') under an id prefix, one request per 1000 folders."""
    articles: List[str] = []
    token = ""
    while True:
        query = {"list-type": "2", "prefix": prefix, "delimiter": "/", "max-keys": "1000"}
        if token:
            query["continuation-token"] = token
        body, _ = _get(f"{config['endpoint']}/?{urllib.parse.urlencode(query)}", config)
        root = ET.fromstring(body)
        articles += [
            p.findtext(f"{S3_NS}Prefix", "").rstrip("/")
            for p in root.findall(f"{S3_NS}CommonPrefixes")
        ]
        token = (
            root.findtext(f"{S3_NS}NextContinuationToken", "")
            if root.findtext(f"{S3_NS}IsTruncated") == "true"
            else ""
        )
        if not token:
            return [a for a in articles if a]


def fetch_article(
    article: str, config: Dict[str, Any], dest_root: Path
) -> Optional[Dict[str, Any]]:
    """Downloads one article when its licence, size and flags qualify.

    Returns its index record, or None when it does not qualify.
    """
    base = f"{config['endpoint']}/{article}/{article}"
    folder = dest_root / article
    record_path = folder / "record.json"
    if record_path.is_file():
        record: Dict[str, Any] = json.loads(record_path.read_text(encoding="utf-8"))
        return record
    try:
        meta = json.loads(_get(f"{base}.json", config)[0])
        if meta.get("license_code") not in config["licenses"] or not meta.get("is_pmc_openaccess"):
            return None
        if config.get("skip_manuscripts") and meta.get("is_manuscript"):
            return None
        _, headers = _get(f"{base}.pdf", config, "HEAD")
        size = int(headers.get("Content-Length", 0))
        if not config["min_pdf_kb"] * 1024 <= size <= config["max_pdf_mb"] * 1024 * 1024:
            return None
        folder.mkdir(parents=True, exist_ok=True)
        pdf_bytes, _ = _get(f"{base}.pdf", config)
        (folder / f"{article}.pdf").write_bytes(pdf_bytes)
        for suffix in SILVER_SUFFIXES:
            try:
                (folder / f"{article}{suffix}").write_bytes(_get(f"{base}{suffix}", config)[0])
            except urllib.error.HTTPError:
                pass
    except (urllib.error.URLError, OSError, ValueError):
        return None
    record = {
        "article": article,
        "pmcid": meta.get("pmcid"),
        "title": meta.get("title"),
        "doi": meta.get("doi"),
        "license_code": meta.get("license_code"),
        "is_historical_ocr": bool(meta.get("is_historical_ocr")),
        "pdf_bytes": len(pdf_bytes),
        "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
    }
    record_path.write_text(json.dumps(record), encoding="utf-8")
    return record


def _iter_batches(prefixes: List[str], config: Dict[str, Any]) -> Iterator[List[str]]:
    for prefix in prefixes:
        try:
            articles = list_articles(prefix, config)
        except (urllib.error.URLError, OSError, ET.ParseError):
            continue
        if articles:
            yield articles


def acquire_pmc_pdf(config_path: Optional[Path] = None) -> DatasetEntry:
    """Acquires a licence-filtered, seed-sampled set of PMC OA PDFs up to the byte budget."""
    config = load_pmc_config(config_path)
    print(f"\n--- Acquiring {PMC_ID} (<= {config['budget_gb']} GB) ---")
    dest_dir = RAW_DIR / "pmc_oa_pdf"
    dest_dir.mkdir(parents=True, exist_ok=True)
    budget = int(float(config["budget_gb"]) * 1e9)
    kept: Dict[str, Dict[str, Any]] = {}
    total = historical = 0
    for existing in dest_dir.glob("*/record.json"):
        rec = json.loads(existing.read_text(encoding="utf-8"))
        kept[rec["article"]] = rec
        total += rec["pdf_bytes"]
        historical += rec["is_historical_ocr"]
    done = False
    with ThreadPoolExecutor(max_workers=int(config["workers"])) as pool:
        for articles in _iter_batches(sample_prefixes(config), config):
            latest: Dict[str, str] = {}
            for article in articles:  # keep only the newest version of each PMCID
                base, _, version = article.partition(".")
                if base not in latest or int(version or 0) > int(
                    latest[base].partition(".")[2] or 0
                ):
                    latest[base] = article
            known = {a.partition(".")[0] for a in kept}
            todo = [a for a in latest.values() if a.partition(".")[0] not in known]
            for record in pool.map(lambda a: fetch_article(a, config, dest_dir), todo):
                if record is None:
                    continue
                if record["is_historical_ocr"] and historical >= config[
                    "keep_historical_ocr_fraction"
                ] * (len(kept) + 1):
                    (dest_dir / record["article"] / "record.json").unlink(missing_ok=True)
                    for file in (dest_dir / record["article"]).glob("*"):
                        file.unlink()
                    (dest_dir / record["article"]).rmdir()
                    continue
                kept[record["article"]] = record
                total += record["pdf_bytes"]
                historical += record["is_historical_ocr"]
                if total >= budget:
                    done = True
                    break
            print(f"  [PMC] {len(kept):,} PDFs, {total / 1e9:.2f} GB")
            if done:
                break
    index = dest_dir / "index.jsonl"
    with open(index, "w", encoding="utf-8") as handle:
        for article in sorted(kept):
            handle.write(json.dumps(kept[article]) + "\n")
    size = sum(f.stat().st_size for f in dest_dir.rglob("*") if f.is_file())
    records = [
        {
            "filename": "index.jsonl",
            "bytes": index.stat().st_size,
            "sample_count": len(kept),
            "sha256": compute_sha256(index),
        }
    ]
    return _finalize_entry(
        dataset_id=PMC_ID,
        name=config["name"],
        version="pmc-oa-opendata (seeded sample)",
        source_url="https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/",
        license_name=" / ".join(config["licenses"]) + " (per article)",
        license_approved=True,
        language="English (mixed)",
        sample_unit="Scientific article PDF with JATS XML and text (silver reference)",
        expected=f">= 1,000 PDFs within {config['budget_gb']} GB",
        dest_dir=dest_dir,
        records=records,
        size=size,
        rows=len(kept),
        complete=bool(kept),
        min_rows=1000,
        notes=(
            f"{config['notes']} Seed {config['seed']}; {historical} of {len(kept)} are "
            "historical scans (degraded stratum). Stage-3 input documents; OCR text and layout "
            "gold still need D05 (T105). Not a training run."
        ),
    )
