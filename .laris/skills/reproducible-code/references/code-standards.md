# Code standards

## Repository layout (Python; adapt for MATLAB / ROS 2)
```text
project/
  README.md            # install, test, reproduce each figure
  environment.yml      # or requirements.txt with pinned versions
  configs/             # YAML/JSON per experiment; no magic numbers in code
  src/<pkg>/           # models, controllers, simulators, utils
  scripts/             # run_experiment.py, make_fig_<name>.py
  tests/               # pytest: unit, known-solution, consistency
  results/             # raw outputs (gitignored), one folder per run: <date>_<config>_<seed>/
  figures/             # final figures (vector PDF/SVG + PNG preview)
```
ROS 2: one package per responsibility, parameters in YAML launch files, record bags for experiments,
note distro and package versions in README.
MATLAB: functions not scripts for reusable code, `rng(seed)`, record MATLAB version and toolboxes.

## Run logging (write next to each result)
config file copy, seed(s), git commit hash, environment export, start/end time, machine, solver settings.

## Tests
- Unit tests for each function with known inputs/outputs.
- Known-solution tests from analytic cases.
- Consistency: discretization convergence as step size decreases; energy/invariant checks when applicable;
  symmetry (left/right turns).
- Regression tests for figures used in papers (numbers within tolerance).

## Plotting standards
- Axis labels with units; legend entries match paper terminology; consistent colors per method across figures.
- Font size readable at the venue's column width; vector output for papers.
- One script per figure, reading saved results (never re-running experiments inside plotting scripts).
- Show variance (shaded CI or error bars) and state n in the caption.

## Version control
Small commits with clear messages; tag commits used for submitted figures (e.g., `paper1-submission`);
never commit large raw data; record data location instead.
