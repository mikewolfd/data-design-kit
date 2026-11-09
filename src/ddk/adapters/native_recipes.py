"""Offline recipe SQL binding against declared ODCS inputs, run in an explicitly selected tool environment.

sqlglot parses the SQL, qualifies every column against a schema built from the
inputs' effective ODCS definitions, and annotates types. DDK adds the checks
sqlglot leaves open: table references outside the declared inputs, nested
fields absent from their declared object, positional parameter binding,
clear comparison type conflicts, and the declared result dataset. Constructs
the parser cannot type, such as engine-specific or JSON functions, stay
unknown. The recipe is never executed and no data is read.
"""

from sqlglot import exp, parse
from sqlglot import __version__ as SQLGLOT_VERSION
from sqlglot.errors import OptimizeError, ParseError, SqlglotError
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify
from sqlglot.schema import MappingSchema

# DataFusion follows PostgreSQL syntax and coercion most closely; sqlglot has no DataFusion dialect.
DIALECTS = {"datafusion": "postgres", "postgres": "postgres", "duckdb": "duckdb"}
LOGICAL = {"string": "TEXT", "integer": "BIGINT", "number": "DOUBLE", "boolean": "BOOLEAN",
           "date": "DATE", "timestamp": "TIMESTAMP", "time": "TIME"}
PARAMETERS = {"string": "TEXT", "integer": "BIGINT", "number": "DOUBLE", "boolean": "BOOLEAN"}
T = exp.DataType.Type
COMPARISONS = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)
JSON_NODES = tuple(getattr(exp, name) for name in ("JSONExtract", "JSONExtractScalar", "JSONBExtract",
                                                    "JSONBExtractScalar", "JSONExtractArray") if hasattr(exp, name))


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
    return {"integer": "number", "date": "temporal", "time": "temporal", "timestamp": "temporal"}.get(logical, logical)


def _fields(data_type):
    return {column.name for column in data_type.expressions} if data_type is not None and data_type.this == T.STRUCT else None


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


def _bind_parameters(tree, recipe, result):
    """Replace each parameter with a typed NULL: `?` by position, `$n` by number, `:name` by name."""
    nodes = list(tree.find_all(exp.Placeholder, exp.Parameter, bfs=False))
    if not nodes:
        return
    schema = recipe.get("parameters", {}).get("properties", {})
    order = recipe.get("parameterOrder")
    positional = [node for node in nodes if isinstance(node, exp.Placeholder) and node.args.get("jdbc")]
    numbered = [node for node in nodes if isinstance(node, exp.Parameter) and node.name.isdigit()]
    if (positional or numbered) and order is None:
        result.fail("CATALOG-RECIPE-PARAMETERS", "Positional parameters need parameterOrder.")
        return
    if positional and len(positional) != len(order):
        result.fail("CATALOG-RECIPE-PARAMETERS", f"The SQL uses {len(positional)} positional parameters; "
                    f"parameterOrder names {len(order)}.")
        return
    by_position = dict(zip(map(id, positional), order or ()))
    for node in nodes:
        if id(node) in by_position:
            name = by_position[id(node)]
        elif node in numbered:
            index = int(node.name) - 1
            name = order[index] if 0 <= index < len(order) else None
        else:
            name = node.name
        if name not in schema:
            result.fail("CATALOG-RECIPE-PARAMETERS", f"Parameter {node.sql()!r} names no declared parameter.")
            continue
        declared = PARAMETERS.get(schema[name].get("type"))
        node.replace(exp.cast(exp.null(), declared) if declared else exp.null())


def _check_nested(tree, result):
    for node in tree.find_all(exp.Dot):
        fields = _fields(node.this.type)
        if fields is None:
            if node.this.type is None or node.this.type.this == T.UNKNOWN:
                result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"Field access {node.sql()!r} has no declared object to bind.")
        elif node.name not in fields:
            result.fail("CATALOG-RECIPE-COLUMN", f"{node.sql()!r} names a field its object does not declare.")
    for node in tree.find_all(exp.Bracket):
        if any(item.is_string for item in node.expressions):
            result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"Keyed access {node.sql()!r} is not bound.")
    elements = {}
    for unnest in tree.find_all(exp.Unnest):
        alias = unnest.args.get("alias")
        source = unnest.expressions[0].type if unnest.expressions else None
        if alias is None or source is None or source.this != T.ARRAY:
            result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"{unnest.sql()!r} has no declared array to bind.")
            continue
        elements[alias.name] = ({column.name for column in alias.columns}, source.expressions[0])
    for column in tree.find_all(exp.Column):
        if column.table in elements:
            named, element = elements[column.table]
            fields = _fields(element)
            if column.name in named:
                continue
            if fields is None:
                result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"{column.sql()!r} reads an unnamed array element.")
            elif column.name not in fields:
                result.fail("CATALOG-RECIPE-COLUMN", f"{column.sql()!r} names a field the array element does not declare.")


