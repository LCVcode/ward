# ward

> Per-project, pre-authenticated, sandboxed OpenCode sessions backed by
> Canonical Workshop.

`ward` is a host-side command-line orchestrator that drops you into an
isolated Ubuntu VM with your OpenCode auth, git identity, and SSH keys
already wired through. One global binary; per-project state lives in
`workshop.yaml` and `AGENTS.md` next to your code.

## Why ward

- You want every OpenCode session in an isolated Ubuntu VM with your
  auth pre-wired.
- You want consistent VM provisioning without copying scripts into
  every repo.
- You want commits, pushes, and clones from inside the VM to use your
  real identity and keys without manual setup.

## Architecture at a glance

```text
+------------------------------------------------------------+
| HOST MACHINE                                               |
|  /snap/bin/ward             (Global System Utility)        |
|                                                            |
|  ~/.config/opencode/         ~/.local/share/opencode/      |
|  (Global JSONC settings)     (Auth sessions & DB layers)   |
|                                                            |
|  ~/.gitconfig                ssh-agent (via SSH_AUTH_SOCK) |
|  (Identity, url rewrites)    (Forwarded into the workshop) |
|                                                            |
|  my-project/                                               |
|   ├── workshop.yaml         (Auto-generated, gitignored)   |
|   └── AGENTS.md             (Version-controlled AI memory) |
+------------------------------------------------------------+
                             |
       ward orchestrates: remounts, connects, injects
                             v
+------------------------------------------------------------+
| CANONICAL WORKSHOP SANDBOX (LXD container: 'ward')         |
|  - opencode SDK (with inline ssh-agent plug)               |
|  - uv SDK                                                  |
|  - /home/workshop/.config/opencode  (mount from host)      |
|  - /home/workshop/.local/share/opencode (mount from host)  |
|  - /home/workshop/.gitconfig (sanitized injection)         |
|  - SSH_AUTH_SOCK -> /var/lib/workshop/run/ssh-agent.sock   |
+------------------------------------------------------------+
```

The generated `workshop.yaml`:

```yaml
name: ward
base: ubuntu@24.04
sdks:
  - name: uv
    channel: latest/stable
  - name: opencode
    channel: latest/stable
    plugs:
      ssh-agent:
        interface: ssh-agent

actions:
  opencode: opencode "$@"
```

## Requirements

`ward init` and `ward up` validate every hard requirement before doing
anything. If a check fails you get a single actionable error line and a
non-zero exit code — ward never tries to auto-fix your host.

### Hard requirements (ward refuses to run)

| # | Requirement | Remediation |
|---|---|---|
| R1 | `workshop` CLI on PATH | `sudo snap install workshop` |
| R2 | `opencode` CLI on PATH | install OpenCode |
| R3 | `git` CLI on PATH | `sudo apt install git` |
| R4 | User in the `lxd` group (or UID 0) | `sudo usermod -aG lxd "$USER"`, then log out / `newgrp lxd` |
| R5 | `~/.config/opencode/` exists | `opencode /connect` on the host first |
| R6 | Current directory is a Git repository | `git init` (only checked by `ward init` / `ward up`) |
| R7 | `SSH_AUTH_SOCK` set in the shell and points at a live Unix socket | `eval "$(ssh-agent -s)" && ssh-add` |
| R8 | `SSH_AUTH_SOCK` also present in the **systemd user environment** | `systemctl --user import-environment SSH_AUTH_SOCK` |

R8 is the one that catches everyone. Workshop's daemon reads
`SSH_AUTH_SOCK` from the systemd user-manager's env block, **not** from
the calling shell. Setting it in your shell isn't enough; it has to be
imported into the user manager once per agent lifetime.

### Soft requirements (ward warns and continues)

| # | Condition | Hint |
|---|---|---|
| R9 | `ssh-add -l` reports no identities | `ssh-add ~/.ssh/id_ed25519` |
| R10 | No host git identity set | `git config --global user.email …` |

Without R9 your SSH agent is reachable but useless for git over SSH.
Without R10 commits inside the workshop will be anonymous.

### Which commands check what

| Command | Tier | Checks |
|---|---|---|
| `ward init` | full | R1–R10 |
| `ward up` | full | R1–R10 |
| `ward down` | minimal | R1, R4 |
| `ward clean` | minimal | R1, R4 |
| `ward purge` | minimal | R1, R4 |

