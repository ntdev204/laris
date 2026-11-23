#!/usr/bin/env python3
"""Extracts the CIAAW abridged standard atomic weights (T276 follow-up) into the solver's data file.

    curl -o abridged.htm https://www.ciaaw.org/abridged-atomic-weights.htm
    python scripts/extract_atomic_weights.py abridged.htm \
        src/laris/model/solver/data/ciaaw-abridged-atomic-weights.tsv

The output is a tab-separated table (Z, symbol, element, value, uncertainty, notes) under a header
that names the source, its release and the SHA-256 of the page it came from. An element without a
standard atomic weight ("—" on the page) keeps empty value and uncertainty. Nothing is computed:
the digits are those CIAAW prints. Afterwards put the file's SHA-256 in
`model_service.solver_atomic_weights_sha256`.
"""

import hashlib
import html
import re
import sys
from pathlib import Path

URL = "https://www.ciaaw.org/abridged-atomic-weights.htm"


def main(argv):
    source, target = Path(argv[0]), Path(argv[1])
    raw = source.read_bytes()
    page = raw.decode("utf-8")
    release = re.search(r"Abridged Standard Atomic Weights (\d{4})", page)
    if not release:
        raise SystemExit("the page names no release year")
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [
            " ".join(html.unescape(re.sub(r"<[^>]+>", "", c)).split())
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        if len(cells) != 5 or not cells[0].isdigit():
            continue
        z, symbol, element, weight, notes = cells
        match = re.fullmatch(r"([\d.]+) ± ([\d.]+)", weight)
        if match:
            value, uncertainty = match.groups()
        elif weight in ("—", ""):
            value = uncertainty = ""
        else:
            raise SystemExit(f"unexpected weight for Z={z}")
        rows.append("\t".join((z, symbol, element, value, uncertainty, notes)))
    if len(rows) != 118:
        raise SystemExit(f"expected 118 elements, found {len(rows)}")
    header = [
        f"# CIAAW Abridged Standard Atomic Weights {release.group(1)} (IUPAC Commission on Isotopic"
        " Abundances and Atomic Weights)",
        f"# source: {URL}",
        f"# source_sha256: {hashlib.sha256(raw).hexdigest()}",
        "# based on: Atomic Weights 2021 (Prohaska et al., Pure Appl. Chem. 94 (2022) 573-600),"
        " with the 2024 revisions of Gd, Lu and Zr",
        "# columns: Z, symbol, element, value, uncertainty (both g/mol, as printed), notes",
    ]
    target.write_text("\n".join(header + rows) + "\n", encoding="utf-8")
    print(target, hashlib.sha256(target.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
