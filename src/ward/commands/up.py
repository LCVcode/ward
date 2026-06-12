"""``ward up`` — bring the sandboxed OpenCode session online.

Lifecycle (matches README "How it works"):
1. Ensure workshop.yaml exists in the project (auto-generate if missing).
2. Query the container's state via the workshop CLI.
3. Reconcile state: ``Off`` → launch; ``Stopped`` → start; ``Ready`` → pass.
4. Run the hydration loop: stop → remount config + data → start.
5. Connect the ssh-agent plug (manual-connect interface).
6. Inject (sanitized) host gitconfig into the workshop.
7. Hand off control with ``workshop run ward opencode`` (replaces process).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ward import manifest, workshop
from ward.errors import die, info, warn
from ward.preflight import (
    OPENCODE_CONFIG_DIR,
    Tier,
    resolve_host_home,
    run_preflight,
)

EXIT_STATUS_QUERY_FAILED = 71
EXIT_REMOUNT_FAILED = 74
EXIT_LAUNCH_FAILED = 70  # generic launch failure (network etc.)

OPENCODE_DATA_DIR = Path("~/.local/share/opencode").expanduser()

CONFIG_PLUG = "opencode:opencode-config"
DATA_PLUG = "opencode:opencode-data"

# SSH agent forwarding: the ssh-agent interface is manual-connect and the plug
# is declared on the opencode SDK (per manifest.MANIFEST_CONTENT), since SSH
# plugs cannot live on the system SDK. ``ward up`` runs `workshop connect`
# after start to wire it.
SSH_AGENT_PLUG = "opencode:ssh-agent"

# Markers in `workshop connect` stderr indicating the workshop's on-disk
# definition is older than what ward expects (plug doesn't exist yet). The
# remedy is a refresh-and-retry. Substring match, case-insensitive.
_STALE_DEFINITION_MARKERS = (
    "has no plug named",
    "no such plug",
    "unknown plug",
)

# Substrings indicating the plug is already connected — treated as success.
_ALREADY_CONNECTED_MARKERS = (
    "already connected",
)

# Substring indicating the host has no SSH agent running (or SSH_AUTH_SOCK
# isn't exported into ward's process). Worth surfacing distinctly because
# the fix is on the host side, not inside the workshop.
_NO_HOST_AGENT_MARKER = "ssh_auth_sock"

# Host git configuration is copied into the sandbox so the agent commits with
# the operator's identity (user.name/user.email) and inherits their git
# settings (url rewrites, default branch, editor, ...). Auth itself flows
# through the forwarded ssh-agent, not this file.
#
# The injected file is always written to ``/home/workshop/.gitconfig`` because
# git inside the workshop reads ``$HOME/.gitconfig`` for the default
# ``workshop`` user (which is also the user ``workshop exec`` runs as).
GITCONFIG_TARGET = "/home/workshop/.gitconfig"

# Sections to drop wholesale from the host gitconfig before injection.
# These either reference host-only resources (gpg agents, includeIf paths)
# or are meaningless / harmful inside the sandbox.
_DROP_SECTIONS = {"includeif", "include", "gpg"}

# Per-section keys to drop. Section names are lowered; key names are matched
# case-insensitively.
_DROP_KEYS: dict[str, set[str]] = {
    "commit": {"gpgsign"},
    "tag": {"gpgsign"},
    "push": {"gpgsign"},
    "user": {"signingkey"},
    "credential": {"helper"},
    "core": {"sshcommand"},
}

_SECTION_RE = re.compile(r'^\s*\[([A-Za-z0-9.-]+)(?:\s+"([^"]*)")?\]\s*$')
_KEY_RE = re.compile(r'^\s*([A-Za-z][A-Za-z0-9-]*)\s*=')


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


def _connect_ssh_agent(project_dir: Path) -> None:
    """Wire the host's SSH agent into the sandbox.

    The ssh-agent interface is manual-connect by design (security boundary
    on host credentials). Without this step ``git clone git@...`` fails
    inside the workshop with "Permission denied (publickey)" even though
    ssh-agent forwarding is declared in the manifest.

    Idempotent: an "already connected" response is treated as success. If
    the workshop was launched against an older manifest that didn't declare
    the plug, attempt a one-shot ``workshop refresh`` to apply the new
    definition, then retry the connect. All failures are warnings, not
    fatal — git operations will still fail loudly inside the sandbox if
    this didn't take, but the agent itself can still run.
    """
    result = workshop.connect(SSH_AGENT_PLUG, project_dir)

    if result.ok or _stderr_matches(result, _ALREADY_CONNECTED_MARKERS):
        info("[INFO] Connected host SSH agent to the ward sandbox "
             f"({SSH_AGENT_PLUG}).")
        return

    if _stderr_matches(result, (_NO_HOST_AGENT_MARKER,)):
        warn(
            "[WARN] Cannot wire ssh-agent: no SSH agent appears to be "
            "running on the host (SSH_AUTH_SOCK is not set in ward's "
            "environment). Start one with 'eval \"$(ssh-agent -s)\" && "
            "ssh-add' on the host, then re-run 'ward up'. Git over SSH "
            "inside the sandbox will otherwise fail with 'Permission "
            "denied (publickey)'."
        )
        return

    if _stderr_matches(result, _STALE_DEFINITION_MARKERS):
        info("[INFO] Workshop definition appears stale (no ssh-agent plug "
             "on opencode SDK). Refreshing to apply the current manifest...")
        refresh_result = workshop.refresh(project_dir)
        if not refresh_result.ok:
            warn(
                "[WARN] Refresh failed; cannot wire ssh-agent. Run "
                "'workshop refresh ward' manually, then re-run 'ward up'."
                + (f"\n{refresh_result.stderr.strip()}"
                   if refresh_result.stderr.strip() else "")
            )
            return
        retry = workshop.connect(SSH_AGENT_PLUG, project_dir)
        if retry.ok or _stderr_matches(retry, _ALREADY_CONNECTED_MARKERS):
            info("[INFO] Connected host SSH agent to the ward sandbox "
                 f"({SSH_AGENT_PLUG}) after refresh.")
            return
        warn(
            "[WARN] Failed to connect ssh-agent after refresh; git over SSH "
            "inside the sandbox will fail with 'Permission denied "
            "(publickey)'. Run 'workshop connect ward/"
            f"{SSH_AGENT_PLUG}' manually to diagnose."
            + (f"\n{retry.stderr.strip()}" if retry.stderr.strip() else "")
        )
        return

    warn(
        "[WARN] Failed to connect ssh-agent; git over SSH inside the "
        "sandbox will fail with 'Permission denied (publickey)'. Run "
        f"'workshop connect ward/{SSH_AGENT_PLUG}' manually to diagnose."
        + (f"\n{result.stderr.strip()}" if result.stderr.strip() else "")
    )


def _stderr_matches(result: workshop.CommandResult, markers: tuple[str, ...]) -> bool:
    """Case-insensitive substring search across the result's combined output."""
    haystack = result.combined.lower()
    return any(marker in haystack for marker in markers)


