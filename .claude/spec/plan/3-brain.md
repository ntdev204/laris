# LARIS — Plan 3: Main brain

Version 2.0.0-draft · 2026-11-13 · Implements [spec.md](../spec.md) sections 5.4 and 7.9; tasks in
[task/3-brain.md](../task/3-brain.md).

## 1. How this programme works

- Starts after the model is finished (T118) and programme 2 reached parity (T161); the design ADR (T162) may be written
  earlier if the owner opens the gate.
- Roles: ResearchLLM advises (proposals), the Obsidian main brain stores verified knowledge with provenance, a
  non-generative decision network decides, the system executes and writes verified results back through one gate.
- The system guarantees faithfulness to sources, not truth of the world. The decision network does not invent text but
  can choose wrongly; it is NOT QUALIFIED until its held-out gates pass, and the rule decider stays in charge until then.
- Training of the decision network is an owner run (SR-M3 applies).

## 2. Phases

### Phase 37 — Design gate
Goal: the main brain is designed and accepted before any code.
Tasks: T162
Exit criteria:
- ADR accepted by the owner (SR-K1).

### Phase 38 — Knowledge base and write gate
Goal: knowledge enters the brain only verified and with provenance.
Tasks: T163, T164, T165, T166
Exit criteria:
- Note types and certainty ladder linted; the write gate refuses model-only claims, records conflicts and downgrades
  dependants of retracted sources; answers are assembled only from accepted claims.

### Phase 39 — Decision network
Goal: decisions move from rules to a measured network.
Tasks: T167, T168, T169, T170, T171
Exit criteria:
- The rule decider passes the scenario suite; the decision dataset has provenance; the network passes its held-out
  gates and the owner promotes it.

### Phase 40 — Integration and evaluation
Goal: the whole cognitive loop with ResearchLLM as advisor, measured.
Tasks: T172
Exit criteria:
- The cognitive evaluation report (SR-K7) is produced with more than one advisor and reviewed by the owner.
