"""Reproduce independently authored synthetic DDK-shaped documents. No native execution."""
from pathlib import Path
from hashlib import sha256
import json

ROOT = Path(__file__).resolve().parent
TOOL = {"id": "urn:ddk-viewer:fixture-author", "version": "1.0.0"}
STAMP = "2026-11-06T17:00:00Z"

def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()

def digest(value):
    return sha256(value).hexdigest()

def write(root, name, value):
    data = value if isinstance(value, bytes) else encoded(value)
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return digest(data)

def field(name, kind, description, **extra):
    return {"name": name, "logicalType": kind, "description": description, **extra}

def ref(value):
    return {"scheme": "urn:ddk-viewer:synthetic-version", "authority": "urn:ddk-viewer:fixture-author", "value": value}

def build(slug, title, description, primary, secondary, definitions, rows, lookup, foreign, parameter, sql):
    root = ROOT / slug
    prefix = f"urn:ddk-viewer:fixture:{slug}"
    rec = {"uri": prefix + ":evidence"}
    definition_hash = write(root, "definitions.json", definitions)
    evidence = {
        "fixture": True,
        "scope": "Independently authored synthetic rows and illustrative owner records; no native DocSpec operation or candidate acceptance.",
        "observedAt": STAMP,
        "captures": ["batch-1 retained", "batch-2 retained", "batch-empty contains zero records", "batch-failed has no retained content"],
        "checks": {"sample_shape": "passed only for these authored rows", "native_candidate": "unknown", "remote_existence": "not_run"},
    }
    evidence_hash = write(root, "evidence.json", evidence)
    sql_path = f"recipes/{primary}-minimum.sql"
    sql_hash = write(root, sql_path, sql.encode())
    policy_hash = write(root, "disclosure.json", {"fixture": True, "audience": "public", "description": "All names and values are synthetic. The explicitly withheld version reference has no data route."})
    data_files = []
    versions, representations, sources, releases = [], [], [], []
    for index, text in enumerate(rows, 1):
        version_id = prefix + f":{primary}:v{index}"
        representation_id = version_id + ":json"
        data_path = f"data/{primary}-v{index}.json"
        data_hash = write(root, data_path, text.encode())
        data_files.append({"path": data_path, "sha256": data_hash, "role": "data", "identity": representation_id})
        source_id = prefix + f":capture:{index}"
        sources.append({"id": source_id, "reference": ref(f"capture-occurrence-{index}"), "content": ref({"sha256": data_hash}), "outcome": "retained", "scope": "This synthetic capture occurrence only", "record": rec})
        versions.append({"id": version_id, "dataset": primary, "reference": ref({"batch": str(index), "sha256": data_hash}), "retention": "present", "scope": "One immutable synthetic JSON file", "record": rec, "sources": [source_id], "coverage": [{"scope": "Authored sample rows only", "unit": "rows", "status": "complete", "observed": len(json.loads(text)), "expected": len(json.loads(text)), "record": rec}]})
        representations.append({"id": representation_id, "version": version_id, "kind": "file", "availability": "available", "location": prefix + f":data:{primary}:v{index}", "mediaType": "application/json", "record": rec})
    for index, text in enumerate(lookup if isinstance(lookup, list) else [lookup], 1):
        lookup_path = f"data/{secondary}-v{index}.json"
        lookup_hash = write(root, lookup_path, text.encode())
        lookup_version = prefix + f":{secondary}:v{index}"
        lookup_rep = lookup_version + ":json"
        data_files.append({"path": lookup_path, "sha256": lookup_hash, "role": "data", "identity": lookup_rep})
        versions.append({"id": lookup_version, "dataset": secondary, "reference": ref({"sha256": lookup_hash}), "retention": "present", "scope": "One synthetic lookup table", "record": rec, "sources": [sources[index - 1]["id"]]})
        representations.append({"id": lookup_rep, "version": lookup_version, "kind": "file", "availability": "available", "location": prefix + f":data:{secondary}:v{index}", "mediaType": "application/json", "record": rec})
    versions.append({"id": prefix + f":{primary}:withheld", "dataset": primary, "referenceDisclosure": "withheld", "retention": "missing", "scope": "Illustrative withheld historical reference; payload unavailable", "record": rec, "sources": []})
    representations.append({"id": prefix + f":{primary}:withheld:json", "version": versions[-1]["id"], "kind": "file", "availability": "unavailable", "record": rec})
    versions.append({"id": prefix + f":{primary}:unresolved", "dataset": primary, "reference": ref("unresolved-native-reference"), "retention": "unknown", "scope": "Illustrative unresolved retention", "record": rec, "sources": []})
    representations.append({"id": prefix + f":{primary}:unresolved:service", "version": versions[-1]["id"], "kind": "service", "availability": "unknown", "record": rec})
    for state in ["empty", "failed"]:
        sources.append({"id": prefix + ":capture:" + state, "reference": ref("capture-occurrence-" + state), "outcome": state, "scope": "Explicit synthetic capture occurrence; no retained payload", "record": rec})
    for index in [1, 2]:
        lookup_index = index if isinstance(lookup, list) else 1
        releases.append({"id": prefix + f":release:{index}", "reference": ref(f"release-{index}"), "members": [prefix + f":{primary}:v{index}", prefix + f":{secondary}:v{lookup_index}"], "membership": "complete", "record": rec})
    relation_id = prefix + ":relationship:lookup"
    external_id = prefix + ":relationship:external"
    dataset_rows = []
    for alias in [primary, secondary]:
        dataset_rows.append({"alias": alias, "id": prefix + ":dataset:" + alias, "title": definitions[alias]["businessName"], "rowMeaning": definitions[alias]["description"], "role": "source_record", "definition": {"contractId": prefix + ":definition", "version": "1.0.0", "object": alias, "source": {"uri": prefix + ":definitions", "sha256": definition_hash}}})
    report = {
        "specVersion": "0.1", "kind": "report", "id": prefix + ":report", "version": "1.0.0", "decision": "incomplete",
        "scope": {"projects": [prefix + ":project"], "artifacts": [primary, secondary], "followedReferences": [], "excludedConsumers": []},
        "coverage": {"requestedGroups": ["catalog.qualification"], "completedProfiles": [], "availableCapabilities": ["synthetic.fixture-reader"], "missingCapabilities": ["runtime-native-candidate-acceptance"], "mappingLimits": ["These are hand-authored format fixtures, not the result of DDK assembly or native execution."]},
        "lock": {"verified": False, "path": "catalog.lock.json"}, "tools": {"fixture-author": {"version": "1.0.0"}},
        "checks": [
            {"id": "declaration", "requirement": "DDK-CATALOG-001", "group": "catalog.qualification", "subject": prefix + ":project", "status": "passed", "required": True, "applicable": True, "evidence": "declared", "reason": "The fixture declares its synthetic inventory; this says nothing about native candidate acceptance.", "diagnostics": []},
            {"id": "native-candidate", "requirement": "DDK-CATALOG-001", "group": "catalog.qualification", "subject": prefix + ":project", "status": "unknown", "required": True, "applicable": True, "evidence": "declared", "reason": "No native candidate or accepted qualification record exists for this fixture.", "diagnostics": []},
            {"id": "remote-existence", "requirement": "DDK-CATALOG-001", "group": "catalog.qualification", "subject": external_id, "status": "not_run", "required": False, "applicable": True, "evidence": "declared", "reason": "The fixture never contacts the external identifier.", "diagnostics": []},
        ], "operationalErrors": [], "limits": {"fixtureOnly": True},
    }
    report_hash = write(root, "catalog.report.json", report)
    catalog = {
        "specVersion": "0.1", "kind": "catalog", "id": prefix + ":catalog", "version": "1.0.0", "project": {"id": prefix + ":project", "version": "1.0.0"}, "audience": "public", "disclosurePolicy": {"uri": prefix + ":disclosure", "sha256": policy_hash},
        "sourceInventory": [{"uri": prefix + ":definitions", "sha256": definition_hash, "role": "definition"}, {"uri": prefix + ":evidence", "sha256": evidence_hash, "role": "metadata"}, {"uri": prefix + ":recipe", "sha256": sql_hash, "role": "recipe"}], "adapters": [TOOL],
        "products": [{"alias": "product", "id": prefix + ":product", "version": "1.0.0", "definition": {"uri": prefix + ":definitions", "sha256": definition_hash}, "ports": [{"product": "product", "direction": "output", "port": alias, "version": "1.0.0", "dataset": alias} for alias in [primary, secondary]]}],
        "datasets": dataset_rows,
        "identities": [{"dataset": primary, "kind": "key", "scope": "dataset_version", "meaning": "The same ID can appear in two versions; bind the exact version before comparing rows.", "fields": [{"path": [{"field": "id"}], "virtual": False, "physicalType": "int64"}]}, {"dataset": secondary, "kind": "key", "scope": "dataset_version", "meaning": "Lookup key within the exact synthetic version", "fields": [{"path": [{"field": "code"}], "virtual": False, "physicalType": "string"}]}],
        "relationships": [{"id": relation_id, "source": {"dataset": primary, "paths": [[{"field": foreign}]]}, "target": {"dataset": secondary, "paths": [[{"field": "code"}]]}, "match": "equal", "cardinality": "many_to_one", "scope": "same_release", "resolution": "unresolved_allowed", "meaning": "Declared lookup meaning; this declaration is not evidence of observed matches.", "nulls": "skip"}, {"id": external_id, "source": {"dataset": secondary, "paths": [[{"field": "code"}]]}, "target": {"external": "https://example.invalid/fixture-registry"}, "match": "equal", "cardinality": "unknown", "scope": "external", "resolution": "external", "meaning": "Explanatory external reference; existence has not been checked.", "nulls": "unknown"}],
        "recipes": [{"id": prefix + ":recipe:minimum", "title": f"Filter {primary} by exact minimum", "notes": ["Runs only the registered fixture evaluator after exact input and SQL digest checks.", "The lookup relationship is context; the query does not read the lookup dataset."], "sql": sql_path, "dialect": "fixture-sql", "inputs": {"records": primary}, "relationships": [], "contextualRelationships": [relation_id], "parameters": {"type": "object", "properties": {parameter: {"type": "number"}}, "required": [parameter], "additionalProperties": False}, "parameterOrder": [parameter], "resultGrain": "One source row meeting the exact minimum; values and source identities are preserved"}],
        "versions": versions, "sources": sources, "representations": representations, "releases": releases,
        "selections": [{"authority": prefix + ":publisher", "purpose": "fixture-demo", "release": releases[1]["id"], "observedAt": STAMP, "record": rec}], "currentSelection": {"authority": prefix + ":publisher", "purpose": "fixture-demo"},
        "runs": [{"id": prefix + ":run:illustrative", "reference": ref("illustrative-record-not-a-native-run"), "inputs": [sources[0]["id"]], "inputCoverage": {"status": "partial", "scope": "Illustrative fixture capture only; not an execution dependency census"}, "outputs": [prefix + f":{primary}:v1"], "outcome": "succeeded", "observedAt": STAMP, "record": rec}, {"id": prefix + ":run:unresolved", "reference": ref("illustrative-unknown-run"), "inputs": [], "inputCoverage": {"status": "unknown", "scope": "No native run evidence"}, "outputs": [], "outcome": "unknown", "observedAt": STAMP, "record": rec}],
        "checks": [{"subject": prefix + f":{primary}:v1", "rule": {"id": prefix + ":rule:sample", "version": "1.0.0"}, "evaluator": TOOL, "scope": "Authored synthetic sample evidence only", "status": "passed", "record": rec}, {"subject": prefix + f":{primary}:v2", "rule": {"id": prefix + ":rule:native-candidate", "version": "1.0.0"}, "evaluator": TOOL, "scope": "Native candidate acceptance", "status": "unknown", "reason": "No native accepted candidate record exists."}, {"subject": external_id, "rule": {"id": prefix + ":rule:remote", "version": "1.0.0"}, "evaluator": TOOL, "scope": "External existence", "status": "not_run", "reason": "No external service was contacted."}],
        "files": [{"path": "catalog.report.json", "sha256": report_hash, "role": "report"}, {"path": sql_path, "sha256": sql_hash, "role": "recipe"}], "productions": [],
        "extensions": {"urn:ddk:catalog:assembly": {"datasetDefinitions": definitions, "projectExtensions": []}, "urn:ddk-viewer:fixture": {"title": title, "description": description, "synthetic": True, "nativeExecution": "not_run", "conformance": "Document shapes checked separately; no DDK producer or native conformance claim"}},
    }
    catalog_hash = write(root, "catalog.ddk.json", catalog)
    lock = {"specVersion": "0.1", "kind": "lock", "id": prefix + ":lock", "version": "1.0.0", "project": prefix + ":project", "files": [{"path": "definitions.json", "sha256": definition_hash, "role": "definition"}, {"path": "evidence.json", "sha256": evidence_hash, "role": "metadata"}, {"path": "disclosure.json", "sha256": policy_hash, "role": "disclosure-policy"}, *data_files, {"path": sql_path, "sha256": sql_hash, "role": "recipe"}], "tools": {"fixture-author": {"version": "1.0.0"}}, "standards": {"ddk": "0.1", "fixture": "independently-authored"}, "catalogOptions": {"audience": "public", "exports": []}, "extensions": {"urn:ddk:catalog:output-set": [{"path": "catalog.ddk.json", "sha256": catalog_hash, "role": "catalog"}, {"path": "catalog.report.json", "sha256": report_hash, "role": "report"}, {"path": sql_path, "sha256": sql_hash, "role": "recipe"}]}}
    lock_hash = write(root, "catalog.lock.json", lock)
    return {"id": slug, "lockSha256": lock_hash}

