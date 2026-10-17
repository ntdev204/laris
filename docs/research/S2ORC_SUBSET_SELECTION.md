---
document_id: "DOC-RES-S2ORC-001"
title: "S2ORC STEM Subset Feasibility Analysis & Hard-Cap Audit"
document_type: "research"
status: "APPROVED"
version: "1.0.0"
created_at: "2026-10-16"
updated_at: "2026-10-16"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/plans/STAGED_LEARNING_PIPELINE.md"
  - "docs/specifications/DATASET_SPECIFICATION.md"
decision_references:
  - "ADR-001"
  - "ADR-002"
  - "ADR-004"
  - "ADR-005"
  - "ADR-008"
change_summary: "Detailed analysis of S2ORC releases, license terms, STEM filtering taxonomy, strict dual caps (<20 GB, <20M samples), and official API authentication blocker."
---

# S2ORC STEM Subset Feasibility Analysis & Hard-Cap Audit

## 1. Executive Summary

In accordance with Section 7 of the master execution mandate and Issue #200 ([M11-DATA-001](https://github.com/ntdev204/laris/issues/200)), this document provides the formal analysis of the Semantic Scholar Open Research Corpus (S2ORC) and evaluates the feasibility of acquiring a bounded STEM-only subset.

### Strict Hard Caps:
The master execution mandate imposes two strict, independent hard caps:
1. **Total Acquired S2ORC Payload:** strictly less than **20 GB** ($< 20.0$ GB uncompressed/download payload).
2. **Total Acquired S2ORC Sample Count:** strictly less than **20,000,000** samples ($< 20,000,000$ records/papers).

### Hard Prohibition:
**Never download the full S2ORC corpus as a workaround.** Downloading the complete corpus to filter locally or downloading large multi-part archives is strictly prohibited.

### Current Acquisition Decision:
**STATUS: `SKIPPED_TEMPORARILY`**

**Reason:** The official Semantic Scholar Academic Graph / S2ORC dataset endpoint (`https://api.semanticscholar.org/datasets/v1/release/latest/dataset/s2orc`) mandates an authenticated API key (`x-api-key`), returning `HTTP 401 Unauthorized` for anonymous requests. The unauthenticated archives on public endpoints consist of thirty 4 GB to 6 GB archive files ($120$ GB to $180$ GB total), which immediately violates the 20 GB hard cap if fetched in bulk. 

In strict compliance with Section 7.2:
> *"If the available official source cannot provide a sufficiently filtered subset within the constraints, or if licensing, network access, technical constraints or disk capacity prevent safe acquisition, stop the S2ORC attempt. Mark it `BLOCKED` or `SKIPPED_TEMPORARILY`, record the exact reason, and proceed with the remaining datasets."*

---

## 2. Release & Licensing Audit

- **Canonical Dataset:** Semantic Scholar Open Research Corpus (`s2orc` / `s2orc_v2`).
- **Release Authority:** Allen Institute for AI (AI2) & Semantic Scholar.
- **Dataset License:** Open Data Commons Attribution License (`ODC-BY-1.0`).
  - Permissions: Redistribution and commercial/non-commercial use permitted with proper attribution.
  - Invariants: Individual paper text retains original publisher/author open-access licenses (Unpaywall metadata embedded per paper).
- **Attribution Requirement:**
  ```bibtex
  @inproceedings{lo-wang-2020-s2orc,
      title = "{S}2{ORC}: The Semantic Scholar Open Research Corpus",
      author = "Lo, Kyle and Wang, Lucy Lu and Neumann, Mark and Kinney, Rodney and Weld, Daniel",
      booktitle = "Proceedings of ACL 2020",
      pages = "4969--4983",
      year = "2020"
  }
  ```

---

## 3. Sample-Unit Definition & STEM Filtering Plan

### 3.1 Sample-Unit Definition
A "sample" in S2ORC is defined at three hierarchical levels:
1. **Primary Unit (Paper Record):** One JSON document containing metadata, open-access status, parsed abstract, and Grobid-extracted body paragraphs.
2. **Sub-Unit (Discourse Paragraph):** Annotated body paragraph tagged with section role (`Introduction`, `Methods`, `Results`, `Discussion`).
3. **Citation Triple:** Bounded in-text citation marker linked to bibliographic entry.

All cap calculations track **Primary Paper Records**.

### 3.2 Documented STEM Taxonomy
When acquired, filtering will select papers classified under explicit STEM fields of study in the Semantic Scholar taxonomy:
- `Computer Science`
- `Mathematics`
- `Physics`
- `Biology`
- `Medicine`
- `Chemistry`
- `Engineering`

Non-STEM fields (`Art`, `History`, `Philosophy`, `Sociology`, `Economics`, `Political Science`) will be excluded.

### 3.3 Selected Payload Fields
To minimize storage and guarantee adherence to the $<20$ GB limit, the bounded subset will extract only:
- `corpusid` (int)
- `title` (str)
- `abstract` (str)
- `fieldsOfStudy` (list[str])
- `year` (int)
- `openAccessPdf` (dict)
- `body_text.text` and `body_text.section` (filtered body paragraphs)

---

## 4. Dual Hard-Cap Sizing Calculations

| Metric | Full S2ORC Corpus | LARIS Bounded STEM Target | Hard Cap Limit | Compliant? |
| :--- | :--- | :--- | :--- | :--- |
| **Total Size** | $120.0 – 180.0$ GB (compressed) | $\mathbf{8.5}$ **GB (uncompressed JSONL)** | $< 20.0$ GB | **YES** (with margin) |
| **Paper Count** | $10,000,000 – 16,000,000$ | $\mathbf{500,000}$ **STEM Papers** | $< 20,000,000$ | **YES** (2.5% of cap) |
| **Paragraph Count** | $> 150,000,000$ | $\sim 12,500,000$ paragraphs | N/A | Planned |

---

## 5. Blocker Details & Retry Condition

1. **Authentication Blocker:**
   - Querying `https://api.semanticscholar.org/datasets/v1/release/latest/dataset/s2orc` returns `HTTP Error 401: Unauthorized`.
   - Semantic Scholar migrated dataset downloads behind required partner API keys.
2. **Safe Future Retry Condition:**
   - Acquisition will be triggered only when:
     a) An authorized `S2_API_KEY` is provided via environment configuration, allowing signed, single-partition downloads; OR
     b) An official pre-filtered STEM slice is published directly by AllenAI or hosted on an accessible open research mirror.
   - At no point will the full 120+ GB archive be downloaded.
