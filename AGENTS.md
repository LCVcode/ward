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

## Design Philosophy

**ward is a thin layer. The thinner the better.**

- ward is an **orchestration shim** over the `workshop` CLI. It should add
  as little code and as few moving parts as possible. Behavior that belongs
  to `workshop`, `snap`, or the OS stays there — ward delegates, it does not
  reimplement.
- **Strong preference for the Python standard library** over third-party
  dependencies. Reach for built-ins (`argparse`, `subprocess`, `pathlib`,
  `dataclasses`, `enum`, `shutil`, etc.) before considering anything on PyPI.
- A **new runtime dependency is a last resort.** It must be genuinely
  unavoidable, justified explicitly in the PR, and approved. The current
  runtime surface is a single dependency (`pyyaml`); keep it that way unless
  there is no reasonable stdlib path.
- Prefer **deleting code over adding it**, and composing built-ins over
  introducing abstractions. When a change can be made smaller, make it
  smaller.

## Setup & Dev Loop

- Python **>=3.12** (pinned in `.python-version`).
- Dependency manager is **uv** (`uv.lock`):
  - `uv sync --extra dev` — set up the environment with dev deps.
- Run without rebuilding the snap:
  - `uv run src/ward/cli.py <subcommand>`
- Run tests:
  - `uv run pytest`
- Lint & type-check (configured in `pyproject.toml`):
  - `uv run ruff check .`
  - `uv run ty check`
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
- `commands/` — one module per subcommand (`init`, `up`, `status`,
  `down`, `clean`, `purge`).

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

## Versioning

ward follows **Semantic Versioning**. Every change that lands bumps the
version **in the same commit/PR** as the change itself — there is no separate
"release" commit. Bump the version in **both** `pyproject.toml` and
`src/ward/__init__.py` together (see Invariants & Gotchas).

### What counts as ward's public contract

A change is **breaking** only if it alters observable behavior that a user or
script depends on. ward's public surface is:

- **Exit codes** (the `EXIT_*` constants / README "Exit codes" table).
- **CLI surface**: subcommand names, flags, and their semantics.
- **Generated artifacts**: the structure/schema of the templated
  `workshop.yaml` and `AGENTS.md`, including invariants like `name: ward`
  and the file layout that `clean` / `purge` rely on.
- **Documented behavior** of `init` / `up` / `down` / `clean` / `purge`.

Internal refactors, private helpers, docstrings, tests, and comments are
**not** part of the contract.

### Bump rules

ward is **pre-1.0** (`0.y.z`), so there is no stability guarantee yet and the
major component stays `0`. We use the common "shift-down" convention while
pre-1.0:

| Change | Pre-1.0 (current) | Post-1.0 |
| --- | --- | --- |
| Breaking change to a public contract above | **MINOR** (`0.y+1.0`) | MAJOR (`x+1.0.0`) |
| New backward-compatible feature, subcommand, or flag | **PATCH** (`0.y.z+1`) | MINOR (`0.y+1.0`) |
| Bug fix, docs, refactor — no behavior change | **PATCH** (`0.y.z+1`) | PATCH (`x.y.z+1`) |

So **while pre-1.0**: a breaking change bumps the **minor**; everything else
bumps the **patch**.

### Commit-prefix mapping

The repo uses Conventional Commits. Map the prefix to the bump:

- `fix:` → patch
- `feat:` → patch (pre-1.0) / minor (post-1.0)
- `feat!:` or a `BREAKING CHANGE:` footer → minor (pre-1.0) / major (post-1.0)
- `docs:`, `refactor:`, `test:`, `chore:`, `ci:` → patch (or no bump if
  nothing user-visible ships)

Any change to exit codes or generated artifacts is **breaking** — bump the
minor (pre-1.0) **and** sync the README in the same commit.

## Testing

- Framework: **pytest** + **pytest-mock** (declared under the `dev` extra).
- Add tests under `tests/` for any new or changed logic. The `tests/`
  directory currently exists but is empty.
- Code is written to be testable (e.g. `workshop.run_action_argv()` returns
  argv rather than executing). Prefer mocking subprocess boundaries.

## Agent Notes

- See **`SKILLS.md`** for external agent skills to use on `workshop`-related
  tasks (notably the upstream `use-workshop` skill). Reference them by URL;
  do not vendor them into this repo.
- Ruff (`ruff check`), ty (`ty check`), and pytest run in GitHub Actions on
  push/PR. Keep all three green; match the existing style.
- `README.md` is the single source of truth for documentation (there is no
  `docs/` directory and no `CONTRIBUTING.md`).
