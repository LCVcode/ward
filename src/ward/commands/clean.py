"""``ward clean`` — remove ward's files from the project directory.

The inverse of ``ward init``. Deletes the ward-managed artifacts
(``workshop.yaml`` and the ``.workshop.lock`` state file) so a
repository can be fully de-warded.

``AGENTS.md`` is intentionally left untouched: users may have
customised it with project-specific context that is independent of
ward and should not be silently destroyed.

Defensive behaviour:
- Refuses to clean while a container still exists for this project,
  to avoid orphaning a live VM whose manifest you just deleted. The
  user is directed to run ``ward purge`` first.
- Operates purely on the host filesystem; it does not require the
  workshop/opencode binaries. The orphan guard is best-effort and is
  skipped when the workshop CLI is unavailable.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ward import manifest, workshop
from ward.commands.init import GITIGNORE_BLOCK_BEGIN, GITIGNORE_BLOCK_END
from ward.errors import die, info
from ward.preflight import Tier, run_preflight

EXIT_CONTAINER_EXISTS = 80

# Ward-managed files, in removal-report order.
_WARD_FILES = (
    manifest.MANIFEST_FILENAME,  # workshop.yaml
    ".workshop.lock",  # workshop CLI local state pin
)


def _orphan_guard(project_dir: Path) -> None:
    """Refuse to clear while a container still exists for this project.

    Best-effort: if the workshop CLI is not installed we cannot query
    state, and a container cannot meaningfully exist without it, so the
    guard is skipped.
    """
    if shutil.which("workshop") is None:
        return

    state, _ = workshop.query_state(project_dir)
    if state in (
        workshop.State.STOPPED,
        workshop.State.READY,
        workshop.State.WAITING,
        workshop.State.PENDING,
    ):
        die(
            EXIT_CONTAINER_EXISTS,
            "[ERROR] A ward container still exists for this project "
            f"(status: {state.value}). Run 'ward purge' to destroy it before "
            "clearing the ward files, otherwise the container would be "
            "orphaned.",
        )


def run() -> None:
    run_preflight(tier=Tier.MINIMAL)
    cwd = Path.cwd()

    _orphan_guard(cwd)

    removed: list[str] = []
    for name in _WARD_FILES:
        target = cwd / name
        if target.exists():
            target.unlink()
            removed.append(name)

    if not removed:
        info("[INFO] No ward files found in this project workspace.")
        return

    for name in removed:
        info(f"[INFO] Removed {name}.")

    _clean_gitignore(cwd)

    info(
        "[INFO] ward files cleaned. Run 'ward init' to re-provision this "
        "project."
    )


def _clean_gitignore(project_dir: Path) -> None:
    """Remove the ward-managed block from .gitignore if present."""
    target = project_dir / ".gitignore"
    if not target.exists():
        return
    existing = target.read_text(encoding="utf-8")
    if GITIGNORE_BLOCK_BEGIN not in existing:
        return
    # Strip the block including its surrounding newline, leaving the rest.
    cleaned = re.sub(
        rf"\n?{re.escape(GITIGNORE_BLOCK_BEGIN)}\n.*?{re.escape(GITIGNORE_BLOCK_END)}\n?",
        "",
        existing,
        flags=re.DOTALL,
    )
    target.write_text(cleaned, encoding="utf-8")
    info("[INFO] Removed ward entries from .gitignore.")
