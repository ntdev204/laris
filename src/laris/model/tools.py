"""Scientific tools of the model block (SR-M2): the generation-1 extraction and scholarly code
served as tool routes, so the Rust client carries no NLP (ADR-021 D41).

A tool is a name, an OpenAI function schema and a function from arguments to a JSON value. Every
tool is deterministic and model-free: none loads weights, so none goes through the GPU queue. A
tool never raises to its caller: bad arguments, an oversized input and a domain refusal become
`ToolError`, which the route returns as `{"error": {"message", "type"}}`; anything unexpected is
reported as `tool_failed` without its text.

Call sites of the Python code this replaces (inventory, T149):
  * `research.evaluation.extraction.extract_spans` -> `extract_discourse` (macro-F1 gate)
  * the citation suite of the removed Python runner -> `parse_bibliography`, `analyse_citations`
  * `shared.scholarly.mining` (overview, term_trends, near_duplicates, group_documents)
                                                   -> `mine_literature`
  * `shared.scientific.limitations`                -> `detect_limitations`
  * `shared.scientific.units`                      -> `normalize_quantities`
The research evaluation code keeps calling the library directly; the generation-2 client calls
only the routes.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from laris.shared.core.errors import LarisError

ToolFunction = Callable[[Dict[str, Any]], Any]

DEFAULT_DOCUMENT_ID = "doc"
HEAD_CHARS = 3000  # the head of a document read for its bibliography (as `docs_from_chunks`)
CITATION_KINDS = ("summary", "edges", "cocitation", "coupling", "centrality", "unresolved")
MINING_KINDS = ("overview", "term_trends", "near_duplicates", "groups")


class ToolError(Exception):
    """A refusal the caller can read: `code` is the error type, `message` carries no input text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class UnknownTool(KeyError):
    """No tool has this name (HTTP 404)."""


@dataclass(frozen=True)
class Limits:
    """What one call may carry; both values come from the `model_service` configuration."""

    max_chars: int
    max_documents: int


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]
    run: ToolFunction

    def schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# -- argument helpers ----------------------------------------------------------------------------
def _text(args: Mapping[str, Any], key: str, limits: Limits, required: bool = True) -> str:
    value = args.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise ToolError("invalid_arguments", f"{key} must be a non-empty string")
    if len(value) > limits.max_chars:
        raise ToolError("input_too_large", f"{key} is longer than {limits.max_chars} characters")
    return value


def _document_id(args: Mapping[str, Any]) -> str:
    value = args.get("document_id", DEFAULT_DOCUMENT_ID)
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ToolError("invalid_arguments", "document_id must be a string of 1 to 200 characters")
    return value


def _flag(args: Mapping[str, Any], key: str, default: bool) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ToolError("invalid_arguments", f"{key} must be true or false")
    return value


def _number(args: Mapping[str, Any], key: str, default: float, low: float, high: float) -> float:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ToolError("invalid_arguments", f"{key} must be a number from {low} to {high}")
    return float(value)


def _choice(args: Mapping[str, Any], key: str, options: Sequence[str]) -> str:
    value = args.get(key, options[0])
    if value not in options:
        raise ToolError("invalid_arguments", f"{key} must be one of: {', '.join(options)}")
    return str(value)


def _documents(args: Mapping[str, Any], limits: Limits) -> List[Any]:
    """The `documents` argument as library `Doc`s, bibliography read from the head of each."""
    from laris.shared.scholarly.biblio import extract
    from laris.shared.scholarly.mining import Doc

    items = args.get("documents")
    if not isinstance(items, list) or not items:
        raise ToolError("invalid_arguments", "documents must be a non-empty list")
    if len(items) > limits.max_documents:
        raise ToolError(
            "input_too_large", f"documents holds more than {limits.max_documents} items"
        )
    docs, seen, chars = [], set(), 0
    for item in items:
        if not isinstance(item, dict):
            raise ToolError("invalid_arguments", "each document must be an object")
        doc_id = item.get("id")
        text = item.get("text")
        if not isinstance(doc_id, str) or not doc_id.strip() or not isinstance(text, str):
            raise ToolError(
                "invalid_arguments", "each document needs a string id and a string text"
            )
        if doc_id in seen:
            raise ToolError("invalid_arguments", "document ids must be unique")
        seen.add(doc_id)
        chars += len(text)
        if chars > limits.max_chars:
            raise ToolError(
                "input_too_large", f"the documents hold more than {limits.max_chars} characters"
            )
        docs.append(Doc(doc_id, doc_id, text, extract(text[:HEAD_CHARS])))
    return docs


