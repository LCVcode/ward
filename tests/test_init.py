"""Tests for ``ward init``'s tailored, minimal precondition checks.

``init`` only writes project files, so it must validate exactly two
things — that the cwd is a Git repository, and that any existing
workshop.yaml is named ``ward`` — and nothing else. In particular it must
NOT enforce the workshop/lxd/opencode/SSH plumbing that only ``ward up``
depends on. The success-without-ssh test is the regression guard for the
original bug, where a missing ``SSH_AUTH_SOCK`` in the systemd user
environment caused ``ward init`` to abort with exit 79.

All checks here are pure filesystem logic, so they run hermetically under
``tmp_path`` with ``monkeypatch.chdir`` standing in for the operator's
cwd. No real workshop, lxd, or SSH agent is involved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ward import manifest
from ward.commands import init
from ward.commands.init import AGENTS_FILENAME, GITIGNORE_BLOCK_BEGIN


def _make_git_repo(path: Path) -> None:
    """Mark ``path`` as a Git repo for the purposes of init's check.

    init only probes for a ``.git`` directory (filesystem-only); it does
    not shell out to the git binary, so an empty ``.git`` dir suffices.
    """
    (path / ".git").mkdir()


def test_init_without_git_repo_exits_64(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        init.run()

    assert excinfo.value.code == 64
    # Phase 1 failed: nothing should have been written.
    assert not manifest.exists(tmp_path)
    assert not (tmp_path / AGENTS_FILENAME).exists()


def test_init_with_wrong_manifest_name_exits_73(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_git_repo(tmp_path)
    (tmp_path / manifest.MANIFEST_FILENAME).write_text(
        "name: not-ward\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        init.run()

    assert excinfo.value.code == 73


def test_init_succeeds_without_ssh_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: init must not depend on SSH/systemd plumbing.

    With no ``SSH_AUTH_SOCK`` in the environment (and, by extension, none
    in the systemd user manager), init previously aborted with exit 79.
    It must now run to completion and write its project files.
    """
    _make_git_repo(tmp_path)
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    monkeypatch.chdir(tmp_path)

    # Should not raise SystemExit — every precondition init cares about
    # is satisfied (git repo present, no conflicting manifest).
    init.run()

    assert manifest.exists(tmp_path)
    agents = tmp_path / AGENTS_FILENAME
    assert agents.is_file()
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert GITIGNORE_BLOCK_BEGIN in gitignore


def test_init_preserves_existing_agents_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_git_repo(tmp_path)
    agents = tmp_path / AGENTS_FILENAME
    agents.write_text("# my own notes\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    init.run()

    # init seeds AGENTS.md only when absent; an existing one is untouched.
    assert agents.read_text(encoding="utf-8") == "# my own notes\n"
