"""Tests for ``ward up``'s state-driven launch vs. reconnect routing.

``up.run()`` has two paths:

- **Reconnect (fast path):** when the workshop is already ``Ready``, ward
  must skip the stop/remount/start/connect/inject churn and hand off
  immediately, using only the MINIMAL preflight tier.
- **Cold start (full path):** from any non-running state ward must run
  the FULL preflight and the complete hydration sequence.

These tests mock the subprocess boundary (``workshop.query_state``) and
the process-replacing handoff (``_handoff``), then assert which helpers
ran. They never touch a real workshop, lxd, or SSH agent.
"""

from __future__ import annotations

import pytest

from ward.commands import up
from ward.preflight import Tier
from ward.workshop import CommandResult, State


@pytest.fixture
def patched_up(mocker):
    """Patch every side-effecting boundary in up.run() and return spies.

    The step helpers are replaced with mocks so we can assert call
    presence/absence; ``_handoff`` is mocked so it does not execvp away.
    """
    spies = {
        "preflight": mocker.patch.object(up, "run_preflight"),
        "ensure_manifest": mocker.patch.object(up, "_ensure_manifest"),
        "ensure_launched": mocker.patch.object(
            up, "_ensure_launched_and_stopped"
        ),
        "hydrate": mocker.patch.object(up, "_hydrate"),
        "start": mocker.patch.object(up, "_start"),
        "connect_ssh": mocker.patch.object(up, "_connect_ssh_agent"),
        "inject_git": mocker.patch.object(up, "_inject_git_config"),
        "handoff": mocker.patch.object(up, "_handoff"),
    }
    # cwd is irrelevant once query_state is mocked; pin it for determinism.
    mocker.patch.object(up.Path, "cwd", return_value=mocker.MagicMock())
    return spies


def _mock_state(mocker, state: State) -> None:
    mocker.patch.object(
        up.workshop,
        "query_state",
        return_value=(state, CommandResult(0, "", "")),
    )


def test_ready_takes_fast_path(patched_up, mocker) -> None:
    _mock_state(mocker, State.READY)

    up.run()

    # Handed off without any hydration churn.
    patched_up["handoff"].assert_called_once()
    for step in (
        "ensure_launched",
        "hydrate",
        "start",
        "connect_ssh",
        "inject_git",
    ):
        patched_up[step].assert_not_called()


def test_ready_uses_minimal_preflight_only(patched_up, mocker) -> None:
    _mock_state(mocker, State.READY)

    up.run()

    # Exactly one preflight call, and it is MINIMAL — never FULL.
    patched_up["preflight"].assert_called_once()
    tier = patched_up["preflight"].call_args.kwargs["tier"]
    assert tier is Tier.MINIMAL


@pytest.mark.parametrize("state", [State.OFF, State.STOPPED])
def test_cold_state_runs_full_sequence(patched_up, mocker, state) -> None:
    _mock_state(mocker, state)

    up.run()

    for step in (
        "ensure_manifest",
        "ensure_launched",
        "hydrate",
        "start",
        "connect_ssh",
        "inject_git",
        "handoff",
    ):
        patched_up[step].assert_called_once()

    # FULL preflight must be enforced on the cold path.
    tiers = [
        c.kwargs.get("tier")
        for c in patched_up["preflight"].call_args_list
    ]
    assert Tier.FULL in tiers


def test_waiting_is_not_fast_pathed(patched_up, mocker) -> None:
    """Waiting is ambiguous (running-but-waiting); take the full path."""
    _mock_state(mocker, State.WAITING)

    up.run()

    # Full hydration sequence runs rather than an immediate reconnect.
    patched_up["hydrate"].assert_called_once()
    patched_up["ensure_launched"].assert_called_once()


def test_unknown_state_exits_71(patched_up, mocker) -> None:
    mocker.patch.object(
        up.workshop,
        "query_state",
        return_value=(State.UNKNOWN, CommandResult(1, "", "boom")),
    )

    with pytest.raises(SystemExit) as excinfo:
        up.run()

    assert excinfo.value.code == up.EXIT_STATUS_QUERY_FAILED
    patched_up["handoff"].assert_not_called()
