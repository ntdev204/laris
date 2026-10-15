"""Scientific Discourse Unit and Formula Extractor.

Module ID: MOD-SCINLP-001 (Boundary D: Scientific Language Intelligence)
Governed by: docs/specifications/MODULE_CONTRACTS.md, ADR-002, ADR-008.
Extracts scientific claims, methods, datasets, metrics, results, limitations,
assumptions, and LaTeX mathematical formulas from scientific texts with exact
source coordinate anchoring and provenance preservation.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from laris.core.errors import (
    ExtractionConfidenceBelowThresholdError,
    MalformedDiscourseSpanError,
    ModuleContractViolationError,
)
from laris.core.schemas import EpistemicStatus, EvidenceCoordinate
from laris.layers.layer3_scinlp.schemas import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    MIN_EXTRACTION_CONFIDENCE,
    AssumptionRecord,
    ClaimRecord,
    DatasetRecord,
    DiscourseExtractionSet,
    FormulaRecord,
    LimitationRecord,
    MethodRecord,
    MetricRecord,
    ResultRecord,
)

# --- Regex Patterns for Scientific Discourse Extraction ---

# Math / Formula patterns
LATEX_DISPLAY_PATTERN = re.compile(r"\$\$([\s\S]+?)\$\$")
LATEX_ENV_PATTERN = re.compile(
    r"\\begin\{(equation|align|gather|multline)\*?\}([\s\S]+?)\\end\{\1\*?\}"
)
LATEX_INLINE_PATTERN = re.compile(r"(?<!\$)\$(?!\$)([^\$\n]+?)(?<!\$)\$(?!\$)")

# Metric patterns
METRIC_VALUE_PATTERN = re.compile(
    r"\b(accuracy|precision|recall|macro-f1|micro-f1|f1-score|f1|bleu(?:-[1-4])?|"
    r"rouge(?:-[12l])?|roc-auc|auc|mrr|plddt|perplexity|mse|rmse|mae)\b"
    r"(?:\s*(?:=|:|of|is|reached|achieved)\s*([0-9]+(?:\.[0-9]+)?%?))?",
    re.IGNORECASE,
)

# Known benchmark dataset patterns
DATASET_PATTERN = re.compile(
    r"\b(ImageNet(?:-1k)?|GLUE|SuperGLUE|SQuAD(?:\s*v?[12](?:\.0)?)?|"
    r"arXiv|PubMed|SciCite|WikiText(?:-103|-2)?|MS-COCO|COCO|PDB|UniProt|"
    r"MedQA|BioASQ|MMLU|GSM8K|SNLI|MNLI|ANLI)\b",
    re.IGNORECASE,
)

# Scientific method / architecture patterns
METHOD_PATTERN = re.compile(
    r"\b(Transformer|BERT|RoBERTa|SciBERT|BioBERT|GPT(?:-[234o])?|LLaMA(?:-[23])?|"
    r"LSTM|BiLSTM|CNN|ResNet|AdamW?|SGD|gradient descent|contrastive learning|"
    r"reinforcement learning|LoRA|cross-entropy loss|self-attention|random forest|"
    r"support vector machine|Markov chain|MCMC)\b",
    re.IGNORECASE,
)

# Discourse marker patterns for sentence-level classifications
CLAIM_MARKER_PATTERN = re.compile(
    r"\b(we demonstrate that|we show that|our results indicate that|"
    r"we establish that|we prove that|we hypothesize that|"
    r"our findings demonstrate that|we propose a novel|this confirms that|"
    r"we observe that|evidence suggests that)\b",
    re.IGNORECASE,
)

RESULT_MARKER_PATTERN = re.compile(
    r"\b(achieves|outperforms|yields a statistically significant|"
    r"statistically significant improvement|reduces error rate|"
    r"leads to state-of-the-art|improves performance by|p\s*[<=]\s*0\.0[0-9]+|"
    r"statistically significant\s*\(p\s*<)\b",
    re.IGNORECASE,
)

LIMITATION_MARKER_PATTERN = re.compile(
    r"\b(a limitation of|our approach is limited to|does not scale to|"
    r"fails when|we do not address|future work is needed to|"
    r"computational cost is prohibitive|restricted to|bottleneck of our)\b",
    re.IGNORECASE,
)

ASSUMPTION_MARKER_PATTERN = re.compile(
    r"\b(we assume that|under the assumption that|under the assumption of|"
    r"assuming that|is assumed to be|we make the assumption that|"
    r"supposing that|held constant)\b",
    re.IGNORECASE,
)


def _split_into_sentences(text: str) -> list[tuple[int, int, str]]:
    """Split text into sentences with character offset ranges, respecting decimals and math."""
    spans: list[tuple[int, int, str]] = []
    if not text.strip():
        return spans

    # Match sentence boundaries: punctuation (. ! ?) followed by whitespace, not part of a decimal
    split_pattern = re.compile(r"(?<=[.!?])(?<!\d\.)\s+(?=[A-Z\$\\])|\n\s*\n")
    start = 0
    for match in split_pattern.finditer(text):
        m_start = match.start()
        raw_part = text[start:m_start]
        stripped = raw_part.strip()
        if stripped:
            real_start = start + raw_part.find(stripped)
            real_end = real_start + len(stripped)
            spans.append((real_start, real_end, stripped))
        start = match.end()

    trailing = text[start:]
    stripped_trailing = trailing.strip()
    if stripped_trailing:
        real_start = start + trailing.find(stripped_trailing)
        real_end = real_start + len(stripped_trailing)
        spans.append((real_start, real_end, stripped_trailing))

    return spans


def _validate_latex_syntax(formula: str) -> bool:
    """Check if LaTeX mathematical string has balanced delimiters and valid syntax."""
    # Check balanced braces
    brace_depth = 0
    bracket_depth = 0
    paren_depth = 0
    in_escape = False

    for char in formula:
        if in_escape:
            in_escape = False
            continue
        if char == "\\":
            in_escape = True
            continue
        if char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
            if brace_depth < 0:
                return False
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth -= 1
            if bracket_depth < 0:
                return False
        elif char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
            if paren_depth < 0:
                return False

    return brace_depth == 0 and bracket_depth == 0 and paren_depth == 0


def _extract_latex_symbols(formula: str) -> list[str]:
    """Extract distinct mathematical symbols and variable identifiers from LaTeX formula."""
    # Find LaTeX commands like \alpha, \beta, \sum, \mathcal{L}
    symbols = set()
    for m in re.finditer(r"\\[a-zA-Z]+", formula):
        cmd = m.group(0)
        if cmd not in {"\\begin", "\\end", "\\left", "\\right", "\\frac", "\\text", "\\cdot"}:
            symbols.add(cmd)
    # Find single-letter variable identifiers
    for m in re.finditer(r"\b([a-zA-Z])\b", formula):
        symbols.add(m.group(1))
    return sorted(symbols)


class ScientificDiscourseExtractor:
    """Extracts scientific discourse entities and mathematical formulas conforming to Boundary D.

    Fulfills DiscourseExtractorContract Protocol. Anchors every extracted unit to
    an EvidenceCoordinate with rigorous character offset verification and provenance.
    """

    def __init__(
        self,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        min_confidence: float = MIN_EXTRACTION_CONFIDENCE,
        enforce_threshold: bool = False,
    ) -> None:
        if not (0.0 <= confidence_threshold <= 1.0):
            raise ModuleContractViolationError(
                f"confidence_threshold must be in [0.0, 1.0], got {confidence_threshold}"
            )
        if not (0.0 <= min_confidence <= 1.0):
            raise ModuleContractViolationError(
                f"min_confidence must be in [0.0, 1.0], got {min_confidence}"
            )
        self.confidence_threshold = confidence_threshold
        self.min_confidence = min_confidence
        self.enforce_threshold = enforce_threshold

    def _create_coordinate(
        self,
        document_id: str,
        document_sha256: str,
        char_start: int,
        char_end: int,
        snippet: str,
        confidence: float,
        provided_coords: list[EvidenceCoordinate] | None = None,
    ) -> EvidenceCoordinate:
        """Create or match coordinate anchored to physical document offsets."""
        if provided_coords:
            # Match to existing coordinate spanning this range
            for coord in provided_coords:
                if coord.char_start <= char_start and coord.char_end >= char_end:
                    return coord

        # Construct deterministic coordinate
        coord_id = f"{document_id}:p1:{char_start}-{char_end}"
        return EvidenceCoordinate(
            coordinate_id=coord_id,
            document_id=document_id,
            document_sha256=document_sha256,
            page_number=1,
            section_identifier="body",
            paragraph_index=0,
            sentence_index=0,
            char_start=char_start,
            char_end=char_end,
            verbatim_snippet=snippet,
            extraction_confidence=confidence,
        )

    def extract(
        self,
        document_id: str,
        text: str,
        coordinates: list[EvidenceCoordinate] | None = None,
    ) -> DiscourseExtractionSet:
        """Extract typed discourse entities from input text or physical coordinates."""
        if not isinstance(document_id, str) or not document_id.strip():
            raise ModuleContractViolationError("document_id must be a non-empty string.")
        if not isinstance(text, str):
            raise ModuleContractViolationError("text must be a string.")

        # Validate provided coordinates
        if coordinates is not None:
            for coord in coordinates:
                if not isinstance(coord, EvidenceCoordinate):
                    raise ModuleContractViolationError(
                        f"Expected EvidenceCoordinate, got {type(coord).__name__}"
                    )
                if (
                    coord.char_start < 0
                    or coord.char_end < coord.char_start
                    or coord.char_end > len(text)
                ):
                    raise MalformedDiscourseSpanError(
                        f"Invalid coordinate offsets: [{coord.char_start}, {coord.char_end}] "
                        f"for text length {len(text)}"
                    )

        doc_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

        claims: list[ClaimRecord] = []
        methods: list[MethodRecord] = []
        datasets: list[DatasetRecord] = []
        metrics: list[MetricRecord] = []
        results: list[ResultRecord] = []
        limitations: list[LimitationRecord] = []
        assumptions: list[AssumptionRecord] = []
        formulas: list[FormulaRecord] = []

        # 1. Extract Formulas (LaTeX environments, display math, inline math)
        formulas.extend(self._extract_formulas(document_id, text, doc_sha256, coordinates))

        # 2. Extract Token/Phrase-level Entities (Metrics, Datasets, Methods)
        metrics.extend(self._extract_metrics(document_id, text, doc_sha256, coordinates))
        datasets.extend(self._extract_datasets(document_id, text, doc_sha256, coordinates))
        methods.extend(self._extract_methods(document_id, text, doc_sha256, coordinates))

        # 3. Extract Sentence-level Units (Claims, Results, Limitations, Assumptions)
        sentence_spans = _split_into_sentences(text)
        for start, end, sent in sentence_spans:
            # Claims
            claim = self._evaluate_claim_sentence(
                document_id, doc_sha256, start, end, sent, coordinates
            )
            if claim is not None:
                claims.append(claim)

            # Results
            res = self._evaluate_result_sentence(
                document_id, doc_sha256, start, end, sent, coordinates
            )
            if res is not None:
                results.append(res)

            # Limitations
            lim = self._evaluate_limitation_sentence(
                document_id, doc_sha256, start, end, sent, coordinates
            )
            if lim is not None:
                limitations.append(lim)

            # Assumptions
            assump = self._evaluate_assumption_sentence(
                document_id, doc_sha256, start, end, sent, coordinates
            )
            if assump is not None:
                assumptions.append(assump)

        # 4. Filter or enforce confidence thresholds
        if self.enforce_threshold:
            confidences = [
                *(c.confidence for c in claims),
                *(m.confidence for m in methods),
                *(d.confidence for d in datasets),
                *(mt.confidence for mt in metrics),
                *(r.confidence for r in results),
                *(lim.confidence for lim in limitations),
                *(a.confidence for a in assumptions),
                *(f.confidence for f in formulas),
            ]
            for conf in confidences:
                if conf < self.confidence_threshold:
                    raise ExtractionConfidenceBelowThresholdError(
                        f"Extraction confidence {conf:.3f} is below "
                        f"threshold {self.confidence_threshold:.3f}"
                    )
        else:
            claims = [c for c in claims if c.confidence >= self.confidence_threshold]
            methods = [m for m in methods if m.confidence >= self.confidence_threshold]
            datasets = [d for d in datasets if d.confidence >= self.confidence_threshold]
            metrics = [mt for mt in metrics if mt.confidence >= self.confidence_threshold]
            results = [r for r in results if r.confidence >= self.confidence_threshold]
            limitations = [
                lim for lim in limitations if lim.confidence >= self.confidence_threshold
            ]
            assumptions = [a for a in assumptions if a.confidence >= self.confidence_threshold]
            formulas = [f for f in formulas if f.confidence >= self.confidence_threshold]

        extraction_id = f"ext-{document_id}-{doc_sha256[:8]}"
        timestamp_now = datetime.now(timezone.utc).isoformat()
        return DiscourseExtractionSet(
            document_id=document_id,
            extraction_id=extraction_id,
            timestamp_iso=timestamp_now,
            claims=claims,
            methods=methods,
            datasets=datasets,
            metrics=metrics,
            results=results,
            limitations=limitations,
            assumptions=assumptions,
            formulas=formulas,
        )

    def _extract_formulas(
        self,
        document_id: str,
        text: str,
        doc_sha256: str,
        coordinates: list[EvidenceCoordinate] | None,
    ) -> list[FormulaRecord]:
        """Extract LaTeX mathematical expressions and detect syntax validity."""
        formulas: list[FormulaRecord] = []
        covered_spans: list[tuple[int, int]] = []

        # LaTeX environments
        for m in LATEX_ENV_PATTERN.finditer(text):
            start, end = m.span()
            raw_tex = m.group(0)
            inner_tex = m.group(2).strip()
            is_valid = _validate_latex_syntax(inner_tex)
            confidence = 0.95 if is_valid else 0.40
            symbols = _extract_latex_symbols(inner_tex)

            coord = self._create_coordinate(
                document_id, doc_sha256, start, end, raw_tex, confidence, coordinates
            )
            formulas.append(
                FormulaRecord(
                    formula_id=f"form-{start}-{end}",
                    latex_source=raw_tex,
                    confidence=confidence,
                    coordinate=coord,
                    variables=tuple(symbols),
                    is_inline=False,
                )
            )
            covered_spans.append((start, end))

        # Display math $$ ... $$
        for m in LATEX_DISPLAY_PATTERN.finditer(text):
            start, end = m.span()
            if any(s <= start and end <= e for s, e in covered_spans):
                continue
            raw_tex = m.group(0)
            inner_tex = m.group(1).strip()
            is_valid = _validate_latex_syntax(inner_tex)
            confidence = 0.90 if is_valid else 0.40
            symbols = _extract_latex_symbols(inner_tex)

            coord = self._create_coordinate(
                document_id, doc_sha256, start, end, raw_tex, confidence, coordinates
            )
            formulas.append(
                FormulaRecord(
                    formula_id=f"form-{start}-{end}",
                    latex_source=raw_tex,
                    confidence=confidence,
                    coordinate=coord,
                    variables=tuple(symbols),
                    is_inline=False,
                )
            )
            covered_spans.append((start, end))

        # Inline math $ ... $
        for m in LATEX_INLINE_PATTERN.finditer(text):
            start, end = m.span()
            if any(s <= start and end <= e for s, e in covered_spans):
                continue
            raw_tex = m.group(0)
            inner_tex = m.group(1).strip()
            is_valid = _validate_latex_syntax(inner_tex)
            confidence = 0.85 if is_valid else 0.35
            symbols = _extract_latex_symbols(inner_tex)

            coord = self._create_coordinate(
                document_id, doc_sha256, start, end, raw_tex, confidence, coordinates
            )
            formulas.append(
                FormulaRecord(
                    formula_id=f"form-{start}-{end}",
                    latex_source=raw_tex,
                    confidence=confidence,
                    coordinate=coord,
                    variables=tuple(symbols),
                    is_inline=True,
                )
            )
            covered_spans.append((start, end))

        return formulas

    def _extract_metrics(
        self,
        document_id: str,
        text: str,
        doc_sha256: str,
        coordinates: list[EvidenceCoordinate] | None,
    ) -> list[MetricRecord]:
        """Extract evaluation metrics and values."""
        metrics: list[MetricRecord] = []
        for m in METRIC_VALUE_PATTERN.finditer(text):
            start, end = m.span()
            snippet = m.group(0)
            metric_name = m.group(1)
            raw_val = m.group(2)

            val: float | None = None
            unit: str | None = None
            confidence = 0.80

            if raw_val is not None:
                confidence = 0.95
                if raw_val.endswith("%"):
                    val = float(raw_val[:-1])
                    unit = "%"
                else:
                    try:
                        val = float(raw_val)
                    except ValueError:
                        val = None

            coord = self._create_coordinate(
                document_id, doc_sha256, start, end, snippet, confidence, coordinates
            )
            metrics.append(
                MetricRecord(
                    metric_id=f"mtr-{start}-{end}",
                    name=metric_name.upper(),
                    confidence=confidence,
                    coordinate=coord,
                    value=val,
                    unit=unit,
                )
            )
        return metrics

    def _extract_datasets(
        self,
        document_id: str,
        text: str,
        doc_sha256: str,
        coordinates: list[EvidenceCoordinate] | None,
    ) -> list[DatasetRecord]:
        """Extract benchmark datasets."""
        datasets: list[DatasetRecord] = []
        for m in DATASET_PATTERN.finditer(text):
            start, end = m.span()
            ds_name = m.group(0)
            confidence = 0.88
            coord = self._create_coordinate(
                document_id, doc_sha256, start, end, ds_name, confidence, coordinates
            )
            datasets.append(
                DatasetRecord(
                    dataset_id=f"ds-{start}-{end}",
                    name=ds_name,
                    confidence=confidence,
                    coordinate=coord,
                )
            )
        return datasets

    def _extract_methods(
        self,
        document_id: str,
        text: str,
        doc_sha256: str,
        coordinates: list[EvidenceCoordinate] | None,
    ) -> list[MethodRecord]:
        """Extract scientific methods and model architectures."""
        methods: list[MethodRecord] = []
        for m in METHOD_PATTERN.finditer(text):
            start, end = m.span()
            method_name = m.group(0)
            confidence = 0.85
            coord = self._create_coordinate(
                document_id, doc_sha256, start, end, method_name, confidence, coordinates
            )
            methods.append(
                MethodRecord(
                    method_id=f"met-{start}-{end}",
                    name=method_name,
                    category="computational",
                    confidence=confidence,
                    coordinate=coord,
                )
            )
        return methods

    def _evaluate_claim_sentence(
        self,
        document_id: str,
        doc_sha256: str,
        start: int,
        end: int,
        sentence: str,
        coordinates: list[EvidenceCoordinate] | None,
    ) -> ClaimRecord | None:
        """Evaluate whether a sentence constitutes a scientific claim."""
        m = CLAIM_MARKER_PATTERN.search(sentence)
        if not m:
            return None
        confidence = 0.86
        coord = self._create_coordinate(
            document_id, doc_sha256, start, end, sentence, confidence, coordinates
        )
        return ClaimRecord(
            claim_id=f"clm-{start}-{end}",
            text=sentence,
            epistemic_status=EpistemicStatus.DIRECT_AUTHOR_CLAIM,
            confidence=confidence,
            coordinate=coord,
        )

    def _evaluate_result_sentence(
        self,
        document_id: str,
        doc_sha256: str,
        start: int,
        end: int,
        sentence: str,
        coordinates: list[EvidenceCoordinate] | None,
    ) -> ResultRecord | None:
        """Evaluate whether a sentence constitutes an empirical result."""
        m = RESULT_MARKER_PATTERN.search(sentence)
        if not m:
            return None
        confidence = 0.88
        p_match = re.search(r"p\s*[<=]\s*(0\.0[0-9]+)", sentence, re.IGNORECASE)

        p_val: float | None = None
        if p_match:
            try:
                p_val = float(p_match.group(1))
            except ValueError:
                p_val = None

        coord = self._create_coordinate(
            document_id, doc_sha256, start, end, sentence, confidence, coordinates
        )
        return ResultRecord(
            result_id=f"res-{start}-{end}",
            description=sentence,
            confidence=confidence,
            coordinate=coord,
            statistically_significant=(p_val is not None and p_val <= 0.05),
            p_value=p_val,
        )

    def _evaluate_limitation_sentence(
        self,
        document_id: str,
        doc_sha256: str,
        start: int,
        end: int,
        sentence: str,
        coordinates: list[EvidenceCoordinate] | None,
    ) -> LimitationRecord | None:
        """Evaluate whether a sentence constitutes a limitation."""
        m = LIMITATION_MARKER_PATTERN.search(sentence)
        if not m:
            return None
        confidence = 0.90
        coord = self._create_coordinate(
            document_id, doc_sha256, start, end, sentence, confidence, coordinates
        )
        return LimitationRecord(
            limitation_id=f"lim-{start}-{end}",
            description=sentence,
            confidence=confidence,
            coordinate=coord,
            scope="general",
            is_author_disclosed=True,
        )

    def _evaluate_assumption_sentence(
        self,
        document_id: str,
        doc_sha256: str,
        start: int,
        end: int,
        sentence: str,
        coordinates: list[EvidenceCoordinate] | None,
    ) -> AssumptionRecord | None:
        """Evaluate whether a sentence constitutes a stated assumption."""
        m = ASSUMPTION_MARKER_PATTERN.search(sentence)
        if not m:
            return None
        confidence = 0.87
        coord = self._create_coordinate(
            document_id, doc_sha256, start, end, sentence, confidence, coordinates
        )
        return AssumptionRecord(
            assumption_id=f"asm-{start}-{end}",
            statement=sentence,
            coordinate=coord,
            is_explicit=True,
            confidence=confidence,
        )
