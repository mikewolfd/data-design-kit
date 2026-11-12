"""Deterministic ODCS 3.x -> DocSpec SQL zero-counter and join-metrics compiler (Decision 3A / S3a)."""

from hashlib import sha256
import re

from .catalog_access import CatalogError
from .documents import json_dumps


def quote_sql_ident(name):
    """Quote a SQL identifier using standard double-quote escaping."""
    return '"' + str(name).replace('"', '""') + '"'


def format_sql_literal(value, logical_type=None):
    """Format a scalar Python value as a deterministic DataFusion SQL literal."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    text = str(value).replace("'", "''")
    if logical_type == "date":
        return f"DATE '{text}'"
    if logical_type == "timestamp":
        return f"CAST('{text}' AS TIMESTAMP)"
    return f"'{text}'"


def _format_table_ref(table_name, table_schema=None):
    """Format an optional schema-qualified SQL table identifier."""
    quoted_name = quote_sql_ident(table_name)
    if table_schema:
        return (
            f"{table_schema}.{quoted_name}"
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_schema)
            else f"{quote_sql_ident(table_schema)}.{quoted_name}"
        )
    return quoted_name


def _table_ref_variants(table_name, table_schema=None):
    """Return acceptable canonical SQL table reference spellings."""
    name_forms = {quote_sql_ident(table_name)}
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
        name_forms.add(table_name)
    if not table_schema:
        return name_forms
    schema_forms = {quote_sql_ident(table_schema)}
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_schema):
        schema_forms.add(table_schema)
    return {f"{sf}.{nf}" for sf in schema_forms for nf in name_forms}


def _substitute_template(sql_text, table_ref, column_name=None):
    """Substitute ODCS ${object}/${table} and ${property}/${column} placeholders."""
    rendered = sql_text
    for token in ("${object}", "{object}", "${table}", "{table}"):
        rendered = rendered.replace(token, table_ref)
    if column_name is not None:
        quoted_col = quote_sql_ident(column_name)
        for token in ("${property}", "{property}", "${column}", "{column}"):
            rendered = rendered.replace(token, quoted_col)
    return rendered.strip().rstrip(";").strip()


def _safe_query_suffix(text):
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
    return slug or sha256(text.encode("utf-8")).hexdigest()[:12]


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compile_odcs_quality_counters(schema_obj, table_name, *, query_name=None, table_schema="outputs"):
    """Lower standard ODCS 3.x quality rules on an object/properties into DocSpec SQL zero-counters.

    Every uniqueness check lowers to a spill-capable ``GROUP BY ... HAVING COUNT(*) > 1`` subquery
    rather than ``COUNT(DISTINCT ...)`` so datasets with multiple unique columns never trigger
    multi-distinct planner failures or unbounded in-memory hash sets in DataFusion.

    By default ``table_schema="outputs"`` targets the exported ``outputs.<table_name>`` relation
    registered by ``docspec`` after Parquet materialization. Pass ``table_schema=None`` only when
    compiling counters against an unqualified standalone or input relation.

    Returns a dictionary containing:
      - ``table``: target table/view name in the JobSpec
      - ``tableSchema``: target SQL schema (``"outputs"`` or ``None``)
      - ``rules``: ordered list of compiled rule descriptors
      - ``queries``: ordered list of ``{"name": ..., "sql": ...}`` DocSpec query objects
      - ``unmapped``: list of ODCS rules outside the zero-counter SQL profile
    """
    if not isinstance(schema_obj, dict):
        raise ValueError("Expected an ODCS schema object dictionary.")
    if not isinstance(table_name, str) or not table_name.strip():
        raise ValueError("Expected a non-empty SQL table/view name.")

    quoted_table = _format_table_ref(table_name, table_schema)
    table_slug = _safe_query_suffix(table_name)
    aggregate_query_name = query_name or f"odcs_counters_{table_slug}"

    rules = []
    scalar_projections = []
    explicit_queries = []
    unmapped = []
    seen_rule_ids = set()
    seen_query_names = set()

    def unique_id(candidate):
        if candidate not in seen_rule_ids:
            seen_rule_ids.add(candidate)
            return candidate
        suffix = 2
        while f"{candidate}:{suffix}" in seen_rule_ids:
            suffix += 1
        final = f"{candidate}:{suffix}"
        seen_rule_ids.add(final)
        return final

    def unique_query_name(candidate):
        if candidate not in seen_query_names and candidate != aggregate_query_name:
            seen_query_names.add(candidate)
            return candidate
        suffix = 2
        while f"{candidate}_{suffix}" in seen_query_names or f"{candidate}_{suffix}" == aggregate_query_name:
            suffix += 1
        final = f"{candidate}_{suffix}"
        seen_query_names.add(final)
        return final

    def add_scalar_counter(rule_id, kind, expr_sql, description, must_be=0):
        rid = unique_id(rule_id)
        alias_sql = f"{expr_sql} AS {quote_sql_ident(rid)}"
        scalar_projections.append(alias_sql)
        rules.append({
            "id": rid,
            "kind": kind,
            "query": aggregate_query_name,
            "column": rid,
            "sql": expr_sql,
            "mustBe": must_be,
            "description": description,
        })

    def add_uniqueness_query(rule_id, preferred_q_name, prop_names, description, must_be=0):
        rid = unique_id(rule_id)
        q_name = unique_query_name(preferred_q_name)
        cols_sql = ", ".join(quote_sql_ident(p) for p in prop_names)
        nn_sql = " AND ".join(f"{quote_sql_ident(p)} IS NOT NULL" for p in prop_names)
        dup_sql = (
            f"SELECT COUNT(*) FROM (SELECT {cols_sql} FROM {quoted_table} "
            f"WHERE {nn_sql} GROUP BY {cols_sql} HAVING COUNT(*) > 1) AS _dup"
        )
        explicit_queries.append({"name": q_name, "sql": dup_sql})
        rules.append({
            "id": rid,
            "kind": "uniqueness",
            "query": q_name,
            "column": None,
            "sql": dup_sql,
            "mustBe": must_be,
            "description": description,
        })

    for prop in schema_obj.get("properties", ()) or ():
        if not isinstance(prop, dict) or not isinstance(prop.get("name"), str) or not prop["name"]:
            continue
        prop_name = prop["name"]
        col = quote_sql_ident(prop_name)
        lt = prop.get("logicalType")
        opts = prop.get("logicalTypeOptions") if isinstance(prop.get("logicalTypeOptions"), dict) else {}
        prop_quality = prop.get("quality") if isinstance(prop.get("quality"), list) else []

        has_explicit_not_null = any(
            isinstance(q, dict)
            and (q.get("metric") or q.get("rule")) in {"nullValues", "notNull"}
            and q.get("mustBe") in (None, 0)
            for q in prop_quality
        )
        if prop.get("required") is True and not has_explicit_not_null:
            add_scalar_counter(
                f"{prop_name}:required",
                "not_null",
                f"COUNT(CASE WHEN {col} IS NULL THEN 1 END)",
                f"Property {prop_name!r} must not be NULL.",
            )

        if prop.get("unique") is True:
            add_uniqueness_query(
                f"{prop_name}:unique",
                f"odcs_uniq_{table_slug}_{_safe_query_suffix(prop_name)}",
                [prop_name],
                f"Property {prop_name!r} must have no duplicate non-null values.",
            )

        raw_enum = prop.get("enum") if isinstance(prop.get("enum"), list) else (
            opts.get("enum") if isinstance(opts.get("enum"), list) else None
        )
        if raw_enum:
            enum_values = [
                item["value"] if isinstance(item, dict) and "value" in item else item
                for item in raw_enum
            ]
            in_list = ", ".join(format_sql_literal(v, lt) for v in enum_values)
            add_scalar_counter(
                f"{prop_name}:enum",
                "enum",
                f"COUNT(CASE WHEN {col} IS NOT NULL AND {col} NOT IN ({in_list}) THEN 1 END)",
                f"Property {prop_name!r} must belong to its declared enum.",
            )

        # String length & regex pattern options
        min_len = opts.get("minLength")
        if _is_int(min_len) and min_len > 0:
            add_scalar_counter(
                f"{prop_name}:minLength",
                "length",
                f"COUNT(CASE WHEN {col} IS NOT NULL AND character_length({col}) < {min_len} THEN 1 END)",
                f"Property {prop_name!r} must have character length >= {min_len}.",
            )
        max_len = opts.get("maxLength")
        if _is_int(max_len) and max_len >= 0:
            add_scalar_counter(
                f"{prop_name}:maxLength",
                "length",
                f"COUNT(CASE WHEN {col} IS NOT NULL AND character_length({col}) > {max_len} THEN 1 END)",
                f"Property {prop_name!r} must have character length <= {max_len}.",
            )
        pattern = opts.get("pattern")
        if isinstance(pattern, str) and pattern:
            pat_lit = format_sql_literal(pattern)
            add_scalar_counter(
                f"{prop_name}:pattern",
                "pattern",
                f"COUNT(CASE WHEN {col} IS NOT NULL AND NOT regexp_like({col}, {pat_lit}) THEN 1 END)",
                f"Property {prop_name!r} must match regex {pattern!r}.",
            )

        # Array cardinality & distinctness options
        min_items = opts.get("minItems")
        if _is_int(min_items) and min_items > 0:
            add_scalar_counter(
                f"{prop_name}:minItems",
                "array_length",
                f"COUNT(CASE WHEN {col} IS NOT NULL AND COALESCE(array_length({col}), 0) < {min_items} THEN 1 END)",
                f"Property {prop_name!r} must contain at least {min_items} item(s).",
            )
        max_items = opts.get("maxItems")
        if _is_int(max_items) and max_items >= 0:
            add_scalar_counter(
                f"{prop_name}:maxItems",
                "array_length",
                f"COUNT(CASE WHEN {col} IS NOT NULL AND COALESCE(array_length({col}), 0) > {max_items} THEN 1 END)",
                f"Property {prop_name!r} must contain at most {max_items} item(s).",
            )
        if opts.get("uniqueItems") is True:
            add_scalar_counter(
                f"{prop_name}:uniqueItems",
                "unique_items",
                (
                    f"COUNT(CASE WHEN {col} IS NOT NULL AND "
                    f"COALESCE(array_length({col}), 0) <> COALESCE(array_length(array_distinct({col})), 0) "
                    f"THEN 1 END)"
                ),
                f"Property {prop_name!r} must contain no duplicate array items.",
            )

        # Range bounds in logicalTypeOptions
        exc_min = opts.get("exclusiveMinimum")
        if _is_number(exc_min):
            lit = format_sql_literal(exc_min, lt)
            add_scalar_counter(
                f"{prop_name}:exclusiveMinimum",
                "range",
                f"COUNT(CASE WHEN {col} IS NOT NULL AND {col} <= {lit} THEN 1 END)",
                f"Property {prop_name!r} must be > {exc_min}.",
            )
        elif "minimum" in opts and _is_number(opts["minimum"]):
            bound = opts["minimum"]
            lit = format_sql_literal(bound, lt)
            if exc_min is True:
                add_scalar_counter(
                    f"{prop_name}:exclusiveMinimum",
                    "range",
                    f"COUNT(CASE WHEN {col} IS NOT NULL AND {col} <= {lit} THEN 1 END)",
                    f"Property {prop_name!r} must be > {bound}.",
                )
            else:
                add_scalar_counter(
                    f"{prop_name}:minimum",
                    "range",
                    f"COUNT(CASE WHEN {col} IS NOT NULL AND {col} < {lit} THEN 1 END)",
                    f"Property {prop_name!r} must be >= {bound}.",
                )

        exc_max = opts.get("exclusiveMaximum")
        if _is_number(exc_max):
            lit = format_sql_literal(exc_max, lt)
            add_scalar_counter(
                f"{prop_name}:exclusiveMaximum",
                "range",
                f"COUNT(CASE WHEN {col} IS NOT NULL AND {col} >= {lit} THEN 1 END)",
                f"Property {prop_name!r} must be < {exc_max}.",
            )
        elif "maximum" in opts and _is_number(opts["maximum"]):
            bound = opts["maximum"]
            lit = format_sql_literal(bound, lt)
            if exc_max is True:
                add_scalar_counter(
                    f"{prop_name}:exclusiveMaximum",
                    "range",
                    f"COUNT(CASE WHEN {col} IS NOT NULL AND {col} >= {lit} THEN 1 END)",
                    f"Property {prop_name!r} must be < {bound}.",
                )
            else:
                add_scalar_counter(
                    f"{prop_name}:maximum",
                    "range",
                    f"COUNT(CASE WHEN {col} IS NOT NULL AND {col} > {lit} THEN 1 END)",
                    f"Property {prop_name!r} must be <= {bound}.",
                )

        # Property-level ODCS quality array
        for q_index, q in enumerate(prop_quality):
            if not isinstance(q, dict):
                continue
            raw_id = q.get("id") or q.get("name") or f"{prop_name}:quality:{q_index}"
            desc = q.get("description") or f"Property {prop_name!r} quality rule {raw_id!r}."
            q_type = (q.get("type") or "library").strip()
            metric = (q.get("metric") or q.get("rule") or "").strip()
            args = q.get("arguments") if isinstance(q.get("arguments"), dict) else {}

            if q_type == "sql" and isinstance(q.get("query"), str) and q["query"].strip():
                rid = unique_id(raw_id)
                preferred_q_name = q.get("id") or q.get("name") or f"odcs_sql_{_safe_query_suffix(rid)}"
                q_name = unique_query_name(preferred_q_name)
                rendered_sql = _substitute_template(q["query"], quoted_table, prop_name)
                must_be = q.get("mustBe", 0)
                if not _is_int(must_be):
                    unmapped.append({"id": rid, "reason": "SQL quality rule mustBe must be an integer counter target."})
                    continue
                explicit_queries.append({"name": q_name, "sql": rendered_sql})
                rules.append({
                    "id": rid,
                    "kind": "sql",
                    "query": q_name,
                    "column": None,
                    "sql": rendered_sql,
                    "mustBe": must_be,
                    "description": desc,
                })
                continue

            if metric in {"nullValues", "notNull"} and q.get("mustBe") in (None, 0):
                add_scalar_counter(raw_id, "not_null", f"COUNT(CASE WHEN {col} IS NULL THEN 1 END)", desc)
                continue

            if metric in {"duplicateValues", "unique"} and (q.get("mustBe") is None or _is_int(q.get("mustBe"))):
                must_be = 0 if q.get("mustBe") is None else q["mustBe"]
                preferred = q.get("id") or q.get("name") or f"odcs_dup_{table_slug}_{_safe_query_suffix(raw_id)}"
                add_uniqueness_query(raw_id, preferred, [prop_name], desc, must_be=must_be)
                continue

            valid_vals = args.get("validValues") if isinstance(args.get("validValues"), list) else (
                q.get("validValues") if isinstance(q.get("validValues"), list) else None
            )
            if valid_vals and q.get("mustBe") in (None, 0):
                in_list = ", ".join(format_sql_literal(v, lt) for v in valid_vals)
                add_scalar_counter(
                    raw_id,
                    "enum",
                    f"COUNT(CASE WHEN {col} IS NOT NULL AND {col} NOT IN ({in_list}) THEN 1 END)",
                    desc,
                )
                continue

            q_pattern = args.get("pattern") if isinstance(args.get("pattern"), str) else (
                q.get("pattern") if isinstance(q.get("pattern"), str) else None
            )
            if q_pattern and q.get("mustBe") in (None, 0):
                pat_lit = format_sql_literal(q_pattern)
                add_scalar_counter(
                    raw_id,
                    "pattern",
                    f"COUNT(CASE WHEN {col} IS NOT NULL AND NOT regexp_like({col}, {pat_lit}) THEN 1 END)",
                    desc,
                )
                continue

            # Range rules inside property quality entries
            range_clauses = []
            for key, op in (
                ("minimum", "<"),
                ("mustBeGreaterOrEqualTo", "<"),
                ("exclusiveMinimum", "<="),
                ("mustBeGreaterThan", "<="),
                ("maximum", ">"),
                ("mustBeLessOrEqualTo", ">"),
                ("exclusiveMaximum", ">="),
                ("mustBeLessThan", ">="),
            ):
                if key in q and _is_number(q[key]):
                    range_clauses.append(f"{col} {op} {format_sql_literal(q[key], lt)}")
            if isinstance(q.get("mustBeBetween"), list) and len(q["mustBeBetween"]) == 2:
                low_v, high_v = q["mustBeBetween"]
                range_clauses.append(
                    f"({col} < {format_sql_literal(low_v, lt)} OR {col} > {format_sql_literal(high_v, lt)})"
                )
            if range_clauses:
                combined = " OR ".join(range_clauses)
                add_scalar_counter(
                    raw_id,
                    "range",
                    f"COUNT(CASE WHEN {col} IS NOT NULL AND ({combined}) THEN 1 END)",
                    desc,
                )
                continue

            unmapped.append({"id": str(raw_id), "reason": f"Unsupported property quality rule {q_type}:{metric or 'unknown'}."})

    # Object-level ODCS quality array
    obj_quality = schema_obj.get("quality") if isinstance(schema_obj.get("quality"), list) else []
    for q_index, q in enumerate(obj_quality):
        if not isinstance(q, dict):
            continue
        raw_id = q.get("id") or q.get("name") or f"object:quality:{q_index}"
        desc = q.get("description") or f"Dataset quality rule {raw_id!r}."
        q_type = (q.get("type") or "library").strip()
        metric = (q.get("metric") or q.get("rule") or "").strip()
        args = q.get("arguments") if isinstance(q.get("arguments"), dict) else {}

        if q_type == "sql" and isinstance(q.get("query"), str) and q["query"].strip():
            rid = unique_id(raw_id)
            preferred_q_name = q.get("id") or q.get("name") or f"odcs_sql_{_safe_query_suffix(rid)}"
            q_name = unique_query_name(preferred_q_name)
            rendered_sql = _substitute_template(q["query"], quoted_table)
            must_be = q.get("mustBe", 0)
            if not _is_int(must_be):
                unmapped.append({"id": rid, "reason": "SQL quality rule mustBe must be an integer counter target."})
                continue
            explicit_queries.append({"name": q_name, "sql": rendered_sql})
            rules.append({
                "id": rid,
                "kind": "sql",
                "query": q_name,
                "column": None,
                "sql": rendered_sql,
                "mustBe": must_be,
                "description": desc,
            })
            continue

        if metric == "duplicateValues" and isinstance(args.get("properties"), list) and args["properties"]:
            dup_props = [str(p) for p in args["properties"]]
            must_be = 0 if q.get("mustBe") is None else q.get("mustBe")
            if not _is_int(must_be):
                unmapped.append({"id": str(raw_id), "reason": "duplicateValues mustBe must be an integer counter target."})
                continue
            preferred = q.get("id") or q.get("name") or f"odcs_dup_{_safe_query_suffix(raw_id)}"
            add_uniqueness_query(raw_id, preferred, dup_props, desc, must_be=must_be)
            continue

        if metric == "rowCount":
            rc_conds = []
            for key, op in (
                ("mustBe", "="),
                ("mustNotBe", "<>"),
                ("mustBeGreaterThan", ">"),
                ("mustBeGreaterOrEqualTo", ">="),
                ("mustBeLessThan", "<"),
                ("mustBeLessOrEqualTo", "<="),
            ):
                if key in q and _is_int(q[key]):
                    rc_conds.append(f"COUNT(*) {op} {q[key]}")
            if (
                isinstance(q.get("mustBeBetween"), list)
                and len(q["mustBeBetween"]) == 2
                and all(_is_int(v) for v in q["mustBeBetween"])
            ):
                low_v, high_v = q["mustBeBetween"]
                rc_conds.append(f"(COUNT(*) >= {low_v} AND COUNT(*) <= {high_v})")
            if rc_conds:
                rid = unique_id(raw_id)
                preferred = q.get("id") or q.get("name") or f"odcs_rowcount_{_safe_query_suffix(rid)}"
                q_name = unique_query_name(preferred)
                rc_sql = f"SELECT CASE WHEN {' AND '.join(rc_conds)} THEN 0 ELSE 1 END AS {quote_sql_ident(rid)} FROM {quoted_table}"
                explicit_queries.append({"name": q_name, "sql": rc_sql})
                rules.append({
                    "id": rid,
                    "kind": "row_count",
                    "query": q_name,
                    "column": None,
                    "sql": rc_sql,
                    "mustBe": 0,
                    "description": desc,
                })
                continue

        unmapped.append({"id": str(raw_id), "reason": f"Unsupported object quality rule {q_type}:{metric or 'unknown'}."})

    # Composite or single-column primaryKey / DDK rowIdentity
    pk_cols = [
        prop["name"]
        for prop in sorted(
            [p for p in (schema_obj.get("properties") or ()) if isinstance(p, dict) and p.get("primaryKey") is True],
            key=lambda p: (p.get("primaryKeyPosition") if isinstance(p.get("primaryKeyPosition"), int) else 10**9, p.get("name", "")),
        )
        if isinstance(prop.get("name"), str) and prop["name"]
    ]
    if not pk_cols:
        for cp in schema_obj.get("customProperties", ()) or ():
            if isinstance(cp, dict) and cp.get("vendor") == "ddk" and cp.get("property") == "rowIdentity":
                if isinstance(cp.get("value"), list) and all(isinstance(x, str) and x for x in cp["value"]):
                    pk_cols = list(cp["value"])
                    break
    if pk_cols and not (len(pk_cols) == 1 and f"{pk_cols[0]}:unique" in seen_rule_ids):
        add_uniqueness_query(
            "primary_key:unique",
            f"odcs_pk_{table_slug}",
            pk_cols,
            f"Primary key ({', '.join(pk_cols)}) must have no duplicate values.",
        )

    queries = []
    if scalar_projections:
        projection_sql = ", ".join(scalar_projections)
        agg_sql = f"SELECT {projection_sql} FROM {quoted_table}"
        queries.append({"name": aggregate_query_name, "sql": agg_sql})
    queries.extend(explicit_queries)

    return {
        "table": table_name,
        "tableSchema": table_schema,
        "rules": rules,
        "queries": queries,
        "unmapped": unmapped,
    }


def compile_relationship_join_metrics_queries(catalog, *, table_schema="outputs", dataset_tables=None):
    """Compile DataFusion SQL join-metrics queries for declared dataset-to-dataset relationships.

    Every generated query places deduplicated target keys on the LEFT side of a ``RIGHT ANTI JOIN``
    so DataFusion builds the hash table on the small target key domain and streams the source table
    without ``COUNT(DISTINCT ...)`` sets or multi-reference CTE re-planning.

    Returns a dictionary containing:
      - ``relationships``: list of ``{"relationshipId", "query", "source", "target", "sql"}``
      - ``queries``: list of ``{"name": ..., "sql": ...}`` DocSpec query objects
      - ``skipped``: list of ``{"relationshipId", "reason"}`` for non-local/non-equality links
    """
    if not isinstance(catalog, dict):
        raise ValueError("Expected an assembled DDK catalog dictionary.")

    table_map = dict(dataset_tables or {})
    known_aliases = set()
    for ds in catalog.get("datasets", ()) or ():
        if isinstance(ds, dict) and isinstance(ds.get("alias"), str):
            alias = ds["alias"]
            known_aliases.add(alias)
            table_map.setdefault(alias, alias.rpartition("/")[2] or alias)

    compiled_rels = []
    queries = []
    skipped = []
    seen_q_names = set()

    for rel in catalog.get("relationships", ()) or ():
        if not isinstance(rel, dict) or not isinstance(rel.get("id"), str):
            continue
        rel_id = rel["id"]
        if rel.get("match") == "project_rule":
            skipped.append({"relationshipId": rel_id, "reason": "Relationship uses a project_rule match."})
            continue
        nulls = rel.get("nulls", "skip")
        if nulls == "unknown":
            skipped.append({"relationshipId": rel_id, "reason": "Relationship null handling is unknown."})
            continue
        source = rel.get("source") or {}
        target = rel.get("target") or {}
        if "catalog" in target or "dataset" not in target or "dataset" not in source:
            skipped.append({"relationshipId": rel_id, "reason": "Relationship target is external or in a peer catalog."})
            continue
        src_alias = source["dataset"]
        tgt_alias = target["dataset"]
        if src_alias not in known_aliases or tgt_alias not in known_aliases:
            skipped.append({"relationshipId": rel_id, "reason": "Source or target dataset is absent from catalog."})
            continue
        src_paths = source.get("paths") or ()
        tgt_paths = target.get("paths") or ()
        if (
            not src_paths
            or len(src_paths) != len(tgt_paths)
            or not all(len(p) == 1 and "field" in p[0] for p in src_paths)
            or not all(len(p) == 1 and "field" in p[0] for p in tgt_paths)
        ):
            skipped.append({"relationshipId": rel_id, "reason": "Relationship paths are nested or array-valued."})
            continue

        src_fields = [p[0]["field"] for p in src_paths]
        tgt_fields = [p[0]["field"] for p in tgt_paths]
        src_ref = _format_table_ref(table_map[src_alias], table_schema)
        tgt_ref = _format_table_ref(table_map[tgt_alias], table_schema)

        src_cols_sql = ", ".join(quote_sql_ident(f) for f in src_fields)
        tgt_cols_sql = ", ".join(quote_sql_ident(f) for f in tgt_fields)
        if nulls == "match":
            eligible_pred = "TRUE"
            tgt_where = ""
            src_where = ""
            join_cond = " AND ".join(
                f"_tgt.{quote_sql_ident(tf)} IS NOT DISTINCT FROM _src.{quote_sql_ident(sf)}"
                for sf, tf in zip(src_fields, tgt_fields)
            )
        else:
            eligible_pred = " AND ".join(f"{quote_sql_ident(sf)} IS NOT NULL" for sf in src_fields)
            tgt_nn = " AND ".join(f"{quote_sql_ident(tf)} IS NOT NULL" for tf in tgt_fields)
            tgt_where = f" WHERE {tgt_nn}"
            src_where = f" WHERE {eligible_pred}"
            join_cond = " AND ".join(
                f"_tgt.{quote_sql_ident(tf)} = _src.{quote_sql_ident(sf)}"
                for sf, tf in zip(src_fields, tgt_fields)
            )

        base_q_name = f"ddk_join_metrics_{_safe_query_suffix(rel_id)}"
        q_name = base_q_name
        suffix = 2
        while q_name in seen_q_names:
            q_name = f"{base_q_name}_{suffix}"
            suffix += 1
        seen_q_names.add(q_name)

        sql = (
            "SELECT "
            "s.source_row_count, "
            "s.eligible_source_rows, "
            "s.eligible_source_rows - u.unmatched_rows AS matched_rows, "
            "u.unmatched_rows "
            f"FROM (SELECT COUNT(*) AS source_row_count, "
            f"COUNT(CASE WHEN {eligible_pred} THEN 1 END) AS eligible_source_rows "
            f"FROM {src_ref}) AS s "
            "CROSS JOIN ("
            "SELECT COUNT(*) AS unmatched_rows "
            f"FROM (SELECT {tgt_cols_sql} FROM {tgt_ref}{tgt_where} GROUP BY {tgt_cols_sql}) AS _tgt "
            f"RIGHT ANTI JOIN (SELECT {src_cols_sql} FROM {src_ref}{src_where}) AS _src "
            f"ON {join_cond}"
            ") AS u"
        )
        queries.append({"name": q_name, "sql": sql})
        compiled_rels.append({
            "relationshipId": rel_id,
            "query": q_name,
            "source": src_alias,
            "target": tgt_alias,
            "sql": sql,
        })

    return {
        "relationships": compiled_rels,
        "queries": queries,
        "skipped": skipped,
    }


def _normalize_sql(sql):
    """Collapse unquoted whitespace runs for canonical zero-counter SQL comparison."""
    out = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch in {"'", '"'}:
            quote = ch
            start = i
            i += 1
            while i < n:
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(sql[start:i])
            continue
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out).strip().rstrip(";").strip()


def _expected_query_sql(selected_rules, table_name, *, table_schema="outputs"):
    """Return acceptable canonical SQL strings for ``selected_rules`` against ``table_name``."""
    ref_variants = _table_ref_variants(table_name, table_schema)
    if all(rule["column"] is not None for rule in selected_rules):
        projections = ", ".join(f"{rule['sql']} AS {quote_sql_ident(rule['column'])}" for rule in selected_rules)
        return {_normalize_sql(f"SELECT {projections} FROM {ref}") for ref in ref_variants}
    if len(selected_rules) == 1 and selected_rules[0]["column"] is None:
        canonical_ref = _format_table_ref(table_name, table_schema)
        base_sql = selected_rules[0]["sql"]
        variants = {base_sql.replace(canonical_ref, ref) for ref in ref_variants}
        return {_normalize_sql(v) for v in variants}
    return None


def evaluate_job_quality_queries(
    *,
    job_artifact,
    job_spec,
    native_queries,
    output_versions_by_alias,
    datasets,
    inventory,
    evaluator,
    record,
    stable_id_fn,
):
    """Bind DocSpec JobResult ``queries`` to ODCS S3a zero-counter checks and qualification obligations."""
    declared_bindings = job_artifact.value.get("qualityQueries") or {}
    if not declared_bindings:
        return [], []

    spec_queries = {item["name"]: item for item in job_spec.get("queries", ()) if isinstance(item, dict) and "name" in item}
    observed_queries = {item["name"]: item for item in (native_queries or ()) if isinstance(item, dict) and "name" in item}

    # Map dataset alias -> output name(s) in jobSpec for table-name resolution
    alias_to_output_names = {}
    for out_name, ds_ref in job_artifact.value.get("outputs", {}).items():
        ds_art = inventory.resolve(ds_ref, job_artifact.namespace, "dataset")
        alias_to_output_names.setdefault(ds_art.alias, []).append(out_name)

    checks = []
    obligations = []
    scope = "DocSpec zero-counter SQL query on exact job output."

    for q_name, binding in sorted(declared_bindings.items()):
        ds_art = inventory.resolve(binding["dataset"], job_artifact.namespace, "dataset")
        ds_alias = ds_art.alias
        if ds_alias not in output_versions_by_alias:
            raise CatalogError(
                "CATALOG-EVIDENCE-SCOPE",
                f"Quality query {q_name!r} targets dataset {ds_alias!r}, which has no materialized version in this job run.",
                status="unknown",
            )
        version = output_versions_by_alias[ds_alias]
        definition = datasets[ds_alias]["definition"]
        rule_version = sha256(json_dumps(ds_art.effective, sort_keys=True).encode("utf-8")).hexdigest()

        if q_name not in spec_queries:
            raise CatalogError(
                "CATALOG-JOB-SPEC-MISMATCH",
                f"Declared quality query {q_name!r} is absent from the pinned DocSpec JobSpec.",
                step="jobs",
            )
        observed = observed_queries.get(q_name)
        out_names = alias_to_output_names.get(ds_alias, [ds_art.effective["name"]])
        default_compiled = compile_odcs_quality_counters(ds_art.effective, out_names[0])
        explicit_matches = [
            rule for rule in default_compiled["rules"]
            if rule["column"] is None and (rule["query"] == q_name or rule["id"] == q_name)
        ]
        compiled = (
            default_compiled
            if explicit_matches
            else compile_odcs_quality_counters(ds_art.effective, out_names[0], query_name=q_name)
        )
        rules_by_id = {rule["id"]: rule for rule in compiled["rules"]}

        requested_rule_ids = binding.get("rules")
        if requested_rule_ids:
            missing = [rid for rid in requested_rule_ids if rid not in rules_by_id]
            if missing:
                raise CatalogError(
                    "CATALOG-QUALITY-COVERAGE",
                    f"Quality query {q_name!r} references unknown ODCS counter rule(s): {missing}.",
                )
            selected_rules = [rules_by_id[rid] for rid in requested_rule_ids]
        elif explicit_matches:
            selected_rules = explicit_matches
        else:
            selected_rules = [
                rule for rule in compiled["rules"]
                if rule["query"] == q_name or rule["id"] == q_name
            ]
            if not selected_rules:
                raise CatalogError(
                    "CATALOG-QUALITY-COVERAGE",
                    f"Quality query {q_name!r} matched no compiled ODCS zero-counter rules on {ds_alias!r}.",
                )

        if len(selected_rules) > 1 and any(rule["column"] is None for rule in selected_rules):
            raise CatalogError(
                "CATALOG-QUALITY-COVERAGE",
                f"Quality query {q_name!r} mixes standalone table/SQL counter rule(s) with multi-rule projections; bind each standalone rule to its own query.",
            )

        expected_sqls = set()
        for out_candidate in out_names:
            candidate_compiled = compile_odcs_quality_counters(
                ds_art.effective,
                out_candidate,
                query_name=None if explicit_matches else q_name,
                table_schema="outputs",
            )
            cand_by_id = {rule["id"]: rule for rule in candidate_compiled["rules"]}
            cand_rules = [cand_by_id[rule["id"]] for rule in selected_rules if rule["id"] in cand_by_id]
            acceptable = _expected_query_sql(cand_rules, out_candidate, table_schema="outputs")
            if acceptable:
                expected_sqls.update(acceptable)
        actual_sql = spec_queries[q_name].get("sql")
        if not isinstance(actual_sql, str) or not expected_sqls or _normalize_sql(actual_sql) not in expected_sqls:
            raise CatalogError(
                "CATALOG-JOB-SPEC-MISMATCH",
                f"DocSpec JobSpec query {q_name!r} SQL does not match compiled ODCS zero-counter SQL for {ds_alias!r}.",
                step="jobs",
            )

        if observed is None or not isinstance(observed.get("data"), list) or len(observed["data"]) != 1:
            for rule in selected_rules:
                identity = {
                    "subject": version,
                    "evaluator": evaluator,
                    "scope": scope,
                    "rule": {
                        "id": stable_id_fn("quality-rule", definition["contractId"], definition["object"], rule["id"]),
                        "version": rule_version,
                    },
                }
                checks.append({
                    **identity,
                    "status": "not_run" if observed is None else "unknown",
                    "reason": f"DocSpec query {q_name!r} did not return a single counter row.",
                })
                obligations.append(identity)
            continue

        row = observed["data"][0]
        if not isinstance(row, dict) or not row:
            raise CatalogError(
                "CATALOG-NATIVE-RECEIPT",
                f"DocSpec quality query {q_name!r} returned an invalid counter row.",
            )

        for rule in selected_rules:
            col_name = rule["column"]
            if col_name is not None:
                if col_name not in row:
                    raise CatalogError(
                        "CATALOG-QUALITY-COVERAGE",
                        f"DocSpec quality query {q_name!r} omitted expected counter column {col_name!r}.",
                    )
                value = row[col_name]
            else:
                if rule["id"] in row:
                    value = row[rule["id"]]
                elif len(row) == 1:
                    value = next(iter(row.values()))
                else:
                    raise CatalogError(
                        "CATALOG-QUALITY-COVERAGE",
                        f"Single-rule SQL query {q_name!r} must return one counter column or column {rule['id']!r}.",
                    )

            identity = {
                "subject": version,
                "evaluator": evaluator,
                "scope": scope,
                "rule": {
                    "id": stable_id_fn("quality-rule", definition["contractId"], definition["object"], rule["id"]),
                    "version": rule_version,
                },
            }
            must_be = rule.get("mustBe", 0)
            if type(value) is not int:
                checks.append({
                    **identity,
                    "status": "unknown",
                    "reason": f"Counter {rule['id']!r} returned non-integer value {value!r}.",
                })
            elif value == must_be:
                checks.append({
                    **identity,
                    "status": "passed",
                    "record": record,
                    "reason": f"Zero-counter SQL rule {rule['id']!r} matched expected count {must_be}.",
                })
            else:
                checks.append({
                    **identity,
                    "status": "failed",
                    "record": record,
                    "reason": f"Zero-counter SQL rule {rule['id']!r} observed {value} violation(s) (expected {must_be}).",
                })
            obligations.append(identity)

    return checks, obligations
