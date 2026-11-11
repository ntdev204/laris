# Gap templates

## Gap types
- Theoretical: missing guarantee or proof (stability, feasibility, robustness bound) under realistic assumptions.
- Methodological: no method handles a known difficulty (e.g., time-varying parameters, actuator limits).
- Experimental: claims never validated beyond simulation, or no fair benchmark exists.
- Application: method exists but not adapted to a setting with distinct constraints.

## Comparison matrix (example columns for vehicle control)
| Paper | Model (kin./dyn.) | Key assumptions | Method | Guarantee | Validation | Scenario | Code |

## Ranking table
| Gap | Value (1-5) | Feasibility (1-5) | Risk (1-5, high = risky) | Fit (1-5) | Confidence gap is real | Reason |

## Falsification log
| Gap | Query / place searched | Date | Closest work found | Does it fill the gap? (yes / partly / no) | Notes |

## Contribution statement pattern
"Existing work on [problem] either [limitation A] or [limitation B] (refs). This [paper/thesis] addresses
[specific gap] by [approach]. We show [property] under [assumptions] and validate it on [setting].
The scope excludes [boundary]."
