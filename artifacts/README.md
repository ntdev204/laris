# LARIS Artifacts Directory

This directory stores generated project artifacts, model checkpoints, benchmark evaluation reports, and runtime execution logs.

> [!CAUTION]
> Large binary model checkpoints (*.pt, *.safetensors) and training state dumps MUST NOT be committed to Git.

## Subdirectory Structure
- `artifacts/checkpoints/`: Local self-trained model weights, tokenizer files, and specialist heads.
- `artifacts/benchmark_reports/`: Permanent, version-controlled markdown reports of empirical benchmark runs.
- `artifacts/logs/`: Detailed execution logs, telemetry snapshots, and error taxonomy dumps.
