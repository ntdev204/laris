"""Runs one problem in a forked worker with a wall-clock and an address-space ceiling.

The tool route calls the solver from a thread pool, where a signal-based timeout does not work, and
a symbolic step can run for minutes or allocate without bound on a hostile input. Each call is
therefore a child of a `forkserver` that has already imported SymPy (start-up cost paid once): the
child sets `RLIMIT_AS` to `memory_bytes`, solves, and sends the answer through a pipe; the parent
kills it after `timeout_s`. Nothing is shared between calls.
"""

from __future__ import annotations

import multiprocessing
import threading
from typing import Any, Dict

from laris.model.solver.errors import SolverError
from laris.model.solver.settings import SolverSettings

_LOCK = threading.Lock()
_CONTEXT = None


def _context():
    global _CONTEXT
    with _LOCK:
        if _CONTEXT is None:
            ctx = multiprocessing.get_context("forkserver")
            ctx.set_forkserver_preload(
                ["sympy", "sympy.physics.units", "laris.model.solver.engine"]
            )
            _CONTEXT = ctx
        return _CONTEXT


def _child(conn, problem: Dict[str, Any], settings: SolverSettings) -> None:
    try:
        if settings.memory_bytes:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (settings.memory_bytes, settings.memory_bytes))
        from laris.model.solver.engine import solve

        conn.send(("ok", solve(problem, settings)))
    except SolverError as exc:
        conn.send(("error", exc.code, exc.message))
    except MemoryError:
        conn.send(("error", "input_too_large", "the problem needs more memory than a call may use"))
    except RecursionError:
        conn.send(("error", "input_too_large", "the expression is nested too deeply"))
    except Exception as exc:  # the class only: its text may quote the input
        conn.send(
            ("error", "rejected", f"the solver could not handle the problem ({type(exc).__name__})")
        )
    finally:
        conn.close()


def run(problem: Dict[str, Any], settings: SolverSettings) -> Dict[str, Any]:
    """The answer of `engine.solve`, computed in a worker; raises `SolverError`."""
    if not settings.isolate:
        from laris.model.solver.engine import solve

        return solve(problem, settings)
    ctx = _context()
    receive, send = ctx.Pipe(duplex=False)
    worker = ctx.Process(target=_child, args=(send, problem, settings), daemon=True)
    worker.start()
    send.close()
    try:
        if not receive.poll(settings.timeout_s):
            raise SolverError("timed_out", f"the solver took longer than {settings.timeout_s:g} s")
        try:
            message = receive.recv()
        except EOFError:
            raise SolverError(
                "input_too_large", "the solver worker stopped (memory or resource limit)"
            ) from None
    finally:
        receive.close()
        if worker.is_alive():
            worker.kill()
        worker.join(5)
    if message[0] == "ok":
        return message[1]
    raise SolverError(message[1], message[2])
