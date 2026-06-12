"""``ward sleep`` — suspend the workshop, freeing CPU and memory."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ward import workshop
from ward.errors import die, info
from ward.preflight import Tier, run_preflight

EXIT_SUSPEND_FAILED = 75

# Generous timeout; LXD stop with cleanly-shutdown processes is fast,
# but cgroup teardown can occasionally drag.
STOP_TIMEOUT_SECONDS = 60.0


def run() -> None:
    run_preflight(tier=Tier.MINIMAL)
    cwd = Path.cwd()

    state, _ = workshop.query_state(cwd)
    if state in (workshop.State.MISSING, workshop.State.OFF, workshop.State.STOPPED):
        info("[INFO] Container 'ward' is already sleeping.")
        return

    try:
        result = workshop.stop(cwd, timeout=STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        die(
            EXIT_SUSPEND_FAILED,
            "[ERROR] Failed to suspend container 'ward'. Force execution "
            "termination via 'workshop stop --force ward'.",
        )

    if not result.ok:
        die(
            EXIT_SUSPEND_FAILED,
            "[ERROR] Failed to suspend container 'ward'. Force execution "
            "termination via 'workshop stop --force ward'."
            + (f"\n{result.stderr.strip()}" if result.stderr.strip() else ""),
        )

    info("[INFO] Container 'ward' is now sleeping.")
