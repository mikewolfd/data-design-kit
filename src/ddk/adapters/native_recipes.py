"""Offline recipe SQL binding against declared ODCS inputs, run in an explicitly selected tool environment.

sqlglot parses the SQL, qualifies every column against a schema built from the
inputs' effective ODCS definitions, and annotates types. DDK adds the checks
sqlglot leaves open: table references outside the declared inputs (per scope),
field and index access the declarations do not support, parameter binding,
type-family conflicts between values that must agree, and the declared result
dataset's shape. For `datafusion` recipes, a pinned table types the DataFusion
and JSON functions the PostgreSQL grammar leaves untyped and checks the argument
types DataFusion accepts. Other constructs the parser cannot type stay unknown.
The recipe is never executed and no data is read.
"""

from datetime import date, datetime, time
from typing import NamedTuple

from sqlglot import exp, parse
from sqlglot import __version__ as SQLGLOT_VERSION
from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import OptimizeError, SqlglotError
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope
from sqlglot.schema import MappingSchema
from sqlglot.tokens import TokenType

# DataFusion follows PostgreSQL syntax and coercion most closely; sqlglot has no DataFusion dialect.
DIALECTS = {"datafusion": "postgres", "postgres": "postgres", "duckdb": "duckdb"}
LOGICAL = {"string": "TEXT", "integer": "BIGINT", "number": "DOUBLE", "boolean": "BOOLEAN",
           "date": "DATE", "timestamp": "TIMESTAMP", "time": "TIME"}
PARAMETERS = {"string": "TEXT", "integer": "BIGINT", "number": "DOUBLE", "boolean": "BOOLEAN"}
POSITIONAL = "__ddk_positional_"
T = exp.DataType.Type
FAMILIES = {"integer": "number", "date": "temporal", "time": "temporal", "timestamp": "temporal"}
NOT_ARITHMETIC = {"string", "boolean", "object", "array"}
JSON_NODES = tuple(getattr(exp, name) for name in ("JSONExtract", "JSONExtractScalar", "JSONBExtract",
                                                    "JSONBExtractScalar", "JSONExtractArray") if hasattr(exp, name))
COLUMN_ERRORS = ("Unknown column", "could not be resolved", "Ambiguous column", "Cannot automatically join",
                 "Unknown output column")


class Signature(NamedTuple):
    arguments: tuple  # accepted logical types for each leading argument
    minimum: int
    more: frozenset | None  # accepted types for any further arguments; None admits none
    returns: str | None  # sqlglot type name; None returns an array of the first typed argument


# DataFusion 53.1 with datafusion-functions-json 0.53.1, as DocSpec registers them. "json" is the value json_get
# returns; DataFusion's union type has no ODCS logical type, so a json result stays untyped in the output.
SIGNATURE_PROFILE = "datafusion-53.1+datafusion-functions-json-0.53.1"
TEXT, ARRAY = frozenset({"string"}), frozenset({"array"})
ANY = frozenset({"string", "integer", "number", "boolean", "date", "time", "timestamp", "object", "array", "json"})
JSON_DOCUMENT, JSON_PATH = frozenset({"string", "json"}), frozenset({"string", "integer"})


def _json(returns):
    return Signature((JSON_DOCUMENT,), 1, JSON_PATH, returns)


FUNCTIONS = {
    "regexp_match": Signature((TEXT, TEXT, TEXT), 2, None, "ARRAY<TEXT>"),
    "make_array": Signature((), 0, ANY, None),
    "json_get": _json("JSON"), "json_get_str": _json("TEXT"), "json_get_json": _json("TEXT"),
    "json_as_text": _json("TEXT"), "json_get_int": _json("BIGINT"), "json_get_float": _json("DOUBLE"),
    "json_get_bool": _json("BOOLEAN"), "json_length": _json("BIGINT"), "json_contains": _json("BOOLEAN"),
    "json_get_array": _json("ARRAY<TEXT>"), "json_object_keys": _json("ARRAY<TEXT>"),
}
# Functions the parser already types under their DataFusion names; DataFusion constrains their arguments.
ARGUMENTS = {
    exp.RegexpLike: ("regexp_like", {"this": TEXT, "expression": TEXT, "flag": TEXT}),
    exp.RegexpReplace: ("regexp_replace", {"this": TEXT, "expression": TEXT, "replacement": TEXT, "modifiers": TEXT}),
    exp.StrToDate: ("to_date", {"this": frozenset({"string", "integer", "number", "date", "timestamp"}), "format": TEXT}),
    exp.ArraySize: ("array_length", {"this": ARRAY, "expression": frozenset({"integer"})}),
    exp.Explode: ("unnest", {"this": frozenset({"array", "object"})}),
    exp.ArrayContains: ("array_has", {"this": ARRAY}),
}


