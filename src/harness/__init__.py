"""Agent harness: configuration, prompt assembly, guards, policies, audit and verification.

The harness wraps the model loop with everything that must hold regardless of which model runs:
no hardcoded tunables, no leaking of internal information, untrusted-content handling, approvals,
verification and an audit trail. `HarnessRuntime` bundles these for the loop.
"""

from harness.runtime import HarnessRuntime

__all__ = ["HarnessRuntime"]
