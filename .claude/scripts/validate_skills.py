#!/usr/bin/env python3
"""Validate the research-workspace skills, CLAUDE.md and project memory.

Usage:
    python3 validate_skills.py <project_root>

Prints one line per check in the form  STATUS | file | check | detail
where STATUS is PASS, FAIL or WARN, then prints totals and exits with
status 1 if any check FAILs. Uses PyYAML when it is installed and a
simple key: value parser for the frontmatter otherwise.

Two layouts are detected automatically from <project_root>:
  project  <root>/.claude/skills exists. Full checks, including the
           @.claude/project-memory imports (E) and project-memory files (F).
  global   <root>/.claude/skills is absent and <root>/skills exists
           (e.g. ~/.claude). Checks E imports and F are skipped with a SKIP
           line, and check B scans only CLAUDE.md, skills/ and research-kit/.
"""

import os
import re
import sys

try:
    import yaml
except ImportError:  # PyYAML is optional
    yaml = None


ALLOWED_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"}
ALLOWED_EFFORTS = {"low", "medium", "high"}
FRONTMATTER_KEYS = ["name", "description", "model", "effort"]
KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REQUIRED_HEADINGS = [
    "## Purpose",
    "## When to use / When NOT to use",
    "## Inputs to confirm before starting",
    "## Model & Effort",
    "## Workflow",
    "## Honesty and verification rules",
    "## Output format",
    "## Handoffs",
    "## Quality checklist",
]
MODEL_EFFORT_TERMS = ["Recommended model", "Effort", "Rationale", "Escalate", "De-escalate"]
VIETNAMESE_REPLY_RULE = "Reply to the user in Vietnamese"
RELATIVE_LINK = re.compile(r"\]\((references/[^)\s]+\.md)\)")
HAIKU_DELEGATION = 'model: "haiku"'

VI_EXAMPLE_BLOCK = re.compile(r"<!-- vi-example:start -->.*?<!-- vi-example:end -->", re.DOTALL)
ALLOWED_PROPER_NAME = "Thiện"
VI_LATIN_CHARS = set("ăâđêôơưĂÂĐÊÔƠƯàáãèéìíòóõùúýÀÁÃÈÉÌÍÒÓÕÙÚÝ")

# The heading in CLAUDE.md carries a suffix, "(model -> effort)", so match by prefix.
ROUTING_HEADING_PREFIX = "### 6.1 Skill routing table"
ROUTING_COLUMNS = ["#", "Skill", "Model", "Effort", "Use for"]
ROUTING_ROW_COUNT = 15

CLAUDE_TERMS = [
    "Language policy",
    "Built-in skill integration",
    "Writing output routing",
    "Project memory policy",
    "Escalation policy",
    "Model policy",
]
CLAUDE_REPLY_RULE = "ALWAYS reply to the user in Vietnamese"
CLAUDE_MAX_LINES = 200
IMPORTS = [
    "project-context.md",
    "research-state.md",
    "notation-and-conventions.md",
    "decisions-log.md",
    "verified-references.md",
    "open-questions.md",
]

# Terms that must appear inside the "## Workflow" section of each skill.
WORKFLOW_TERMS = {
    "literature-review": ["deep-research"],
    "scientific-writing": [
        "docx",
        "LaTeX",
        "`pdf`",
        "`docs`",
        "Compile check",
        "Choose output route (docx or LaTeX) from document type and venue, record it in the format spec block",
    ],
    "grant-proposal": ["docx"],
    "research-roadmap": ["docx"],
    "research-presentation": ["pptx"],
    "experiment-and-validation": ["xlsx", "Haiku"],
}
# Terms that must appear anywhere in the file of each skill.
FILE_TERMS = {
    "scientific-writing": ["% UNVERIFIED"],
    "reproducible-code": ["Haiku"],
}

counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
ROOT = ""
LAYOUT = "project"  # "project" or "global", set in main()
SKILLS_REL = ".claude/skills"  # skills folder relative to ROOT, set in main()


def report(status, where, check, detail=""):
    counts[status] += 1
    print(f"{status} | {where} | {check} | {detail}")


