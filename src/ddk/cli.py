"""DDK command-line composition root; optional engines load only on invocation."""

import argparse
import os
import re
from pathlib import Path
import sys
import tempfile
import shutil

from .core import check_inventory, check_project, load_project
from .documents import DocumentError, ResourceLimit, json_dumps, read_json, resolve_path
from .impact import impact_projects
from .locks import lock_project, write_json_atomic
from .results import ReportBuilder, diagnostic, exit_code


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def _parser():
    parser = Parser(prog="ddk", description="Check data designs offline; explicitly select native integrations.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "lock", "impact", "build", "test", "catalog", "files", "stage", "quality", "managed"):
        command = commands.add_parser(name)
        if name != "impact":
            command.add_argument("project")
        else:
            command.add_argument("--base", required=True)
            command.add_argument("--candidate", required=True)
            command.add_argument("--non-weakening", action="store_true")
            command.add_argument("--base-catalog")
            command.add_argument("--candidate-catalog")
            command.add_argument("--require-complete-scope", action="store_true")
        command.add_argument("--format", choices=("json", "human"), default="human")
        command.add_argument("--progress", action="store_true", help="Send command progress to standard error")
        command.add_argument("--severity", choices=("error", "warning", "info"), action="append",
                             help="Display only these diagnostic severities in human output")
        command.add_argument("--require", action="append", default=[])
        command.add_argument("--permit-root", action="append", default=[])
        command.add_argument("--select", action="append")
        command.add_argument("--output")
        if name != "catalog":  # catalog writes catalog.lock.json every build but verifies no prior lock (DDK-CATALOG-007)
            command.add_argument("--lock")
            command.add_argument("--locked", action="store_true")
        if name in ("check", "lock"):
            command.add_argument("--adapter-manifest", action="append", default=[])
        if name in ("check", "build", "test", "files", "stage", "quality", "managed", "catalog"):
            command.add_argument("--tool-python")
            command.add_argument("--timeout", type=float, default=120)
            command.add_argument("--docspec")
            command.add_argument("--limits")
        if name == "catalog":
            command.add_argument("--docspec-limits")
        if name == "build":
            command.add_argument("--component", required=True)
            command.add_argument("--export", action="append", default=[])
        if name == "test":
            selection = command.add_mutually_exclusive_group(required=True)
            selection.add_argument("--fixture")
            selection.add_argument("--bindings")
            command.add_argument("--implementation", choices=("sql", "substrait", "both"), default="both")
            command.add_argument("--secret-parameter", metavar="NAME=ENV", action="append", default=[],
                                 help="Bind a designated bounded SQL parameter from the named environment variable")
        if name == "catalog":
            command.add_argument("--metadata")
            command.add_argument("--metadata-adapter")
            command.add_argument("--current-selection", nargs=2, metavar=("AUTHORITY", "PURPOSE"))
            command.add_argument("--disclosure-policy")
            command.add_argument("--export", action="append", default=[])
        if name in ("files", "stage", "quality"):
            command.add_argument("--dataset", required=True)
            command.add_argument("--request", required=True, help="Exact files, target, and optional tool configuration")
        if name == "managed":
            command.add_argument("--workspace", required=True)
            command.add_argument("--backend", default="local-iceberg")
            command.add_argument("--request", required=True)
            command.add_argument("--prior", help="Retained managed receipt or report for reconciliation")
    return parser


def _native(args, folder, secret_values=()):
    runtime = tools = None
    if args.docspec:
        if not args.limits:
            raise UsageError("--docspec requires explicit --limits")
        from .adapters.docspec import DocSpecAdapter
        runtime = DocSpecAdapter(args.docspec, read_json(args.limits).value, timeout=args.timeout,
                                 evidence_dir=folder / "docspec", secret_values=secret_values)
    if args.tool_python:
        from .adapters.native import NativeTools
        tools = NativeTools(args.tool_python, output=folder / "native", timeout=args.timeout, secret_values=secret_values)
    return runtime, tools


def _secret_parameters(args):
    bindings = {}
    for argument in getattr(args, "secret_parameter", ()):
        name, separator, variable = argument.partition("=")
        if not separator or not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable):
            raise UsageError("--secret-parameter requires NAME=ENV")
        if name in bindings:
            raise UsageError("Each secret parameter requires one environment binding")
        if not (value := os.environ.get(variable)):
            raise UsageError("The named secret environment variable is missing or empty")
        bindings[name] = value
    return bindings


