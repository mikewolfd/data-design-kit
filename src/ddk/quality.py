"""Application-level quality requests without importing a native engine."""

from copy import deepcopy


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

    def evaluate(self, artifact, target, *, required_check_ids=(), max_bytes=64 << 20,
                 expected_rows=None, comparison=None):
        fixture = {} if expected_rows is None else {"expectedRows": expected_rows, "comparison": comparison}
        return self.tools.invoke("quality", {**dataset_rules(artifact), "target": target,
                                 "requiredCheckIds": list(required_check_ids), "maxBytes": max_bytes, **fixture})
