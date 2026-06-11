# Functional Specification: Ward

## 1. Overview & Objective

`ward` is a system-wide, open-source command-line tool packaged as a single, centralized utility. It acts as an opinionated infrastructure coordinator that manages the lifecycle of Canonical Workshop VMs (LXD system containers) and orchestrates OpenCode AI agent execution within individual project directories.

Rather than copying script wrappers into every project repository, `ward` resides globally on the host machine. When invoked within a codebase directory, it dynamically handles the localized VM lifecycle, enforces zero-trust security boundaries, and automates host credential injection via runtime remount overrides.

```text
+------------------------------------------------------------+
| HOST MACHINE                                               |
|  /usr/bin/ward (Global System Utility)                     |
|                                                            |
|  ~/.config/opencode/       ~/.local/share/opencode/        |
|  (Global JSONC Settings)    (Auth Sessions & DB Layers)    |
|                                                            |
|  my-project/ (Codebase Workspace Volume)                   |
|   ├── workshop.yaml (Auto-generated Blueprint)             |
|   └── AGENTS.md     (Version-Controlled AI memory)         |
+------------------------------------------------------------+
                               |
            ward dynamically configures / remounts
                               v
+------------------------------------------------------------+
| CANONICAL WORKSHOP SANDBOX (VM: ward)                      |
|  - Managed OpenCode Official SDK Layer                     |
|  - Config plug mapped to: /home/workshop/.config/opencode  |
|  - Data plug mapped to:   /home/workshop/.local/share/...  |
|  - Isolated system execution layer                         |
+------------------------------------------------------------+
```

## 2. Core Architecture Components

- **The Global Orchestrator:** `ward` runs as a singular host-level application. It carries no local project directory artifacts; instead, it dynamically inspects the host's current working directory to read, generate, or execute infrastructure tasks.
- **The Sandbox Provider:** Canonical Workshop VMs (`workshop`). Provisions an unprivileged, isolated Ubuntu environment using a standardized project-level `workshop.yaml` blueprint.
- **The Agent Driver:** OpenCode (`opencode`). Operates strictly inside the sandbox to process codebase intelligence, modify files, and run tools via segregated Plan and Build states.
- **The Bridge Mechanism:** Secure host-configuration pass-through. Because Workshop bans arbitrary hardcoded volume paths in the configuration manifest for security, `ward` utilizes the `workshop remount` runtime override. This maps the host's active `opencode-config` and `opencode-data` slots straight to the container's unprivileged `/home/workshop/` environment, achieving instant, pre-authenticated pass-through of all API keys and backends.

## 3. Verified Manifest Template (`workshop.yaml`)

When provisioning an environment, `ward` automatically generates and manages the following verified blueprint format within the target project folder:

```yaml
name: ward
base: ubuntu@24.04
sdks:
  - name: opencode
    channel: latest/stable

actions:
  opencode: opencode "$@"

interfaces:
  - type: network
  - type: ssh-agent
```

## 4. Global Error Handling & Defensive Guardrails

To prevent silent failures, obscure stack traces, or broken environments, `ward` enforces strict defensive programming across all commands.

### Host Pre-Flight Dependency Engine (Run Before Every Command)

Before executing any sub-command, `ward` verifies host dependencies. If any check fails, it immediately terminates with a clear, actionable instruction:

1. **Verify Host `workshop` Binary:**
   - Check: Executes `command -v workshop`.
   - On Failure: Exits with code 127. Prints: `[ERROR] Canonical Workshop CLI ('workshop') is not installed on the host. Please install it via snap: 'sudo snap install workshop'.`
2. **Verify Host `opencode` Binary:**
   - Check: Executes `command -v opencode`.
   - On Failure: Exits with code 127. Prints: `[ERROR] OpenCode CLI ('opencode') is missing from the host path. Install it via your host package manager to establish global configuration paths.`
3. **Verify Host Local Configuration Directory:**
   - Check: Verifies `[ -d ~/.config/opencode ]`.
   - On Failure: Exits with code 65. Prints: `[ERROR] No local OpenCode configuration found at ~/.config/opencode. Run 'opencode /connect' on your host machine first to authenticate your backend accounts.`

## 5. Command Specification & Syntax

### `ward init`

- **Behavior:** Assures the current working directory is an active Git repository. Generates the verified `workshop.yaml` manifest blueprint directly in the project root if it does not already exist.
- **Defensive Failure Guardrails:**
  - If `[ ! -d .git ]`: Exits with code 64. Prints: `[ERROR] Active directory is not a Git repository. 'ward' requires a Git root directory to securely pin local AI agent states via version control.`
  - If `workshop.yaml` exists but has a conflicting `name:` element: Exits with code 73. Prints: `[ERROR] A workshop.yaml exists but is configured with an invalid name '[found_name]'. 'ward' requires the container namespace to be explicitly set to 'name: ward'.`
- **Context Seeding:** Checks for the presence of `AGENTS.md`. If missing, it instructs OpenCode to initialize it, capturing the local codebase rules and dependencies to anchor long-term context memory inside the Git tree.

### `ward up`

- **Behavior:** Automatically detects or generates the local `workshop.yaml` file, then inspects the state of the Canonical Workshop instance matching the project context.
- **Defensive Lifecycle Logic:**
  - Fetches state via `workshop status`. If the command errors out due to daemon misconfigurations, exits with code 71. Prints: `[ERROR] Failed to query Canonical Workshop status. Verify your user belongs to the 'lxd' group or try restarting the system container daemon.`
  - If missing → Runs `workshop launch`. If compilation fails due to network issues, prints: `[ERROR] Workshop launch timed out or failed. Verify your internet connection and network interfaces policy.`
  - If stopped → Runs `workshop start`.
- **Hydration Loop:** Gracefully halts the container execution state, enforces host directory injection via runtime remounts, and reactivates the system:

  ```bash
  workshop stop ward
  workshop remount ward/opencode:opencode-config ~/.config/opencode
  workshop remount ward/opencode:opencode-data ~/.local/share/opencode
  workshop start ward
  ```

  - **Mount Guard:** If `workshop remount` fails, exits with code 74. Prints: `[ERROR] Configuration bridge failed. Ensure target directory paths are not locked or modified by another systemic execution window.`
- **Handoff:** Invokes the containerized execution wrapper: `workshop run ward opencode`, dropping the operator straight into the pre-authenticated, sandboxed OpenCode TUI workspace.

### `ward sleep`

- **Behavior:** Suspends active agent interactions in the current workspace directory and issues a `workshop stop ward` command. Immediately deallocates host CPU and memory footprint while anchoring the container's state safely on disk.
- **Defensive Guardrails:** If the container is already stopped, gracefully exits with code 0. Prints: `[INFO] Container 'ward' is already sleeping.` If the process hangs, exits with code 75. Prints: `[ERROR] Failed to suspend container 'ward'. Force execution termination via 'workshop stop --force ward'.`

### `ward purge`

- **Behavior:** Executes `workshop remove --force ward` against the container mapped to the current project. Deletes the entire container environment layout. Because all code changes and the `AGENTS.md` log reside natively on the host filesystem mount, zero project history or agent memory is lost during environment teardown.
- **Defensive Guardrails:** If no environment exists, exits with code 0. Prints: `[INFO] No active container found to purge for this project workspace.` If deletion fails due to locked underlying resources, exits with code 76. Prints: `[ERROR] Infrastructure removal failed. An active process inside the VM may be locking files. Terminate active sessions first via 'ward sleep'.`