def _execute(args, secret_parameters=None):
    shared = {"required_groups": args.require, "permitted_roots": args.permit_root}
    if args.command == "impact":
        return impact_projects(args.base, args.candidate, non_weakening=args.non_weakening, selection=args.select,
                               base_catalog=args.base_catalog, candidate_catalog=args.candidate_catalog,
                               require_complete_scope=args.require_complete_scope, **shared)
    if args.command == "lock":
        if not args.output:
            raise UsageError("lock requires --output")
        report, _ = lock_project(args.project, output=args.output, adapter_manifests=args.adapter_manifest, **shared)
        return report
    if args.command == "catalog":
        from .catalog import build_catalog
        if not args.output:
            raise UsageError("catalog requires --output")
        docspec_evidence = None
        if args.docspec:
            evidence_root = Path(args.output).resolve()
            evidence_root = evidence_root.with_name(evidence_root.name + ".evidence")
            evidence_root.mkdir(parents=True, exist_ok=True)
            docspec_evidence = Path(tempfile.mkdtemp(prefix="evidence-", dir=evidence_root))
        limits_arg = args.docspec_limits or args.limits
        report = build_catalog(
            args.project, metadata=args.metadata, metadata_adapter=args.metadata_adapter,
            exports=args.export, output=args.output, current_selection=args.current_selection,
            disclosure_policy=args.disclosure_policy, docspec=args.docspec,
            docspec_limits=read_json(limits_arg).value if limits_arg else None,
            docspec_evidence_dir=docspec_evidence, timeout=args.timeout, **shared,
        )
        if docspec_evidence is not None and docspec_evidence.exists() and not any(docspec_evidence.iterdir()):
            docspec_evidence.rmdir()
            if not any(docspec_evidence.parent.iterdir()):
                docspec_evidence.parent.rmdir()
        return report
    if args.command == "check" and not args.tool_python:
        return check_project(args.project, lock=args.lock, locked=args.locked, selection=args.select,
                             adapter_manifests=args.adapter_manifest, **shared)
    if args.output and args.command in ("test", "build", "files", "stage", "quality", "managed"):
        retained = Path(args.output).resolve()
        if args.command != "test":
            retained = retained.with_name(retained.name + ".evidence")
        retained.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="evidence-", dir=retained))
    else:
        folder = Path(tempfile.mkdtemp(prefix="ddk-command-"))
    runtime, tools = _native(args, folder, tuple((secret_parameters or {}).values()))
    if args.command == "check":
        from .quality import dataset_rules
        inventory = load_project(args.project, permitted_roots=args.permit_root)
        check_inventory(inventory, required_groups=args.require, handled_groups=("odcs.lint",), selection=args.select,
                        lock=args.lock, locked=args.locked, adapter_manifests=args.adapter_manifest)
        from .execution import _record
        if "odcs.lint" in inventory.report.required_groups:
            if inventory.report.build()["decision"] in ("failed", "error"):
                return inventory.report.build()
            datasets = [(alias, artifact) for alias, artifact in inventory.artifacts.items() if artifact.kind == "dataset"]
            if datasets:
                batch = tools.invoke(
                    "odcs-lint",
                    {"documents": [{"alias": alias, **dataset_rules(artifact)} for alias, artifact in datasets]},
                )
                if batch.get("status") in {"passed", "failed", "unknown", "not_run"} and isinstance(batch.get("results"), dict):
                    receipt = batch.get("receipt")
                    for alias, _ in datasets:
                        item = batch["results"][alias]
                        _record(
                            inventory.report, "odcs.lint", alias,
                            {**item, **({"receipt": receipt} if receipt else {})},
                            requirement="DDK-ADAPTER-003",
                        )
                else:
                    for alias, _ in datasets:
                        _record(inventory.report, "odcs.lint", alias, batch, requirement="DDK-ADAPTER-003")
        return inventory.report.build()
    if args.command == "build":
        from .execution import build_project
        if not args.output:
            raise UsageError("build requires --output")
        return build_project(args.project, args.component, runtime=runtime, output=args.output, formats=args.export or ("sql", "substrait"),
                             lock=args.lock, locked=args.locked, **shared)
    if args.command == "test":
        from .execution import run_fixture
        fixtures = [args.fixture] if args.fixture else []
        if args.bindings:
            binding = read_json(args.bindings)
            from .documents import validate_document
            if issues := validate_document(binding.value, "bindings"):
                raise DocumentError(issues[0].code, issues[0].message, issues[0].pointer)
            fixtures = [str(resolve_path(binding.path, path, (binding.path.parent, *map(Path, args.permit_root)))) for path in binding.value.get("fixtures", [])]
        if not fixtures:
            raise UsageError("test requires at least one explicitly selected fixture")
        if len(fixtures) > 1:
            raise UsageError("Run one explicitly selected fixture per command")
        formats = ("sql", "substrait") if args.implementation == "both" else (args.implementation,)
        # The command owns this temporary directory. Explicit --output retains
        # the complete run; successful default runs clean only their own files.
        target = args.output or str(folder / "fixture")
        report = run_fixture(args.project, fixtures[0], runtime=runtime, tools=tools, output=target,
                             formats=formats, lock=args.lock, locked=args.locked, bindings=args.bindings,
                             secret_parameters=secret_parameters, **shared)
        retained = args.output is not None or report["decision"] != "passed"
        report.setdefault("metadata", {})["dataLifetime"] = {
            "retained": retained, "path": str(folder),
            "scope": "Caller-owned local fixture inputs, outputs, and evidence",
            "sensitivity": "may contain designated parameter values in fixture data" if secret_parameters else "local fixture",
            "reason": "Explicit output or failure evidence" if retained else "Successful temporary fixture run cleaned",
        }
        if not retained:
            shutil.rmtree(folder)
        return report
    from .execution import _record
    group = {"files": "files.structure", "stage": "ingest.receipt", "quality": "data.odcs", "managed": "runtime.managed"}[args.command]
    groups = [group, *args.require]
    inventory = load_project(args.project, permitted_roots=args.permit_root)
    check_inventory(inventory, required_groups=groups, handled_groups=(group,), lock=args.lock, locked=args.locked)
    if inventory.report.build()["decision"] in ("failed", "error"):
        return inventory.report.build()
    request = read_json(args.request).value
    if args.command == "managed":
        if runtime is None:
            inventory.report.add("DDK-CLI-004", group, "managed", "not_run", reason="Explicit DocSpec executable is required")
            return inventory.report.build()
        prior = None
        if args.prior:
            prior = read_json(args.prior).value
            if isinstance(prior, dict) and prior.get("kind") == "report":
                prior = prior.get("metadata", {}).get("managed")
            if not isinstance(prior, dict) or "operationContext" not in prior:
                raise DocumentError("EXEC-RECONCILIATION-RECEIPT", "Expected a managed receipt with original operation scope")
        try:
            result = runtime.managed(args.workspace, request, prior=prior, backend=args.backend)
        except ValueError as exc:
            if prior is None:
                raise
            raise DocumentError("EXEC-RECONCILIATION-SCOPE", str(exc)) from exc
    elif tools is None:
        inventory.report.add("DDK-CLI-004", group, args.dataset, "not_run", reason="Explicit native tool environment is required")
        return inventory.report.build()
    elif args.command == "quality":
        from .quality import dataset_rules
        allowed = {"target", "requiredCheckIds", "parameters", "maxBytes"}
        if set(request) - allowed:
            raise DocumentError("QUALITY-REQUEST-FIELDS", "Runtime quality requests cannot replace maintained definitions")
        result = tools.invoke("quality", {**request, **dataset_rules(inventory.resolve(args.dataset))})
    else:
        result = tools.invoke(args.command, {**request, "dataset": inventory.resolve(args.dataset).effective})
    _record(inventory.report, group, args.command, result)
    inventory.report.metadata[args.command] = result
    report = inventory.report.build(**({"operations": [result["operation"]]} if result.get("operation") else {}))
    if args.output:
        if report["decision"] == "passed" or not Path(args.output).exists():
            write_json_atomic(args.output, report)
    return report


