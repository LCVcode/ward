"""Tests for canonical workshop.yaml generation and validation.

These exercise the manifest's ownership invariant (``name: ward``) and the
generate/validate/ensure round-trip — all pure filesystem logic with no
subprocess boundary, so they run fast and hermetically under a tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ward import manifest


def test_generate_writes_canonical_manifest(tmp_path: Path) -> None:
    target = manifest.generate(tmp_path)

    assert target == tmp_path / manifest.MANIFEST_FILENAME
    assert target.is_file()
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert data["name"] == manifest.EXPECTED_NAME


def test_exists_reflects_presence(tmp_path: Path) -> None:
    assert manifest.exists(tmp_path) is False
    manifest.generate(tmp_path)
    assert manifest.exists(tmp_path) is True


def test_validate_accepts_generated_manifest(tmp_path: Path) -> None:
    manifest.generate(tmp_path)
    # Should not raise for the canonical blueprint.
    manifest.validate(tmp_path)


def test_validate_rejects_foreign_name(tmp_path: Path) -> None:
    target = tmp_path / manifest.MANIFEST_FILENAME
    target.write_text("name: not-ward\n", encoding="utf-8")

    with pytest.raises(manifest.WrongNameError) as excinfo:
        manifest.validate(tmp_path)
    assert excinfo.value.found_name == "not-ward"


def test_validate_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        manifest.validate(tmp_path)


def test_ensure_generates_when_absent(tmp_path: Path) -> None:
    assert not manifest.exists(tmp_path)
    target = manifest.ensure(tmp_path)
    assert target.is_file()


def test_ensure_validates_when_present(tmp_path: Path) -> None:
    manifest.generate(tmp_path)
    # Re-running ensure on a valid manifest is a no-op that returns the path.
    target = manifest.ensure(tmp_path)
    assert target == tmp_path / manifest.MANIFEST_FILENAME


def test_ensure_propagates_wrong_name(tmp_path: Path) -> None:
    (tmp_path / manifest.MANIFEST_FILENAME).write_text(
        "name: intruder\n", encoding="utf-8"
    )
    with pytest.raises(manifest.WrongNameError):
        manifest.ensure(tmp_path)
