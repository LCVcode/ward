"""``ward init`` — provision the project for ward.

Behaviour:
- Run a tailored, minimal precondition check. ``init`` only writes
  project files (it never touches the workshop daemon, lxd, or the SSH
  agent), so it validates exactly two things: that the current directory
  is a Git repository, and that any existing workshop.yaml is named
  ``ward``. All workshop/lxd/opencode/SSH plumbing is deferred to
  ``ward up``, which is the command that actually depends on it.
- Refuse to operate on an existing workshop.yaml whose name is not
  ``ward`` (exit 73).
- Generate the canonical workshop.yaml if absent.
- Seed a minimal AGENTS.md placeholder if absent.

All preconditions are checked before any file in the project directory
is created or modified. If any check fails, ward prints every failure
and exits without writing anything.
"""

from __future__ import annotations

from pathlib import Path

from ward import manifest
from ward.errors import info
from ward.preflight import (
    PreflightFailure,
    git_repo_failure,
    report_and_exit,
)

GITIGNORE_FILENAME = ".gitignore"
GITIGNORE_BLOCK_BEGIN = "# ward-managed-begin"
GITIGNORE_BLOCK_END = "# ward-managed-end"
GITIGNORE_BLOCK = (
    f"\n{GITIGNORE_BLOCK_BEGIN}\n"
    "workshop.yaml\n"
    ".workshop.lock\n"
    f"{GITIGNORE_BLOCK_END}\n"
)

EXIT_BAD_MANIFEST_NAME = 73

AGENTS_FILENAME = "AGENTS.md"
AGENTS_TEMPLATE = """\
# AGENTS.md

<!--
This file anchors long-term, version-controlled context for AI coding
agents (such as OpenCode) operating in this repository. Update it as
the project's conventions, dependencies, and goals evolve.
-->

## Project Overview

<!-- Describe the purpose and scope of this project. -->

## Coding Conventions

<!-- Language, style, formatting, testing rules. -->

## Key Dependencies

<!-- Major libraries, frameworks, tools, and external services. -->

## Agent Notes

<!-- OpenCode and other agents may append session-level memory here. -->
"""


# ---------- precondition checks (no writes) ----------


def _manifest_failure(project_dir: Path) -> PreflightFailure | None:
    if not manifest.exists(project_dir):
        return None
    try:
        manifest.validate(project_dir)
    except manifest.WrongNameError as exc:
        return PreflightFailure(
            EXIT_BAD_MANIFEST_NAME,
            f"[ERROR] A workshop.yaml exists but is configured with an "
            f"invalid name '{exc.found_name}'. ward requires the container "
            f"namespace to be explicitly set to 'name: ward'.",
        )
    return None


# ---------- mutations (only run once all checks pass) ----------


def _write_manifest_if_missing(project_dir: Path) -> None:
    if manifest.exists(project_dir):
        info("[INFO] Existing workshop.yaml validated.")
        return
    manifest.generate(project_dir)
    info("[INFO] Generated workshop.yaml in current directory.")


def _write_agents_md_if_missing(project_dir: Path) -> None:
    target = project_dir / AGENTS_FILENAME
    if target.exists():
        return
    target.write_text(AGENTS_TEMPLATE, encoding="utf-8")
    info("[INFO] Created AGENTS.md placeholder for agent context memory.")


def _update_gitignore(project_dir: Path) -> None:
    """Append the ward-managed block to .gitignore if not already present."""
    target = project_dir / GITIGNORE_FILENAME
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if GITIGNORE_BLOCK_BEGIN in existing:
        return
    target.write_text(existing + GITIGNORE_BLOCK, encoding="utf-8")
    info("[INFO] Updated .gitignore with ward artifact entries.")


def run() -> None:
    cwd = Path.cwd()

    # Phase 1: validate every precondition. Exit with full diagnostics
    # before any project file is created or modified. init only writes
    # project files, so it checks just the two things it depends on: a
    # Git root, and a correctly-named existing manifest. Everything else
    # (workshop/lxd/SSH plumbing) is enforced by 'ward up'.
    failures: list[PreflightFailure] = []
    repo_fail = git_repo_failure(cwd)
    if repo_fail is not None:
        failures.append(repo_fail)
    manifest_fail = _manifest_failure(cwd)
    if manifest_fail is not None:
        failures.append(manifest_fail)
    report_and_exit(failures, [])

    # Phase 2: mutations. Only reached when every hard check passed.
    _write_manifest_if_missing(cwd)
    _write_agents_md_if_missing(cwd)
    _update_gitignore(cwd)
    info(
        "[INFO] ward environment initialised. Run 'ward up' to launch your "
        "sandboxed OpenCode session."
    )
