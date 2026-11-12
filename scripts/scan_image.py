#!/usr/bin/env python3
"""Fail when a Docker image holds policy, weights, data or secrets.

    python scripts/scan_image.py laris-api laris-model

The image's file system is exported and listed (nothing is run inside it). Forbidden: the policy
tree (`.laris/`, `LARIS.md`), `.env` files, model weights and checkpoints, datasets and arrays,
databases, key and certificate files, and git history.
"""

import fnmatch
import subprocess
import sys
import tarfile
from typing import List

FORBIDDEN = (
    "*/.laris/*", "*/LARIS.md", "*/.env", "*/.env.*", "*/.git/*",
    "*.pt", "*.pth", "*.ckpt", "*.safetensors", "*.gguf", "*.npy", "*.npz", "*.parquet",
    "*.sqlite", "*.db", "*.secret", "*.key", "*.pem",
    "*/app/data/*", "*/app/artifacts/*", "*/app/experiments/*", "*/models/*.*",
)  # fmt: skip
# files inside installed packages that merely share an extension (test data of a dependency)
ALLOWED_PARTS = ("site-packages/", "dist-packages/", "/usr/share/", "/usr/lib/", "/etc/ssl/")


def listing(image: str) -> List[str]:
    created = subprocess.run(
        ["docker", "create", image], check=True, capture_output=True, text=True
    ).stdout.strip()
    try:
        export = subprocess.Popen(["docker", "export", created], stdout=subprocess.PIPE)
        assert export.stdout is not None
        with tarfile.open(fileobj=export.stdout, mode="r|") as tar:
            names = ["/" + m.name for m in tar if m.isfile() or m.isdir()]
        export.wait()
        return names
    finally:
        subprocess.run(["docker", "rm", "-f", created], capture_output=True)


def violations(names: List[str]) -> List[str]:
    found = []
    for name in names:
        if any(part in name for part in ALLOWED_PARTS):
            continue
        if any(fnmatch.fnmatch(name, pattern) for pattern in FORBIDDEN):
            found.append(name)
    return found


def main(images: List[str]) -> int:
    status = 0
    for image in images:
        names = listing(image)
        bad = violations(names)
        print(f"{image}: {len(names)} paths scanned, {len(bad)} forbidden")
        for name in bad[:20]:
            print(f"  FORBIDDEN {name}")
        status |= 1 if bad else 0
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) if len(sys.argv) > 1 else 2)
