"""Training authorization gate and governance enforcement.

Adheres to ADR-007, ADR-008, and DOC-PLAN-TRAIN-001.
Enforces strict training freeze by default across all execution contexts.
Transitioning to authorized training requires explicit repository owner authorization,
verifiable via environment variables or explicit configuration overrides.
"""

import os
from contextlib import contextmanager
from typing import Generator

from laris.core.errors import TrainingExecutionProhibitedError

ENV_TRAINING_AUTHORIZED = "LARIS_TRAINING_AUTHORIZED"
ENV_TOKENIZER_TRAINING_AUTHORIZED = "LARIS_TOKENIZER_TRAINING_AUTHORIZED"


def is_training_authorized() -> bool:
    """Checks whether full neural model training is formally authorized.

    Defaults to False. Requires LARIS_TRAINING_AUTHORIZED="1" in environment.
    """
    return os.environ.get(ENV_TRAINING_AUTHORIZED, "").strip() == "1"


def is_tokenizer_training_authorized() -> bool:
    """Checks whether subword tokenizer fitting is formally authorized.

    Authorized if LARIS_TOKENIZER_TRAINING_AUTHORIZED="1" or LARIS_TRAINING_AUTHORIZED="1".
    """
    if is_training_authorized():
        return True
    return os.environ.get(ENV_TOKENIZER_TRAINING_AUTHORIZED, "").strip() == "1"


def assert_training_authorized(context: str = "neural model training") -> None:
    """Enforces absolute prohibition barrier unless explicitly authorized by owner."""
    if not is_training_authorized():
        raise TrainingExecutionProhibitedError(
            f"ABSOLUTE TRAINING PROHIBITION: Execution of {context} is prohibited. "
            f"Adheres to ADR-008 and Milestone M11 governance freeze. "
            f"To authorize training on verified target hardware, set {ENV_TRAINING_AUTHORIZED}=1."
        )


def assert_tokenizer_training_authorized(context: str = "subword tokenizer fitting") -> None:
    """Enforces prohibition barrier on tokenizer training unless explicitly authorized."""
    if not is_tokenizer_training_authorized():
        raise TrainingExecutionProhibitedError(
            f"ABSOLUTE TOKENIZER TRAINING PROHIBITION: Execution of {context} is prohibited. "
            f"Adheres to ADR-008 and Milestone M11 governance freeze. "
            f"To authorize tokenizer training, set {ENV_TOKENIZER_TRAINING_AUTHORIZED}=1."
        )


@contextmanager
def temporary_training_authorization(
    enable: bool = True,
    tokenizer_only: bool = False,
) -> Generator[None, None, None]:
    """Scoped context manager for authorized testing and controlled execution routines."""
    var_name = ENV_TOKENIZER_TRAINING_AUTHORIZED if tokenizer_only else ENV_TRAINING_AUTHORIZED
    original = os.environ.get(var_name)
    try:
        if enable:
            os.environ[var_name] = "1"
        else:
            os.environ[var_name] = "0"
        yield
    finally:
        if original is not None:
            os.environ[var_name] = original
        else:
            os.environ.pop(var_name, None)