def verdict(ok, where, check, detail_ok="", detail_bad=""):
    report("PASS" if ok else "FAIL", where, check, detail_ok if ok else detail_bad)


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def read_text(path):
    with open(path, encoding="utf-8-sig") as handle:
        return handle.read()


def load(path, where, check):
    """Read a file, reporting a FAIL and returning None if it cannot be read."""
    try:
        return read_text(path)
    except (OSError, UnicodeDecodeError) as exc:
        report("FAIL", where, check, f"cannot read: {exc}")
        return None


def split_frontmatter(text):
    """Return (frontmatter_block, body, error). The block is None when the markers are missing."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text, "file does not start with ---"
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            return "\n".join(lines[1:end]), "\n".join(lines[end + 1:]), ""
    return None, text, "no closing --- line"


def parse_simple_yaml(block):
    """Fallback parser for top-level key: value pairs, used only when PyYAML is absent."""
    data = {}
    current = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if match and not line[0].isspace():
            current = match.group(1)
            data[current] = match.group(2).strip()
        elif current is not None and line[0].isspace():
            data[current] = (data[current] + " " + line.strip()).strip()
        else:
            raise ValueError(f"unparseable line: {line!r}")
    for key, value in data.items():
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            data[key] = value[1:-1]
    return data


def parse_frontmatter(block):
    """Return (mapping, error). Uses PyYAML when available, else the fallback parser."""
    if yaml is not None:
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError as exc:
            return None, "YAML error: " + str(exc).splitlines()[0]
    else:
        try:
            data = parse_simple_yaml(block)
        except ValueError as exc:
            return None, str(exc)
    if not isinstance(data, dict):
        return None, "frontmatter is not a key: value mapping"
    return data, ""


def level2_headings(body):
    """Return the level-2 heading lines of a body, ignoring fenced code blocks."""
    headings = []
    in_fence = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("## "):
            headings.append(line.rstrip())
    return headings


def section(body, heading):
    """Text of one level-2 section, from its heading to the next level-2 heading, or None."""
    lines = body.splitlines()
    start = None
    in_fence = False
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line.startswith("## "):
            continue
        if start is None:
            if line.rstrip() == heading:
                start = index
        else:
            return "\n".join(lines[start:index])
    if start is None:
        return None
    return "\n".join(lines[start:])


def check_skill(skill_dir, folder):
    """Checks A1 to A12 for one skill. Returns a info dict for later checks, or None."""
    path = os.path.join(skill_dir, "SKILL.md")
    where = rel(path)
    if not os.path.isfile(path):
        report("FAIL", where, "A SKILL.md exists", "file missing")
        return None
    text = load(path, where, "A SKILL.md readable")
    if text is None:
        return None

    # A1: frontmatter parses and has the required keys
    block, body, error = split_frontmatter(text)
    values = None
    if block is not None:
        values, error = parse_frontmatter(block)
    if values is None:
        report("FAIL", where, "1 frontmatter parses", error)
        values = {}
    else:
        missing = [key for key in FRONTMATTER_KEYS if key not in values]
        verdict(not missing, where, "1 frontmatter parses",
                "keys: " + ", ".join(FRONTMATTER_KEYS), "missing keys: " + ", ".join(missing))

    # A2: name equals folder name and is kebab-case
    name = str(values.get("name", "")).strip()
    name_problems = []
    if name != folder:
        name_problems.append(f"name '{name}' differs from folder '{folder}'")
    if not KEBAB_CASE.match(name):
        name_problems.append(f"name '{name}' is not kebab-case")
    verdict(not name_problems, where, "2 name equals folder and is kebab-case",
            f"name = {name}", "; ".join(name_problems))

    # A3: description length
    description = str(values.get("description", "")).strip()
    verdict(len(description) <= 1000, where, "3 description at most 1000 chars",
            f"{len(description)} chars", f"{len(description)} chars, limit is 1000")

    # A4: model and effort values
    model = str(values.get("model", "")).strip()
    effort = str(values.get("effort", "")).strip()
    problems = []
    if model not in ALLOWED_MODELS:
        problems.append(f"model '{model}' not allowed")
    if effort not in ALLOWED_EFFORTS:
        problems.append(f"effort '{effort}' not allowed")
    verdict(not problems, where, "4 model and effort allowed",
            f"model {model}, effort {effort}", "; ".join(problems))

    # A5: level-2 headings present, in the required order
    headings = level2_headings(body)
    absent = [heading for heading in REQUIRED_HEADINGS if heading not in headings]
    if absent:
        verdict(False, where, "5 level-2 headings in order", "", "missing: " + ", ".join(absent))
    else:
        positions = [headings.index(heading) for heading in REQUIRED_HEADINGS]
        verdict(positions == sorted(positions), where, "5 level-2 headings in order",
                f"{len(REQUIRED_HEADINGS)} headings present, in order", "present but out of order")

    # A6: Model & Effort section terms
    model_section = section(body, "## Model & Effort")
    if model_section is None:
        report("FAIL", where, "6 Model & Effort terms", "section missing")
    else:
        absent = [term for term in MODEL_EFFORT_TERMS if term not in model_section]
        verdict(not absent, where, "6 Model & Effort terms", "all terms present",
                "missing: " + ", ".join(absent))

    # A7: Vietnamese reply rule in the body
    verdict(VIETNAMESE_REPLY_RULE in body, where, "7 body has Vietnamese reply rule",
            "found", "not found")

    # A8 and A9: project memory mentioned in two sections
    for number, heading in ((8, "## Inputs to confirm before starting"), (9, "## Output format")):
        body_section = section(body, heading)
        verdict(body_section is not None and "project memory" in body_section.lower(), where,
                f"{number} '{heading}' mentions project memory", "found",
                "section missing or no 'project memory'")

    # A10: file length
    line_count = len(text.splitlines())
    verdict(line_count < 400, where, "10 file under 400 lines",
            f"{line_count} lines", f"{line_count} lines, limit is under 400")

    # A11: relative reference links resolve
    links = sorted(set(RELATIVE_LINK.findall(text)))
    if not links:
        report("PASS", where, "11 relative links resolve", "no references/*.md links")
    for link in links:
        verdict(os.path.isfile(os.path.join(skill_dir, link)), where,
                f"11 link {link} resolves", "target exists", "target missing")

    # A12: Haiku delegation string
    verdict(HAIKU_DELEGATION in text, where, '12 contains model: "haiku"', "found", "not found")

    return {"dir": skill_dir, "body": body, "text": text, "model": model, "effort": effort}


def is_vietnamese(char):
    return "Ạ" <= char <= "ỹ" or char in VI_LATIN_CHARS


def walk_md(base):
    """Yield every .md file under base, in sorted order."""
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for name in sorted(filenames):
            if name.lower().endswith(".md"):
                yield os.path.join(dirpath, name)


def markdown_files():
    """Yield the .md files that check B scans for the detected layout."""
    if LAYOUT == "project":
        yield from walk_md(ROOT)
        return
    # Global layout: never scan other folders under the root (projects/, plugins/, ...).
    claude_path = os.path.join(ROOT, "CLAUDE.md")
    if os.path.isfile(claude_path):
        yield claude_path
    for folder in ("skills", "research-kit"):
        base = os.path.join(ROOT, folder)
        if os.path.isdir(base):
            yield from walk_md(base)


def check_english_only():
    """Check B: no Vietnamese characters in any .md file outside the vi-example blocks."""
    for path in markdown_files():
        where = rel(path)
        text = load(path, where, "B english-only")
        if text is None:
            continue
        # Replace each example block with the same number of newlines so line numbers hold.
        scrubbed = VI_EXAMPLE_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), text)
        # Allowlist: the researcher's proper name contains Vietnamese letters.
        scrubbed = scrubbed.replace(ALLOWED_PROPER_NAME, "")
        hits = 0
        for lineno, line in enumerate(scrubbed.splitlines(), start=1):
            found = sorted({char for char in line if is_vietnamese(char)})
            if found:
                hits += 1
                report("FAIL", f"{where}:{lineno}", "B english-only",
                       "Vietnamese characters: " + "".join(found))
        if not hits:
            report("PASS", where, "B english-only", "no Vietnamese characters")


def split_row(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def check_routing(claude_lines, skill_info):
    """Check C: the routing table in CLAUDE.md matches the skill folders and frontmatter."""
    where = "CLAUDE.md"
    start = None
    for index, line in enumerate(claude_lines):
        if line.startswith(ROUTING_HEADING_PREFIX):
            start = index
            break
    if start is None:
        report("FAIL", where, "C routing table", f"heading '{ROUTING_HEADING_PREFIX}' not found")
        return

    rows = []
    for line in claude_lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if stripped.startswith("|"):
            rows.append(split_row(stripped))
        elif rows:
            break

    if not rows or rows[0] != ROUTING_COLUMNS:
        report("FAIL", where, "C routing table columns", f"expected columns {ROUTING_COLUMNS}")
        return
    data = [cells for cells in rows[1:]
            if not all(re.fullmatch(r":?-+:?", cell) for cell in cells)]

    verdict(len(data) == ROUTING_ROW_COUNT, where, "C routing table row count",
            f"{len(data)} rows", f"{len(data)} rows, expected {ROUTING_ROW_COUNT}")

    listed = set()
    for cells in data:
        if len(cells) != 5:
            report("FAIL", where, "C routing table row", f"expected 5 cells, got {len(cells)}: {cells}")
            continue
        number, skill = cells[0], cells[1].strip("`")
        table_model, table_effort = cells[2].strip("`"), cells[3].strip("`")
        listed.add(skill)
        info = skill_info.get(skill)
        problems = []
        if info is None:
            problems.append("skill folder or readable SKILL.md missing")
        else:
            if table_model != info["model"]:
                problems.append(f"table model {table_model} != SKILL.md {info['model']}")
            if table_effort != info["effort"]:
                problems.append(f"table effort {table_effort} != SKILL.md {info['effort']}")
        verdict(not problems, where, f"C routing row {number} {skill}",
                f"model {table_model}, effort {table_effort} match SKILL.md",
                "; ".join(problems))

    unlisted = sorted(set(skill_info) - listed)
    unknown = sorted(listed - set(skill_info))
    problems = []
    if unlisted:
        problems.append("folders not in table: " + ", ".join(unlisted))
    if unknown:
        problems.append("table rows without folder: " + ", ".join(unknown))
    verdict(not problems, where, "C every skill folder is in the table",
            f"{len(skill_info)} folders listed", "; ".join(problems))


def check_claude_md(claude_text):
    """Check E: CLAUDE.md headings, rules, imports and length."""
    where = "CLAUDE.md"
    lines = claude_text.splitlines()

    for term in CLAUDE_TERMS:
        found = any(line.startswith("#") and term in line for line in lines)
        verdict(found, where, f"E heading mentions '{term}'", "found", "no heading contains it")

    verdict(CLAUDE_REPLY_RULE in claude_text, where, "E reply rule", "found", "not found")

    if LAYOUT == "global":
        report("SKIP", where, "E project-memory imports", "skipped in global layout")
    else:
        for name in IMPORTS:
            target = f"@.claude/project-memory/{name}"
            imported = any(target in re.sub(r"`[^`]*`", "", line) for line in lines)
            exists = os.path.isfile(os.path.join(ROOT, ".claude", "project-memory", name))
            problems = []
            if not imported:
                problems.append("no import line outside backticks")
            if not exists:
                problems.append("imported file missing")
            verdict(not problems, where, f"E import {name}", "import present, file exists",
                    "; ".join(problems))

    count = len(lines)
    if count < CLAUDE_MAX_LINES:
        report("PASS", where, "E CLAUDE.md under 200 lines", f"{count} lines")
    else:
        report("WARN", where, "E CLAUDE.md under 200 lines", f"{count} lines, limit is 200")


def check_integration(skill_info):
    """Check D: integration strings in the Workflow section, and whole-file strings."""
    for skill, terms in WORKFLOW_TERMS.items():
        where = f"{SKILLS_REL}/{skill}/SKILL.md"
        info = skill_info.get(skill)
        if info is None:
            report("FAIL", where, "D skill present", "folder or readable SKILL.md missing")
            continue
        where = rel(os.path.join(info["dir"], "SKILL.md"))
        workflow = section(info["body"], "## Workflow")
        if workflow is None:
            report("FAIL", where, "D Workflow section", "section missing")
            continue
        for term in terms:
            verdict(term in workflow, where, f"D Workflow contains {term}", "found", "not found")

    for skill, terms in FILE_TERMS.items():
        where = f"{SKILLS_REL}/{skill}/SKILL.md"
        info = skill_info.get(skill)
        if info is None:
            report("FAIL", where, "D skill present", "folder or readable SKILL.md missing")
            continue
        where = rel(os.path.join(info["dir"], "SKILL.md"))
        for term in terms:
            verdict(term in info["text"], where, f"D file contains {term}", "found", "not found")


def check_project_memory():
    """Check F: each project-memory file has a title and the Purpose and Update when lines."""
    if LAYOUT == "global":
        report("SKIP", "project-memory", "F project-memory files", "skipped in global layout")
        return
    directory = os.path.join(ROOT, ".claude", "project-memory")
    if not os.path.isdir(directory):
        report("FAIL", rel(directory), "F project-memory directory", "directory missing")
        return
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        where = rel(path)
        text = load(path, where, "F project-memory readable")
        if text is None:
            continue
        lines = text.splitlines()
        first = lines[0] if lines else ""
        problems = []
        if not first.startswith("# "):
            problems.append("first line is not a '# ' heading")
        if "Purpose:" not in text:
            problems.append("no 'Purpose:' line")
        if "Update when:" not in text:
            problems.append("no 'Update when:' line")
        verdict(not problems, where, "F heading, Purpose:, Update when:",
                "all present", "; ".join(problems))


def main(argv):
    global ROOT, LAYOUT, SKILLS_REL
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if len(argv) != 2:
        print("usage: validate_skills.py <project_root>", file=sys.stderr)
        return 2
    ROOT = os.path.abspath(argv[1])
    if not os.path.isdir(ROOT):
        print(f"not a directory: {ROOT}", file=sys.stderr)
        return 2

    # Detect the layout: project if <root>/.claude/skills exists, else global if <root>/skills exists.
    if os.path.isdir(os.path.join(ROOT, ".claude", "skills")):
        LAYOUT, SKILLS_REL = "project", ".claude/skills"
    elif os.path.isdir(os.path.join(ROOT, "skills")):
        LAYOUT, SKILLS_REL = "global", "skills"
    else:
        # Neither exists: keep the project checks so the missing folder is reported as before.
        LAYOUT, SKILLS_REL = "project", ".claude/skills"

    # Check A: every skill folder
    skills_dir = os.path.join(ROOT, *SKILLS_REL.split("/"))
    skill_info = {}
    if not os.path.isdir(skills_dir):
        report("FAIL", rel(skills_dir), "A skills directory", "directory missing")
    else:
        for folder in sorted(os.listdir(skills_dir)):
            skill_dir = os.path.join(skills_dir, folder)
            if not os.path.isdir(skill_dir):
                continue
            info = check_skill(skill_dir, folder)
            if info is not None:
                skill_info[folder] = info

    check_english_only()

    claude_path = os.path.join(ROOT, "CLAUDE.md")
    claude_text = load(claude_path, "CLAUDE.md", "E CLAUDE.md readable") if os.path.isfile(claude_path) else None
    if claude_text is None and not os.path.isfile(claude_path):
        report("FAIL", "CLAUDE.md", "E CLAUDE.md exists", "file missing")
    if claude_text is not None:
        check_routing(claude_text.splitlines(), skill_info)
        check_claude_md(claude_text)

    check_integration(skill_info)
    check_project_memory()

    summary = f"{counts['PASS']} PASS, {counts['FAIL']} FAIL, {counts['WARN']} WARN"
    if counts["SKIP"]:
        summary += f", {counts['SKIP']} SKIP"
    print(summary)
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
