# Research State

> Purpose: where the research stands right now: questions, chosen gap and contribution, status of each paper/chapter, next actions.
> Update when: a gap is chosen, a status changes (done / in progress / blocked), or next actions change.
> Rules: short dated lines. Replace stale status instead of appending; summarize old entries when the file grows past ~100 lines.

Last updated: 2026-11-10

## Current research questions
- Hypotheses from docs/proposals/proposal.docx (sec. 6-7): H1 stop-and-go feasibility, H2 split horizon cuts solve time (p99 -40 %, ey +<=10 %), H3 INMPC vs KMB at high speed, H4 delay compensation, H5 KMB vs KIN with steering lag (H5 no longer testable: needed the removed Python plant).
- Controllers compared (src/inmpc/controllers/): KIN (kinematic Euler, lambda=0), KMB (kinematic + heading-lag lambda), DYN (dynamic Pacejka, RK4 whole horizon), INMPC (blended dynamic head N1=10,h=0.05 + projection + KMB tail N2=6,h=0.2).

## Chosen gap -> contribution statement
- Gap / contribution: [PLACEHOLDER] (not yet written by research-gap).

## Status 2026-11-04 (Python + CARLA)
- On `develop` (nothing in `main`, nothing pushed; tags prereg-v0-proposed, prereg-v1, prereg-v1.1): Python plant study (900 runs), CARLA open-loop (1050 recordings) and closed-loop (1113 runs, 3 vehicles), proof of Corollary (4.7) (fixed-horizon form), literature check, V5/H3 diagnostics. 186 tests pass (-m "not carla"), 1 xfail.
- Prereg D4-D8 approved by the user message of 2026-11-04 at the proposed values (no other values were written to the repo); D3 testable rule and (4.7) fixed-horizon form are the assistant's reading of that message.
- Verdicts (Python / CARLA): H1 supported / supported x3; H2 rejected / partial (V3 only stop-go medium_K, artefact); H3 rejected / not run (CARLA friction scaling unverified); H4 supported / supported x3; H5 inconclusive / vehicle-dependent; H6 inconclusive after D3 rule (12/48 testable) / inconclusive; H7 rejected by rule but weak / rejected by rule, weak.
- D5 NOT MET on CARLA (K ratios 3.14, 1.43; Python-only vehicles meet it). acados (P7) blocked: the harness denied cloning/building acados.
- Report: reports/2026-11-04_bao_cao_mo_phong_python_va_carla.docx (not rendered: no LibreOffice). Data: data/py, data/carla, data/openloop_carla (gitignored); results reports/sim_results/{py,carla}.
- Not done: acados RTI; H3/wet and syn_dlc/syn_corner_brake on CARLA; cross-run mu repeatability (F12 original problem); manual literature check outside the searched databases.

## Update 2026-11-05 (spec/plan/task phases P11-P16)
- Method change logged: tire grip estimated by UKF, dry/known mu removed (decisions-log). Docs chain: proposal -> spec -> plan -> task (git develop).
- Done this session (merged into develop, tests re-run by the reviewer): T104 grip literature (21 verified refs), T91 UKF spec (docs/estimation/ukf_spec.md), T93 mu_ctrl removed (interim grip.mode nominal_interim), T98 plant friction by arc length (H9 layout missing). Suite: 264 passed, 2 xfailed with acados env vars.
- D12-D20, D26 chosen by the assistant under user delegation and frozen in prereg-v4 (2026-11-05, T103 done). Chain now blocked by code tasks T110-T118 (rate limit, plant stiffness key, H8/H3/H9 builders, metrics, Q/R builder, config switch): T99-T102, T108.
- Also merged: T92 (UKF off-loop, 43 tests) and T94 (filter in loop, (5.18) as OCP parameters, IPOPT, Python only); suite 334 passed, 7 xfailed with acados env. D21-D25 decided by the user; D12-D20 pending. Finding: with the default plant the UKF theta is biased (0.33 vs 0.60) — threat to H8.
- Also merged: T57 (acados grip parameters, V0 only), T109 (timing: filter+solve p99 33 ms vs 100 ms, 0/450 exceed), T97 (oscillation diagnosis, cause open). Suite 385 passed, 12 xfailed.
- Also merged: T55 presets V1/V5-V9 on acados (agreement fails at many points; 36 strict xfails). Suite on merged develop to be re-run.
- T105 (cross-check of spec, plan, task) done for the three-file consistency after five independent reviews; cosmetic residue and open user decisions are listed in the T105 board row.
- Not done: T90 (needs the user, own prereg tag, §7.6 edit), RTI stall cause and SQP status-4 failures, V6 validity, T105 final independent pass; code tasks T110-T118.

