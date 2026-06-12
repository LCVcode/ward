"""workshop.yaml generation and validation.

The manifest is treated as opinionated and verified. ward writes the
canonical blueprint verbatim and refuses to operate on any pre-existing
manifest whose `name:` field does not equal `ward` — the container
namespace ward orchestrates is hardcoded by design.
"""

from __future__ import annotations

from pathlib import Path

import yaml

MANIFEST_FILENAME = "workshop.yaml"
EXPECTED_NAME = "ward"

# The canonical workshop manifest written by 'ward init'.
# Written verbatim so the on-disk file is reproducible across hosts.
#
# Notes on shape:
# - The workshop definition schema only accepts: name, base, sdks, connections,
#   actions. There is no top-level `interfaces:` key; any such block is silently
#   ignored. Network access is always available; the SSH agent must be wired
#   through an explicit plug on a regular SDK (the system SDK cannot host
#   ssh-agent plugs per the SSH interface reference).
# - The `ssh-agent` plug is declared inline on the `opencode` SDK so the agent
#   can use the operator's forwarded SSH identities for git remotes. The
#   ssh-agent interface is manual-connect, so `ward up` runs `workshop connect`
#   after starting the workshop.
MANIFEST_CONTENT = """\
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
"""


class WrongNameError(Exception):
    """Raised when an existing workshop.yaml has a name other than 'ward'."""

    def __init__(self, found_name: str) -> None:
        super().__init__(found_name)
        self.found_name = found_name


def manifest_path(project_dir: Path) -> Path:
    """Return the canonical manifest path within a project directory."""
    return project_dir / MANIFEST_FILENAME


def exists(project_dir: Path) -> bool:
    return manifest_path(project_dir).is_file()


def generate(project_dir: Path) -> Path:
    """Write the canonical manifest to ``project_dir`` and return its path."""
    target = manifest_path(project_dir)
    target.write_text(MANIFEST_CONTENT, encoding="utf-8")
    return target


def validate(project_dir: Path) -> None:
    """Parse the on-disk manifest and assert it is owned by ward.

    Raises:
        FileNotFoundError: If the manifest does not exist.
        WrongNameError:    If ``name:`` is anything other than 'ward'.
        yaml.YAMLError:    If the file is not valid YAML.
    """
    target = manifest_path(project_dir)
    raw = target.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    name = ""
    if isinstance(data, dict):
        name = str(data.get("name", "")).strip()

    if name != EXPECTED_NAME:
        raise WrongNameError(name)


def ensure(project_dir: Path) -> Path:
    """Validate or generate the manifest. Returns the manifest path.

    If the manifest is absent, the canonical blueprint is written.
    If present, it is validated; ``WrongNameError`` propagates on mismatch.
    """
    target = manifest_path(project_dir)
    if target.is_file():
        validate(project_dir)
        return target
    return generate(project_dir)
