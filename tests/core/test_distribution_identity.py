"""Independent cases for installed build records and honest development locks."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ddk import __version__, distribution, locks
from ddk.core import load_project

from test_core import check, codes, commerce


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root = tmp_path / "site-packages"
    package = root / "ddk"
    package.mkdir(parents=True)
    record = {"formatVersion": 1, "distributionVersion": "0.1.0.dev1",
              "sourceCommit": "1" * 40, "sourceTreeSha256": "a" * 64}
    (package / "_build.json").write_text(json.dumps(record))
    direct = {"url": "file:///no-longer-retained/data_design_kit-0.1.0.dev1-py3-none-any.whl",
              "archive_info": {"hashes": {"sha256": "b" * 64}}}
    metadata = SimpleNamespace(version="0.1.0.dev1", files=[Path("ddk/distribution.py"), Path("ddk/_build.json")],
                               locate_file=lambda path: root / path,
                               read_text=lambda name: json.dumps(direct) if name == "direct_url.json" else None)
    lookup = distribution.metadata.distribution
    monkeypatch.setattr(distribution.metadata, "distribution", lambda name: metadata if name == "data-design-kit" else lookup(name))
    monkeypatch.setattr(distribution, "__file__", str(package / "distribution.py"))
    return metadata, package, record, direct


def test_installed_identity_uses_build_and_installer_records_without_wheel_reads(installed, monkeypatch):
    monkeypatch.setenv("DDK_SOURCE_COMMIT", "2" * 40)
    monkeypatch.setenv("DDK_DISTRIBUTION_SHA256", "c" * 64)
    assert distribution.distribution_identity() == {
        "version": "0.1.0.dev1", "commit": "1" * 40, "distributionSha256": "b" * 64,
    }


def test_source_checkout_does_not_claim_another_installation_or_env_identity(installed, monkeypatch, tmp_path):
    monkeypatch.setattr(distribution, "__file__", str(tmp_path / "checkout/src/ddk/distribution.py"))
    monkeypatch.setenv("DDK_SOURCE_COMMIT", "2" * 40)
    monkeypatch.setenv("DDK_DISTRIBUTION_SHA256", "c" * 64)
    assert distribution.distribution_identity() == {"version": __version__}


def test_no_installation_keeps_the_source_version(monkeypatch):
    def absent(name):
        raise distribution.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(distribution.metadata, "distribution", absent)
    assert distribution.distribution_identity() == {"version": __version__}


@pytest.mark.parametrize("files", [None, [], [Path("_ddk.pth")]])
def test_missing_file_inventory_and_editable_installs_do_not_identify_loaded_code(installed, files):
    metadata, *_ = installed
    metadata.files = files
    assert distribution.distribution_identity() == {"version": __version__}


@pytest.mark.parametrize("change", [
    {"formatVersion": 2}, {"formatVersion": True}, {"distributionVersion": "0.1.0.dev99"},
    {"sourceCommit": "short"}, {"sourceTreeSha256": "invalid"},
])
def test_invalid_build_record_does_not_supply_a_commit(installed, change):
    _, package, record, _ = installed
    (package / "_build.json").write_text(json.dumps({**record, **change}))
    assert distribution.distribution_identity() == {"version": "0.1.0.dev1", "distributionSha256": "b" * 64}


def test_missing_or_malformed_build_record_preserves_the_independent_installer_record(installed):
    _, package, *_ = installed
    (package / "_build.json").write_text("{invalid")
    assert "commit" not in distribution.distribution_identity()
    (package / "_build.json").unlink()
    assert distribution.distribution_identity() == {"version": "0.1.0.dev1", "distributionSha256": "b" * 64}


@pytest.mark.parametrize("direct", [None, "{invalid", "[]", '{"archive_info": {"hashes":{"sha256":"bad"}}}'])
def test_missing_or_malformed_installer_record_does_not_supply_a_digest(installed, direct):
    metadata, *_ = installed
    metadata.read_text = lambda name: direct
    assert distribution.distribution_identity() == {"version": "0.1.0.dev1", "commit": "1" * 40}


@pytest.mark.parametrize("archive, expected", [
    ({"hash": "sha256=" + "d" * 64}, "d" * 64),
    ({"hashes": {"sha256": "b" * 64}, "hash": "sha256=" + "b" * 64}, "b" * 64),
    ({"hashes": {"sha256": "b" * 64}, "hash": "sha256=" + "d" * 64}, None),
    ({"hashes": {"md5": "d" * 32}, "hash": "sha256=" + "d" * 64}, None),
    ({"hashes": {"sha256": "bad"}}, None),
    ({}, None),
])
def test_installer_sha256_formats_and_conflicts(installed, archive, expected):
    *_, direct = installed
    direct["archive_info"] = archive
    assert distribution.distribution_identity().get("distributionSha256") == expected


def test_source_archive_digest_cannot_stand_in_for_the_built_wheel(installed):
    *_, direct = installed
    direct["url"] = "https://example.invalid/data_design_kit-0.1.0.dev1.tar.gz"
    assert "distributionSha256" not in distribution.distribution_identity()


@pytest.mark.parametrize("missing", ["commit", "distributionSha256", "both"])
def test_missing_development_identity_blocks_locked_proof_but_keeps_ordinary_check(commerce, monkeypatch, missing):
    identity = {"version": "0.1.0.dev1", "commit": "1" * 40, "distributionSha256": "a" * 64}
    for field in ("commit", "distributionSha256") if missing == "both" else (missing,):
        identity.pop(field)
    monkeypatch.setattr(locks, "distribution_identity", lambda: dict(identity))
    check(commerce, "passed")
    lock = locks.build_lock(load_project(commerce / "project.ddk.json"))
    report = check(commerce, "failed", locked=True, lock=lock)
    assert "LOCK-TOOL-IDENTITY-MISSING" in codes(report)
    assert report["lock"]["verified"] is False


def test_available_installed_development_identity_allows_locked_proof(commerce, installed):
    lock = locks.build_lock(load_project(commerce / "project.ddk.json"))
    report = check(commerce, "passed", locked=True, lock=lock)
    assert report["lock"]["verified"] is True


@pytest.mark.parametrize("missing", ["commit", "distributionSha256", "both"])
def test_missing_development_identity_refuses_lock_creation_and_preserves_output(commerce, monkeypatch, missing):
    identity = {"version": "0.1.0.dev1", "commit": "1" * 40, "distributionSha256": "a" * 64}
    for field in ("commit", "distributionSha256") if missing == "both" else (missing,):
        identity.pop(field)
    monkeypatch.setattr(locks, "distribution_identity", lambda: dict(identity))
    destination = commerce / "retained.lock.json"
    report, lock = locks.lock_project(commerce / "project.ddk.json", destination)
    assert report["decision"] == "incomplete" and lock is None
    assert "LOCK-TOOL-IDENTITY-MISSING" in codes(report)
    assert not destination.exists()
    destination.write_text("previous lock bytes\n")
    report, lock = locks.lock_project(commerce / "project.ddk.json", destination)
    assert report["decision"] == "incomplete" and lock is None
    assert destination.read_text() == "previous lock bytes\n"
    check(commerce, "passed")


def test_installed_identity_allows_lock_creation_without_environment_overrides(commerce, installed):
    destination = commerce / "selected.lock.json"
    report, lock = locks.lock_project(commerce / "project.ddk.json", destination)
    assert report["decision"] == "passed"
    assert json.loads(destination.read_text()) == lock
    assert lock["tools"]["ddk"] == distribution.distribution_identity()


def test_caller_cannot_replace_observed_ddk_identity_or_drop_its_fields(commerce, installed):
    inventory = load_project(commerce / "project.ddk.json")
    with pytest.raises(ValueError, match="conflicts"):
        locks.build_lock(inventory, tools={"ddk": {"version": "0.1.0.dev1", "commit": "2" * 40}})
    lock = locks.build_lock(inventory, tools={"ddk": {"version": "0.1.0.dev1"}, "engine": {"version": "9.1"}})
    assert lock["tools"]["ddk"] == distribution.distribution_identity()
    assert lock["tools"]["engine"] == {"version": "9.1"}
    assert not locks.verify_lock(inventory, lock, tools={"ddk": {"distributionSha256": "c" * 64}})
    assert "LOCK-INPUT-MISMATCH" in codes(inventory.report.build())
