"""ward command-line entry point.

Exposed via the ``[project.scripts]`` table in pyproject.toml so that
``pip install ward`` (or ``uv tool install ward``) provides a global
``ward`` executable on the host.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable, Sequence

from ward import __version__
from ward.commands import clean as cmd_clean
from ward.commands import init as cmd_init
from ward.commands import purge as cmd_purge
from ward.commands import sleep as cmd_sleep
from ward.commands import up as cmd_up


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ward",
        description=(
            "Infrastructure coordinator for Canonical Workshop VMs and "
            "OpenCode agents. Run inside a project directory to manage "
            "an isolated, pre-authenticated OpenCode sandbox."
        ),
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"ward {__version__}"
    )

    sub = parser.add_subparsers(
        dest="command",
        metavar="<command>",
        required=True,
    )
    sub.add_parser(
        "init",
        help="Provision workshop.yaml and AGENTS.md in the current Git repository.",
    )
    sub.add_parser(
        "up",
        help="Launch (or resume) the sandboxed OpenCode session.",
    )
    sub.add_parser(
        "sleep",
        help="Suspend the ward container, freeing host CPU and memory.",
    )
    sub.add_parser(
        "purge",
        help="Destroy the ward container (host project files are preserved).",
    )
    sub.add_parser(
        "clean",
        help="Remove ward files (workshop.yaml, AGENTS.md) from the project.",
    )
    return parser


_DISPATCH: dict[str, Callable[[], None]] = {
    "init": cmd_init.run,
    "up": cmd_up.run,
    "sleep": cmd_sleep.run,
    "purge": cmd_purge.run,
    "clean": cmd_clean.run,
}


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = _DISPATCH[args.command]
    handler()


if __name__ == "__main__":  # pragma: no cover
    main()