# -- the tools -----------------------------------------------------------------------------------
def _extract_discourse(args: Dict[str, Any], limits: Limits) -> Any:
    from laris.shared.scientific.extractor import ScientificDiscourseExtractor

    text, doc_id = _text(args, "text", limits), _document_id(args)
    return ScientificDiscourseExtractor().extract(doc_id, text).to_dict()


def _detect_limitations(args: Dict[str, Any], limits: Limits) -> Any:
    from laris.shared.scientific.limitations import HeadingIndependentLimitationDetector

    text, doc_id = _text(args, "text", limits), _document_id(args)
    strip = _flag(args, "strip_headers", False)
    return HeadingIndependentLimitationDetector().detect(text, doc_id, None, strip).to_dict()


def _normalize_quantities(args: Dict[str, Any], limits: Limits) -> Any:
    from laris.shared.scientific.units import STEMUnitNormalizer

    text, doc_id = _text(args, "text", limits), _document_id(args)
    return [q.to_dict() for q in STEMUnitNormalizer().extract_quantities(text, doc_id)]


def _parse_bibliography(args: Dict[str, Any], limits: Limits) -> Any:
    from laris.shared.scholarly.biblio import extract

    text = _text(args, "text", limits)
    metadata = args.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ToolError("invalid_arguments", "metadata must be an object")
    found = extract(text[:HEAD_CHARS], metadata)
    return {
        "title": found.title,
        "authors": list(found.authors),
        "year": found.year,
        "doi": found.doi,
        "arxiv": found.arxiv,
        "evidence": dict(found.evidence),
        "properties": found.properties(),
    }


def _analyse_citations(args: Dict[str, Any], limits: Limits) -> Any:
    from laris.shared.scholarly.citations import analyse, summary

    kind = _choice(args, "kind", CITATION_KINDS)
    report = analyse(_documents(args, limits))
    result = summary(report, kind)
    if kind == "summary":  # the edges are part of what a caller checks against a gold list
        result["edges"] = [{"citing": a, "cited": b} for a, b in report.edges]
    return result


def _mine_literature(args: Dict[str, Any], limits: Limits) -> Any:
    from laris.shared.scholarly import mining

    kind = _choice(args, "kind", MINING_KINDS)
    docs = _documents(args, limits)
    if kind == "overview":
        return mining.overview(docs)
    if kind == "term_trends":
        return mining.term_trends(
            docs,
            top=int(_number(args, "top", 10, 1, 100)),
            min_docs=int(_number(args, "min_docs", 2, 1, 1000)),
        )
    threshold = _number(args, "threshold", 0.8 if kind == "near_duplicates" else 0.25, 0.0, 1.0)
    if kind == "near_duplicates":
        return mining.near_duplicates(docs, threshold=threshold, max_docs=limits.max_documents)
    return mining.group_documents(docs, threshold=threshold, max_docs=limits.max_documents)


_DOCUMENTS = {
    "type": "array",
    "minItems": 1,
    "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
        "required": ["id", "text"],
        "additionalProperties": False,
    },
    "description": "Documents with a unique id and their full text; a reference list ends "
    "the text.",
}
_TEXT = {"type": "string", "description": "The text to read."}
_DOC_ID = {"type": "string", "description": "Name used in evidence coordinates (default 'doc')."}


