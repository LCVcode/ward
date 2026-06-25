# SKILLS.md

External agent **skills** that agents working on `ward` should reach for.

These skills live **upstream** and are referenced by URL, not vendored. In
keeping with ward's thin-layer ethos (see `AGENTS.md`), do **not** copy,
transcribe, or fork their content into this repo — fetch them on demand and
treat the upstream source as authoritative. Several are also GPL-licensed,
and ward carries no license of its own; a URL pointer keeps that boundary
clean.

## use-workshop

Operating the **Workshop** CLI: launching/refreshing workshops, running
commands inside them, wiring interfaces, debugging failed changes, and
orchestrating parallel environments via git worktrees.

**When to use it.** Any task that touches the `workshop` CLI, a
`workshop.yaml` / `.workshop.yaml` definition, an LXD-backed dev
environment, interface connections, or a failed/stuck `workshop change`.
This is directly relevant to `ward`, which is a thin orchestrator **over**
the `workshop` CLI.

**Source (authoritative, do not vendor):**

- Repo: <https://github.com/canonical/use-workshop-skill>
- Router (`SKILL.md`) to fetch first:
  `https://raw.githubusercontent.com/canonical/use-workshop-skill/main/.github/skills/use-workshop/SKILL.md`
- Raw base for the router's relative `workflows/`, `references/`, and
  `templates/` links:
  `https://raw.githubusercontent.com/canonical/use-workshop-skill/main/.github/skills/use-workshop/`

**How to use it.** `SKILL.md` is a *router*, not a playbook. Fetch it, then
follow its `<routing>` / `<reference_index>` to the one workflow and the one
or two reference files you actually need, resolving each relative path
against the raw base above. The Workshop docs site
(<https://ubuntu.com/workshop/docs/>) is the source of truth for CLI
behavior; the skill only routes you to the right page.

**Local shortcut.** On a host where this skill is installed at
`~/.config/opencode/skills/use-workshop/`, load it directly via the agent's
skill mechanism instead of fetching over the network.

Pinned to `main` so upstream fixes flow through automatically.
