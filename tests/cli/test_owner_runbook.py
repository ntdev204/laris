"""Parse owner commands and verify the approved run budget without executing handlers."""

import re
import shlex
from pathlib import Path

from laris.cli.commands.language_encoder import _resolve_hyperparameters
from laris.cli.main import build_parser


def test_owner_runbook_commands_parse_without_execution():
    root = Path(__file__).resolve().parents[2]
    text = (root / "docs/training/OWNER_RUNBOOK.md").read_text()
    parser = build_parser()
    parsed = []
    runs = {}
    budget = {"baseline": [0, 0], "sampling": [0, 0]}
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        for line in block.replace("\\\n", " ").splitlines():
            tokens = shlex.split(line.split("|", 1)[0])
            if ".venv/bin/laris" not in tokens:
                continue
            index = tokens.index(".venv/bin/laris")
            args = parser.parse_args([token for token in tokens[index + 1 :] if token != "2>&1"])
            parsed.append(args)
            prefix = tokens[:index]
            if args.group == "train":
                assert prefix[0] == "LARIS_TRAINING_AUTHORIZED=1"
                assert args.command == "language-encoder"
                if args.profile_only:
                    continue
                assert args.authorized and args.evaluate_after is False
                assert args.no_8bit_adam and args.init_from.endswith("/compact-1024-04/best")
                assert args.eval_interval == 500 and args.patience == 3
                assert prefix[1:4] == ["timeout", "-s", "KILL"]
                _, _, arm, phase = args.run_id.split("-")
                budget[arm][0] += int(prefix[4].removesuffix("s"))
                budget[arm][1] += args.steps
                hyper = _resolve_hyperparameters(args)
                assert hyper.micro_batch_size * hyper.gradient_accumulation_steps == 64
                assert hyper.loss_lambda_retrieval == 0
                runs[(arm, phase)] = hyper
            elif prefix[:3] == ["timeout", "-s", "KILL"]:
                assert args.group == "evaluate" and args.split == "val"
                arm = Path(args.checkpoint).parent.name.split("-")[2]
                budget[arm][0] += int(prefix[3].removesuffix("s"))
    assert len(parsed) == 9
    assert all(seconds <= 3600 and steps <= 2000 for seconds, steps in budget.values())
    for phase in ("smoke", "run"):
        baseline = runs["baseline", phase].model_dump()
        sampling = runs["sampling", phase].model_dump()
        assert baseline.pop("dataset_sampling_exponents") == {}
        assert sampling.pop("dataset_sampling_exponents") == {
            "nli": 0.7, "paraphrase": 0.7, "qa": 0.7
        }
        assert baseline == sampling
