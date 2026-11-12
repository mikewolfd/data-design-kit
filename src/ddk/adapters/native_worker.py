"""One explicitly requested native-tool operation in a separate environment."""

from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
import sys
import traceback

from ddk.documents import json_dumps, read_json
from ddk.arrow_mapping import MappingUnavailable
from ddk.quality import QualityOperationalError
from .docspec_stream import NativeStreamError


def main():
    action, path, directory, *allocation = sys.argv[1:]
    folder = Path(directory)
    try:
        request = deepcopy(read_json(path).value)
        with redirect_stdout(sys.stderr):
            if action in ("quality", "quality-plan", "odcs-lint", "odcs-versions"):
                from . import native_quality
                if action == "odcs-lint":
                    result = native_quality.lint(request, folder)
                elif action == "odcs-versions":
                    result = native_quality.versions(request, folder)
                else:
                    if len(allocation) > 1 or allocation and action != "quality":
                        raise ValueError("Unexpected native worker allocation arguments")
                    result = native_quality.evaluate(request, folder, plan_only=action == "quality-plan",
                                                     scratch=allocation[0] if allocation else None)
            elif action in ("files", "stage", "fixture-files"):
                from . import native_intake
                result = getattr(native_intake, action.replace("-", "_"))(request, folder)
            else:
                raise ValueError("Unknown native action: " + action)
    except (QualityOperationalError, NativeStreamError) as exc:
        result = {"status": "unknown", "reason": str(exc),
                  "operationalError": {"type": type(exc).__name__, "code": exc.code, "message": str(exc)}}
    except MappingUnavailable as exc:
        result = {"status": "unknown", "reason": str(exc)}
    except ValueError as exc:
        result = {"status": "failed", "reason": str(exc)}
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        result = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    print(json_dumps(result))
    return 3 if result.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