def _render_human(report, severities):
    print("DDK " + report["decision"])
    for item in report["checks"]:
        visible = [record for record in item["diagnostics"]
                   if not severities or record["severity"] in severities]
        for record in visible:
            print(f"  {record['code']}: {record['message']}")
        if (not item["diagnostics"] and item["status"] != "passed" and item["applicable"]
                and not severities):
            print(f"  {item['group']}: {item['status']} — {item.get('reason', item['subject'])}")
    for record in report["operationalErrors"]:
        if not severities or record["severity"] in severities:
            print(f"  {record['code']}: {record['message']}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    code = None
    severities = ()
    json_output = any(argv[i:i+2] == ["--format", "json"] for i in range(len(argv))) or "--format=json" in argv
    try:
        args = _parser().parse_args(argv)
        severities = args.severity or ()
        if args.progress:
            print(f"DDK {args.command} started", file=sys.stderr)
        report = _execute(args, _secret_parameters(args))
        if args.output and args.command in ("check", "impact") and (
            report["decision"] == "passed" or not Path(args.output).exists()
        ):
            write_json_atomic(args.output, report)
        code = exit_code(report)
    except (UsageError, DocumentError, OSError, ResourceLimit, ValueError) as exc:
        builder = ReportBuilder("urn:ddk:command")
        if isinstance(exc, UsageError):
            code = 64
        if isinstance(exc, DocumentError):
            builder.add("DDK-SYNTAX-002", "core.documents", "command", "failed",
                        diagnostics=[diagnostic(exc.code, str(exc), pointer=exc.pointer)])
        else:
            builder.error(diagnostic("CLI-USAGE" if isinstance(exc, UsageError) else "CLI-ERROR", str(exc)))
        report = builder.build()
        code = code if code is not None else exit_code(report)
    if json_output:
        print(json_dumps(report))
    else:
        _render_human(report, severities)
    return code
