"""Host pre-flight dependency engine.

Runs before every ward sub-command to verify required host-side binaries,
group memberships, configuration directories, and (for the heavier
commands) the SSH-agent plumbing that workshop's daemon depends on.

Failures are *collected* (not fail-fast) so the user sees every missing
prerequisite in a single invocation and can fix the host once rather
than iteratively. Soft warnings are printed but do not exit.

Two tiers, exposed via :func:`run_preflight`:

- ``Tier.MINIMAL`` — bare-minimum host sanity. Used by lifecycle
  commands that must remain usable when the host's SSH/git setup is
  broken (``sleep``, ``clean``, ``purge``).
- ``Tier.FULL`` — every hard check plus soft warnings. Used by ``up``
  so first-launch errors surface immediately rather than during the
  long hydration loop.

``init`` does not use either tier: it only writes project files and so
runs a tailored, minimal check (just :func:`git_repo_failure`, plus its
own manifest-name validation). All workshop/lxd/SSH plumbing is deferred
to ``up``, which is the command that actually depends on it.

Never auto-fixes anything: every failure prints an actionable
remediation command and exits.
"""

from __future__ import annotations

import os
import pwd
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Exit codes — kept stable for scripted callers; documented in README.
EXIT_NO_GIT_REPO = 64
EXIT_MISSING_CONFIG = 65
EXIT_LXD_GROUP = 77
EXIT_SSH_SOCK = 78
EXIT_SYSTEMD_USER_ENV = 79
EXIT_MISSING_BINARY = 127


class Tier(Enum):
    """Preflight tier — which checks to run."""

    MINIMAL = "minimal"
    FULL = "full"


# ---------- shared helpers ----------


def resolve_host_home() -> Path:
    """Return the operator's real home directory.

    When ward is installed as a classic snap, ``$HOME`` may be the snap's
    per-user data directory (``~/snap/ward/current/``) rather than the
    operator's actual home. snapd exposes the real path via
    ``$SNAP_REAL_HOME``; falling back to the passwd entry for the current
    UID handles non-snap installs and unusual launch contexts (sudo,
    cron). ``Path.home()`` is the final fallback.
    """
    real = os.environ.get("SNAP_REAL_HOME")
    if real:
        return Path(real)
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except KeyError:
        return Path.home()


OPENCODE_CONFIG_DIR = resolve_host_home() / ".config" / "opencode"


# ---------- result types ----------


@dataclass(frozen=True)
class PreflightFailure:
    """A single failed precondition: exit code + actionable message."""

    code: int
    message: str


@dataclass(frozen=True)
class PreflightWarning:
    """A soft precondition that is suspicious but non-fatal."""

    message: str


# ---------- individual checks (return None when OK) ----------


def _binary_failure(name: str, install_hint: str) -> PreflightFailure | None:
    if shutil.which(name) is None:
        return PreflightFailure(EXIT_MISSING_BINARY, install_hint)
    return None


def _lxd_group_failure() -> PreflightFailure | None:
    """Verify the calling user has LXD access.

    The workshop CLI talks to LXD; without group membership, every
    ``workshop`` invocation fails with a permission error inside a task,
    which is much noisier than a single up-front check here. Root (UID 0)
    short-circuits since it always has access.
    """
    if os.getuid() == 0:
        return None

    import grp

    try:
        members = set(grp.getgrnam("lxd").gr_mem)
    except KeyError:
        return PreflightFailure(
            EXIT_LXD_GROUP,
            "[ERROR] No 'lxd' group exists on this host, which means LXD "
            "is not installed. The workshop snap depends on it. Install "
            "with: 'sudo snap install lxd && sudo lxd init --auto', then "
            "log out and back in.",
        )

    user = pwd.getpwuid(os.getuid()).pw_name
    if user in members:
        return None

    return PreflightFailure(
        EXIT_LXD_GROUP,
        f"[ERROR] User '{user}' is not in the 'lxd' group, so the workshop "
        "CLI cannot talk to LXD. Fix with: 'sudo usermod -aG lxd \"$USER\"' "
        "then log out and back in (or run 'newgrp lxd' for the current "
        "shell).",
    )