class _DataFusionSchema(MappingSchema):
    """Return types for FUNCTIONS; sqlglot annotates a call's arguments before asking for its type."""

    def get_udf_type(self, udf, dialect=None, normalize=None):
        signature = FUNCTIONS.get(udf.name.lower()) if isinstance(udf, exp.Anonymous) else None
        if signature is None:
            return super().get_udf_type(udf, dialect, normalize)
        if signature.returns is not None:
            return exp.DataType.build(signature.returns)
        element = next((arg.type for arg in udf.expressions if _known(arg.type)), exp.DataType(this=T.UNKNOWN))
        return exp.DataType(this=T.ARRAY, nested=True, expressions=[element.copy()])


def _type(prop):
    logical = prop.get("logicalType")
    if logical == "object" and prop.get("properties"):
        return exp.DataType(this=T.STRUCT, nested=True, expressions=[
            exp.ColumnDef(this=exp.to_identifier(child["name"], quoted=True), kind=_type(child))
            for child in prop["properties"]])
    if logical == "array" and isinstance(prop.get("items"), dict):
        return exp.DataType(this=T.ARRAY, nested=True, expressions=[_type(prop["items"])])
    return exp.DataType.build(LOGICAL[logical]) if logical in LOGICAL else exp.DataType(this=T.UNKNOWN)


def _logical(data_type):
    """The ODCS logical type a produced SQL type satisfies, or None when unknown."""
    if data_type is None:
        return None
    kind = data_type.this
    for logical, kinds in (("string", exp.DataType.TEXT_TYPES), ("integer", exp.DataType.INTEGER_TYPES),
                           ("number", exp.DataType.REAL_TYPES | {T.DECIMAL, T.BIGDECIMAL, T.DOUBLE, T.FLOAT}),
                           ("boolean", {T.BOOLEAN}), ("date", {T.DATE, T.DATE32}), ("time", {T.TIME, T.TIMETZ}),
                           ("timestamp", exp.DataType.TEMPORAL_TYPES - {T.DATE, T.DATE32, T.TIME, T.TIMETZ}),
                           ("object", {T.STRUCT}), ("array", {T.ARRAY})):
        if kind in kinds:
            return logical
    return None


def _family(node):
    logical = _logical(node.type)
    return FAMILIES.get(logical, logical)


def _known(data_type):
    return data_type is not None and data_type.this not in {T.UNKNOWN, T.NULL}


def _kind(node):
    """The logical type an argument supplies, "json" for json_get's value, or None when it is untyped."""
    if node is None or not _known(node.type):
        return None
    return "json" if node.type.this == T.JSON else _logical(node.type)


def _iso_time(text):
    for parser in (date.fromisoformat, datetime.fromisoformat, time.fromisoformat):
        try:
            parser(text)
            return True
        except ValueError:
            pass
    return False


class _Result:
    def __init__(self):
        self.failed, self.unknown = [], []

    def fail(self, code, message):
        self.failed.append({"code": code, "message": message, "severity": "error"})

    def defer(self, code, message):
        self.unknown.append({"code": code, "message": message, "severity": "warning"})

    def record(self, **details):
        status = "failed" if self.failed else "unknown" if self.unknown else "passed"
        reason = self.unknown[0]["message"] if status == "unknown" else None
        return {"status": status, "reason": reason, "diagnostics": self.failed + self.unknown, **details}


def _number_positional(sql, dialect):
    """Name each `?` by its position in the SQL text; tree order differs from text order."""
    marks = [token for token in Dialect.get_or_raise(dialect).tokenize(sql)
             if token.token_type == TokenType.PLACEHOLDER and token.text == "?"]
    for index, token in reversed(list(enumerate(marks))):
        sql = f"{sql[:token.start]}:{POSITIONAL}{index}{sql[token.end + 1:]}"
    return sql, len(marks)


