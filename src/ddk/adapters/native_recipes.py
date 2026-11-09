"""Offline recipe SQL binding against declared ODCS inputs, run in an explicitly selected tool environment.

sqlglot parses the SQL, qualifies every column against a schema built from the
inputs' effective ODCS definitions, and annotates types. DDK adds the checks
sqlglot leaves open: table references outside the declared inputs (per scope),
field and index access the declarations do not support, parameter binding,
type-family conflicts between values that must agree, and the declared result
dataset's shape. Constructs the parser cannot type, such as engine-specific or
JSON functions, stay unknown. The recipe is never executed and no data is read.
"""

from datetime import date, datetime, time

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
    parser = {"dialect": dialect}
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
    try:
        _check_tables(tree, inputs, result)
    except SqlglotError as exc:
        result.defer("CATALOG-RECIPE-SQL-UNSUPPORTED", str(exc).splitlines()[0])
    if result.failed:
        return result.record(parser=parser)
    _bind_parameters(tree, recipe, positional, result)
    schema = MappingSchema({name: {prop["name"]: _type(prop) for prop in definition.get("properties", ())}
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
    if functions := sorted({node.name for node in tree.find_all(exp.Anonymous)}):
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