def _opencode_config_failure() -> PreflightFailure | None:
    if OPENCODE_CONFIG_DIR.is_dir():
        return None
    return PreflightFailure(
        EXIT_MISSING_CONFIG,
        "[ERROR] No local OpenCode configuration found at "
        f"{OPENCODE_CONFIG_DIR}. Run 'opencode /connect' on your host "
        "machine first to authenticate your backend accounts.",
    )


def git_repo_failure(project_dir: Path) -> PreflightFailure | None:
    if (project_dir / ".git").is_dir():
        return None
    return PreflightFailure(
        EXIT_NO_GIT_REPO,
        "[ERROR] Current directory is not a Git repository. ward requires "
        "a Git root so AGENTS.md and project edits live under version "
        "control. Initialise one with: 'git init'.",
    )


def _ssh_sock_failure() -> PreflightFailure | None:
    """Verify SSH_AUTH_SOCK is set and points at a live Unix socket."""
    sock = os.environ.get("SSH_AUTH_SOCK")
    if not sock:
        return PreflightFailure(
            EXIT_SSH_SOCK,
            "[ERROR] SSH_AUTH_SOCK is not set in this shell, so ward "
            "cannot wire your SSH agent into the workshop. Start an agent "
            'and load your key with: \'eval "$(ssh-agent -s)" && '
            "ssh-add', then re-run.",
        )
    try:
        st = Path(sock).stat()
    except OSError as exc:
        return PreflightFailure(
            EXIT_SSH_SOCK,
            f"[ERROR] SSH_AUTH_SOCK points at '{sock}' but the path is "
            f"unreadable ({exc.strerror}). Start a fresh agent with: "
            "'eval \"$(ssh-agent -s)\" && ssh-add', then re-run.",
        )
    if not stat.S_ISSOCK(st.st_mode):
        return PreflightFailure(
            EXIT_SSH_SOCK,
            f"[ERROR] SSH_AUTH_SOCK points at '{sock}' but that path is "
            "not a Unix socket. Start a fresh agent with: 'eval "
            '"$(ssh-agent -s)" && ssh-add\', then re-run.',
        )
    return None


def _systemd_user_env_ssh_failure() -> PreflightFailure | None:
    """Verify SSH_AUTH_SOCK is present in the systemd user environment.

    The workshop daemon does NOT read SSH_AUTH_SOCK from the calling
    shell — it reads from the systemd user manager's environment block.
    Without this, ``workshop connect ward/opencode:ssh-agent`` fails
    with 'environment variable SSH_AUTH_SOCK not found' even though the
    invoking shell has it set.

    Skipped gracefully on hosts without systemctl (returns None).
    """
    if shutil.which("systemctl") is None:
        return None

    try:
        result = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None  # Best-effort: don't block on a flaky systemctl probe.

    if result.returncode != 0:
        return None  # No user-systemd instance; can't enforce, don't fail.

    for line in result.stdout.splitlines():
        if line.startswith("SSH_AUTH_SOCK="):
            return None

    return PreflightFailure(
        EXIT_SYSTEMD_USER_ENV,
        "[ERROR] SSH_AUTH_SOCK is not present in the systemd user "
        "environment, which is where workshop's daemon reads it from. "
        "Without this, 'workshop connect ward/opencode:ssh-agent' will "
        "fail and git over SSH inside the workshop will not work. Import "
        "it (once per agent lifetime) with: 'systemctl --user "
        "import-environment SSH_AUTH_SOCK', then re-run.",
    )


