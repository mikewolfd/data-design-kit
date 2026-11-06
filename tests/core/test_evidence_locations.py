"""Retained receipt identities survive an explicit evidence-directory move."""

from hashlib import sha256

import pytest

from ddk.conformance import _admitted, _read_reference
from ddk.evidence_locations import EvidenceDirectory, evidence_path


def test_remapped_reference_reads_copied_bytes_without_rewriting_identity(tmp_path):
    captured = tmp_path / "original"
    moved = tmp_path / "relocated"
    moved.mkdir()
    data = b'{"source":"original captured bytes"}'
    (moved / "receipt.json").write_bytes(data)
    reference = {"path": str(captured / "receipt.json"), "sha256": sha256(data).hexdigest()}
    root = EvidenceDirectory(moved, captured)
    assert not captured.exists()
    assert _admitted(reference, root, {})
    assert _read_reference(reference, root).value == {"source": "original captured bytes"}
    assert reference["path"] == str(captured / "receipt.json")
    assert evidence_path(root, "receipt.json") == moved / "receipt.json"
    assert not _admitted(reference, moved, {})
    (moved / "receipt.json").write_bytes(b'{"source":"substituted"}')
    assert not _admitted(reference, root, {})


def test_relocation_refuses_foreign_roots_parent_traversal_and_symlink_escape(tmp_path):
    retained = tmp_path / "retained"
    retained.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{}')
    (retained / "escape.json").symlink_to(outside)
    captured = tmp_path / "old-root"
    root = EvidenceDirectory(retained, captured)
    for path in (outside, "../outside.json", captured / "escape.json", captured / ".." / "outside.json"):
        with pytest.raises(ValueError):
            evidence_path(root, path)
    with pytest.raises(ValueError):
        EvidenceDirectory(retained, "relative-original-root")
