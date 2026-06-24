# AGENTS.md

Guidance for AI agents working **on the `ward` codebase itself**.

> Note: `ward` *generates* an `AGENTS.md` and a `workshop.yaml` for **user**
> projects (templates live in `src/ward/commands/init.py` and
> `src/ward/manifest.py`). Those generated files are NOT this repo's own
> config — do not confuse them with this file.

## Project Overview

`ward` is a host-side CLI orchestrator that wraps **Canonical Workshop**
(LXD-backed Ubuntu VMs) to provide per-project, pre-authenticated, sandboxed
**OpenCode** agent sessions. It ships as a single global **classic snap**
binary. Subcommands: `init`, `up`, `down`, `clean`, `purge`.

## Setup & Dev Loop

- Python **>=3.12** (pinned in `.python-version`).
- Dependency manager is **uv** (`uv.lock`):
  - `uv sync --extra dev` — set up the environment with dev deps.
- Run without rebuilding the snap:
  - `uv run src/ward/cli.py <subcommand>`
- Run tests:
  - `uv run pytest`
- Build/install the snap (the real distribution path):
  - `snapcraft pack --use-lxd` then
    `sudo snap install --classic --dangerous ./ward_*.snap`
  - or the helper scripts in `scripts/snap-install.sh` / `snap-uninstall.sh`.

## Architecture

`src/` layout; package at `src/ward/`.

- `cli.py` — `argparse` parser, dispatches subcommands to `command.run()`.
- `preflight.py` — tiered host precondition checks; stable exit-code constants.
- `manifest.py` — canonical `workshop.yaml` templating + validation.
- `workshop.py` — defensive subprocess wrapper around the `workshop` CLI.
- `errors.py` — centralized `die()` / `info()` / `warn()` output helpers.
- `commands/` — one module per subcommand (`init`, `up`, `down`, `clean`,
  `purge`).

**Invariant:** the `workshop` CLI is only ever invoked through `workshop.py`.
Never call it directly from command modules.

## Coding Conventions

- `from __future__ import annotations` at the top of every module.
- Modern typing everywhere: `X | None`, `list[str]`, `NoReturn` for `die()`.
- Rich module + function docstrings that explain *why*, not just *what*.
- `@dataclass` / `@dataclass(frozen=True)` for value types; `Enum` for
  state/tier modeling.
- `_`-prefixed private helpers; `UPPER_SNAKE_CASE` constants; regexes
  precompiled at module level.
- Line length ~79–80 columns (black-compatible, but no formatter is enforced).
- All user-facing output goes through `errors.die/info/warn`, is prefixed
  `[ERROR]` / `[WARN]` / `[INFO]`, and always includes an actionable
  remediation command.
- `subprocess.run` calls always use
  `capture_output=True, text=True, check=False, timeout=...`.

## Invariants & Gotchas

- **Exit codes are a stable public contract.** The module constants (e.g.
  `EXIT_NO_GIT_REPO = 64`) must stay in sync with the "Exit codes" table in
  `README.md`. Update both together.
- **Version is duplicated** in `pyproject.toml` and `src/ward/__init__.py`
  (the snap adopts its version from `pyproject.toml`). Keep them in sync.
- `ward clean` intentionally **preserves `AGENTS.md`** — it removes only
  `workshop.yaml` and `.workshop.lock`.
- `manifest.py` refuses any manifest whose `name:` is not `ward`.

## Testing

- Framework: **pytest** + **pytest-mock** (declared under the `dev` extra).
- Add tests under `tests/` for any new or changed logic. The `tests/`
  directory currently exists but is empty.
- Code is written to be testable (e.g. `workshop.run_action_argv()` returns
  argv rather than executing). Prefer mocking subprocess boundaries.

## Agent Notes

- No CI, linter, or formatter is currently wired up. Match the existing style.
- `README.md` is the single source of truth for documentation (there is no
  `docs/` directory and no `CONTRIBUTING.md`).
