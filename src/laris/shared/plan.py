"""The agent's plan: a short list of steps with a status, shown to the user and kept across turns.

The plan belongs to the loop, not to a prompt: the model changes it through the `update_plan`
tool; the harness shows it, remembers it in the conversation and refuses to call a goal finished
while steps are still open.
"""

from typing import Any, Dict, List, Optional

from laris.shared.config.runtime_schemas import PlanConfig

PLAN_TOOL = "update_plan"
STATUSES = ("pending", "in_progress", "done", "failed", "skipped")
CLOSED = {"done", "skipped", "failed"}  # nothing more to do on these; failures are reported
MARKS = {"pending": " ", "in_progress": "~", "done": "x", "failed": "!", "skipped": "-"}


class PlanError(ValueError):
    """The model sent a plan the harness cannot accept."""


class Plan:
    def __init__(self, steps: Optional[List[Dict[str, str]]] = None) -> None:
        self.steps: List[Dict[str, str]] = [dict(s) for s in steps or []]

    # -- state -----------------------------------------------------------------------------
    def __bool__(self) -> bool:
        return bool(self.steps)

    def open_steps(self) -> List[str]:
        return [s["text"] for s in self.steps if s["status"] not in CLOSED]

    def failed_steps(self) -> List[str]:
        return [s["text"] for s in self.steps if s["status"] == "failed"]

    def complete(self) -> bool:
        return bool(self.steps) and not self.open_steps()

    def to_list(self) -> List[Dict[str, str]]:
        return [dict(s) for s in self.steps]

    # -- changes ---------------------------------------------------------------------------
    def update(self, arguments: Dict[str, Any], cfg: PlanConfig) -> None:
        """Replace the plan with `steps`: [{text, status}]. Strict: nothing is guessed."""
        raw = arguments.get("steps")
        if not isinstance(raw, list) or not raw:
            raise PlanError("steps must be a non-empty list")
        if len(raw) > cfg.max_steps:
            raise PlanError(f"at most {cfg.max_steps} steps")
        steps = []
        for item in raw:
            if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                raise PlanError("every step needs text")
            status = str(item.get("status", "pending"))
            if status not in STATUSES:
                raise PlanError(f"status must be one of {', '.join(STATUSES)}")
            steps.append({"text": str(item["text"]).strip()[: cfg.step_chars], "status": status})
        self.steps = steps

    def add_auto(self, text: str, cfg: PlanConfig) -> int:
        """A step the harness records itself when the model started acting without a plan."""
        self.steps.append({"text": text[: cfg.step_chars], "status": "in_progress"})
        return len(self.steps) - 1

    def mark(self, index: int, status: str) -> None:
        if 0 <= index < len(self.steps):
            self.steps[index]["status"] = status

    # -- views -----------------------------------------------------------------------------
    def render(self) -> str:
        return "\n".join(
            f"{i}. [{MARKS[s['status']]}] {s['text']} ({s['status']})"
            for i, s in enumerate(self.steps, 1)
        )

    def summary_lines(self) -> List[str]:
        return [f"- [{MARKS[s['status']]}] {s['text']}" for s in self.steps]