## Update 2026-11-10 (advisor review nhanxet.docx)
- T126 diagnosis (user asked to skip codex, no sub-agents): INMPC oscillation cause = control period 0.10 s vs head step 0.05 s; ts 0.05 or h1 0.10 gives ey_p95 about 0.1 m (better than KMB) in Python; v4 estimated mode also cannot hold speed (mu_bar 0.18). Fix choice pending the user. Evidence: reports/audit/2026-11_inmpc_settings_check.md.
- Review adopted for steps 0-5: plan P17/G17, D27, spec 2.9 R-77-R-82, tasks T122-T128 (not started); steps 6-9 deferred. AGENTS.md and .agents removed. Reviewed runs predate T110-T118; V2/V3/V4 reinterpreted (open-questions 2026-11-10). Codex branch `codex/t99-h8` (own task numbering) unreviewed, piecewise review = T128.

## Replan 2026-11-10 (user decisions D28-D31)
- Two root defects treated as implementation defects (no proposal edit): control period vs head step (R-83) and longitudinal channel not as (5.5) (R-84). Earlier INMPC/DYN results (H2, H3, H7 of 2026-11-04, v4 V0 runs, T97 stage 3) are affected (D30).
- Order: T122 -> T123, T124 -> T129 (compare fixes a/b/d) -> T130 -> T131 -> T133 (re-run confounded diagnoses) -> T125 -> T126 (CARLA, acados) -> T132 (unused variables) -> T134 (prereg-v5, labels) -> T127. Nothing of this is started; T128 (codex) deferred. No sub-agents.
- Review numbers recomputed from the seed-1 CSV: KMB ey max 2.172 m, INMPC beta max 71.7 deg, KMB vx*r max 16.77; large reference heading steps at t = 1131, 1298, 1504, 1562, 1591 s coincide with KMB ey peaks (junction cause not verified).

## Progress 2026-11-10 (execution of the replan, all merged into develop)
- Done: T122 (effective parameters, commit-named folders), T129 (option (a) selected), T130 (ts 0.05 s, start-up check, warm start by one period), T131 (a_x is net acceleration, resistance added at the plant input), T133 (re-run: V0 with the estimated grip still fails, cause is mu_bar 0.18 of the v4 back-off, not the INMPC mechanics), T123 (route metrics, review numbers confirmed as artefacts), T124 superseded by T135 (the route has no heading jumps; the reference speed was a function of time, not position), T135 (arc-indexed reference speed: Python KMB whole route e_y max 71.9 -> 0.81 m).
- Suite 667 passed, 14 xfailed with acados env. Open for the user: what to change in the accepted v4 values or the excitation strategy (open-questions 2026-11-10); D27 step-2 value 0.5 m vs 0.81 m at a tight junction turn.
- Not done: T125 (CARLA identification), T126 (CARLA and acados validation, INMPC acceptance), T132 (unused variables), T134 (labels, prereg-v5), T127 (baselines), T128 deferred. No CARLA run was made in this block; no sub-agents.

## Progress 2026-11-10 (second block)
- Merged: T136 (reference speed and OCP limits consistent), T137 (CARLA a_y channel for the filter), T138 (update gate against the theta collapse, 3 options compared), T132 (unused keys removed), T134 (prereg v5 block, tag prereg-v5, labels), T125 partial (CARLA re-identification: mu 1.625, spread 0.1 %).
- Running: T127 queue on CARLA GUI (KIN, KMB, INMPC, V0, seeds 1-5, chapters 0-9), results to data/carla_101126 and reports/101126 (builder scripts/report_baselines.py). Not done: skidpad/step-steer identification and the D-vs-K criterion (T125), whole-route INMPC acceptance (T126), acados validation, T128 deferred, independent cross-check pass 11 (no sub-agents allowed).
- V0 never learns grip at the excitation of the route (gate 0.4, a_y max 2.9 m/s2): mu_bar stays 0.18.

