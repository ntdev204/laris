---
document_id: "DOC-SPEC-DEV-001"
title: "LARIS Canonical Coding Standards & Engineering Principles"
document_type: "specification"
status: "APPROVED"
version: "1.0.0"
created_at: "2026-10-15"
updated_at: "2026-10-16"
owner: "LARIS Architecture Team"
reviewers: []
source_of_truth: true
related_documents:
  - "docs/development/DOCUMENTATION.md"
  - "docs/architecture/LAYER_ARCHITECTURE.md"
  - "docs/specifications/MODULE_CONTRACTS.md"
  - "docs/testing/TEST_STRATEGY.md"
decision_references:
  - "ADR-001"
  - "ADR-002"
  - "ADR-004"
  - "ADR-005"
  - "ADR-006"
  - "ADR-008"
change_summary: "Canonical specification of engineering principles, code design, type standards, testing, and review governance."
---

# LARIS Canonical Coding Standards & Engineering Principles

## 1. Overview & Authority

This document defines the canonical engineering principles, design rules, and implementation standards for all code in the LARIS repository (including data pipelines, language modeling, scientific NLP, retrieval, agent orchestration, adaptive execution, policy learning, and productization).

Every implementation subtask, pull request, and code review must adhere to these standards.

---

## 2. Core Engineering Principles

### 2.1 DRY (Don't Repeat Yourself)
- Keep each authoritative business rule, validation logic, and epistemic invariant in one authoritative module.
- Reuse established abstractions when they represent the exact same domain concept.
- Do not confuse similar-looking code with identical domain knowledge; if semantics or evolution paths differ, separate implementations are preferred.

### 2.2 KISS (Keep It Simple)
- Prefer the simplest design that completely and correctly satisfies current acceptance criteria.
- Minimize unnecessary layers of indirection, speculative configuration knobs, and complex control flow.
- Prefer readable, explicit code over clever metaprogramming or obscure one-liners.

### 2.3 YAGNI (You Aren't Gonna Need It)
- Implement only requirements directly specified by approved roadmap tasks and architectural contracts.
- Do not build speculative extension hooks, unused generic plugin engines, or future-proof abstractions without a concrete requirement.
- YAGNI must never be used as an excuse to omit required boundary validation or required acceptance tests.

### 2.4 WET / Rule of Three
- Do not introduce an abstraction prematurely when two code fragments merely look similar.
- Two occurrences may remain explicit when abstraction would obscure contextual differences.
- When a third genuinely equivalent occurrence emerges, extract a shared, well-tested helper or utility.

### 2.5 Separation of Concerns
- Maintain clean boundaries between domain models (`src/laris/core/`), layer processing logic (`src/laris/layers/`), external execution adapters, and CLI presentation.
- Do not mix business rules with infrastructure details or I/O handling.

### 2.6 SOLID Principles
- **Single Responsibility Principle (SRP):** Each class, function, and module must have one coherent reason to change.
- **Open/Closed Principle (OCP):** Components are open for extension via composition and explicit protocols, closed for modification of stable contracts.
- **Liskov Substitution Principle (LSP):** Subtypes and protocol implementers must honor base invariants, postconditions, and error semantics.
- **Interface Segregation Principle (ISP):** Keep interfaces, protocols, and abstract bases minimal and client-specific.
- **Dependency Inversion Principle (DIP):** High-level modules must depend on domain abstractions rather than concrete lower-level infrastructure implementations.

### 2.7 Architectural & Object Design
- **Law of Demeter:** Minimize deep navigation chains through unrelated objects (`a.b.c.d()`). Expose cohesive operations on owning entities.
- **Composition over Inheritance:** Prefer composition and explicit Python `Protocol` or `abc.ABC` definitions over deep class inheritance hierarchies.
- **High Cohesion, Low Coupling:** Keep logically related routines grouped together; prevent circular imports and hidden side effects across modules.
- **Encapsulation:** Hide internal mutable state; expose immutable dataclasses or strictly validated properties.
- **Principle of Least Astonishment:** Functions, defaults, and error types must behave predictably. Avoid hidden side effects, unexpected network access, or silent mutations.
- **Fail Fast:** Validate inputs, schemas, and preconditions at module entry points. Raise precise domain exceptions from `src/laris/core/errors.py`. Never silently swallow exceptions or substitute arbitrary defaults.