def _check_comparisons(tree, result):
    for node in tree.find_all(*COMPARISONS):
        left, right = node.this, node.expression
        families = {_family(left), _family(right)}
        literal_time = "temporal" in families and any(isinstance(side, exp.Literal) and side.is_string for side in (left, right))
        if None not in families and len(families) > 1 and not literal_time:
            result.fail("CATALOG-RECIPE-TYPE", f"{node.sql()!r} compares {_family(left)} with {_family(right)}.")


def _check_result(output, definition, result):
    declared = {prop["name"]: prop.get("logicalType") for prop in definition.get("properties", ())}
    produced = [item["name"] for item in output]
    for name in sorted(set(produced) - declared.keys()):
        result.fail("CATALOG-RECIPE-RESULT", f"Output column {name!r} is not declared by the result dataset.")
    for name in sorted(declared.keys() - set(produced)):
        result.fail("CATALOG-RECIPE-RESULT", f"Declared result property {name!r} is not produced.")
    for name in sorted({name for name in produced if produced.count(name) > 1}):
        result.fail("CATALOG-RECIPE-RESULT", f"Output column {name!r} is produced more than once.")
    for item in output:
        want = declared.get(item["name"])
        have = item["logicalType"]
        if want is None:
            continue
        if have is None:
            result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"Output column {item['name']!r} has no inferred type.")
        elif have != want and not (want == "number" and have == "integer"):
            result.fail("CATALOG-RECIPE-RESULT", f"Output column {item['name']!r} is {have}; the result declares {want}.")


def bind_one(recipe):
    result = _Result()
    dialect = DIALECTS.get(recipe["dialect"])
    if dialect is None:
        result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"No parser profile supports dialect {recipe['dialect']!r}.")
        return result.record()
    try:
        statements = [statement for statement in parse(recipe["sql"], read=dialect) if statement is not None]
    except ParseError as exc:
        result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"The {dialect} parser cannot read the SQL: {str(exc).splitlines()[0]}")
        return result.record(parser={"dialect": dialect})
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        result.fail("CATALOG-RECIPE-SQL-SHAPE", "A recipe must be exactly one query.")
        return result.record(parser={"dialect": dialect})
    tree = statements[0]
    inputs = recipe["inputs"]
    ctes = {cte.alias for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"Table source {table.sql()!r} is not a named input.")
        elif table.args.get("db") or (table.name not in inputs and table.name not in ctes):
            result.fail("CATALOG-RECIPE-TABLE", f"Table {table.sql()!r} is not a recipe input.")
    if result.failed:
        return result.record(parser={"dialect": dialect})
    _bind_parameters(tree, recipe, result)
    schema = MappingSchema({name: {prop["name"]: _type(prop) for prop in definition.get("properties", ())}
                            for name, definition in inputs.items()}, dialect=dialect, normalize=False)
    try:
        tree = annotate_types(qualify(tree, schema=schema, dialect=dialect, validate_qualify_columns=True),
                              schema=schema, dialect=dialect)
    except OptimizeError as exc:
        message = str(exc).splitlines()[0]
        if any(text in message for text in ("Unknown column", "could not be resolved", "Ambiguous column")):
            result.fail("CATALOG-RECIPE-COLUMN", message)
        else:
            result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", message)
        return result.record(parser={"dialect": dialect})
    except SqlglotError as exc:
        result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", str(exc).splitlines()[0])
        return result.record(parser={"dialect": dialect})
    _check_nested(tree, result)
    _check_comparisons(tree, result)
    functions = sorted({node.name for node in tree.find_all(exp.Anonymous)})
    if functions:
        result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", f"Functions without a parser signature: {', '.join(functions)}.")
    if JSON_NODES and next(tree.find_all(*JSON_NODES), None) is not None:
        result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", "JSON extraction semantics are engine-specific.")
    output = [{"name": select.alias_or_name, "logicalType": _logical(select.type)} for select in tree.selects]
    if recipe.get("result") is not None:
        _check_result(output, recipe["result"], result)
    return result.record(parser={"dialect": dialect}, output=output)


def bind(request, _folder):
    """Bind every recipe in one request; each result keeps its own status."""
    return {"status": "completed", "parser": {"id": "sqlglot", "version": SQLGLOT_VERSION},
            "results": {recipe["id"]: bind_one(recipe) for recipe in request["recipes"]}}
