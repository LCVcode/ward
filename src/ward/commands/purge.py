"""``ward purge`` — destroy the workshop, keeping host files intact.

All project files (source code, AGENTS.md, workshop.yaml) live on the
host filesystem and are unaffected by removal.
"""

from __future__ import annotations

from pathlib import Path

from ward import workshop
from ward.errors import die, info
from ward.preflight import Tier, run_preflight

EXIT_REMOVAL_FAILED = 76

# Substrings that indicate the container is locked (active processes
# inside the VM holding file handles, namespaces, etc.).
_LOCK_MARKERS = (
    "locked",
    "in use",
    "busy",
    "device or resource busy",
)


def run() -> None:
    run_preflight(tier=Tier.MINIMAL)
    cwd = Path.cwd()

    state, _ = workshop.query_state(cwd)
    if state in (workshop.State.MISSING, workshop.State.OFF):
        info("[INFO] No active container found to purge for this project workspace.")
        return

    # `workshop remove` rejects Off/Pending; for Ready/Waiting we stop first
    # so removal proceeds cleanly without forcing the user to run `ward down`.
    if state in (workshop.State.READY, workshop.State.WAITING):
        workshop.stop(cwd)

    result = workshop.remove(cwd)
    if not result.ok:
        message = (
            "[ERROR] Infrastructure removal failed. An active process inside "
            "the VM may be locking files. Terminate active sessions first via "
            "'ward down'."
        )
        if result.stderr.strip():
            message += f"\n{result.stderr.strip()}"
        die(EXIT_REMOVAL_FAILED, message)

    info("[INFO] Ward container purged. Host project files are untouched.")
