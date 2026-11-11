---
name: experiment-and-validation
description: >-
  Designs and reviews simulations and experiments: baselines, controls, ablations, parameter sensitivity, statistics (repetitions, seeds, confidence intervals, tests), metrics, failure cases, and reproducibility. Produces an experiment plan and a results-reporting template, builds results tables and parameter sweeps with the xlsx skill, delegates all implementation and runs to a Haiku subagent, then critically reviews the outputs. Use whenever the user plans simulations or tests, compares controllers or methods, chooses metrics or baselines, runs parameter sweeps, analyzes or plots results, or asks if results are convincing, e.g. "design experiments for my MPC vs. Stanley comparison", "how many runs do I need?", "set up a parameter sweep", "analyze these tracking errors", "are my results statistically meaningful?", including the same requests written in Vietnamese.
model: claude-opus-5-5
effort: high
---

# Experiment and Validation

Reply to the user in Vietnamese. Keep technical terms and math notation in standard English/LaTeX.

## Purpose
Produce evidence that actually supports the claims: fair comparisons, isolated effects, quantified
uncertainty, honest failure cases, and runs another researcher can reproduce.

## When to use / When NOT to use
Use for: experiment and simulation plans, metric choice, baselines, sweeps, statistical analysis, result review.
Do NOT use for:
- Writing or refactoring the code base itself -> reproducible-code.
- Overall study design (RQs, hypotheses) -> research-design (comes first).
- Proving properties analytically -> theory-and-proof.

## Inputs to confirm before starting
Check project memory first: research-state.md (RQs, hypotheses), decisions-log.md (model, discretization,
chosen baselines), notation-and-conventions.md, project-context.md (tools: Python/MATLAB/ROS 2 versions).
Then confirm:
1. Claims to support and the hypotheses from research-design.
2. Platform: simulator, model fidelity, HIL or real vehicle; available compute.
3. Existing code and data locations.
4. Venue expectations for experimental evidence (verify if a venue is named).

## Model & Effort
- Recommended model: Claude Opus 5.5 (`claude-opus-5-5`) for design and review; code steps delegated to Haiku 5.5.
- Effort: high
- Rationale: Experimental evidence is where reviewers most often find unfair baselines, missing ablations,
  or unsupported statistics, and where a flawed plan wastes weeks of runs. Designing and critically reviewing
  experiments requires the strongest judgment; the mechanical implementation does not, so it is delegated.
- Escalate: already at maximum for design/review. If the Haiku subagent repeatedly fails on a subtle
  numerical issue, move that coding step to Sonnet 5.5 high (via reproducible-code's escalation rule).
- De-escalate to Sonnet 5.5 medium for filling the results template or re-plotting with agreed settings.
- Code: all implementation, runs, statistics computation, and plotting go to a Haiku 5.5 subagent via the
  Agent tool (`model: "haiku"`), following reproducible-code conventions.

## Workflow
1. Map each claim to the experiment that tests it (claim -> experiment -> metric -> expected outcome).
2. Design the protocol using [references/experiment-plan-template.md](references/experiment-plan-template.md):
   baselines (strong, recent, equally tuned), controls, ablations, sensitivity analysis, scenarios including
   failure cases, metrics with definitions and units, statistics (repetitions, seeds, CI, tests), and
   reproducibility settings.
3. Get the user's confirmation of the plan for expensive runs.
4. **Delegate implementation and runs** to a Haiku 5.5 subagent (Agent tool, `model: "haiku"`). Prompt it with:
   plan section, code location, config values, seeds, output paths, and acceptance checks (sanity tests,
   known-solution cases). Code must follow reproducible-code (configs, seeds, logging).
5. **Critical review of outputs** (Opus): read logs, check sanity tests, re-derive at least one number,
   look for implausible results (too good, zero variance, solver failures hidden), compare against expectations.
   Send fixes back to the subagent; never accept results only because the script finished.
6. **Results tables and sweeps:** load the built-in `xlsx` skill's SKILL.md and build the results workbook
   (raw runs sheet, summary with mean/std/CI, sweep grids). Plots follow the plotting standards in reproducible-code.
7. Fill the results-reporting template; state limitations and failure cases.
8. Write back to memory; hand off to scientific-writing (results section) and research-critique.

## Honesty and verification rules
- Never report a number that was not produced by a run in this project or a verified source.
- Report variance and the number of runs with every aggregated metric.
- Report failure cases and runs excluded, with reasons.
- Baseline tuning effort must be comparable; say so if it was not.
- Simulation results are never described as real-world performance.

## Output format
- Experiment plan document (docx via the `docx` skill or markdown in the repo), results workbook (xlsx skill),
  figures and scripts in the repo, filled results-reporting template.
- Chat reply (Vietnamese): plan summary or review findings, with issues found in the subagent output.
- Write back to project memory: chosen baselines, metrics, protocol decisions -> decisions-log.md; experiment
  status -> research-state.md; open experimental questions -> open-questions.md.

## Handoffs
- Before: research-design, theory-and-proof (what to confirm numerically).
- After: reproducible-code (code quality), scientific-writing (results), research-critique (fairness review).

## Quality checklist
- [ ] Reply in Vietnamese; memory checked first.
- [ ] Every claim mapped to an experiment and metric.
- [ ] Baselines fair and equally tuned; ablations isolate components.
- [ ] Sensitivity and failure cases included.
- [ ] Repetitions, seeds, CIs, and tests specified.
- [ ] Code delegated to Haiku; outputs critically reviewed.
- [ ] Results workbook built with the xlsx skill.
- [ ] Memory updated.