def _handoff() -> None:
    """Replace the current process with ``workshop run ward opencode``.

    Using ``execvp`` ensures no ward wrapper process sits above the
    interactive OpenCode TUI — signals (Ctrl-C, window-size changes,
    EOF) flow natively to opencode.
    """
    argv = workshop.run_action_argv("opencode")
    os.execvp(argv[0], argv)  # pragma: no cover — replaces process


def _resolve_host_home() -> Path:
    """Compatibility shim — defers to :func:`ward.preflight.resolve_host_home`."""
    return resolve_host_home()


def _find_host_gitconfig() -> Path | None:
    """Locate the operator's git config, preferring ``~/.gitconfig``.

    Falls back to the XDG location ``~/.config/git/config`` which many
    modern setups (and ``git config --global``'s own write target when
    XDG_CONFIG_HOME is set) use instead.
    """
    home = _resolve_host_home()
    for candidate in (home / ".gitconfig", home / ".config" / "git" / "config"):
        if candidate.is_file():
            return candidate
    return None


def _sanitize_gitconfig(text: str) -> tuple[str, list[str]]:
    """Strip host-only directives from a gitconfig text.

    Returns ``(sanitized_text, stripped_descriptions)``. Drops entire
    ``[includeIf]`` / ``[include]`` / ``[gpg]`` sections (they reference
    host-only paths or programs), and per-section keys that depend on the
    host's keychain, GPG agent, or SSH wrapper (signing keys, credential
    helpers, custom ssh commands).

    The parser is line-based and intentionally simple: git's config grammar
    permits multi-line values via backslash continuation, but those are
    vanishingly rare in user configs and surviving them here would just
    yield slightly noisier output, not incorrect identity propagation.
    """
    out: list[str] = []
    stripped: list[str] = []
    current: str | None = None
    skip_section = False

    for line in text.splitlines(keepends=True):
        section_match = _SECTION_RE.match(line)
        if section_match:
            current = section_match.group(1).lower()
            skip_section = current in _DROP_SECTIONS
            if skip_section:
                stripped.append(f"[{section_match.group(1)}]")
                continue
            out.append(line)
            continue
        if skip_section:
            continue
        key_match = _KEY_RE.match(line)
        if (
            key_match
            and current is not None
            and current in _DROP_KEYS
            and key_match.group(1).lower() in _DROP_KEYS[current]
        ):
            stripped.append(f"{current}.{key_match.group(1).lower()}")
            continue
        out.append(line)

    return "".join(out), stripped