def _bind_parameters(tree, recipe, positional, result):
    """Replace each parameter with a typed NULL: `?` by position, `$n` by number, `:name` by name."""
    nodes = list(tree.find_all(exp.Placeholder, exp.Parameter))
    schema = recipe.get("parameters", {}).get("properties", {})
    order = recipe.get("parameterOrder")
    if (positional or any(isinstance(node, exp.Parameter) for node in nodes)) and order is None:
        result.fail("CATALOG-RECIPE-PARAMETERS", "Positional parameters need parameterOrder.")
        return
    if positional and positional != len(order):
        result.fail("CATALOG-RECIPE-PARAMETERS", f"The SQL uses {positional} positional parameters; "
                    f"parameterOrder names {len(order)}.")
        return
    for node in nodes:
        if isinstance(node, exp.Placeholder) and node.name.startswith(POSITIONAL):
            name, shown = order[int(node.name.removeprefix(POSITIONAL))], "?"
        elif isinstance(node, exp.Parameter) and node.name.isdigit():
            index = int(node.name) - 1
            name, shown = (order[index] if 0 <= index < len(order) else None), node.sql()
        else:
            name, shown = node.name, node.sql()
        if name not in schema:
            result.fail("CATALOG-RECIPE-PARAMETERS", f"Parameter {shown!r} names no declared parameter.")
            continue
        declared = PARAMETERS.get(schema[name].get("type"))
        node.replace(exp.cast(exp.null(), declared) if declared else exp.null())


def _check_tables(tree, inputs, result):
    """Every table a scope reads is a recipe input; CTE names count only where they are visible."""
    for scope in traverse_scope(tree):
        for source in scope.sources.values():
            if not isinstance(source, exp.Table):
                continue
            if not isinstance(source.this, exp.Identifier):
                result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"Table source {source.sql()!r} is not a named input.")
            elif source.args.get("db") or source.name not in inputs:
                result.fail("CATALOG-RECIPE-TABLE", f"Table {source.sql()!r} is not a recipe input.")


def _check_access(tree, result):
    """Field access needs a declared object, index access a declared array, UNNEST a declared array."""
    for node in tree.find_all(exp.Dot):
        base = node.this.type
        if not _known(base):
            result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"Field access {node.sql()!r} has no declared object to bind.")
        elif base.this != T.STRUCT:
            result.fail("CATALOG-RECIPE-COLUMN", f"{node.sql()!r} reads a field of a value that is not an object.")
        elif node.name not in {column.name for column in base.expressions}:
            result.fail("CATALOG-RECIPE-COLUMN", f"{node.sql()!r} names a field its object does not declare.")
    for node in tree.find_all(exp.Bracket):
        if any(item.is_string for item in node.expressions):
            result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"Keyed access {node.sql()!r} is not bound.")
        elif _known(node.this.type) and node.this.type.this != T.ARRAY:
            result.fail("CATALOG-RECIPE-COLUMN", f"{node.sql()!r} indexes a value that is not an array.")
    elements = {}
    for unnest in tree.find_all(exp.Unnest):
        alias, source = unnest.args.get("alias"), unnest.expressions[0].type if unnest.expressions else None
        if _known(source) and source.this != T.ARRAY:
            result.fail("CATALOG-RECIPE-COLUMN", f"{unnest.sql()!r} unnests a value that is not an array.")
        elif alias is None or not _known(source):
            result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"{unnest.sql()!r} has no declared array to bind.")
        else:
            elements[alias.name] = ({column.name for column in alias.columns}, source.expressions[0])
    for column in tree.find_all(exp.Column):
        if column.table not in elements:
            continue
        named, element = elements[column.table]
        if column.name in named:
            continue
        if element.this != T.STRUCT or column.name not in {field.name for field in element.expressions}:
            result.fail("CATALOG-RECIPE-COLUMN", f"{column.sql()!r} names a field the array element does not declare.")


def _agreeing_groups(tree):
    """Yield (node, values) for every place whose values must share one type family."""
    for node in tree.find_all(exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.NullSafeEQ, exp.NullSafeNEQ):
        yield node, [node.this, node.expression]
    for node in tree.find_all(exp.Between):
        yield node, [node.this, node.args["low"], node.args["high"]]
    for node in tree.find_all(exp.In):
        query = node.args.get("query")
        selected = query.unnest().selects if query is not None else []
        yield node, [node.this, *node.expressions, *selected[:1]]
    for node in tree.find_all(exp.Coalesce):
        yield node, [node.this, *node.expressions]
    for node in tree.find_all(exp.Case):
        branches = [branch.args["true"] for branch in node.args.get("ifs", ())]
        yield node, branches + ([node.args["default"]] if node.args.get("default") is not None else [])
    for node in tree.find_all(exp.If):
        if node.args.get("false") is not None:
            yield node, [node.args["true"], node.args["false"]]
    for node in tree.find_all(exp.SetOperation):
        for left, right in zip(node.left.selects, node.right.selects):
            yield node, [left, right]
    for node in tree.find_all(exp.Anonymous):
        if node.name.lower() == "make_array":
            yield node, list(node.expressions)


