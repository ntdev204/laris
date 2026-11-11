# Notation and Conventions

> Purpose: keep symbols, frames, units, and document conventions identical across sessions and documents.
> Update when: a symbol, frame, unit, naming rule, equation-numbering rule, or citation style is fixed or changed.
> Rules: only record conventions the user confirmed or adopted. Proposed but unconfirmed symbols go under "Proposed".

Last updated: 2026-11-03

## Symbol table (adopted in code, follows proposal.docx)
| Symbol | Meaning | Unit | Notes |
|---|---|---|---|
| X, Y, psi | position of the CoG, yaw | m, rad | local right-handed frame, origin and x-axis at the start of the lane line |
| vx, vy, r | body-frame speeds, yaw rate | m/s, rad/s | |
| delta, delta_cmd | steering angle at front wheel, command | rad | state vector x=[X,Y,psi,vx,vy,r,delta], input u=[ax, delta_cmd] |
| ax | longitudinal acceleration command (traction, resistance subtracted in the model) | m/s2 | control variable, NOT speed |
| lf, lr, L, m, Iz | geometry/inertia | m, kg, kg m2 | CoG as reference point |
| Cf, Cr, mu | cornering stiffness, friction coefficient | N/rad, - | identified in CARLA |
| tau_delta, tau_a, tau_meas, tau_cmd | steering lag, accel lag, measurement delay, command delay | s | |
| lambda | heading-lag compensation of the kinematic model | s | lam*_N(v,N,h) as in proposal (4.8) |
| sigma(vx) | blend weight dynamic/kinematic | - | tanh with v_b=4, w=1 |
| ey | lateral error to path | m | positive to the left of the path |

## Coordinate frames
- Inertial/local: right-handed, psi counter-clockwise positive. CARLA world is left-handed: X=x, Y=-y, psi=-yaw; the bridge converts.
- Lane numbering for scenarios: 1 = leftmost lane, 5 = rightmost (Town06 route spawn 398, lane 3 at spawn).

## Units
- SI everywhere in code and configs; angles in rad (degrees only in HUD/plots).

## Naming conventions
- Controller labels: KIN, KMB, DYN, INMPC, INMPC-nc (no delay compensation).
- Run names: <scenario>_<tag>_v<speed>_<ctrl>_tc<tau_cmd>_comp<0|1>_<disturbance>_s<seed>.
- Continuous vs discrete: x(t) vs x_k as in proposal.

## Equations and theorems
- Follow proposal.docx numbering (5.1)-(5.17) for model equations.

## Citation style
- [PLACEHOLDER]
