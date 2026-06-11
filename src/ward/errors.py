"""Centralised error helpers for ward.

Keeps message-and-exit logic in one place so every command emits
identically-formatted output to stderr.
"""

from __future__ import annotations

import sys
from typing import NoReturn


def die(code: int, message: str) -> NoReturn:
    """Print message to stderr and exit with the given code."""
    print(message, file=sys.stderr)
    sys.exit(code)


def info(message: str) -> None:
    """Print an informational message to stdout."""
    print(message)