def _verify_git_identity(project_dir: Path) -> tuple[str, str]:
    """Read user.name and user.email back from the workshop's git config.

    Returns ``(name, email)`` with empty strings for any field that git
    reports as unset (exit code 1 from ``git config --get``). Any other
    failure mode (git missing, exec rejection) returns empty strings as
    well — the caller treats absence as "verification inconclusive" and
    surfaces a warning rather than aborting the session.
    """
    def _get(key: str) -> str:
        result = workshop.exec_capture(
            ["git", "config", "--global", "--get", key], project_dir
        )
        if result.ok:
            return result.stdout.strip()
        return ""

    return _get("user.name"), _get("user.email")


def _inject_git_config(project_dir: Path) -> None:
    """Copy the host's git config into the running sandbox.

    Without this the sandboxed agent has no git identity and cannot create
    commits. Auth is handled separately via the forwarded ssh-agent.

    Best-effort: a missing host config is logged (so the operator sees the
    skip), and an injection failure warns but does not abort the session
    (the agent can still run; only the git identity/config would be
    absent).
    """
    source = _find_host_gitconfig()
    if source is None:
        home = _resolve_host_home()
        info(
            f"[INFO] No host git config found at {home}/.gitconfig or "
            f"{home}/.config/git/config. Skipping git config injection; "
            "commits inside the sandbox will need user.name/user.email set."
        )
        return

    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        warn(f"[WARN] Could not read {source}: {exc}. "
             "Skipping git config injection.")
        return

    content, stripped = _sanitize_gitconfig(raw)

    result = workshop.write_file(GITCONFIG_TARGET, content, project_dir)
    if not result.ok:
        warn(
            "[WARN] Failed to inject git configuration into the sandbox; "
            "commits inside it may need 'git config user.name/user.email' "
            "set manually."
            + (f"\n{result.stderr.strip()}" if result.stderr.strip() else "")
        )
        return

    info(f"[INFO] Injected host git configuration from {source} into the "
         "ward sandbox.")
    if stripped:
        info("[INFO] Stripped host-only directives during injection: "
             + ", ".join(stripped))

    name, email = _verify_git_identity(project_dir)
    if name and email:
        info(f"[INFO] Verified sandbox git identity: {name} <{email}>.")
    else:
        missing = []
        if not name:
            missing.append("user.name")
        if not email:
            missing.append("user.email")
        warn(
            "[WARN] Git config injected but identity verification could not "
            f"read {', '.join(missing)} inside the sandbox. The host config "
            "may rely on '[includeIf]'/'[include]' files (which are not "
            "transported) or set identity outside the user.* section. Set "
            "the missing fields manually inside the sandbox if commits fail."
        )


def run() -> None:
    cwd = Path.cwd()
    run_preflight(tier=Tier.FULL, project_dir=cwd)
    _ensure_manifest(cwd)
    _ensure_launched_and_stopped(cwd)
    _hydrate(cwd)
    _start(cwd)
    _connect_ssh_agent(cwd)
    _inject_git_config(cwd)
    info("[INFO] Handing off to OpenCode inside the ward sandbox...")
    _handoff()
