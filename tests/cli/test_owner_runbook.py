"""Parse documented owner commands without invoking a training or inference handler."""

import re
import shlex
from pathlib import Path

from laris.cli.main import build_parser


def test_owner_runbook_commands_parse_without_execution():
    root = Path(__file__).resolve().parents[2]
    text = (root / "docs/training/OWNER_RUNBOOK.md").read_text()
    parser = build_parser()
    parsed = []
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        for line in block.replace("\\\n", " ").splitlines():
            tokens = shlex.split(line)
            if ".venv/bin/laris" not in tokens:
                continue
            index = tokens.index(".venv/bin/laris")
            args = parser.parse_args(tokens[index + 1 :])
            parsed.append(args)
            if args.group == "train":
                assert tokens[:index] == ["LARIS_TRAINING_AUTHORIZED=1"]
                assert args.command == "language-encoder"
                if not args.profile_only:
                    assert args.authorized and args.evaluate_after is False
                    assert args.micro_batch_size * args.grad_accum_steps == 64
                    assert args.run_id == "foundation-candidate-001"
            # Deliberately do not call args.handler or construct a model.
    assert len(parsed) == 6
    assert "no model 02 training command" in text
