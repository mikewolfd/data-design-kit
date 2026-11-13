"""Interpret DocSpec Parquet-directory identities without opening data files."""

from hashlib import sha256
import json
from pathlib import Path
import re


DIRECTORY_SCHEME = "urn:ddk:version:docspec-parquet-directory-sha256"


def parquet_directory_members(observation):
    """Validate a native directory inventory and return catalog member records.

    DocSpec hashes compact UTF-8 JSON tuples of relative path, SHA-256 and byte
    count, in sorted path order. This digest identifies the complete inventory;
    it is not the byte digest of a single Parquet file. No payload is opened.
    """
    root = Path(observation["path"])
    files = observation["files"]
    if not root.is_absolute() or not isinstance(files, list) or not files:
        raise ValueError("A Parquet directory requires an absolute path and nonempty member inventory")
    members, canonical, seen = [], [], set()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("A Parquet directory member requires an absolute path")
        path = Path(item["path"])
        if not path.is_absolute() or ".." in path.parts or path == root:
            raise ValueError("A Parquet directory member must be inside its input directory")
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError("A Parquet directory member must be inside its input directory") from exc
        if path.parent != root:
            raise ValueError("Only flat Parquet directory inventories are supported; nested members are not admitted")
        digest, size = item.get("sha256"), item.get("bytes")
        if (relative in seen or path.suffix != ".parquet"
                or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or type(size) is not int or size <= 0 or item.get("key") is not None):
            raise ValueError("A Parquet directory has an invalid or duplicate member")
        seen.add(relative)
        members.append({"path": relative, "sha256": digest, "byteSize": size})
        canonical.append([relative, digest, size])
    if canonical != sorted(canonical, key=lambda item: item[0]):
        raise ValueError("Parquet directory members must preserve native sorted path order")
    identity = parquet_directory_identity(root, files)
    if observation.get("sha256") != identity["sha256"]:
        raise ValueError("Parquet directory member inventory disagrees with its native SHA-256")
    if type(observation.get("bytes")) is not int or observation["bytes"] != identity["bytes"]:
        raise ValueError("Parquet directory member byte counts disagree with the native total")
    return members


def parquet_directory_identity(path, files):
    """Return the native inventory digest and size for already observed files."""
    root = Path(path)
    canonical = [[Path(item["path"]).relative_to(root).as_posix(), item["sha256"], item["bytes"]]
                 for item in files]
    return {
        "sha256": sha256(json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
        "bytes": sum(item[2] for item in canonical),
    }