def main():
    watershed = {
        "observations": {"name": "observations", "businessName": "Watershed observations", "description": "One synthetic instrument observation with nested readings", "properties": [field("id", "integer", "Exact observation ID above JavaScript's safe integer range", physicalType="int64"), field("station_code", "string", "Station code, scoped through the release"), field("concentration", "number", "Exact decimal concentration in milligrams per litre", physicalType="decimal128(28,18)"), field("readings", "array", "Null, empty and populated lists differ", items=field("reading", "object", "Nested measurement", properties=[field("depth", "number", "Exact depth"), field("flags", "array", "Repeated flag values", items=field("flag", "string", "Flag"))])), field("note", "string", "May be missing, null or empty"), field("$number", "string", "Literal source key preserved by escaped transport"), field("metadata", "object", "Literal tag-shaped source object", properties=[field("$number", "string", "Source text, not a number transport tag")]) ]},
        "stations": {"name": "stations", "businessName": "Synthetic station register", "description": "One synthetic station per station code", "properties": [field("code", "string", "Station code"), field("name", "string", "Station label")]},
    }
    grants = {
        "awards": {"name": "awards", "businessName": "Public-service grants", "description": "One synthetic grant award with repeated payment records", "properties": [field("id", "integer", "Exact grant identifier", physicalType="uint64"), field("program_code", "string", "Program code scoped through the release"), field("amount", "number", "Exact awarded currency amount", physicalType="decimal128(30,8)"), field("payments", "array", "Repeated payments; null differs from empty", items=field("payment", "object", "Payment record", properties=[field("amount", "number", "Exact payment amount"), field("tags", "array", "Nested tags", items=field("tag", "string", "Tag"))])), field("note", "string", "May be absent, null or empty")]},
        "programs": {"name": "programs", "businessName": "Synthetic grant programs", "description": "One synthetic grant program per code", "properties": [field("code", "string", "Program key"), field("name", "string", "Program name")]},
    }
    pins = [build("watershed", "Watershed observatory", "Synthetic watershed observations and station register. Exact decimals, nested readings and version-scoped keys.", "observations", "stations", watershed,
        ['[{"id":9007199254740993,"station_code":"ALDER","concentration":0.100000000000000001,"readings":[{"depth":1.2500,"flags":["calibrated","calibrated"]}],"note":null},{"id":9007199254740995,"station_code":"BIRCH","concentration":2.750000000000000001,"readings":[],"note":""},{"id":9007199254740997,"station_code":null,"concentration":0.000000000000000019,"readings":null}]\n',
         '[{"id":9007199254740993,"station_code":"ALDER","concentration":0.200000000000000001,"readings":[{"depth":0.000000000000000001,"flags":[]}]},{"id":9007199254740999,"station_code":"BIRCH","concentration":3.000000000000000001,"readings":[],"note":"resampled"},{"id":9007199254741001,"station_code":"ALDER","concentration":1.100000000000000001,"readings":null,"note":null},{"id":9007199254741003,"station_code":"BIRCH","concentration":1.200000000000000001,"readings":[],"note":""},{"id":9007199254741005,"station_code":null,"concentration":0.000000000000000021,"readings":[{"depth":2.5000,"flags":["repeat","repeat"]}]},{"id":9007199254741007,"station_code":"ALDER","concentration":1.300000000000000001,"readings":[]},{"id":9007199254741009,"station_code":"BIRCH","concentration":1.400000000000000001,"readings":null},{"id":9007199254741011,"station_code":"ALDER","concentration":1.500000000000000001,"readings":[{"depth":1.0000,"flags":[]},{"depth":1.0000,"flags":[]}]},{"id":9007199254741013,"station_code":"BIRCH","concentration":1.600000000000000001,"readings":[],"metadata":{"$number":"source literal"}},{"id":9007199254741015,"station_code":"ALDER","concentration":1.700000000000000001,"readings":[]},{"id":9007199254741017,"station_code":"BIRCH","concentration":1.800000000000000001,"readings":null},{"id":9007199254741019,"station_code":"ALDER","concentration":1.900000000000000001,"readings":[]},{"id":9007199254741021,"station_code":"BIRCH","concentration":2.000000000000000001,"readings":[],"$number":"source literal"},{"id":9007199254741023,"station_code":"ALDER","concentration":2.100000000000000001,"readings":[{"depth":3.000000000000000001,"flags":["end"]}]}]\n'],
        ['[{"code":"ALDER","name":"Alder Creek (historical register)"},{"code":"BIRCH","name":"Birch Brook (historical register)"}]\n', '[{"code":"ALDER","name":"Alder Creek (current register)"},{"code":"BIRCH","name":"Birch Brook (current register)"}]\n'], "station_code", "minimum_concentration", "SELECT * FROM records WHERE concentration >= $minimum_concentration;\n"),
        build("grants", "Public-service grants", "Synthetic grants and program register. Large identifiers, exact currency and repeated payment records.", "awards", "programs", grants,
        ['[{"id":18446744073709551615,"program_code":"NEIGHBOR","amount":12345678901234567890.12345678,"payments":[{"amount":0.10000001,"tags":["scheduled","scheduled"]}],"note":null},{"id":18446744073709551614,"program_code":"LIBRARY","amount":2500.00000001,"payments":[],"note":""},{"id":18446744073709551613,"program_code":null,"amount":0.00000001,"payments":null}]\n',
         '[{"id":18446744073709551615,"program_code":"NEIGHBOR","amount":12345678901234567890.12345679,"payments":[{"amount":100.01000000,"tags":[]}]},{"id":18446744073709551612,"program_code":"LIBRARY","amount":3500.00000001,"payments":[],"note":"amended"}]\n'],
        '[{"code":"NEIGHBOR","name":"Neighborhood support"},{"code":"LIBRARY","name":"Library access"}]\n', "program_code", "minimum_amount", "SELECT * FROM records WHERE amount >= $minimum_amount;\n")]
    target = ROOT.parent / "src/server/fixture-pins.ts"
    target.write_text("// Exact immutable fixture lock pins. Regenerate with fixtures/build_fixtures.py.\nexport const fixturePins = " + json.dumps(pins, indent=2) + " as const;\n")

if __name__ == "__main__":
    main()