def _object(properties: Dict[str, Any], required: Sequence[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "extract_discourse",
            "description": (
                "Find claims, methods, datasets, metrics, results, limitations, "
                "assumptions and formulas "
                "in scientific text, each with its character range in the text."
            ),
            "parameters": _object({"text": _TEXT, "document_id": _DOC_ID}, ["text"]),
            "run": _extract_discourse,
        },
        {
            "name": "detect_limitations",
            "description": (
                "Find limitations, assumptions and negative findings without relying on "
                "headings, with "
                "uncertainty scores and character ranges."
            ),
            "parameters": _object(
                {
                    "text": _TEXT,
                    "document_id": _DOC_ID,
                    "strip_headers": {"type": "boolean", "description": "Ignore heading lines."},
                },
                ["text"],
            ),
            "run": _detect_limitations,
        },
        {
            "name": "normalize_quantities",
            "description": (
                "Find physical quantities (value, unit, uncertainty) and convert each to its SI "
                "representation with its dimension and character range."
            ),
            "parameters": _object({"text": _TEXT, "document_id": _DOC_ID}, ["text"]),
            "run": _normalize_quantities,
        },
        {
            "name": "parse_bibliography",
            "description": (
                "Read title, authors, year, DOI and arXiv id from the head of a paper; a "
                "field not stated "
                "stays empty. Optional file metadata fills what the text does not say."
            ),
            "parameters": _object(
                {"text": _TEXT, "metadata": {"type": "object", "description": "File metadata."}},
                ["text"],
            ),
            "run": _parse_bibliography,
        },
        {
            "name": "analyse_citations",
            "description": (
                "Resolve the reference lists of the given documents against each other and "
                "report the "
                "citation graph: summary, edges, co-citation, coupling, centrality or "
                "unresolved entries."
            ),
            "parameters": _object(
                {"documents": _DOCUMENTS, "kind": {"type": "string", "enum": list(CITATION_KINDS)}},
                ["documents"],
            ),
            "run": _analyse_citations,
        },
        {
            "name": "mine_literature",
            "description": (
                "Statistics over a set of documents: overview, term trends by year, near "
                "duplicates or "
                "similarity groups. Counts name the scope they were computed over."
            ),
            "parameters": _object(
                {
                    "documents": _DOCUMENTS,
                    "kind": {"type": "string", "enum": list(MINING_KINDS)},
                    "threshold": {"type": "number", "minimum": 0, "maximum": 1},
                    "top": {"type": "integer", "minimum": 1, "maximum": 100},
                    "min_docs": {"type": "integer", "minimum": 1},
                },
                ["documents"],
            ),
            "run": _mine_literature,
        },
    ]


class ToolBox:
    """The scientific tools, with the limits one call may use."""

    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self._tools: Dict[str, Tool] = {}
        for item in _definitions():
            run = item["run"]
            self._tools[item["name"]] = Tool(
                item["name"],
                item["description"],
                item["parameters"],
                lambda args, run=run: run(args, limits),  # type: ignore[misc]
            )

    def schemas(self) -> List[Dict[str, Any]]:
        return [self._tools[name].schema() for name in sorted(self._tools)]

    def call(self, name: str, arguments: Optional[Any]) -> Any:
        """The result of tool `name`; raises `UnknownTool` or `ToolError`."""
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownTool(name)
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise ToolError("invalid_arguments", "arguments must be an object")
        extra = sorted(set(arguments) - set(tool.parameters["properties"]))
        if extra:
            raise ToolError("invalid_arguments", f"unknown argument: {extra[0]}")
        missing = [k for k in tool.parameters["required"] if k not in arguments]
        if missing:
            raise ToolError("invalid_arguments", f"missing argument: {missing[0]}")
        try:
            return tool.run(arguments)
        except ToolError:
            raise
        except (
            LarisError
        ) as exc:  # a domain refusal; its text may quote the input, so it is not passed on
            raise ToolError("rejected", f"the input was refused ({type(exc).__name__})") from exc
        except Exception as exc:
            raise ToolError("tool_failed", f"the tool failed ({type(exc).__name__})") from exc
