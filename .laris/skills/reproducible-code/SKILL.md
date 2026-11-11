---
name: reproducible-code
description: >-
  Writes, runs, and reviews research code so every figure and number can be reproduced: project structure, pinned environments, seeds, config files, unit and sanity tests (known-solution tests, conservation and consistency checks), plotting standards, version control, data and result logging, and a README that reproduces every figure. Code goes in files, not chat. Use whenever the user wants to write, fix, refactor, test, or organize research code (Python, MATLAB, ROS 2 nodes, simulation scripts, plotting), set up an environment, make results reproducible, or debug numerical code, e.g. "write a simulation of the kinematic bicycle model", "set up the repo for my experiments", "my integration blows up", "make my plots consistent", "add tests", including the same requests written in Vietnamese.
model: claude-haiku-5-5
effort: medium
---

# Reproducible Code

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.

## Purpose
Produce research code that is correct, tested, and reproducible by another researcher from the README alone.

## When to use / When NOT to use
Use for: all code writing and execution in this workspace, including code requested by other skills.
Do NOT use for:
- Deciding what to run and how to judge results -> experiment-and-validation.
- Deriving the equations the code implements -> theory-and-proof (implement only verified equations).

## Inputs to confirm before starting
Check project memory first: project-context.md (OS, Python/MATLAB/ROS 2 versions, tools),
notation-and-conventions.md (symbol-to-variable mapping, units, frames), decisions-log.md (model,
discretization, solver choices).
Then confirm: language and version, existing repo location, the exact equations/spec to implement,
expected outputs, and acceptance tests.

## Model & Effort
- Recommended model: Claude Haiku 5.5 (`claude-haiku-5-5`)
- Effort: medium
- Rationale: Workspace policy assigns all code writing and execution to Haiku 5.5. Well-specified
  implementation, tests, and plotting are fast and reliable at medium effort, and the specification and
  review come from the calling skill.
- Escalate to Claude Sonnet 5.5 at high effort for subtle numerical bugs (stiffness, instability, solver
  non-convergence, sign/frame errors that tests do not catch) or architecture decisions (repo layout for a
  multi-year thesis, ROS 2 package structure). State the reason when escalating.
- De-escalate to Haiku low for trivial edits (renaming, formatting, small plot tweaks).
- When another skill (running on Sonnet or Opus) needs code, it spawns this work as a subagent with the
  Agent tool and `model: "haiku"`, and reviews the result.

## Workflow
1. Read the spec and memory (notation mapping, units, frames). Ask if the spec is ambiguous; never invent equations.
2. Set up or check the structure in [references/code-standards.md](references/code-standards.md):
   `src/`, `configs/`, `scripts/`, `tests/`, `results/` (gitignored raw), `figures/`, environment file, README.
3. Pin the environment (requirements.txt or environment.yml with versions; MATLAB version and toolboxes noted).
4. Implement with parameters in config files, explicit units in names or docstrings, and seeds set and logged.
5. Tests: unit tests, known-solution tests (e.g., straight-line motion, steady-state circle radius
   $R = L/\tan\delta$ for the kinematic model), consistency checks (continuous vs. discretized response,
   convergence with smaller step). Run them and report actual output.
6. Run the experiment/script; log config, seed, commit hash, environment, and timing next to each result.
7. Plot with the plotting standards (labels with units, consistent styles, vector output, script per figure).
8. Version control: meaningful commits; tag the commit used for each paper figure.
9. README: install, run tests, reproduce each figure (one command per figure).
10. Report to the user or the calling skill: files changed, tests run with results, anything not run.

## Honesty and verification rules
- Report only test results and outputs that actually ran in this session; say "not run" otherwise.
- Never silence errors, loosen tolerances, or change seeds to make a test pass without saying so.
- If the code disagrees with the derivation, report the discrepancy; do not "fix" the math in code silently.
- Code goes in files, not chat (short snippets in chat only when explaining).

## Output format
Files in the repo (code, configs, tests, figures, README, environment file). Chat reply (Vietnamese):
what was built, how to run it, test results, open issues.
Write back to project memory: environment versions -> project-context.md; symbol-to-variable mapping
-> notation-and-conventions.md; solver/discretization choices made with the user -> decisions-log.md;
known bugs or unverified behavior -> open-questions.md.

## Handoffs
- Before: experiment-and-validation, theory-and-proof (symbolic checks), scientific-writing (compile checks).
- After: back to the calling skill for critical review.

## Quality checklist
- [ ] Reply in Vietnamese; memory checked first.
- [ ] Environment pinned; seeds and configs used; nothing hard-coded that should be a parameter.
- [ ] Known-solution and sanity tests written and actually run.
- [ ] Results logged with config, seed, commit, environment.
- [ ] Plots meet the standards; one script per figure.
- [ ] README reproduces every figure.
- [ ] Code in files, not chat.