## Close of goal 2026-11-06 (user closed the goal; handover)
- Done and merged into develop: prereg-v4 and v4.1 (tags local, not pushed; user accepted the v4 values and UKF numerics on 2026-11-06); code tasks T110-T118; cross-check pass 9 (spec/plan/task, independent reviewer, findings fixed); proposal edited ((5.22), (4.7), sec. 7.6, tau_r validity, sec. 1 novelty with refs [11]-[15]); T97 stages 1-3 (reports/audit/2026-11_inmpc_oscillation_diagnosis.md). Suite with acados env: 599 passed, 49 xfailed.
- Not done: T99 (H8) runs - runner committed on branch `exp/t99-h8` (worktree `.worktrees/t99`, commit 0d828a1), NOT reviewed, NOT merged, run stopped by the user's close, partial data deleted, no H8 verdict; T100, T101, T102, T108, T106, T90 not started; CARLA runs of the v4 filter impossible until a CARLA a_y source exists.
- CARLA demos 2026-11-06: lien_tuc INMPC 15 m/s seed 1: ey_p95 0.13 m, no lane departure (legacy path, no filter, data/demo_carla). Full Town06 line INMPC (one lap, prescribed 15 m/s, no filter): stopped by the user at t = 87 s, |ey| max 3.96 m, 14 of 88 log lines beyond 1.75 m; cause unverified (hypotheses: prescribed speed above the friction limit in high-curvature sections, intrinsic oscillation of T97); data deleted.
- Must be resolved next: (1) theta_hat collapse below the floor in 41-69 % of INMPC time with the filter in the loop (T97 stage 3) - blocks H3, H8-in-loop, H9; run the control with controller grip fixed at the tire model mu; (2) INMPC oscillation (ey_p95 about 6 m in Python) and curvature vs prescribed-speed check offline for the full line; (3) review/merge or redo T99 and continue T100-T102, T108 one by one with a cross-check after each; (4) CARLA a_y source for the filter (D23); (5) T104 manual IEEE Xplore/Scopus/Scholar check; (6) V6 validity, RTI/SQP failures (G7), UKF bias with the default plant; (7) T106 advisor report (Vietnamese docx), T90 only with its own prereg tag.
- Cross-check state: pass 9 passed for IDs, decisions and statuses (a)(c)(d) and (b)(e) after the fixes; edits made after it (T97 stage 3 note, proposal follow-ups) were not re-reviewed independently.

## Handover 2026-11-05 (goal paused by the user)
- prereg-v4 registered (local tag, `configs/prereg.yaml`; D9 revised, D12-D20, D26 chosen by the assistant under user delegation; user has NOT yet accepted the specific values, least certain ones in docs/prereg/2026-11_prereg_v4_proposal.md sec. 15).
- Merged since: T97 stage 2 (oscillation report, sec. 8), T110 rate limit min(a_dec, mu_bar g), T111 rain mu mapping, T112 plant stiffness law (`fixed_B` default, `constant`), T113/T114 H8/H3/H9 builders, T115 metrics and verdict code (`src/inmpc/prereg_v4.py`), T116 Q/R builder (partial), T117 friction-draw switch. Suite with acados env: 554 passed, 49 xfailed.
- T118 merged (597 passed, 49 xfailed with acados env); T116 closed with it. All code tasks T110-T118 are done; T99-T102 and T108 are code-unblocked but have not been run (need user approval for runs; CARLA only with one server and GUI).
- Oscillation (T97): ey_p95 about 6 m vs 0.23 m for KMB, 46 % of time outside the lane; stage-1 "ay/(mu g) 1.2-1.3" was vx*r/(mu g) (actual tyre a_y max about 0.95 mu g). Only a_lat reference 1.5 with matched grip removes it (6/6 at 90 s, 5/6 at 300 s); cause (tyre a_y reaching the controller bound) is a correlation. Changing the reference a_lat changes the reference speed, needs a user decision; plan: re-check the criterion after T118 with the filter in the loop.
- T97 stage 3 (2026-11-06): a_lat 2.0 and 3.5 did not remove the oscillation with the filter on; theta_hat collapses below the floor in 41-69 % of INMPC time. Stage-2 F2 result (3/6 at a_lat 2.0 without filter) does not reproduce with the filter. Filter-in-loop defect is now the leading suspect; see open-questions.
- Next order: T99 (H8), T100 (H3), T101 (H9), T102, T108 (Python first; CARLA one server, GUI, only when the user approves) -> T106 advisor report -> T90 only after the user revises proposal sec. 7.6.
- Proposal edited 2026-11-06 by the assistant under user instruction: (5.22) measured a_y with disturbance force, (4.7) fixed-horizon form, sec. 7.6 one map with no generality claim, tau_r validity in (3.2), sec. 1 novelty wording with refs [11]-[15]. Spec/plan/task follow-ups: T104 manual IEEE Xplore/Scopus/Scholar check still open; T90 now needs only its own prereg tag.

