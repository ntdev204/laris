"""The solver's refusals: `code` is a tool error type; `message` never quotes the input."""

CODES = ("invalid_arguments", "input_too_large", "rejected", "timed_out")


class SolverError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        if code not in CODES:
            code = "rejected"
        self.code, self.message = code, message
