#!/usr/bin/env python3
"""
LARIS Documentation & Metadata Validation Tool (Quality Gate)
Validates metadata, unique document IDs, lifecycle statuses, internal link integrity,
ADR cross-references, and governance invariants.
"""

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"

REQUIRED_FIELDS = [
    "document_id",
    "title",
    "document_type",
    "status",
    "version",
    "created_at",
    "updated_at",
    "owner",
    "reviewers",
    "source_of_truth",
    "related_documents",
    "decision_references",
    "change_summary",
]

ALLOWED_STATUSES = {
    "DRAFT",
    "IN_REVIEW",
    "APPROVED",
    "FROZEN",
    "DEPRECATED",
    "ACCEPTED",
    "PROPOSED",
    "REJECTED",
    "SUPERSEDED",
}

ALLOWED_TYPES = {
    "idea",
    "architecture",
    "specification",
    "adr",
    "plan",
    "research",
    "test",
    "report",
    "template",
}

BANNED_BUZZWORDS = [
    r"\bultra-fast\b",
    r"\bsuper-intelligent\b",
    r"\bAI thông minh\b",
]

def parse_front_matter(content: str):
    """Extracts and parses YAML front matter from a markdown file."""
    if not content.startswith("---"):
        return None, "File does not start with YAML front matter ('---')"
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, "Incomplete YAML front matter block (missing closing '---')"
    yaml_text = parts[1]
    try:
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            return None, "Front matter must parse into a key-value dictionary"
        return data, None
    except Exception as e:
        return None, f"YAML parsing error: {e}"

def validate_all_docs():
    errors = []
    warnings = []
    doc_ids = {}
    validated_count = 0

    md_files = sorted(DOCS_DIR.rglob("*.md"))
    if not md_files:
        errors.append("No markdown documentation files found in docs/")
        return errors, warnings, 0

    for file_path in md_files:
        rel_path = file_path.relative_to(REPO_ROOT)
        content = file_path.read_text(encoding="utf-8")

        meta, err = parse_front_matter(content)
        if err:
            errors.append(f"[{rel_path}] {err}")
            continue

        validated_count += 1

        # Check required fields
        for field in REQUIRED_FIELDS:
            if field not in meta:
                errors.append(f"[{rel_path}] Missing required metadata field: '{field}'")

        # Check document_id uniqueness
        doc_id = meta.get("document_id")
        if doc_id:
            if doc_id in doc_ids:
                errors.append(
                    f"[{rel_path}] Duplicate document_id '{doc_id}' "
                    f"(first seen in {doc_ids[doc_id]})"
                )
            else:
                doc_ids[doc_id] = rel_path

        # Check document_type
        doc_type = meta.get("document_type")
        if doc_type and doc_type not in ALLOWED_TYPES:
            errors.append(
                f"[{rel_path}] Invalid document_type '{doc_type}'. "
                f"Allowed: {sorted(ALLOWED_TYPES)}"
            )

        # Check status
        status = meta.get("status")
        if status and status not in ALLOWED_STATUSES:
            errors.append(
                f"[{rel_path}] Invalid status '{status}'. "
                f"Allowed: {sorted(ALLOWED_STATUSES)}"
            )

        # Check that no document is prematurely marked FROZEN without formal log
        if status == "FROZEN":
            decision_log = (DOCS_DIR / "DECISION_LOG.md").read_text(encoding="utf-8")
            if doc_id not in decision_log:
                errors.append(
                    f"[{rel_path}] Document marked FROZEN but lacks "
                    f"corresponding entry in docs/DECISION_LOG.md"
                )

        # Check related_documents existence
        related_docs = meta.get("related_documents", [])
        if isinstance(related_docs, list):
            for ref in related_docs:
                target_path = REPO_ROOT / ref
                if not target_path.exists():
                    errors.append(
                        f"[{rel_path}] Target in related_documents does not exist: '{ref}'"
                    )

        # Check decision_references existence
        decision_refs = meta.get("decision_references", [])
        if isinstance(decision_refs, list):
            for adr_ref in decision_refs:
                matching_adrs = list((DOCS_DIR / "adr").glob(f"*{adr_ref}*.md"))
                if not matching_adrs and adr_ref.startswith("ADR-"):
                    errors.append(
                        f"[{rel_path}] Referenced ADR does not exist in docs/adr/: '{adr_ref}'"
                    )

        # Check internal markdown file links: [label](path_or_file_uri)
        link_matches = re.findall(
            r'\[([^\]]+)\]\((file:///home/thientn204/laris/([^)]+)|([^)]+))\)',
            content,
        )
        for match in link_matches:
            # group 2 is relative path from file:///home/thientn204/laris/, group 3 is other link
            link_target = match[2] if match[2] else match[3]
            if (
                link_target.startswith("#")
                or link_target.startswith("http://")
                or link_target.startswith("https://")
            ):
                continue
            # Strip anchors e.g. path#section
            clean_link = link_target.split("#")[0]
            if not clean_link:
                continue

            # Resolve relative or root path
            if clean_link.startswith("/"):
                target = Path(clean_link)
            else:
                target = (file_path.parent / clean_link).resolve()

            if not target.exists():
                # Try repo root relative
                target_from_root = (REPO_ROOT / clean_link).resolve()
                if not target_from_root.exists():
                    errors.append(f"[{rel_path}] Broken internal link '{link_target}'")

        # Check for empty marketing buzzwords
        for buzz_regex in BANNED_BUZZWORDS:
            if re.search(buzz_regex, content, re.IGNORECASE):
                warnings.append(
                    f"[{rel_path}] Found banned marketing buzzword matching regex: '{buzz_regex}'"
                )

    return errors, warnings, validated_count

def main():
    print("=" * 60)
    print("LARIS Documentation & Metadata Validation Quality Gate")
    print("=" * 60)

    errors, warnings, count = validate_all_docs()

    print(f"Scanned and parsed {count} documentation files.\n")

    if warnings:
        print(f"--- WARNINGS ({len(warnings)}) ---")
        for w in warnings:
            print(f"  [WARN] {w}")
        print()

    if errors:
        print(f"--- FAILED VALIDATION CHECKS ({len(errors)}) ---")
        for e in errors:
            print(f"  [ERROR] {e}")
        print("\nQuality Gate: REJECTED (Errors found)")
        sys.exit(1)

    print("--- SUCCESS ---")
    print("All documents passed metadata completeness, uniqueness, lifecycle status,")
    print("ADR cross-referencing, and link integrity checks.")
    print("Quality Gate: PASSED")
    sys.exit(0)

if __name__ == "__main__":
    main()
