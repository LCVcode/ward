"""Host pre-flight dependency engine.

Runs before every ward sub-command to verify required host-side binaries
and configuration directories are present. Failures are *collected* (not
fail-fast) so the user sees every missing prerequisite in a single
invocation and can fix the host once rather than iteratively.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# Exit codes — must match SPEC.md section 4.
EXIT_MISSING_BINARY = 127
EXIT_MISSING_CONFIG = 65

OPENCODE_CONFIG_DIR = Path("~/.config/opencode").expanduser()


@dataclass(frozen=True)
class PreflightFailure:
    """A single failed precondition: exit code + actionable message."""

    code: int
    message: str


def _binary_failure(name: str, install_hint: str) -> PreflightFailure | None:
    if shutil.which(name) is None:
        return PreflightFailure(EXIT_MISSING_BINARY, install_hint)
    return None


def _config_dir_failure() -> PreflightFailure | None:
    if not OPENCODE_CONFIG_DIR.is_dir():
        return PreflightFailure(
            EXIT_MISSING_CONFIG,
            "[ERROR] No local OpenCode configuration found at "
            "~/.config/opencode. Run 'opencode /connect' on your host machine "
            "first to authenticate your backend accounts.",
        )
    return None


def collect_failures() -> list[PreflightFailure]:
    """Return every failed host-precondition check, in canonical order."""
    candidates = (
        _binary_failure(
            "workshop",
            "[ERROR] Canonical Workshop CLI ('workshop') is not installed on "
            "the host. Please install it via snap: 'sudo snap install workshop'.",
        ),
        _binary_failure(
            "opencode",
            "[ERROR] OpenCode CLI ('opencode') is missing from the host path. "
            "Install it via your host package manager to establish global "
            "configuration paths.",
        ),
        _config_dir_failure(),
    )
    return [f for f in candidates if f is not None]


def report_and_exit(failures: list[PreflightFailure]) -> None:
    """Print every failure to stderr and exit with the first failure's code.

    Using the first failure's code keeps scripted callers' behaviour
    deterministic when exactly one precondition is broken (the common
    case), while still showing the user every missing piece in
    multi-failure scenarios.
    """
    if not failures:
        return
    for failure in failures:
        print(failure.message, file=sys.stderr)
    sys.exit(failures[0].code)


def run_preflight() -> None:
    """Verify host dependencies. Exits the process if any check fails."""
    report_and_exit(collect_failures())