Lifecycle commands stay minimal so you can still tear things down when
the host's SSH/git setup is broken.

## Installation

ward is distributed as a classic snap built from this repo. There is no
public release yet — build and install it yourself:

```bash
git clone https://github.com/LCVcode/ward.git
cd ward
snapcraft pack --use-lxd
sudo snap install --classic --dangerous ./ward_*.snap
```

Prerequisites for the build itself:

```bash
sudo snap install snapcraft --classic
sudo snap install lxd        # snapcraft uses LXD as the build backend
```

After installation, `which ward` should resolve to `/snap/bin/ward`.

### Dev loop without rebuilding

For a tight iteration cycle (no snap rebuild between edits), invoke
ward straight from the source tree:

```bash
uv run src/ward/cli.py <subcommand>
```

This uses your local Python environment instead of the snap-bundled
interpreter, so changes under `src/ward/` take effect immediately.

## Quickstart

```bash
ward init     # provisions workshop.yaml + AGENTS.md in this Git repo
ward up       # launches the workshop and hands off to OpenCode inside it
ward down     # when you're done, frees host CPU/memory
```

If any of R1–R8 isn't satisfied, `ward init` prints exactly what's
missing and how to fix it, then exits. Fix, re-run.

## Commands

### `ward init`

Provisions the project. Validates the full preflight, then writes
`workshop.yaml` (canonical blueprint with the `ssh-agent` plug on the
`opencode` SDK), seeds `AGENTS.md` (if missing), and adds the
`ward-managed-begin`/`-end` block to `.gitignore`.

Exits 64 (no git repo), 65 (no opencode config), 73 (existing
`workshop.yaml` with wrong `name:`), 77 (lxd group), 78 (SSH socket),
79 (systemd user env), 127 (missing binary).

### `ward up`

The main entry point. Idempotent.

1. Runs the full preflight (R1–R10).
2. Auto-generates `workshop.yaml` if missing.
3. Reconciles container state: launches if Off, stops if Ready/Waiting.
4. Remounts `~/.config/opencode/` and `~/.local/share/opencode/` into
   the workshop user's HOME.
5. Starts the workshop.
6. Connects the `opencode:ssh-agent` plug. If the workshop was launched
   against an older manifest that didn't have the plug, automatically
   runs `workshop refresh` and retries.
7. Injects a sanitized copy of `~/.gitconfig` (or
   `~/.config/git/config`) into `/home/workshop/.gitconfig`. Strips
   `[includeIf]`, `[include]`, `[gpg]`, plus `commit.gpgsign`,
   `user.signingkey`, `credential.helper`, and `core.sshCommand` —
   anything that would either reference host-only resources or break
   inside the sandbox.
8. Verifies `user.name` / `user.email` are readable inside the workshop.
9. `execvp`s `workshop run ward opencode` so signals (Ctrl-C, SIGWINCH)
   flow natively to the TUI.

Exits 70 (launch failed), 71 (status query failed), 74 (remount
failed), plus any preflight code.

### `ward down`

Stops the workshop container, releasing host CPU and memory. Container
state is preserved on disk; `ward up` resumes from where you left off.
No-ops if the workshop is already down. Exit 75 on failure.

### `ward clean`

Removes ward's per-project artifacts (`workshop.yaml`,
`.workshop.lock`, `AGENTS.md`) and the ward-managed `.gitignore` block.
Refuses if a container still exists for the project — run `ward purge`
first. Exit 80 if a container exists.

### `ward purge`

Destroys the workshop container. Host project files (your code,
`AGENTS.md`, `workshop.yaml`) are untouched. Exit 76 if removal fails
because something inside the VM is holding files.

## How it works

### Lifecycle

`ward up` always drives the workshop into `Stopped` before remounting,
because `workshop remount` only operates safely on a stopped workshop
unless the source happens to be on the same filesystem (which we don't
assume). After remount it `start`s the workshop, then runs the
manual-connect interfaces (just `ssh-agent` today), then the injection
steps, then `execvp`s into the OpenCode TUI.

### Mount bridge

Workshop's definition schema doesn't allow arbitrary host paths in the
manifest — that's a deliberate security boundary. ward uses
`workshop remount <plug> <host-path>` at runtime to wire host-side
config and data directories into the workshop's `/home/workshop/`. The
plugs are defined by the upstream `opencode` SDK; ward only supplies
the host source paths.

### SSH agent path

