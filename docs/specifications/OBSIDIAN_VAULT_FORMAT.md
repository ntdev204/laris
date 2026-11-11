---
document_id: "DOC-SPEC-VAULT-FORMAT-001"
title: "Obsidian-Compatible Vault Format Used by LARIS"
document_type: "specification"
status: "DRAFT"
version: "0.1.0"
created_at: "2026-11-11"
updated_at: "2026-11-11"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/architecture/AGENT_HARNESS.md"
  - "docs/architecture/BRAIN_THREAT_MODEL.md"
decision_references:
  - "ADR-014"
change_summary: "Defines the subset of the Obsidian vault format that LARIS reads and writes, the naming and property rules, and the behaviours that are verified or deliberately avoided."
---

# Obsidian-Compatible Vault Format Used by LARIS

LARIS keeps two vaults: the **project vault** (`vault/` in the user's codebase) and the **system brain**
(`.laris/brain/`, protected). Both are plain folders of Markdown files. LARIS implements the file format
itself in `src/vault/`; it never calls Obsidian and never needs it to run. A person may open either folder
in Obsidian, or in any editor.

## 1. Sources

The rules below come from the official Obsidian help pages (help.obsidian.md): *How Obsidian stores data*,
*Internal links*, *Properties*, *Tags*, *Graph view*, *Obsidian CLI*. Where a page was not read or a
behaviour could not be verified, section 6 says so and LARIS avoids depending on it.

## 2. Vault and files

- A vault is a folder. Notes are `*.md` files in UTF-8. A note's name is its file name without `.md`.
- The `.obsidian/` folder holds per-vault settings. LARIS writes only `app.json` with
  `useMarkdownLinks: false`, `newLinkFormat: "shortest"`, `alwaysUpdateLinks: true`, and a
  `.gitignore` that excludes `.obsidian/workspace.json` and `.obsidian/workspace-mobile.json`
  (personal layout state).
- The indexer ignores `.obsidian`, `.git`, `.trash` and `__pycache__`. Everything else is scanned.
- LARIS refuses to create a vault inside another vault.

## 3. Links, embeds, tags

| Form | Example | Handling |
|---|---|---|
| Wikilink to a note | `[[Note]]` | resolved by shortest path, case-insensitive |
| With folder | `[[Folder/Note]]` | matches the path suffix |
| Heading / block | `[[Note#Heading]]`, `[[Note#^id]]` | target note resolved; heading kept |
| Alias | `[[Note\|text]]` | alias kept, target unchanged |
| Embed | `![[Note]]` | counted as a link with `embed=True` |
| Markdown link | text in brackets followed by a path to a `.md` file in parentheses | counted as a link to the note |
| Link in a property | `related: ["[[Note]]"]` | counted as a property link |
| Tag | `#topic/sub`, `tags: [topic]` | collected |

Links inside fenced code, inline code and `%% comments %%` are ignored. Ambiguous names (two notes with
the same name) are reported, never guessed. LARIS names must not contain `# | ^ : % [ ] \ / " < > ? *`;
`safe_title` replaces them with spaces, collapses whitespace and caps the length at 100 characters.

## 4. Properties

Properties are YAML between `---` lines on the first line of the file. Rules enforced by lint:

1. Property names are unique in a note and match `[A-Za-z][\w-]*`.
2. One type per property name across the vault (text, list, number, boolean, date).
3. No nested objects.
4. A link in a property is a quoted string `"[[Note]]"`, a list of them for several.

LARIS notes use: `type`, `trust` (`untrusted` for notes made from documents, `model` for model-written),
`created`, `source`, `session`, `sources`, `concepts`, `status`, `origin`. The system brain additionally
uses `domain`, `level`, `summary`, `parent`, `children`, `keywords`, `version`, and the relation properties
`requires`, `uses`, `feeds`, `contrasts`, `validates`.

## 5. Managed blocks (project vault)

LARIS writes only inside blocks it owns:

```text
<!-- laris:begin NAME sha=0123456789abcdef -->
generated text
<!-- laris:end NAME -->
```

`sha` is the SHA-256 prefix of the text LARIS last wrote. When a person edits a block, the hash no longer
matches and LARIS reports a conflict and leaves the block alone. Text outside blocks is never modified.

## 6. Unverified behaviours and what LARIS does instead

| Topic | Status | LARIS behaviour |
|---|---|---|
| Whether dot-folders other than `.obsidian` are indexed by the app | not verified | LARIS creates no dot-folders besides `.obsidian`; the inbox is `_inbox/` |
| Exact keys of `.obsidian/*.json` beyond `app.json` | not verified | only the three keys of section 2 are written; no `graph.json`, no plugin files |
| JSON Canvas (`.canvas`) | the public JSON Canvas 1.0 specification (jsoncanvas.org: `nodes` with `id`, `type`, `x`, `y`, `width`, `height`, `text`; `edges` with `id`, `fromNode`, `toNode`, `label`) | written only by `laris vault graph --format canvas` and `kg_query` export, validated by a test; never read |
| Licence terms of the help pages | page not found | no help text is copied; rules are restated in LARIS's own words |
| Obsidian CLI | needs the running app | not used |

## 7. Golden fixture

`tests/fixtures/vault/` contains notes that exercise every row of section 3, properties, tags, code
fences, an unresolved link, an ambiguous name and a forbidden-character link. `tests/unit/vault/test_fixture.py`
fixes the expected index. A change to the parser must update the fixture and this document together.
