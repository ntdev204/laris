"""Static checks of the Docker build inputs; they need no Docker daemon."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API = (ROOT / "docker" / "api.Dockerfile").read_text(encoding="utf-8")
MODEL = (ROOT / "docker" / "model.Dockerfile").read_text(encoding="utf-8")
IGNORE = [
    line.strip()
    for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#")
]


def test_the_build_context_leaves_out_policy_weights_data_and_secrets():
    for needed in (".laris", "LARIS.md", ".env", "data", "artifacts", ".git", "**/*.safetensors",
                   "**/*.pt", "**/*.ckpt", "**/*.sqlite", "**/*.key"):  # fmt: skip
        assert needed in IGNORE, needed


def test_images_copy_only_source_and_configs_and_run_as_a_non_root_user():
    for text in (API, MODEL):
        copies = re.findall(r"^COPY (?:--\S+ )*(\S+) ", text, re.M)
        assert set(copies) <= {"pyproject.toml", "src", "configs", "/wheels"}, copies
        assert re.search(r"^USER 10001$", text, re.M)
        assert "ENTRYPOINT" in text and "HEALTHCHECK" in text
        assert not re.search(r"(?i)(password|secret|api_key)\s*=", text)
    assert '".[server]"' in API and "ARG LARIS_EXTRAS=model,gpu" in MODEL
    assert "training" not in MODEL.split("ARG LARIS_EXTRAS=")[1].split("\n")[0]  # inference only
    assert "nvidia/cuda" in MODEL and "slim" in API


def test_configs_in_the_image_are_free_of_secrets_and_policy():
    configs = list((ROOT / "configs").rglob("*"))
    assert configs and all(p.suffix in ("", ".yaml", ".yml", ".md") for p in configs if p.is_file())


def test_the_image_scanner_flags_policy_weights_and_data_but_not_installed_packages():
    path = ROOT / "scripts" / "scan_image.py"
    spec = importlib.util.spec_from_file_location("scan_image", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clean = ["/app/configs/default.yaml", "/usr/local/lib/python3.12/site-packages/numpy/x.npy"]
    dirty = ["/app/.laris/rules/a.md", "/app/LARIS.md", "/app/.env", "/models/w.safetensors",
             "/app/data/raw.parquet", "/data/laris-server.db"]  # fmt: skip
    assert module.violations(clean) == []
    assert module.violations(clean + dirty) == dirty
