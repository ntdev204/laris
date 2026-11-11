# Project Context

> Purpose: stable facts about the researcher, the thesis, the lab, target venues, deadlines, and tools.
> Update when: a placeholder is filled, a venue or deadline is chosen or changes, the toolchain changes.
> Rules: facts stated by the user or verified only. Mark guesses as `(assumed)`. Date every change (YYYY-MM-DD).
> No personal identifiers (student/ID numbers, phone, email) and nothing the user marks confidential.

Last updated: 2026-11-03

## Researcher
- Name: Thiện. PhD student (NCS). Writes in Vietnamese; Claude replies in Vietnamese.
- Field: robotics and autonomous systems.
- Topic: kinematic and dynamic modeling and control of Ackermann-steered autonomous vehicles
  (nonlinear models, linearization, discretization, proofs supporting control design).
- Reports to an advisor.

## Advisor and lab
- Advisor name: [PLACEHOLDER]
- Lab / group: [PLACEHOLDER]
- Meeting cadence and preferred report format: [PLACEHOLDER]

## Thesis
- Working title: [PLACEHOLDER]
- Stage (e.g., proposal, year 2, writing): [PLACEHOLDER]
- Planned chapter structure: [PLACEHOLDER]

## Papers in progress
- [PLACEHOLDER: title, target venue, status] (track status in research-state.md)

## Target venues
- Confirmed targets: [PLACEHOLDER]
- Candidates mentioned in earlier conversations, NOT yet confirmed for this project:
  IEEE Transactions on Fuzzy Systems, IEEE Robotics and Automation Letters (RA-L),
  IEEE Transactions on Intelligent Transportation Systems (T-ITS).
- Venue requirements are always verified from official author guidelines before use.

## Deadlines
- [PLACEHOLDER: YYYY-MM-DD, item]

## Format preferences
- Preferred citation style: [PLACEHOLDER]
- Manuscripts: LaTeX or Word? [PLACEHOLDER] (default per CLAUDE.md: LaTeX for manuscripts, docx for reports)
- Reports: when a sample report is provided, follow its style (mostly prose and bullet lists, few tables). (stated)
- Algorithm flowcharts: drawn in draw.io, column layout, straight connectors (no curved arrows),
  short natural-language labels with no code, variable, signal, or instruction names. (stated)

## Tools and environment
- OS: Linux (Ubuntu), shell bash; project path /home/vth/ws/autonomous-vehicles (verified 2026-11-03). The earlier "Windows" note was wrong.
- Python: venv ~/carla-env (python 3.10); packages casadi, numpy, pandas, scipy, matplotlib, pyyaml, carla 0.9.15. Install: `python -m pip install -e .[carla]`.
- Simulator: CARLA 0.9.15 at ~/CARLA_0.9.15, GUI server on port 2000 (`./CarlaUE4.sh -carla-rpc-port=2000 -quality-level=Low -windowed -ResX=1280 -ResY=720`, DISPLAY=:1). Several servers at once segfault: use ONE server. The user wants the GUI visible during runs.
- Do not `pkill -f` with a pattern that appears in your own command line (kills the shell); use PID lists.
- MATLAB removed from the repo (2026-11-03). TeX/Word/Zotero not tested.
- Reports: docx by default (docx skill), figures as PNG in reports/sim_results/.
