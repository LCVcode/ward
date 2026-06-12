"""``ward up`` — bring the sandboxed OpenCode session online.

Per SPEC.md section 5:
1. Ensure workshop.yaml exists in the project (auto-generate if missing).
2. Query the container's state via the workshop CLI.
3. Reconcile state: ``Off`` → launch; ``Stopped`` → start; ``Ready`` → pass.
4. Run the hydration loop: stop → remount config + data → start.
5. Hand off control with ``workshop run ward opencode`` (replaces process).
"""

from __future__ import annotations

import os
from pathlib import Path

from ward import manifest, workshop
from ward.errors import die, info, warn
from ward.preflight import OPENCODE_CONFIG_DIR, run_preflight

EXIT_STATUS_QUERY_FAILED = 71
EXIT_REMOUNT_FAILED = 74
EXIT_LAUNCH_FAILED = 70  # generic launch failure (network etc.)

OPENCODE_DATA_DIR = Path("~/.local/share/opencode").expanduser()

CONFIG_PLUG = "opencode:opencode-config"
DATA_PLUG = "opencode:opencode-data"

# Host git configuration is copied into the sandbox so the agent commits with
# the operator's identity (user.name/user.email) and inherits their git
# settings (url rewrites, default branch, editor, ...). Auth itself flows
# through the forwarded ssh-agent, not this file.
GITCONFIG_HOST = Path("~/.gitconfig").expanduser()
GITCONFIG_TARGET = "/home/workshop/.gitconfig"


def _ensure_manifest(project_dir: Path) -> None:
    """Auto-generate the manifest if missing; refuse if name is wrong."""
    if manifest.exists(project_dir):
        try:
            manifest.validate(project_dir)
        except manifest.WrongNameError as exc:
            die(
                73,
                f"[ERROR] A workshop.yaml exists but is configured with an "
                f"invalid name '{exc.found_name}'. 'ward' requires the "
                f"container namespace to be explicitly set to 'name: ward'.",
            )
    else:
        manifest.generate(project_dir)
        info("[INFO] Generated workshop.yaml in current directory.")


def _ensure_launched_and_stopped(project_dir: Path) -> None:
    """Drive the container into the ``Stopped`` state from any starting point.

    This is the precondition for ``workshop remount`` (which requires a
    stopped workshop unless the source happens to be on the same
    filesystem — we never assume that).
    """
    state, result = workshop.query_state(project_dir)

    if state is workshop.State.UNKNOWN:
        die(
            EXIT_STATUS_QUERY_FAILED,
            "[ERROR] Failed to query Canonical Workshop status. Verify your "
            "user belongs to the 'lxd' group or try restarting the system "
            "container daemon."
            + (f"\n{result.stderr.strip()}" if result.stderr.strip() else ""),
        )

    if state in (workshop.State.MISSING, workshop.State.OFF):
        info("[INFO] Launching ward workshop (first run may take a while)...")
        launch_result = workshop.launch(project_dir)
        if not launch_result.ok:
            die(
                EXIT_LAUNCH_FAILED,
                "[ERROR] Workshop launch timed out or failed. Verify your "
                "internet connection and network interfaces policy."
                + (f"\n{launch_result.stderr.strip()}"
                   if launch_result.stderr.strip() else ""),
            )
        # After a successful launch the workshop is started; we then stop
        # it so the hydration remounts can proceed safely.
        state = workshop.State.READY

    if state in (workshop.State.READY, workshop.State.WAITING):
        stop_result = workshop.stop(project_dir)
        if not stop_result.ok:
            die(
                EXIT_REMOUNT_FAILED,
                "[ERROR] Could not stop ward workshop prior to remount."
                + (f"\n{stop_result.stderr.strip()}"
                   if stop_result.stderr.strip() else ""),
            )
    # State.STOPPED — nothing to do.
    # State.PENDING — let workshop CLI surface its own retry guidance via the
    # subsequent remount call; we don't second-guess transitional states.


def _remount(plug: str, source: Path, project_dir: Path) -> None:
    result = workshop.remount(plug, source, project_dir)
    if not result.ok:
        die(
            EXIT_REMOUNT_FAILED,
            "[ERROR] Configuration bridge failed. Ensure target directory "
            "paths are not locked or modified by another systemic execution "
            "window."
            + (f"\n{result.stderr.strip()}" if result.stderr.strip() else ""),
        )


def _hydrate(project_dir: Path) -> None:
    _remount(CONFIG_PLUG, OPENCODE_CONFIG_DIR, project_dir)
    _remount(DATA_PLUG, OPENCODE_DATA_DIR, project_dir)


def _start(project_dir: Path) -> None:
    result = workshop.start(project_dir)
    if not result.ok:
        die(
            EXIT_LAUNCH_FAILED,
            "[ERROR] Failed to start ward workshop after hydration."
            + (f"\n{result.stderr.strip()}" if result.stderr.strip() else ""),
        )


def _handoff() -> None:
    """Replace the current process with ``workshop run ward opencode``.

    Using ``execvp`` ensures no ward wrapper process sits above the
    interactive OpenCode TUI — signals (Ctrl-C, window-size changes,
    EOF) flow natively to opencode.
    """
    argv = workshop.run_action_argv("opencode")
    os.execvp(argv[0], argv)  # pragma: no cover — replaces process


def _inject_git_config(project_dir: Path) -> None:
    """Copy the host's ~/.gitconfig into the running sandbox.

    Without this the sandboxed agent has no git identity and cannot create
    commits. Auth is handled separately via the forwarded ssh-agent.

    Best-effort: a missing host config is skipped silently, and an injection
    failure warns but does not abort the session (the agent can still run;
    only the git identity/config would be absent).
    """
    if not GITCONFIG_HOST.is_file():
        return
    try:
        content = GITCONFIG_HOST.read_text(encoding="utf-8")
    except OSError as exc:
        warn(f"[WARN] Could not read {GITCONFIG_HOST}: {exc}. "
             "Skipping git config injection.")
        return

    result = workshop.write_file(GITCONFIG_TARGET, content, project_dir)
    if result.ok:
        info("[INFO] Injected host git configuration into the ward sandbox.")
    else:
        warn(
            "[WARN] Failed to inject git configuration into the sandbox; "
            "commits inside it may need 'git config user.name/user.email' set "
            "manually."
            + (f"\n{result.stderr.strip()}" if result.stderr.strip() else "")
        )


def run() -> None:
    run_preflight()
    cwd = Path.cwd()
    _ensure_manifest(cwd)
    _ensure_launched_and_stopped(cwd)
    _hydrate(cwd)
    _start(cwd)
    _inject_git_config(cwd)
    info("[INFO] Handing off to OpenCode inside the ward sandbox...")
    _handoff()