### 2.8 Clean Code, Naming & Simplicity
- **Domain-Specific Naming:** Use clear, unambiguous identifiers (`evidence_coordinate_id`, `epistemic_status`, `citation_span`). Avoid cryptic abbreviations.
- **Focused Functions:** Functions should accomplish one logical task. Extract helpers where it improves clarity, reduces branching, or isolates testable invariants.
- **Self-Explanatory Code:** Write expressive code. Use comments to document *why* a design choice was made, non-obvious algorithms, or hardware constraints, rather than stating what the code does.
- **Avoid Magic Values:** Use named constants, `Enum` classes, or dataclasses for domain thresholds, epistemic labels, and configuration parameters.
- **Tell, Don't Ask:** Encapsulate operations within entities that own the state, avoiding unnecessary exposure of internal state.

### 2.9 Additional Governance Principles
- **Avoid Premature Optimization:** Optimize only when backed by profiled bottlenecks or hardware budgets (e.g. 15.0 GB VRAM limit per ADR-005).
- **Principle of Least Privilege:** Components and tools execute with minimal necessary permissions. Never expose system credentials or unrestricted execution environments.
- **Convention over Configuration:** Follow standard repository layout, consistent function signatures, and established data contracts.
- **Design by Contract:** Enforce preconditions, postconditions, and invariants via schemas (`DATA_SCHEMAS.md`) and contracts (`MODULE_CONTRACTS.md`).
- **Boy Scout Rule:** Clean up small imperfections in touched code (e.g., formatting, typing, docstrings) within the focused PR scope without expanding into unrelated refactoring.

---

## 3. Principle Conflict Resolution Hierarchy

When engineering trade-offs arise, resolve conflicts using the following priority order:

1. **Correctness, security, privacy, and explicit acceptance criteria** (non-negotiable).
2. **Existing architectural contracts, epistemic invariants, and compatibility** (`MODULE_CONTRACTS.md`, `DATA_SCHEMAS.md`).
3. **Simplicity, clarity, and maintainability** (KISS over cleverness).
4. **Separation of concerns and clean dependency boundaries**.
5. **Reuse and abstraction** (DRY applied to genuine domain shared concepts).
6. **Performance optimization** supported by empirical profiling or hardware budgets.

---

## 4. Code Organization & Type Standards

### 4.1 Python Standards
- Target Python version: 3.10+ (supporting 3.10, 3.11, and 3.12).
- Strict typing with standard library `typing`, `dataclasses`, and `pydantic`.
- Type annotations required on all public functions, methods, and module exports.
- All code formatted and linted according to `ruff` rules configured in `pyproject.toml`.
- All code passes static analysis with `mypy src`.

### 4.2 Module Boundaries
- `src/laris/core/`: Common schemas, error hierarchy, logging, and mathematical utilities.
- `src/laris/layers/`: Layer implementations (0 through 11) adhering to `MODULE_CONTRACTS.md`.
- `tests/`: Organized into `tests/unit/`, `tests/contract/`, `tests/integration/`, and `tests/documentation/`.

---

## 5. Testing, Reproducibility & Quality Gates

Every implementation unit must satisfy all applicable local quality gates:

1. **Unit & Contract Tests:** `pytest` or `python -m unittest discover tests` with 100% pass rate.
2. **Documentation Quality Gate:** `python3 scripts/validate_docs.py` passes with zero errors.
3. **Linting:** `ruff check .` passes with zero violations.
4. **Type Checking:** `mypy src` passes with zero errors.
5. **Environment Smoke Test:** Clean setup verification in `./laris-env/`.
6. **Package Buildability:** `uv build` or `python -m build` completes cleanly without warnings.
7. **Empirical Evidence:** All benchmark or metric claims must be backed by committed, reproducible test outputs. Zero fabrication is tolerated.

---

## 6. Review & Acceptance Process

- **One Subtask, One PR:** Every implementation issue requires a dedicated feature branch and focused pull request targeting `develop`.
- **Review Loop:** Use the configured Code Review workflow. All actionable findings must be addressed on the same PR branch until resolved.
- **Merge Readiness:** A PR may only be merged when CI checks pass, review findings are resolved, and acceptance criteria are verified.
- **Traceability:** PR descriptions and commit messages must cite the relevant issue ID (`Refs #N`, `Closes #N`).
