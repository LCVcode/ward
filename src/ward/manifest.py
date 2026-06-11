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

# The canonical, verified blueprint from SPEC.md section 3.
# Written verbatim so the on-disk file matches the spec character-for-character.
MANIFEST_CONTENT = """\
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