def _check_types(tree, result):
    for node, values in _agreeing_groups(tree):
        literals = [value for value in values if isinstance(value, exp.Literal) and value.is_string]
        families = {_family(value) for value in values if not any(value is literal for literal in literals)} - {None}
        if "temporal" in families:
            if bad := [value.sql() for value in literals if not _iso_time(value.name)]:
                result.fail("CATALOG-RECIPE-TYPE", f"{node.sql()!r} compares a temporal value with {', '.join(bad)}.")
        elif literals:
            families.add("string")
        if len(families) > 1:
            result.fail("CATALOG-RECIPE-TYPE", f"{node.sql()!r} mixes {' and '.join(sorted(families))} values.")
    for node in tree.find_all(exp.SetOperation):
        if len(node.left.selects) != len(node.right.selects):
            result.fail("CATALOG-RECIPE-TYPE", f"{node.key.upper()} branches produce different column counts.")
    for node in tree.find_all(exp.Like, exp.ILike):
        if {_family(node.this), _family(node.expression)} - {"string", None}:
            result.fail("CATALOG-RECIPE-TYPE", f"{node.sql()!r} applies a pattern to a value that is not a string.")
    for node in tree.find_all(exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod):
        if {_family(node.this), _family(node.expression)} & NOT_ARITHMETIC:
            result.fail("CATALOG-RECIPE-TYPE", f"{node.sql()!r} applies arithmetic to a value that is not numeric.")


def _check_unique_names(tree, result):
    """DataFusion refuses a projection that repeats an output name. Before qualification adds aliases, a repeated
    alias or an identical unaliased expression always repeats one; other repeats are left to the engine."""
    for select in tree.find_all(exp.Select):
        seen = set()
        for column in select.expressions:
            if column.is_star:
                continue
            key = ("alias", column.alias) if isinstance(column, exp.Alias) else ("expression", column.sql())
            if key in seen:
                result.fail("CATALOG-RECIPE-SQL-SHAPE", f"A projection repeats the output name of {column.sql()!r}; "
                            "DataFusion requires distinct names, so alias one of them.")
            seen.add(key)


def _check_functions(tree, result):
    """Argument counts and types DataFusion accepts for FUNCTIONS and ARGUMENTS."""
    for node in tree.find_all(exp.Anonymous, *ARGUMENTS):
        if isinstance(node, exp.Anonymous):
            name, signature = node.name.lower(), FUNCTIONS.get(node.name.lower())
            if signature is None:
                continue
            values, leading = list(node.expressions), len(signature.arguments)
            if len(values) < signature.minimum or (signature.more is None and len(values) > leading):
                result.fail("CATALOG-RECIPE-TYPE", f"{name} does not take {len(values)} arguments: {node.sql()!r}.")
                continue
            pairs = [(value, signature.arguments[index] if index < leading else signature.more)
                     for index, value in enumerate(values)]
        else:
            name, accepted = next(rule for kind, rule in ARGUMENTS.items() if isinstance(node, kind))
            pairs = [(node.args.get(key), allowed) for key, allowed in accepted.items()]
        for value, allowed in pairs:
            if (kind := _kind(value)) is not None and kind not in allowed:
                result.fail("CATALOG-RECIPE-TYPE", f"{name} does not accept the {kind} value {value.sql()!r}.")
    for node in tree.find_all(exp.ArrayContains):
        array, needle = node.this.type, _kind(node.expression)
        element = _logical(array.expressions[0]) if _known(array) and array.this == T.ARRAY and array.expressions else None
        if needle is not None and element is not None and FAMILIES.get(needle, needle) != FAMILIES.get(element, element):
            result.fail("CATALOG-RECIPE-TYPE", f"array_has looks for a {needle} value in an array of {element} values.")


