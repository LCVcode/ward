"""``ward status`` — report the workshop's state without entering it.

A read-only inspection command. Unlike ``up``/``down``/``purge`` it never
mutates the workshop; it only queries lifecycle state (via
``workshop list``) and, when the workshop is running, the SSH-agent
interface connection (via ``workshop connections``).

It runs the MINIMAL preflight tier (binary + lxd group only) so that
status remains usable even when the host's SSH/git setup is broken — the
same rationale that keeps the teardown commands minimal.

The SSH-agent report is best-effort: the exact column layout of
``workshop connections`` is an upstream concern, so this command only
asserts "connected" / "not connected" when the relevant row is
unambiguous, and otherwise echoes the raw output rather than guessing.
"""

from __future__ import annotations

from pathlib import Path

from ward import workshop
from ward.commands.up import EXIT_STATUS_QUERY_FAILED
from ward.errors import die, info
from ward.preflight import Tier, run_preflight

# States in which the workshop is running and ``exec``/``connections`` are
# meaningful. Outside these, querying interface connections is pointless.
_RUNNING_STATES = (workshop.State.READY, workshop.State.WAITING)

# Substring identifying the ssh-agent interface row in `workshop
# connections` output. Matched case-insensitively against each line.
_SSH_AGENT_MARKER = "ssh-agent"


def _report_ssh_agent(project_dir: Path) -> None:
    """Best-effort report of the ssh-agent plug's connection status.

    A connected plug shows a real slot in the slot column; an unconnected
    one shows ``-``. We only assert a conclusion when the ssh-agent row is
    found and unambiguous; otherwise we print the raw output so the
    operator can interpret it, rather than risk a wrong claim.
    """
    result = workshop.connections(project_dir)
    if not result.ok:
        info(
            "[INFO] Could not query interface connections "
            "('workshop connections ward' failed)."
        )
        return

    rows = [
        line
        for line in result.stdout.splitlines()
        if _SSH_AGENT_MARKER in line.lower()
    ]
    if len(rows) != 1:
        # Zero or multiple matches — don't guess. Show what we have.
        info("[INFO] Interface connections:")
        info(result.stdout.rstrip() or "(no connections reported)")
        return

    # A trailing '-' token means the slot is empty (not connected).
    if rows[0].split()[-1] == "-":
        info(
            "[INFO] SSH agent: not connected. Run 'ward up' to wire it "
            "(git over SSH inside the sandbox will fail until then)."
        )
    else:
        info("[INFO] SSH agent: connected.")


def run() -> None:
    run_preflight(tier=Tier.MINIMAL)
    cwd = Path.cwd()

    state, result = workshop.query_state(cwd)

    if state is workshop.State.MISSING:
        info(
            "[INFO] No ward workshop is provisioned for this project. "
            "Run 'ward init' to set one up."
        )
        return

    if state is workshop.State.UNKNOWN:
        die(
            EXIT_STATUS_QUERY_FAILED,
            "[ERROR] Failed to query Canonical Workshop status. Verify your "
            "user belongs to the 'lxd' group or try restarting the system "
            "container daemon."
            + (f"\n{result.stderr.strip()}" if result.stderr.strip() else ""),
        )

    info(f"[INFO] ward workshop status: {state.value}")

    if state in _RUNNING_STATES:
        _report_ssh_agent(cwd)
    elif state in (workshop.State.OFF, workshop.State.STOPPED):
        info("[INFO] Workshop is not running. Run 'ward up' to launch it.")
