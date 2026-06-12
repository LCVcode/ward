"""Thin, defensive wrapper around the ``workshop`` CLI.

All interactions with Canonical Workshop flow through this module so that
parsing of state, retry semantics, and error classification live in one
auditable place.

State discovery uses ``workshop list --no-headers`` rather than
``workshop status`` (which does not exist) or ``workshop info`` (which
errors with exit 1 when the workshop has not yet been launched, making
state-vs-error disambiguation noisier).
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence

# The container name is hardcoded by SPEC.md — ward owns exactly one workshop
# named "ward" per project directory.
WORKSHOP_NAME = "ward"


class State(str, Enum):
    """Lifecycle states recognised by Canonical Workshop.

    Values mirror the literal strings printed by ``workshop list``.
    """

    OFF = "Off"           # Not launched
    PENDING = "Pending"   # Transitional (launching/refreshing)
    STOPPED = "Stopped"   # Launched but not running
    READY = "Ready"       # Running and accepting actions
    WAITING = "Waiting"   # Running but waiting on something
    UNKNOWN = "Unknown"   # Could not classify the printed status
    MISSING = "Missing"   # No workshop.yaml in the project (not a project)


@dataclass
class CommandResult:
    """Captured outcome of a workshop subprocess invocation."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def combined(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


def _run(
    args: Sequence[str],
    cwd: Path | None = None,
    timeout: float | None = None,
) -> CommandResult:
    """Invoke a workshop command, capturing stdout/stderr.

    Never raises on non-zero exit — callers interpret the result so that
    error messages can be tailored to the failing lifecycle stage.
    """
    proc = subprocess.run(
        ["workshop", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


# ---------- state discovery ----------

# Substrings observed in stderr when no project file is present.
_MISSING_PROJECT_MARKERS = (
    "not a project",
    "no workshop files",
)


def _looks_like_missing_project(result: CommandResult) -> bool:
    text = result.combined.lower()
    return any(marker in text for marker in _MISSING_PROJECT_MARKERS)


def query_state(project_dir: Path) -> tuple[State, CommandResult]:
    """Return the lifecycle state for ward's workshop in ``project_dir``.

    The caller receives both the parsed state and the raw command result
    so it can surface daemon diagnostics in its own error message.
    """
    result = _run(["list", "--no-headers", "-p", str(project_dir)])

    if not result.ok:
        if _looks_like_missing_project(result):
            return State.MISSING, result
        return State.UNKNOWN, result

    # `workshop list --no-headers` prints lines of the form:
    #     ward      Off     -
    # Whitespace-delimited; second column is the status.
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == WORKSHOP_NAME:
            status_token = parts[1]
            try:
                return State(status_token), result
            except ValueError:
                return State.UNKNOWN, result

    # The project exists but no row for our workshop name was found.
    return State.MISSING, result


# ---------- lifecycle actions ----------

def launch(project_dir: Path, timeout: float | None = None) -> CommandResult:
    """Construct the workshop from its manifest. Auto-starts on success."""
    return _run(["launch", WORKSHOP_NAME, "-p", str(project_dir)], timeout=timeout)


def start(project_dir: Path, timeout: float | None = None) -> CommandResult:
    return _run(["start", WORKSHOP_NAME, "-p", str(project_dir)], timeout=timeout)


def stop(project_dir: Path, timeout: float | None = None) -> CommandResult:
    return _run(["stop", WORKSHOP_NAME, "-p", str(project_dir)], timeout=timeout)


def remove(project_dir: Path, timeout: float | None = None) -> CommandResult:
    return _run(["remove", WORKSHOP_NAME, "-p", str(project_dir)], timeout=timeout)


def remount(
    plug: str,
    source: Path,
    project_dir: Path,
    timeout: float | None = None,
) -> CommandResult:
    """Mount ``source`` (host path) onto the given workshop/SDK plug.

    ``plug`` is the qualified plug name without the workshop prefix, e.g.
    ``opencode:opencode-config``.
    """
    target = f"{WORKSHOP_NAME}/{plug}"
    return _run(
        ["remount", target, str(source), "-p", str(project_dir)],
        timeout=timeout,
    )


def connect(
    plug: str,
    project_dir: Path,
    timeout: float | None = None,
) -> CommandResult:
    """Connect a plug to its default slot.

    ``plug`` is the qualified plug name without the workshop prefix, e.g.
    ``opencode:ssh-agent``. Workshop resolves the slot by interface when no
    explicit slot is supplied.
    """
    target = f"{WORKSHOP_NAME}/{plug}"
    return _run(["connect", target, "-p", str(project_dir)], timeout=timeout)


def connections(
    project_dir: Path,
    timeout: float | None = None,
) -> CommandResult:
    """List interface connections for ward's workshop in ``project_dir``."""
    return _run(
        ["connections", WORKSHOP_NAME, "-p", str(project_dir)],
        timeout=timeout,
    )


def refresh(
    project_dir: Path,
    timeout: float | None = None,
) -> CommandResult:
    """Refresh ward's workshop in ``project_dir`` against its current definition."""
    return _run(
        ["refresh", WORKSHOP_NAME, "-p", str(project_dir)],
        timeout=timeout,
    )


# ---------- in-workshop file writes ----------

def write_file(
    target_path: str,
    content: str,
    project_dir: Path,
    timeout: float | None = None,
) -> CommandResult:
    """Write ``content`` to ``target_path`` inside the workshop.

    Runs ``workshop exec -I -p <project_dir> ward -- tee <target_path>``
    non-interactively, feeding ``content`` on stdin. The workshop must be
    ``Ready`` (or ``Waiting``) for ``exec`` to be accepted.

    ``tee`` echoes stdin to stdout as well; that captured output is ignored
    by callers, which only inspect the returned :class:`CommandResult`.

    Flag ordering follows the documented form ``workshop exec [flags]
    <WORKSHOP> -- <cmd>``: all flags precede the positional workshop name.
    """
    proc = subprocess.run(
        [
            "workshop", "exec", "-I",
            "-p", str(project_dir),
            WORKSHOP_NAME,
            "--", "tee", target_path,
        ],
        input=content,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


def exec_capture(
    argv: Sequence[str],
    project_dir: Path,
    timeout: float | None = None,
) -> CommandResult:
    """Run an ad-hoc command inside the workshop, capturing stdout/stderr.

    Runs ``workshop exec -I -p <project_dir> ward -- <argv...>``. Intended
    for short, non-interactive probes (e.g. verifying that a written file
    is readable). The workshop must be ``Ready`` or ``Waiting``.
    """
    proc = subprocess.run(
        [
            "workshop", "exec", "-I",
            "-p", str(project_dir),
            WORKSHOP_NAME,
            "--", *argv,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


# ---------- handoff ----------

def run_action_argv(action: str) -> list[str]:
    """Build the argv used to hand off control to ``workshop run``.

    A separate function (returning argv rather than executing) keeps the
    handoff cleanly mockable in tests and lets the caller decide between
    ``os.execvp`` (replace process) and ``subprocess.run`` (wrap process).
    """
    return ["workshop", "run", WORKSHOP_NAME, action]


def quote(args: Sequence[str]) -> str:
    """Render a workshop invocation for diagnostic logging."""
    return " ".join(shlex.quote(a) for a in args)
