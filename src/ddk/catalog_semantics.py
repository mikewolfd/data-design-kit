"""Explicit, data-free relationship reasoning supplied by an application owner."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from inspect import iscoroutinefunction
import os
from pathlib import Path
import stat
from typing import Literal, Protocol

from .catalog_access import CatalogError
from .documents import (
    Document, FORMAT_CHECKER, ResourceLimit, freeze_json, resolve_path, schema_registry, schema_validator,
)


@dataclass(frozen=True)
class ResolvedKey:
    """One ordered key component, isolated from admitted source definitions."""

    path: tuple[Mapping, ...]
    definition: Mapping
    shared_type: str | None
    virtual_scope: str | None = None


@dataclass(frozen=True)
class ResolvedRelationship:
    """An admitted declaration and its resolved keys; ``target=None`` is external.

    The declaration retains the external identifier. No data values, native
    versions, or target-existence observations are supplied to a profile.
    """

    declaration: Mapping
    source: tuple[ResolvedKey, ...]
    target: tuple[ResolvedKey, ...] | None


@dataclass(frozen=True)
class RelationshipAssessment:
    """Declaration support only, without match, cardinality, or quality evidence."""

    status: Literal["supported", "failed", "unknown"]
    reason: str


class RelationshipProfile(Protocol):
    """A concrete, explicitly composed owner of additional declaration semantics.

    ``identity`` uses DDK's existing tool identity. Supply either an explicit
    ``source`` file or a distribution/source-commit pin in that identity. Captured
    source identifies supplied bytes, not the implementation's dependency closure
    or an independently verified binding between those bytes and the callable.
    Implementations must return ``unknown`` for unsupported exact rule versions
    and types. They receive isolated, deeply immutable JSON values.
    """

    identity: Mapping[str, str]
    source: str | Path | None

    def assess(self, relationship: ResolvedRelationship) -> RelationshipAssessment: ...


@dataclass(frozen=True)
class SelectedProfile:
    identity: Mapping
    source: Document | None
    callback: Callable

    def assess(self, relationship):
        try:
            result = self.callback(relationship)
        except Exception as exc:
            raise CatalogError("CATALOG-PROFILE-ERROR", "The selected profile could not assess this declaration.",
                               status="unknown") from exc
        if (not isinstance(result, RelationshipAssessment) or not isinstance(result.status, str)
                or result.status not in {"supported", "failed", "unknown"}
                or not isinstance(result.reason, str) or not result.reason.strip()):
            raise CatalogError("CATALOG-PROFILE-RESULT", "The selected profile returned an invalid declaration assessment.",
                               status="unknown")
        return result


def admit_profile(profile, inventory):
    """Capture explicit profile provenance without discovering or importing code."""
    try:
        identity = dict(profile.identity)
        callback = profile.assess
        source = getattr(profile, "source", None)
    except Exception as exc:
        raise CatalogError("CATALOG-PROFILE-IDENTITY", "A selected profile needs an exact identity and synchronous assessor.",
                           status="unknown") from exc
    registry, schemas, _ = schema_registry()
    validator = schema_validator({"$ref": f"{schemas['common']['$id']}#/$defs/toolIdentity"}, resource_registry=registry)
    if (not validator.is_valid(identity) or not FORMAT_CHECKER.conforms(identity.get("id"), "uri")
            or not callable(callback) or iscoroutinefunction(callback)):
        raise CatalogError("CATALOG-PROFILE-IDENTITY", "A selected profile needs an absolute ID, version, and callable assessor.",
                           status="unknown")
    if source is None and not {"commit", "distributionSha256"} & identity.keys():
        raise CatalogError("CATALOG-PROFILE-IDENTITY", "A selected profile needs captured source or an exact source/distribution pin.",
                           status="unknown")
    document = None
    if source is not None:
        if not isinstance(source, (str, Path)):
            raise CatalogError("CATALOG-PROFILE-IDENTITY", "A profile source must be an explicit local file path.", status="unknown")
        path = resolve_path(inventory.path, str(source), inventory.permitted_roots)
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise OSError("A relationship profile source must be a regular file.")
            data = stream.read(inventory.limits["maxDocumentBytes"] + 1)
        if len(data) > inventory.limits["maxDocumentBytes"]:
            raise ResourceLimit("Relationship profile source exceeds the document byte limit.")
        document = Document(path, None, sha256(data).hexdigest(), data)
    return SelectedProfile(freeze_json(identity), document, callback)


def resolved_key(path, definition, virtual_scope=None):
    """Copy JSON recursively so even mutation bypasses cannot alter admission."""
    from .catalog_access import field_type

    return ResolvedKey(tuple(freeze_json(segment) for segment in path), freeze_json(definition),
                       field_type(definition), virtual_scope)


def resolved_relationship(declaration, keys):
    return ResolvedRelationship(freeze_json(declaration), tuple(keys["source"]),
                                tuple(keys["target"]) if "target" in keys else None)