## Code and data state (2026-11-03)
- Repo on GitHub ntdev204/autonomous-vehicles, branch main is the working line. Structure: src/inmpc (models/, controllers/, carla_bridge, delay, disturbance, scenarios, experiment, metrics, identification, config), configs/ (default.yaml, campaign.yaml, vehicles/lincoln_mkz_2020.yaml), scripts/ (extract_vehicle, identify, run_experiment, campaign, report_tables, build_dataset).
- Vehicle parameters are real CARLA values (API + in-sim identification), file configs/vehicles/lincoln_mkz_2020.yaml with provenance. Measured: m=1696 kg, lf=1.178, lr=1.682, Iz~1970, Cf~105 kN/rad, Cr~93 kN/rad, mu~1.39, tau_a~0.04 s, steering applied within one tick (tau_delta clamped to dt), steering rate ~2.66 rad/s, resistance traction-equivalent c0~2.71 m/s2.
- Rules from user: no comments/docstrings in code, no hardcoded parameters (everything in configs/), 15 m/s is the REFERENCE speed, control variables are acceleration and steering, state is CARLA ground truth + injected delay/noise/disturbances, vehicle starts exactly on the line start with straight wheels, data of every run saved (csv + npz) as future training dataset.
- Disturbance profiles: none, realistic, severe, rain, heavy_rain (aerodynamic wind from wind speed, absolute wet friction mu_abs for rain, weather, sensor noise/bias/dropout, payload mass). Friction and mass are applied once before reset (changing physics mid-run zeroes the velocity).
- First checks (lien_tuc 15 m/s, INMPC, seed 1): all profiles keep the lane (ey_mean 5-11 cm). Rain profiles were redefined on 2026-11-03 (mu_abs 0.5-0.7 and 0.3-0.5, mean crosswind) and NOT yet run.
- Data folder data/ was wiped; no benchmark results exist yet.

## Papers / chapters
| Item | Target | Status | Updated |
|---|---|---|---|
| Simulation report (docx with figures) | advisor | not started | 2026-11-03 |

## Done
- Real-parameter extraction + identification pipeline; controllers split into modules; disturbance + rain; dataset export; campaign matrix.

## In progress
- Benchmark run (group report_core, ~192 runs ~5 h) then report.

## Blocked
- (none)

## Next actions
1. New session: read CLAUDE.md + all project-memory, check `git status`, check the CARLA server on port 2000 (start it if missing).
2. Run `python scripts/campaign.py timing` then `python scripts/campaign.py report_core` (sequential, one server). Watch logs in data/_logs; failed jobs rerun by repeating the command.
3. `python scripts/report_tables.py` -> reports/sim_results (tables, F1-F6 figures, verdicts.json).
4. Write the Vietnamese docx report (docx skill) with real figures, honest verdicts for H1-H4, limits (single seed counts, ground-truth state, friction fixed per run, no aquaplaning, assumed Pacejka shape, drive_front_ratio assumed), proposal.docx cross-check.
5. Not yet: further optimisation of controllers.