This is the non-obvious bit. To get `git clone git@github.com:…`
working inside the workshop, **three** layers all have to be set up:

1. **Shell:** `SSH_AUTH_SOCK` is exported in the shell that runs
   `ward up`. Provided by `eval "$(ssh-agent -s)" && ssh-add` (or a
   systemd user `ssh-agent.service`).
2. **Systemd user environment:** the same value is also visible to the
   user-manager, via `systemctl --user import-environment SSH_AUTH_SOCK`.
   This is what workshop's daemon reads when wiring the plug — not the
   shell env of the `workshop` CLI process. Without this, `workshop
   connect ward/opencode:ssh-agent` fails with `environment variable
   SSH_AUTH_SOCK not found`.
3. **Workshop plug:** the `ssh-agent` plug, declared on the `opencode`
   SDK in `workshop.yaml` and manually connected by `ward up`. SSH
   plugs are manual-connect by design; ward handles the `connect` step
   automatically.

When all three line up, the workshop user gets
`SSH_AUTH_SOCK=/var/lib/workshop/run/ssh-agent.sock`, and
`ssh-add -l` inside the VM lists your host keys.

## Troubleshooting

### "Permission denied (publickey)" inside the workshop

Walk through R7–R9 in order:

```bash
echo "$SSH_AUTH_SOCK"                                # should be non-empty
ssh-add -l                                           # should list keys
systemctl --user show-environment | grep SSH_AUTH    # should appear
workshop connections ward                            # slot column should NOT be '-'
```

If `systemctl --user show-environment` doesn't include `SSH_AUTH_SOCK`,
run `systemctl --user import-environment SSH_AUTH_SOCK` and then
`ward up` again. (You'll need to redo this every time you start a new
agent — that's why ward enforces it at preflight rather than auto-fixing.)

### `ssh-add -l` inside the VM says "Could not open a connection"

`workshop connections ward` will show the ssh-agent plug with a `-` in
the slot column, meaning the connect step never succeeded. The cause is
almost always R8 (systemd user env). Fix R8 on the host, then re-run
`ward up`.

### `sudo git …` inside the VM fails even though plain `git …` works

Don't use `sudo` inside the workshop. It switches to root, which has
`HOME=/root` (so `/home/workshop/.gitconfig` is invisible) and drops
`SSH_AUTH_SOCK` from its env (so ssh has no keys). Git and ssh always
work as the default `workshop` user.

### "Workshop has no plug named ssh-agent" after editing the manifest

The workshop was launched against an older `workshop.yaml`. `ward up`
detects this automatically and runs `workshop refresh` before retrying
the connect. If you hit it from a manual `workshop connect`, just run
`workshop refresh ward` once.

## Exit codes

Single source of truth — every non-zero exit ward emits.

| Code | Meaning |
|---|---|
| 64 | Current directory is not a Git repository |
| 65 | Missing `~/.config/opencode/` (run `opencode /connect`) |
| 70 | Workshop launch failed (network, snap store, etc.) |
| 71 | Workshop status query failed (lxd daemon / permissions) |
| 73 | Existing `workshop.yaml` has wrong `name:` |
| 74 | Mount remount failed |
| 75 | Workshop shutdown (`down`) failed |
| 76 | Workshop removal (`purge`) failed |
| 77 | User not in `lxd` group, or lxd not installed |
| 78 | `SSH_AUTH_SOCK` unset or invalid in shell |
| 79 | `SSH_AUTH_SOCK` missing from systemd user environment |
| 80 | `ward clean` blocked because a container still exists |
| 127 | A required binary (`workshop` / `opencode` / `git`) is missing |

## Project layout

```text
src/ward/
  cli.py              # argparse entry point
  preflight.py        # tiered host dependency checks
  manifest.py         # workshop.yaml templating + validation
  workshop.py         # thin, defensive wrapper around the workshop CLI
  errors.py           # die/info/warn helpers
  commands/
    init.py
    up.py
    down.py
    clean.py
    purge.py
snap/snapcraft.yaml   # classic snap definition (core24)
```

Per-project, written by `ward init`:

- `workshop.yaml` — the canonical manifest (gitignored).
- `AGENTS.md` — long-term version-controlled context for AI agents.
  Seeded as a placeholder if absent; commit it.
- `.workshop.lock` — workshop CLI local state pin (gitignored).
- `.gitignore` — gets a `# ward-managed-begin`/`# ward-managed-end`
  block appended; `ward clean` removes the block in place.
