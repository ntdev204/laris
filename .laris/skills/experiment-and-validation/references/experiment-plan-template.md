# Experiment plan and results-reporting template

## Claim map
| Claim | Experiment | Metric (definition, unit) | Expected outcome | Refuting outcome |

## Setup
- Platform: simulator/version, model fidelity (kinematic/dynamic, tire model), HIL/real vehicle.
- Plant used for evaluation vs. model used in the controller (state the mismatch explicitly).
- Sampling period, solver, horizon, actuator limits, delays, noise models.

## Baselines
| Baseline | Source (verified ref) | Tuning procedure | Tuning budget | Same information? |

## Ablations and controls
| Variant | Component removed/changed | Question it answers |

## Sensitivity analysis
| Parameter | Nominal | Range | Grid/sampling | Reason |

## Scenarios
Nominal, aggressive (high curvature/speed), disturbances, parameter mismatch, failure/edge cases.

## Statistics
- Repetitions per condition, seeds listed, what is randomized.
- Report mean ± std and 95% CI; tests appropriate to the data (paired tests across seeds/scenarios,
  non-parametric if distributions are skewed); correct for multiple comparisons if many.
- Effect sizes, not only p-values.

## Reproducibility
Config files, seeds, code commit hash, environment file, data and result paths, figure scripts.

## Results-reporting template
1. Setup summary table. 2. Main comparison table (mean ± std, CI, n). 3. Ablation table.
4. Sensitivity plots. 5. Failure cases with explanation. 6. Computation time (hardware stated).
7. Limitations of the evidence.