def _shape(declared, produced, path, result):
    """Compare a declared ODCS property with a produced SQL type, recursing into objects and arrays."""
    want, have = declared.get("logicalType"), _logical(produced)
    if want is None:
        return
    if have is None:
        result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"Output {path!r} has no inferred type.")
    elif have != want and not (want == "number" and have == "integer"):
        result.fail("CATALOG-RECIPE-RESULT", f"Output {path!r} is {have}; the result declares {want}.")
    elif want == "object" and declared.get("properties"):
        fields = {column.name: column.args.get("kind") for column in produced.expressions}
        for prop in declared["properties"]:
            if prop["name"] not in fields:
                result.fail("CATALOG-RECIPE-RESULT", f"Declared field {path}.{prop['name']} is not produced.")
            else:
                _shape(prop, fields[prop["name"]], f"{path}.{prop['name']}", result)
        for name in sorted(fields.keys() - {prop["name"] for prop in declared["properties"]}):
            result.fail("CATALOG-RECIPE-RESULT", f"Produced field {path}.{name} is not declared.")
    elif want == "array" and isinstance(declared.get("items"), dict) and produced.expressions:
        _shape(declared["items"], produced.expressions[0], f"{path}[]", result)


def _check_result(selects, definition, result):
    declared = {prop["name"]: prop for prop in definition.get("properties", ())}
    names = [select.alias_or_name for select in selects]
    for name in sorted(set(names) - declared.keys()):
        result.fail("CATALOG-RECIPE-RESULT", f"Output column {name!r} is not declared by the result dataset.")
    for name in sorted(declared.keys() - set(names)):
        result.fail("CATALOG-RECIPE-RESULT", f"Declared result property {name!r} is not produced.")
    seen = set()
    for name, select in zip(names, selects):
        if name in seen:
            result.fail("CATALOG-RECIPE-RESULT", f"Output column {name!r} is produced more than once.")
        elif name in declared:
            _shape(declared[name], select.type, name, result)
        seen.add(name)


def bind_one(recipe):
    result = _Result()
    dialect = DIALECTS.get(recipe["dialect"])
    if dialect is None:
        result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"No parser profile supports dialect {recipe['dialect']!r}.")
        return result.record()
    datafusion = recipe["dialect"] == "datafusion"
    parser = {"dialect": dialect, **({"signatures": SIGNATURE_PROFILE} if datafusion else {})}
    try:
        sql, positional = _number_positional(recipe["sql"], dialect)
        statements = [statement for statement in parse(sql, read=dialect) if statement is not None]
    except SqlglotError as exc:
        result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"The {dialect} parser cannot read the SQL: {str(exc).splitlines()[0]}")
        return result.record(parser=parser)
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        result.fail("CATALOG-RECIPE-SQL-SHAPE", "A recipe must be exactly one query.")
        return result.record(parser=parser)
    tree, inputs = statements[0], recipe["inputs"]
    if datafusion:
        _check_unique_names(tree, result)
    try:
        _check_tables(tree, inputs, result)
    except SqlglotError as exc:
        result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", str(exc).splitlines()[0])
    if result.failed:
        return result.record(parser=parser)
    _bind_parameters(tree, recipe, positional, result)
    schema = (_DataFusionSchema if datafusion else MappingSchema)(
        {name: {prop["name"]: _type(prop) for prop in definition.get("properties", ())}
         for name, definition in inputs.items()}, dialect=dialect, normalize=False)
    try:
        tree = annotate_types(qualify(tree, schema=schema, dialect=dialect, validate_qualify_columns=True),
                              schema=schema, dialect=dialect)
    except SqlglotError as exc:
        message = str(exc).splitlines()[0]
        if isinstance(exc, OptimizeError) and any(text in message for text in COLUMN_ERRORS):
            result.fail("CATALOG-RECIPE-COLUMN", message)
        else:
            result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", message)
        return result.record(parser=parser)
    _check_access(tree, result)
    _check_types(tree, result)
    if datafusion:
        _check_functions(tree, result)
    if functions := sorted({node.name for node in tree.find_all(exp.Anonymous)
                            if not (datafusion and node.name.lower() in FUNCTIONS)}):
        result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"Functions without a parser signature: {', '.join(functions)}.")
    if JSON_NODES and next(tree.find_all(*JSON_NODES), None) is not None:
        result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", "JSON extraction semantics are engine-specific.")
    if recipe.get("result") is not None:
        _check_result(tree.selects, recipe["result"], result)
    output = [{"name": select.alias_or_name, "logicalType": _logical(select.type)} for select in tree.selects]
    return result.record(parser=parser, output=output)


def bind(request, _folder):
    """Bind every recipe in one request; each result keeps its own status."""
    return {"status": "completed", "parser": {"id": "sqlglot", "version": SQLGLOT_VERSION},
            "results": {recipe["id"]: bind_one(recipe) for recipe in request["recipes"]}}
