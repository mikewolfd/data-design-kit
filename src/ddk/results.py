"""Check records and the decision reducer shared by all DDK profiles."""

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from . import __version__

CORE_GROUPS = (
    "core.documents", "core.references", "core.graph",
    "core.calls", "core.datasets", "core.policies",
)
# Required only when the loaded scope declares a component or design (DDK-CHECK-002).
DESIGN_GROUPS = ("core.graph", "core.calls")
VERSION = __version__


def location(path, pointer=""):
    return {"path": str(path), "pointer": pointer}


def diagnostic(code, message, *, path=None, pointer="", related=(), severity="error"):
    record = {
        "code": code,
        "severity": severity,
        "message": message,
        "location": location(path if path is not None else "<command>", pointer),
    }
    if related:
        record["related"] = sorted(related, key=lambda x: (x["path"], x["pointer"]))
    return record


def diagnostic_key(record):
    source = record["location"]
    return (Path(source["path"]).as_posix(), source["pointer"], record["code"], record["message"])


def decision(report):
    if report.get("operationalErrors"):
        return "error"
    statuses = {
        item["status"] for item in report.get("checks", ())
        if item["required"] and item["applicable"]
    }
    if "failed" in statuses:
        return "failed"
    if statuses & {"unknown", "not_run"}:
        return "incomplete"
    return "passed"


def exit_code(report):
    return {"passed": 0, "failed": 1, "incomplete": 2, "error": 3}[decision(report)]


def stable_report(report):
    """Return the report content independent of explicitly marked observations."""
    stable = deepcopy(report)
    metadata = stable.get("metadata", {})
    metadata.pop("volatile", None)
    if not metadata:
        stable.pop("metadata", None)
    return stable


class ReportBuilder:
    def __init__(self, project, required_groups=(), scope=None):
        project = getattr(project, "value", project)
        self.project = project.get("id", "urn:ddk:unknown-project") if isinstance(project, Mapping) else str(project)
        self.required_groups = list(dict.fromkeys(required_groups or CORE_GROUPS))
        self.scope = scope if scope is not None else {
            "projects": [self.project],
            "artifacts": [],
            "followedReferences": [],
            "excludedConsumers": [],
        }
        self.checks = []
        self.operational_errors = []
        self.completed_profiles = set()
        self.available_capabilities = set()
        self.missing_capabilities = set()
        self.mapping_limits = set()
        self.limits = {}
        self.lock = {"verified": False}
        self.tools = {"ddk": {"version": VERSION}}
        self.metadata = {}
        self._identities = set()
        self._diagnostic_count = 0
        self._diagnostic_limit_hit = False

    def add(self, requirement, group, subject, status, *, required=None, applicable=True,
            evidence="declared", reason=None, diagnostics=(), evidence_records=(), id=None):
        if status not in {"passed", "failed", "unknown", "not_run"}:
            raise ValueError(f"Unrecognized check status {status!r}")
        if not applicable and status != "not_run":
            raise ValueError("A nonapplicable check must be not_run")
        if status in {"unknown", "not_run"} and not reason:
            raise ValueError(f"A {status} check must have a reason")
        if evidence == "executed" and status in {"passed", "failed"} and not evidence_records:
            raise ValueError("An executed pass or failure requires evidence records")
        identifier = id if id is not None else f"{group}/{requirement}/{subject}"
        if identifier in self._identities:
            raise ValueError(f"Duplicate check identity {identifier!r}")
        self._identities.add(identifier)
        diagnostics = sorted(diagnostics, key=diagnostic_key)
        limit = self.limits.get("maxDiagnostics")
        if limit is not None and self._diagnostic_count + len(diagnostics) > limit:
            diagnostics = diagnostics[:max(0, limit - self._diagnostic_count)]
            if not self._diagnostic_limit_hit:
                self._diagnostic_limit_hit = True
                self.error(diagnostic("EXEC-RESOURCE-LIMIT", "Captured diagnostics exceeded the configured limit."))
        self._diagnostic_count += len(diagnostics)
        item = {
            "id": identifier, "requirement": requirement, "group": group,
            "subject": str(subject), "status": status,
            "required": group in self.required_groups if required is None else required,
            "applicable": applicable, "evidence": evidence, "diagnostics": diagnostics,
        }
        if reason is not None:
            item["reason"] = reason
        if evidence_records:
            item["evidenceRecords"] = list(evidence_records)
        self.checks.append(item)
        return item

    def error(self, record):
        self.operational_errors.append(record)

    def build(self, **extra):
        report = {
            "specVersion": "0.1",
            "kind": "report",
            "id": f"urn:ddk:report:{self.project.encode().hex()}",
            "version": VERSION,
            "scope": self.scope,
            "coverage": {
                "requestedGroups": self.required_groups,
                "completedProfiles": sorted(self.completed_profiles),
                "availableCapabilities": sorted(self.available_capabilities),
                "missingCapabilities": sorted(self.missing_capabilities),
                "mappingLimits": sorted(self.mapping_limits),
            },
            "lock": self.lock,
            "tools": self.tools,
            "checks": sorted(self.checks, key=lambda item: (
                diagnostic_key(item["diagnostics"][0])[:3] if item["diagnostics"] else ("", "", ""),
                item["id"],
            )),
            "operationalErrors": sorted(self.operational_errors, key=diagnostic_key),
            "limits": self.limits,
        }
        if self.metadata:
            report["metadata"] = self.metadata
        report.update(extra)
        report["decision"] = decision(report)
        return deepcopy(report)
