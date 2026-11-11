# Verification checks

## Analytic checks (do these yourself)
- Special cases: zero input, straight-line motion, steady-state cornering, $v \to 0$, small angles.
- Limits and symmetry: left/right turn symmetry, sign of yaw rate vs. steering.
- Dimensional analysis: every term in a sum has the same unit.
- Consistency with a known textbook result (cite a verified source).

## Delegated checks (Haiku 5.5 subagent via Agent tool, model: "haiku")
Prompt template for the subagent:
- Goal: verify [expression/claim].
- Inputs: exact expressions in SymPy-ready form, parameter values, ranges.
- Tasks: e.g., compute Jacobian symbolically and compare with the derived matrix; compare continuous and
  ZOH-discretized responses; check eigenvalues over a parameter grid; finite-difference check of a gradient.
- Output: a script file, its printed results, and PASS/FAIL per check with tolerances.
- Do not modify the expressions; report any mismatch exactly.

Parent review of the result:
- Confirm the script tested the same expression as the derivation (read the code).
- Re-check one number by hand where possible.
- A numeric pass on a grid is evidence, not proof; label it so.
