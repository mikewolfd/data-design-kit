"""One bounded local viewer request through the maintained catalog SQL API.

The operator supplies configuration on disk; the browser supplies only SQL,
version bindings and a row allowance. DocSpec remains the execution owner.
"""

import argparse
from pathlib import Path
import sys

from .adapters.docspec import DocSpecAdapter
from .adapters.native import file_sha256, write_json
from .catalog_query import execute_catalog_sql
from .documents import ResourceLimit, json_dumps, parse_json


def run(config, request):
    if not isinstance(request, dict) or set(request) != {"bindings", "sql", "limit"}:
        raise ValueError("Supply explicit version bindings, SQL and a row limit")
    if type(request["limit"]) is not int or not 1 <= request["limit"] <= 100:
        raise ValueError("The row limit must be between 1 and 100")
    binary = Path(config["docspecBinary"]).resolve(strict=True)
    if file_sha256(binary) != config["docspecSha256"]:
        raise ValueError("The selected DocSpec executable changed")
    folder = Path(config["attemptDirectory"]).resolve(strict=True)
    adapter = DocSpecAdapter(binary, config["docspecLimits"], timeout=float(config["timeoutSeconds"]),
                             evidence_dir=folder / "native", capture_bytes=4 << 20,
                             metadata_bytes=4 << 20, new_process_group=False)
    answer = execute_catalog_sql(config["directory"], expected_lock_sha256=config["lockSha256"],
        bindings=request["bindings"], sql=request["sql"], adapter=adapter, scratch=folder / "scratch",
        permitted_roots=config["permittedRoots"], max_rows=request["limit"],
        max_input_bytes=config["maxInputBytes"], max_members=config["maxMembers"])
    retained = write_json(folder / "answer.json", answer)
    receipt = answer["receipt"]
    result = {"status": "ok" if answer["status"] == "succeeded" else
                        "unknown" if answer["status"] in {"unknown", "error"} else "refused",
              "bindings": answer["bindings"], "sqlSha256": answer["sqlSha256"],
              "record": {"uri": Path(retained["path"]).as_uri(), "sha256": retained["sha256"]}}
    if result["status"] == "ok":
        # Carry rows as raw JSON text until the viewer's lossless decoder. Never
        # pass data numbers through JavaScript's binary floating point parser.
        result.update(rowsJson=json_dumps(answer["rows"]), columns=answer["columns"])
    else:
        result["reason"] = answer.get("reason") or receipt.get("error", {}).get("message") or "No complete answer was established"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        config_bytes = Path(args.config).read_bytes()
        if len(config_bytes) > 64 << 10:
            raise ValueError("Operator configuration exceeds the byte allowance")
        request_bytes = sys.stdin.buffer.read((64 << 10) + 1)
        if len(request_bytes) > 64 << 10:
            raise ValueError("Query request exceeds the byte allowance")
        result = run(parse_json(config_bytes), parse_json(request_bytes))
    except (OSError, ValueError, KeyError, TypeError, ResourceLimit) as exc:
        result = {"status": "refused", "reason": str(exc)}
    sys.stdout.write(json_dumps(result) + "\n")


if __name__ == "__main__":
    main()
