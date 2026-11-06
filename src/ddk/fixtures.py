"""Independent expected-row comparison; it never computes business expectations."""

from collections import Counter
from decimal import Decimal
from math import isfinite


def _number(value):
    return type(value) in (int, float, Decimal)


def _key(value):
    if isinstance(value, dict):
        return ("object", tuple(sorted((k, _key(v)) for k, v in value.items())))
    if isinstance(value, list):
        return ("array", tuple(map(_key, value)))
    if _number(value):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("Fixture numbers must be finite")
        return ("number", number)
    return (type(value).__name__, value)


def _close(expected, actual, absolute, relative):
    if _number(expected) and _number(actual):
        a, b = Decimal(str(expected)), Decimal(str(actual))
        return a.is_finite() and b.is_finite() and abs(a-b) <= max(absolute, relative * abs(a))
    if isinstance(expected, dict) and isinstance(actual, dict):
        return expected.keys() == actual.keys() and all(
            _close(value, actual[key], absolute, relative) for key, value in expected.items())
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(
            _close(a, b, absolute, relative) for a, b in zip(expected, actual))
    return type(expected) is type(actual) and expected == actual


def compare_rows(expected, actual, comparison=None, *, max_rows=10_000):
    settings = {"rows": "unordered-multiset", "absoluteTolerance": 0,
                "relativeTolerance": 0, **(comparison or {})}
    absolute, relative = (Decimal(str(settings[key])) for key in ("absoluteTolerance", "relativeTolerance"))
    if not absolute.is_finite() or not relative.is_finite() or min(absolute, relative) < 0:
        raise ValueError("Fixture tolerances must be finite and nonnegative")
    if settings["rows"] not in ("unordered-multiset", "ordered"):
        raise ValueError("Unknown fixture comparison")
    if max(len(expected), len(actual)) > max_rows:
        return {"status": "unknown", "reason": "Fixture row budget exceeded"}
    if len(expected) != len(actual):
        return {"status": "failed", "reason": "Row counts differ",
                "expectedCount": len(expected), "actualCount": len(actual)}
    keys = settings.get("sortKeys")
    if keys:
        try:
            expected = sorted(expected, key=lambda row: tuple(_key(row[k]) for k in keys))
            actual = sorted(actual, key=lambda row: tuple(_key(row[k]) for k in keys))
        except (KeyError, TypeError) as exc:
            return {"status": "failed", "reason": "Sort keys are absent or incomparable: " + str(exc)}
    if settings["rows"] == "ordered":
        equal = all(_close(a, b, absolute, relative) for a, b in zip(expected, actual))
    elif absolute == relative == 0:
        equal = Counter(map(_key, expected)) == Counter(map(_key, actual))
    else:
        # A greedy matcher loses valid assignments when tolerance windows overlap.
        # Bound the quadratic work and use augmenting paths to preserve multiplicity.
        if len(expected) > 500:
            return {"status": "unknown", "reason": "Tolerant comparison exceeds its 500-row budget"}
        edges = [[j for j, row in enumerate(actual) if _close(e, row, absolute, relative)] for e in expected]
        matches = {}
        def assign(i, seen):
            for j in edges[i]:
                if j in seen:
                    continue
                seen.add(j)
                if j not in matches or assign(matches[j], seen):
                    matches[j] = i
                    return True
            return False
        equal = all(assign(i, set()) for i in range(len(expected)))
    return {"status": "passed" if equal else "failed", "reason": "Rows match" if equal else "Column names, values, order, or multiplicity differ",
            "expectedCount": len(expected), "actualCount": len(actual)}
