"""Records the request/response fixtures of the scientific tools (T149) from the tool box.

    PYTHONPATH=src python scripts/record_scientific_fixtures.py [output-directory]

The output is what `laris-protocol` round-trips and validates
(`crates/laris-protocol/tests/fixtures/scientific`). Only the extraction timestamp differs between
runs. No weights are loaded and nothing is trained.
"""

import json
import sys
from pathlib import Path

from laris.model.tools import Limits, ToolBox, ToolError

ROOT = Path(__file__).resolve().parents[1]
TEXT = (
    "We propose a novel framework for citation parsing. We trained a BiLSTM with AdamW on the "
    "PubMed corpus. Our results indicate that the model achieves an accuracy of 0.91 and an F1 of "
    "87.5%. "
    "We assume that references are well formed. A limitation of this study is that only English "
    "papers (café, naïve, α-helix) were used. Samples were heated to 300 K under 2.5 GPa. "
    "The energy is $E = mc^2$."
)


def calls():
    path = ROOT / "tests/fixtures/scholarly/citations.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    documents = [{"id": k, "text": t} for k, t in sorted(data["documents"].items())]
    return {
        "extract_discourse": {"text": TEXT, "document_id": "paper"},
        "detect_limitations": {"text": TEXT, "document_id": "paper"},
        "normalize_quantities": {"text": TEXT, "document_id": "paper"},
        "parse_bibliography": {"text": documents[0]["text"][:600]},
        "analyse_citations": {"documents": documents},
        "mine_literature": {"documents": documents, "kind": "overview"},
    }


def main(argv):
    out = Path(argv[0]) if argv else ROOT / "crates/laris-protocol/tests/fixtures/scientific"
    out.mkdir(parents=True, exist_ok=True)
    tools = ToolBox(Limits(max_chars=2_000_000, max_documents=200))

    def write(name, value):
        text = json.dumps(value, indent=1, ensure_ascii=False) + "\n"
        (out / name).write_text(text, encoding="utf-8")

    write("tools.list.json", {"tools": tools.schemas()})
    for name, arguments in calls().items():
        write(f"{name}.request.json", {"arguments": arguments})
        write(f"{name}.response.json", {"result": tools.call(name, arguments)})
    try:
        tools.call("extract_discourse", {"text": ""})
    except ToolError as exc:
        write("error.response.json", {"error": {"message": exc.message, "type": exc.code}})


if __name__ == "__main__":
    main(sys.argv[1:])
