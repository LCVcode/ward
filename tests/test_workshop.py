"""Tests for the workshop CLI wrapper's pure logic.

The subprocess boundary is mocked so no real ``workshop`` binary is
required. We cover argv construction (the handoff seam designed to be
mockable per AGENTS.md), state parsing from ``workshop list`` output, and
the CommandResult value type.
"""

from __future__ import annotations

from pathlib import Path

from pytest_mock import MockerFixture

from ward import workshop
from ward.workshop import CommandResult, State


def test_run_action_argv_shape() -> None:
    assert workshop.run_action_argv("opencode") == [
        "workshop",
        "run",
        "ward",
        "opencode",
    ]


def test_quote_renders_invocation() -> None:
    rendered = workshop.quote(["workshop", "run", "a b", "c"])
    assert rendered == "workshop run 'a b' c"


def test_command_result_ok_and_combined() -> None:
    ok = CommandResult(returncode=0, stdout="out", stderr="")
    assert ok.ok is True
    assert ok.combined == "out"

    bad = CommandResult(returncode=1, stdout="o", stderr="e")
    assert bad.ok is False
    assert bad.combined == "oe"


def test_state_is_strenum_value_lookup() -> None:
    # Values mirror the literal tokens printed by ``workshop list``.
    assert State("Off") is State.OFF
    assert State.READY == "Ready"


def _mock_run(
    mocker: MockerFixture, returncode: int, stdout: str = "", stderr: str = ""
) -> None:
    proc = mocker.Mock(returncode=returncode, stdout=stdout, stderr=stderr)
    mocker.patch("ward.workshop.subprocess.run", return_value=proc)


def test_query_state_parses_ready(mocker: MockerFixture) -> None:
    _mock_run(mocker, 0, stdout="ward      Ready     -\n")
    state, result = workshop.query_state(Path("/tmp/project"))
    assert state is State.READY
    assert result.ok


def test_query_state_off(mocker: MockerFixture) -> None:
    _mock_run(mocker, 0, stdout="ward      Off     -\n")
    state, _ = workshop.query_state(Path("/tmp/project"))
    assert state is State.OFF


def test_query_state_unknown_token(mocker: MockerFixture) -> None:
    _mock_run(mocker, 0, stdout="ward      Bogus     -\n")
    state, _ = workshop.query_state(Path("/tmp/project"))
    assert state is State.UNKNOWN


def test_query_state_missing_project(mocker: MockerFixture) -> None:
    _mock_run(mocker, 1, stderr="error: not a project")
    state, _ = workshop.query_state(Path("/tmp/project"))
    assert state is State.MISSING


def test_query_state_unknown_on_error(mocker: MockerFixture) -> None:
    _mock_run(mocker, 1, stderr="daemon unreachable")
    state, _ = workshop.query_state(Path("/tmp/project"))
    assert state is State.UNKNOWN


def test_query_state_no_matching_row(mocker: MockerFixture) -> None:
    _mock_run(mocker, 0, stdout="other     Ready     -\n")
    state, _ = workshop.query_state(Path("/tmp/project"))
    assert state is State.MISSING
