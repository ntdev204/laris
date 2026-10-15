"""Canonical exception and error hierarchies for LARIS."""

class LarisError(Exception):
    """Base exception class for all LARIS system failures."""
    pass


class ProvenanceViolationError(LarisError):
    """Raised when an extracted claim or report assertion lacks verified evidence coordinates."""
    pass


class EpistemicOverreachError(LarisError):
    """Raised when a correlational finding is described as causal, or absence of evidence is claimed as negation."""
    pass


class HardwareBudgetExceededError(LarisError):
    """Raised when an operation would exceed the 14.5 GB safety threshold on the RTX 5070 Ti."""
    pass


class ModuleContractViolationError(LarisError):
    """Raised when input or output data violates the interface contract of a module boundary."""
    pass


class CyclicExecutionError(LarisError):
    """Raised when an agent enters an infinite recursion or dispatches duplicate tool calls."""
    pass
