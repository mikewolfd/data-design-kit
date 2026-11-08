"""Application-level quality requests without importing a native engine."""

from copy import deepcopy
from dataclasses import dataclass, fields
from decimal import Decimal
import math


class QualityOperationalError(RuntimeError):
    """Incomplete execution or exhausted resources, not a data-rule violation."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class QualityResources:
    """Separate engine, transport, input and scratch allocations.

    These are component limits, not a hard aggregate RAM reservation. The caller
    owns aggregate admission and the outer worker's deadline/cancellation.
    """

    engineMemoryBytes: int = 64 << 20
    scratchBytes: int = 0
    maxInputBytes: int | None = None
    maxDecodedInputBytes: int | None = None
    maxEncodedReadBytes: int = 8 << 20
    maxEncodedMessageBytes: int = 16 << 20
    maxDecodedBatchBytes: int = 8 << 20
    maxMetadataBytes: int = 2 << 20
    maxStderrBytes: int = 64 << 10
    readTimeoutSeconds: float = 60
    cleanupTimeoutSeconds: float = 1

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name in {"readTimeoutSeconds", "cleanupTimeoutSeconds"}:
                # The strict JSON reader preserves fractional numbers as
                # Decimal. Durations enter monotonic-clock arithmetic as float.
                if isinstance(value, Decimal) and value.is_finite():
                    value = float(value)
                    object.__setattr__(self, item.name, value)
                if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                    raise ValueError(f"{item.name} must be finite and positive")
            elif item.name in {"maxInputBytes", "maxDecodedInputBytes"} and value is None:
                continue
            elif type(value) is not int or value < (0 if item.name == "scratchBytes" else 1):
                raise ValueError(f"{item.name} has no valid finite byte allocation")

    def record(self):
        return {item.name: getattr(self, item.name) for item in fields(self)}

    @classmethod
    def from_request(cls, request):
        if "resources" in request:
            if "maxBytes" in request:
                raise ValueError("Use resources or legacy maxBytes, not both")
            value = request["resources"]
            if not isinstance(value, dict) or set(value) - {item.name for item in fields(cls)}:
                raise ValueError("Quality resources must contain only named supported allocations")
            return cls(**value), "separate-allocations"
        maximum = request.get("maxBytes", 64 << 20)
        if type(maximum) is not int or maximum <= 0:
            raise ValueError("Legacy maxBytes must be a positive integer")
        # Preserve each old limit separately, including total decoded native
        # input; none of these quantities is an aggregate process-memory limit.
        return cls(engineMemoryBytes=maximum, maxInputBytes=maximum, maxDecodedInputBytes=maximum,
                   maxEncodedReadBytes=min(maximum, 8 << 20), maxEncodedMessageBytes=min(maximum, 16 << 20),
                   maxDecodedBatchBytes=maximum), "legacy-maxBytes"


def dataset_rules(artifact):
    if artifact.kind != "dataset" or artifact.definition_status != "passed":
        raise ValueError("Quality requires a completely resolved dataset definition")
    original = artifact.document.value
    document = {key: deepcopy(value) for key, value in original.items()
                if key not in ("schema", "servers", "$schema")}
    document["schema"] = [deepcopy(artifact.effective)]
    sources = [{"path": str(artifact.document.path), "sha256": artifact.document.sha256,
                "selection": artifact.selection}]
    sources.extend(definition.record() for definition in artifact.definition_sources)
    return {"document": document, "sourceDefinitions": sources}


class QualityEvaluator:
    def __init__(self, tools):
        self.tools = tools

    def plan(self, artifact, *, required_check_ids=()):
        return self.tools.invoke("quality-plan", {**dataset_rules(artifact), "requiredCheckIds": list(required_check_ids)})

    def evaluate(self, artifact, target, *, required_check_ids=(), max_bytes=None, resources=None,
                 expected_rows=None, comparison=None):
        if resources is not None and max_bytes is not None:
            raise ValueError("Use resources or legacy max_bytes, not both")
        allocation = ({"resources": resources.record() if isinstance(resources, QualityResources) else resources}
                      if resources is not None else {"maxBytes": 64 << 20 if max_bytes is None else max_bytes})
        QualityResources.from_request(allocation)
        fixture = {} if expected_rows is None else {"expectedRows": expected_rows, "comparison": comparison}
        return self.tools.invoke("quality", {**dataset_rules(artifact), "target": target,
                                 "requiredCheckIds": list(required_check_ids), **allocation, **fixture})