def _ssh_keys_loaded_warning() -> PreflightWarning | None:
    """Warn (non-fatal) if ssh-add reports no identities loaded."""
    if shutil.which("ssh-add") is None:
        return None
    try:
        result = subprocess.run(
            ["ssh-add", "-l"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    # ssh-add -l exit codes: 0 = identities listed, 1 = no identities,
    # 2 = cannot contact agent (covered separately by _ssh_sock_failure).
    if result.returncode == 1:
        return PreflightWarning(
            "[WARN] ssh-agent has no identities loaded. Load yours with: "
            "'ssh-add ~/.ssh/id_ed25519' (or whichever key you use). Git "
            "operations against private SSH remotes will fail inside the "
            "workshop until you do."
        )
    return None


def _git_identity_warning() -> PreflightWarning | None:
    """Warn if host git identity is unset (name AND email both empty)."""
    if shutil.which("git") is None:
        return None  # _git_binary_failure handles this as a hard fail.

    def _get(key: str) -> str:
        try:
            result = subprocess.run(
                ["git", "config", "--global", "--get", key],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    name, email = _get("user.name"), _get("user.email")
    if name or email:
        return None
    return PreflightWarning(
        "[WARN] Host git identity is not set (user.name and user.email "
        "are both empty). Commits inside the workshop will be anonymous. "
        'Set with: \'git config --global user.name "Your Name" && git '
        "config --global user.email you@example.com'."
    )


# ---------- collection ----------


def collect_failures(
    tier: Tier = Tier.FULL,
    project_dir: Path | None = None,
) -> tuple[list[PreflightFailure], list[PreflightWarning]]:
    """Run every check appropriate to ``tier``; return (failures, warnings).

    Order is deterministic: binaries → group membership → configuration
    directories → git repo → SSH socket → systemd user env → warnings.
    The first failure's exit code is used by :func:`report_and_exit`,
    but every failure is printed so the user can fix them all in one pass.
    """
    failures: list[PreflightFailure] = []
    warnings: list[PreflightWarning] = []

    # Tier.MINIMAL: binaries + group membership only.
    workshop_fail = _binary_failure(
        "workshop",
        "[ERROR] Canonical Workshop CLI ('workshop') is not installed on "
        "the host. Install it with: 'sudo snap install workshop'.",
    )
    if workshop_fail:
        failures.append(workshop_fail)

    lxd_fail = _lxd_group_failure()
    if lxd_fail:
        failures.append(lxd_fail)

    if tier is Tier.MINIMAL:
        return failures, warnings

    # Tier.FULL: also check opencode, git, opencode config, git repo, SSH.
    opencode_fail = _binary_failure(
        "opencode",
        "[ERROR] OpenCode CLI ('opencode') is missing from the host PATH. "
        "Install it (e.g. 'sudo snap install opencode --classic') to "
        "establish global configuration paths.",
    )
    if opencode_fail:
        failures.append(opencode_fail)

    git_fail = _binary_failure(
        "git",
        "[ERROR] git is not installed on the host. ward requires it to "
        "manage the project repository. Install with: 'sudo apt install "
        "git'.",
    )
    if git_fail:
        failures.append(git_fail)

    opencode_cfg_fail = _opencode_config_failure()
    if opencode_cfg_fail:
        failures.append(opencode_cfg_fail)

    if project_dir is not None:
        repo_fail = git_repo_failure(project_dir)
        if repo_fail:
            failures.append(repo_fail)

    ssh_sock_fail = _ssh_sock_failure()
    if ssh_sock_fail:
        failures.append(ssh_sock_fail)
    else:
        # Only check systemd user env when the shell-level socket is OK;
        # otherwise the user can't fix it anyway.
        systemd_fail = _systemd_user_env_ssh_failure()
        if systemd_fail:
            failures.append(systemd_fail)

    # Soft warnings — printed even when hard checks pass.
    for warning in (_ssh_keys_loaded_warning(), _git_identity_warning()):
        if warning is not None:
            warnings.append(warning)

    return failures, warnings


def report_and_exit(
    failures: list[PreflightFailure],
    warnings: list[PreflightWarning],
) -> None:
    """Print warnings, then failures. Exit on any failure.

    Using the first failure's code keeps scripted callers' behaviour
    deterministic when exactly one precondition is broken (the common
    case), while still surfacing every missing piece in multi-failure
    scenarios.
    """
    for warning in warnings:
        print(warning.message, file=sys.stderr)

    if not failures:
        return

    for failure in failures:
        print(failure.message, file=sys.stderr)
    sys.exit(failures[0].code)


def run_preflight(
    tier: Tier = Tier.FULL,
    project_dir: Path | None = None,
) -> None:
    """Verify host dependencies for the given tier. Exits on any failure.

    ``project_dir`` is required for ``Tier.FULL`` to check that the cwd
    is a Git repository.
    """
    failures, warnings = collect_failures(tier=tier, project_dir=project_dir)
    report_and_exit(failures, warnings)
