"""Download a pinned, bounded reading corpus; never add it to training splits."""

import concurrent.futures
import hashlib
import html
import json
import re
import subprocess
from pathlib import Path
from urllib.request import urlopen

ROOT = Path("artifacts/pilots/scientific_nlp").resolve()
IDS = [
    "D18-1360",
    "2020.acl-main.670",
    "D19-1371",
    "N19-1361",
    "2020.emnlp-main.609",
    "2022.findings-emnlp.347",
    "2023.emnlp-main.483",
    "2025.coling-main.573",
    "2026.findings-acl.644",
    "2026.acl-long.669",
    "2026.lrec-1.864",
    "2025.findings-emnlp.631",
    "2026.emnlp-main.2616",
    "2024.sdp-1.3",
    "2024.lrec-main.248",
    "2026.findings-eacl.81",
    "2026.lrec-1.404",
    "2023.acl-short.61",
    "2023.findings-acl.888",
    "2024.findings-acl.8",
]


def acquire(pid):
    url = f"https://aclanthology.org/{pid}/"
    folder = ROOT / "sources"
    folder.mkdir(exist_ok=True)
    page_path, pdf_path, text_path = [folder / f"{pid}.{ext}" for ext in ("html", "pdf", "txt")]
    for path, remote in ((page_path, url), (pdf_path, url.rstrip("/") + ".pdf")):
        if not path.exists():
            with urlopen(remote, timeout=90) as response:
                path.write_bytes(response.read())
    if not pdf_path.read_bytes().startswith(b"%PDF"):
        raise ValueError(f"Not a PDF: {pid}")
    subprocess.run(["pdftotext", str(pdf_path), str(text_path)], check=True)
    page = page_path.read_text()
    title = html.unescape(re.search(r"<title>(.*?)</title>", page, re.S).group(1))
    text = text_path.read_text()
    return {
        "id": pid,
        "title": re.sub("<[^>]+>", "", title).removesuffix(" - ACL Anthology"),
        "url": url,
        "pdf_url": url.rstrip("/") + ".pdf",
        "pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "text_file": str(text_path.relative_to(ROOT)),
        "pages": len(text.split("\f")) - int(text.endswith("\f")),
        "license_links": sorted(set(re.findall(r'https?://creativecommons.org/[^\s"<>]+', page))),
        "use": "local_reading_and_pilot_only_not_training",
    }


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(acquire, IDS))
    (ROOT / "corpus.json").write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    for record in records:
        print(record["id"], record["pages"], record["title"], flush=True)
