from typing import Iterable, List, Optional, Sequence

from sqlglot import expressions as exp

from data_structures.column import Column
from data_structures.table import Table

from .models import InferredColumnType
from .parser import parse_query
from .schema_context import SchemaContext

_NUMERIC_TYPES = {
    "INT",
    "INTEGER",
    "BIGINT",
    "SMALLINT",
    "TINYINT",
    "MEDIUMINT",
    "DECIMAL",
    "NUMERIC",
    "FLOAT",
    "DOUBLE",
    "REAL",
}
_STRING_TYPES = {"CHAR", "VARCHAR", "TEXT", "TINYTEXT", "MEDIUMTEXT", "LONGTEXT", "ENUM", "SET"}
_DATETIME_TYPES = {"DATE", "TIME", "DATETIME", "TIMESTAMP", "YEAR"}
_BOOLEAN_TYPES = {"BOOLEAN", "BOOL"}
_JSON_TYPES = {"JSON"}
_BINARY_TYPES = {"BINARY", "VARBINARY", "BLOB", "TINYBLOB", "MEDIUMBLOB", "LONGBLOB", "BIT"}


def infer_column_types(
    sql: str,
    tables: Optional[Iterable[Table]] = None,
    dialect: Optional[str] = None,
) -> List[InferredColumnType]:
    """Infer SELECT result column types in output order."""

    query_expr = parse_query(sql, dialect=dialect)
    return _query_types(query_expr, list(tables or []))


def _query_types(query_expr: exp.Expression, tables: Sequence[Table]) -> List[InferredColumnType]:
    if isinstance(query_expr, exp.SetOperation):
        scoped_tables = _tables_with_ctes(query_expr, tables)
        left = _query_types(_unwrap_query(query_expr.this), scoped_tables)
        right = _query_types(_unwrap_query(query_expr.expression), scoped_tables)
        if len(left) != len(right):
            raise ValueError(
                "Set operation branches must return the same number of columns "
                f"({len(left)} != {len(right)})."
            )
        return [_merge_setop_types(left_type, right_type) for left_type, right_type in zip(left, right)]

    if not isinstance(query_expr, exp.Select):
        select_expr = query_expr.find(exp.Select)
        if select_expr is None:
            raise ValueError("DQL metadata inference currently requires a SELECT statement.")
        query_expr = select_expr

    context = SchemaContext(_tables_with_ctes(query_expr, tables)).bind_select(query_expr)
    result: List[InferredColumnType] = []

    for projection in query_expr.expressions or []:
        result.extend(_projection_types(projection, context))

    return result


def _unwrap_query(query_expr: exp.Expression) -> exp.Expression:
    if isinstance(query_expr, exp.Subquery):
        return query_expr.this
    return query_expr


def _merge_setop_types(left: InferredColumnType, right: InferredColumnType) -> InferredColumnType:
    return _merge_mysql_common_types([left, right], source="setop")


def _merge_mysql_common_types(
    inferred_types: Sequence[InferredColumnType],
    source: str,
) -> InferredColumnType:
    types = [item for item in inferred_types if item is not None]
    known = [item for item in types if item.type_family not in {"null", "unknown"}]
    if not known:
        if any(item.type_family == "null" for item in types):
            return InferredColumnType(data_type="NULL", type_family="null", source=source)
        return InferredColumnType(data_type="UNKNOWN", type_family="unknown", source=source)

    families = {item.type_family for item in known}
    if families == {"numeric"}:
        return InferredColumnType(
            data_type=_merge_numeric_types([item.data_type for item in known]),
            type_family="numeric",
            source=source,
        )
    if families == {"datetime"}:
        if not _datetime_types_are_compatible([item.data_type for item in known]):
            return InferredColumnType(data_type="VARCHAR", type_family="string", source=source)
        return InferredColumnType(
            data_type=_merge_datetime_types([item.data_type for item in known]),
            type_family="datetime",
            source=source,
        )
    if families == {"string"}:
        return InferredColumnType(data_type="VARCHAR", type_family="string", source=source)
    if families == {"binary"}:
        return InferredColumnType(data_type="BLOB", type_family="binary", source=source)
    if families == {"json"}:
        return InferredColumnType(data_type="JSON", type_family="json", source=source)
    if families <= {"boolean", "numeric"}:
        return InferredColumnType(data_type="BIGINT", type_family="numeric", source=source)
    if families <= {"datetime", "numeric"} and any(
        item.type_family == "datetime" and _base_type(item.data_type) == "YEAR"
        for item in known
    ):
        return InferredColumnType(data_type="BIGINT", type_family="numeric", source=source)

    # MySQL exposes most mixed scalar results as character data. This is especially
    # visible for UNION and IF/IFNULL/NULLIF with JSON, temporal, or string operands.
    if source == "conditional" and "binary" in families and "string" in families and any(
        item.type_family == "string" and "TEXT" in _base_type(item.data_type)
        for item in known
    ):
        return InferredColumnType(data_type="BLOB", type_family="binary", source=source)
    if source == "conditional" and "binary" in families and "string" in families and any(
        item.type_family == "binary" and _base_type(item.data_type) == "BIT"
        for item in known
    ):
        return InferredColumnType(data_type="BLOB", type_family="binary", source=source)
    if source == "setop" and "binary" in families and "string" in families and any(
        _is_binary_string_type(item)
        for item in known
    ):
        return InferredColumnType(data_type="BLOB", type_family="binary", source=source)
    if "string" in families:
        return InferredColumnType(data_type="VARCHAR", type_family="string", source=source)
    if "datetime" in families:
        return InferredColumnType(data_type="VARCHAR", type_family="string", source=source)
    if "json" in families:
        return InferredColumnType(data_type="VARCHAR", type_family="string", source=source)
    if "binary" in families:
        if "numeric" in families and all(
            item.type_family != "binary" or _base_type(item.data_type) == "BIT"
            for item in known
        ):
            return InferredColumnType(data_type="BIGINT", type_family="numeric", source=source)
        return InferredColumnType(data_type="BLOB", type_family="binary", source=source)

    return InferredColumnType(data_type="UNKNOWN", type_family="unknown", source=source)


def _base_type(type_name: str) -> str:
    return (type_name or "").upper().split("(", 1)[0].strip()


def _merge_numeric_type(left: str, right: str) -> str:
    return _merge_numeric_types([left, right])


def _merge_numeric_types(type_names: Sequence[str]) -> str:
    uppers = [(type_name or "").upper() for type_name in type_names]
    joined = " ".join(uppers)
    if any(token in joined for token in ("DECIMAL", "NUMERIC")):
        return "DECIMAL"
    if any(token in joined for token in ("DOUBLE", "FLOAT", "REAL")):
        return "DOUBLE"
    if any(token in joined for token in ("BIGINT", "LONGLONG")):
        return "BIGINT"
    return "BIGINT"


def _merge_datetime_type(left: str, right: str) -> str:
    return _merge_datetime_types([left, right])


def _merge_datetime_types(type_names: Sequence[str]) -> str:
    normalized = {_base_type(type_name) for type_name in type_names}
    if "DATETIME" in normalized or "TIMESTAMP" in normalized:
        return "DATETIME"
    if "TIME" in normalized and "DATE" not in normalized and "YEAR" not in normalized:
        return "TIME"
    if "YEAR" in normalized and len(normalized) == 1:
        return "YEAR"
    return "DATE"


def _datetime_types_are_compatible(type_names: Sequence[str]) -> bool:
    normalized = {_base_type(type_name) for type_name in type_names}
    if "YEAR" in normalized and len(normalized) > 1:
        return False
    return True


def _tables_with_ctes(select_expr: exp.Select, base_tables: Sequence[Table]) -> List[Table]:
    tables = list(base_tables)
    with_expr = select_expr.args.get("with_") or select_expr.args.get("with")

    if with_expr:
        for cte in with_expr.expressions or []:
            cte_name = cte.alias
            if not cte_name:
                continue
            columns = _query_output_columns(_unwrap_query(cte.this), tables, cte_name)
            if columns:
                tables.append(Table(name=cte_name, columns=columns, primary_key=columns[0].name, foreign_keys=[]))

    if isinstance(select_expr, exp.Select):
        for source in _select_sources(select_expr):
            if not isinstance(source, exp.Subquery):
                continue
            alias = source.alias_or_name
            if not alias:
                continue
            columns = _query_output_columns(_unwrap_query(source.this), tables, alias)
            if columns:
                tables = [table for table in tables if table.name.lower() != alias.lower()]
                tables.append(Table(name=alias, columns=columns, primary_key=columns[0].name, foreign_keys=[]))
    return tables


def _select_sources(select_expr: exp.Select) -> List[exp.Expression]:
    sources: List[exp.Expression] = []
    from_expr = select_expr.args.get("from_")
    if from_expr is not None and from_expr.this is not None:
        sources.append(from_expr.this)
    for join_expr in select_expr.args.get("joins") or []:
        if join_expr.this is not None:
            sources.append(join_expr.this)
    return sources


def _query_output_columns(query_expr: exp.Expression, tables: Sequence[Table], table_name: str) -> List[Column]:
    query_expr = _unwrap_query(query_expr)
    if isinstance(query_expr, exp.SetOperation):
        names = _query_output_names(_unwrap_query(query_expr.this), tables)
        types = _query_types(query_expr, tables)
    else:
        select_expr = query_expr if isinstance(query_expr, exp.Select) else query_expr.find(exp.Select)
        if select_expr is None:
            return []
        scoped_tables = _tables_with_ctes(select_expr, tables)
        context = SchemaContext(scoped_tables).bind_select(select_expr)
        names = []
        types = []
        for projection in select_expr.expressions or []:
            names.extend(_projection_output_names(projection, context))
            types.extend(_projection_types(projection, context))

    columns: List[Column] = []
    for index, inferred in enumerate(types):
        name = names[index] if index < len(names) else f"col_{index + 1}"
        columns.append(
            Column(
                name=name,
                data_type=inferred.data_type,
                category=inferred.type_family,
                is_nullable=True,
                table_name=table_name,
            )
        )
    return columns


def _query_output_names(query_expr: exp.Expression, tables: Sequence[Table]) -> List[str]:
    query_expr = _unwrap_query(query_expr)
    if isinstance(query_expr, exp.SetOperation):
        return _query_output_names(_unwrap_query(query_expr.this), tables)

    select_expr = query_expr if isinstance(query_expr, exp.Select) else query_expr.find(exp.Select)
    if select_expr is None:
        return []

    context = SchemaContext(_tables_with_ctes(select_expr, tables)).bind_select(select_expr)
    names: List[str] = []
    for projection in select_expr.expressions or []:
        names.extend(_projection_output_names(projection, context))
    return names


def _projection_output_names(projection: exp.Expression, context: SchemaContext) -> List[str]:
    if isinstance(projection, exp.Alias):
        return [str(projection.alias)]

    target = projection.this if isinstance(projection, exp.Alias) else projection
    if isinstance(target, exp.Star):
        return [column.name for table in context.visible_tables() for column in table.columns]

    if isinstance(target, exp.Column):
        if target.name == "*":
            return [column.name for table in context.visible_tables() for column in table.columns]
        return [target.name]

    alias = getattr(projection, "alias", None)
    if alias:
        return [str(alias)]

    name = getattr(projection, "name", None)
    if name and name != "*":
        return [str(name)]

    return [projection.sql()]


def _projection_types(projection: exp.Expression, context: SchemaContext) -> List[InferredColumnType]:
    target = projection.this if isinstance(projection, exp.Alias) else projection

    if isinstance(target, exp.Star):
        return _star_types(context)

    if isinstance(target, exp.Column) and target.name == "*":
        return _star_types(context)

    return [_infer_expression_type(target, context)]


def _star_types(context: SchemaContext) -> List[InferredColumnType]:
    types: List[InferredColumnType] = []
    for table in context.visible_tables():
        for column in table.columns:
            types.append(_from_schema_column(column))
    return types or [InferredColumnType(data_type="UNKNOWN", type_family="unknown", source="star")]


def _infer_expression_type(expr: exp.Expression, context: SchemaContext) -> InferredColumnType:
    if isinstance(expr, exp.Column):
        column = context.resolve_column(expr)
        if column:
            return _from_schema_column(column)
        return InferredColumnType(data_type="UNKNOWN", type_family="unknown", source="column")

    if isinstance(expr, exp.Literal):
        if expr.is_string:
            return InferredColumnType(data_type="VARCHAR", type_family="string", source="literal")
        return InferredColumnType(data_type="NUMERIC", type_family="numeric", source="literal")

    if isinstance(expr, exp.HexString):
        return InferredColumnType(data_type="BLOB", type_family="binary", source="literal")

    if isinstance(expr, exp.Null):
        return InferredColumnType(data_type="NULL", type_family="null", source="literal")

    if isinstance(expr, exp.Boolean):
        return InferredColumnType(data_type="BOOLEAN", type_family="boolean", source="literal")

    if isinstance(expr, exp.Cast):
        type_name = _datatype_name(expr.args.get("to"))
        return InferredColumnType(
            data_type=type_name,
            type_family=_type_family(type_name),
            source="cast",
        )

    if isinstance(expr, exp.Interval):
        return InferredColumnType(data_type="INTERVAL", type_family="interval", source="literal")

    if isinstance(expr, (exp.Add, exp.Sub)):
        left = _infer_expression_type(expr.this, context)
        right = _infer_expression_type(expr.expression, context)
        families = {left.type_family, right.type_family}
        if "datetime" in families and "interval" in families:
            datetime_operand = left if left.type_family == "datetime" else right
            if _base_type(datetime_operand.data_type) == "YEAR":
                return InferredColumnType(data_type="VARCHAR", type_family="string", source="datetime_arithmetic")
            return InferredColumnType(data_type="DATETIME", type_family="datetime", source="datetime_arithmetic")
        if "string" in families and "interval" in families:
            return InferredColumnType(data_type="VARCHAR", type_family="string", source="datetime_arithmetic")
        return InferredColumnType(data_type="NUMERIC", type_family="numeric", source="arithmetic")

    if isinstance(expr, (exp.Mul, exp.Div, exp.Mod, exp.Neg, exp.IntDiv)):
        return InferredColumnType(data_type="NUMERIC", type_family="numeric", source="arithmetic")

    if isinstance(expr, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.And, exp.Or, exp.Not)):
        return InferredColumnType(data_type="BOOLEAN", type_family="boolean", source="predicate")

    if isinstance(expr, exp.Case):
        branch_types: List[InferredColumnType] = []
        for item in expr.args.get("ifs") or []:
            value = item.args.get("true")
            if isinstance(value, exp.Expression):
                branch_types.append(_infer_expression_type(value, context))
        default = expr.args.get("default")
        if isinstance(default, exp.Expression):
            branch_types.append(_infer_expression_type(default, context))
        if branch_types:
            return _merge_mysql_common_types(branch_types, source="conditional")
        return InferredColumnType(data_type="UNKNOWN", type_family="unknown", source="case")

    if isinstance(expr, exp.If):
        return _merge_mysql_common_types(
            [
                _infer_expression_type(expr.args.get("true"), context),
                _infer_expression_type(expr.args.get("false"), context),
            ],
            source="conditional",
        )

    if isinstance(expr, exp.Nullif):
        first_arg_type = _infer_expression_type(expr.this, context)
        return InferredColumnType(
            data_type=first_arg_type.data_type,
            type_family=first_arg_type.type_family,
            source="conditional",
        )

    if isinstance(expr, exp.Coalesce):
        return _merge_mysql_common_types(
            [_infer_expression_type(child, context) for child in [expr.this, *(expr.expressions or [])]],
            source="conditional",
        )

    if isinstance(expr, exp.Distinct):
        expressions = expr.expressions or []
        if expressions:
            return _infer_expression_type(expressions[0], context)
        return InferredColumnType(data_type="UNKNOWN", type_family="unknown", source="distinct")

    if isinstance(expr, exp.Subquery):
        subquery_types = _query_types(_unwrap_query(expr.this), list(context.tables.values()))
        if subquery_types:
            inferred = subquery_types[0]
            return InferredColumnType(
                data_type=inferred.data_type,
                type_family=inferred.type_family,
                source="subquery",
            )
        return InferredColumnType(data_type="UNKNOWN", type_family="unknown", source="subquery")

    if isinstance(expr, exp.Exists):
        return InferredColumnType(data_type="BOOLEAN", type_family="boolean", source="predicate")

    if isinstance(expr, exp.JSONValue):
        return InferredColumnType(data_type="VARCHAR", type_family="string", source="function")

    if isinstance(expr, exp.Count):
        return InferredColumnType(data_type="BIGINT", type_family="numeric", source="aggregate")

    if isinstance(expr, exp.AggFunc):
        return _aggregate_type(expr, context)

    if isinstance(expr, exp.Anonymous):
        return _function_type(str(expr.this or ""), expr, context)

    if isinstance(expr, exp.Func):
        return _function_type(expr.sql_name(), expr, context)

    return InferredColumnType(data_type="UNKNOWN", type_family="unknown", source=expr.__class__.__name__)


def _aggregate_type(expr: exp.Expression, context: SchemaContext) -> InferredColumnType:
    name = expr.__class__.__name__.upper()
    sql_name = expr.sql_name().upper() if hasattr(expr, "sql_name") else ""
    if name in {"GROUPCONCAT"} or sql_name in {"GROUP_CONCAT"}:
        args = _group_concat_value_args(expr)
        if any(_infer_expression_type(arg, context).type_family == "binary" for arg in args):
            return InferredColumnType(data_type="BLOB", type_family="binary", source="aggregate")
        return InferredColumnType(data_type="VARCHAR", type_family="string", source="aggregate")
    if name in {"JSONOBJECTAGG"} or sql_name in {"J_S_O_N_OBJECT_AGG", "JSON_OBJECTAGG"}:
        return InferredColumnType(data_type="JSON", type_family="json", source="aggregate")
    if name in {"BITWISEANDAGG", "BITWISEORAGG", "BITWISEXORAGG"} or sql_name in {
        "BITWISE_AND_AGG",
        "BITWISE_OR_AGG",
        "BITWISE_XOR_AGG",
        "BIT_AND",
        "BIT_OR",
        "BIT_XOR",
    }:
        return InferredColumnType(data_type="BIGINT", type_family="numeric", source="aggregate")
    if name in {"SUM", "AVG", "STD", "STDDEV", "STDDEVPOP", "STDDEVSAMP", "VARIANCE", "VARSAMP", "VARPOP"} or sql_name in {
        "SUM",
        "AVG",
        "STD",
        "STDDEV",
        "STDDEV_POP",
        "STDDEV_SAMP",
        "VARIANCE",
        "VAR_SAMP",
        "VAR_POP",
    }:
        return InferredColumnType(data_type="NUMERIC", type_family="numeric", source="aggregate")
    if name in {"MIN", "MAX"}:
        arg = expr.args.get("this")
        if isinstance(arg, exp.Expression):
            return _infer_expression_type(arg, context)
    return InferredColumnType(data_type="NUMERIC", type_family="numeric", source="aggregate")


def _group_concat_value_args(expr: exp.Expression) -> List[exp.Expression]:
    """Return GROUP_CONCAT value expressions, excluding ORDER BY and SEPARATOR."""

    def unwrap(node: Optional[exp.Expression]) -> List[exp.Expression]:
        if node is None:
            return []
        if isinstance(node, exp.Order):
            return unwrap(node.this)
        if isinstance(node, exp.Distinct):
            return [child for child in node.expressions if isinstance(child, exp.Expression)]
        if isinstance(node, exp.Concat):
            return [child for child in node.expressions if isinstance(child, exp.Expression)]
        if isinstance(node, exp.Paren):
            return unwrap(node.this)
        return [node]

    args = unwrap(expr.this)
    args.extend(child for child in expr.expressions if isinstance(child, exp.Expression))
    return args


def _function_value_args(expr: exp.Expression) -> List[exp.Expression]:
    args: List[exp.Expression] = []
    seen = set()

    def add(node: Optional[exp.Expression]) -> None:
        if not isinstance(node, exp.Expression):
            return
        marker = id(node)
        if marker in seen:
            return
        seen.add(marker)
        args.append(node)

    add(expr.this if isinstance(expr.this, exp.Expression) else None)
    add(expr.expression if isinstance(expr.expression, exp.Expression) else None)
    for child in expr.expressions or []:
        add(child)
    return args


def _binary_preserving_string_type(
    expr: exp.Expression,
    context: SchemaContext,
) -> InferredColumnType:
    if any(_is_binary_string_type(_infer_expression_type(arg, context)) for arg in _function_value_args(expr)):
        return InferredColumnType(data_type="BLOB", type_family="binary", source="function")
    return InferredColumnType(data_type="VARCHAR", type_family="string", source="function")


def _is_binary_string_type(inferred_type: InferredColumnType) -> bool:
    return inferred_type.type_family == "binary"


def _merge_expression_types(
    left: InferredColumnType,
    right: InferredColumnType,
    source: str,
) -> InferredColumnType:
    return _merge_mysql_common_types([left, right], source=source)


def _date_function_type(
    normalized: str,
    expr: exp.Expression,
    context: SchemaContext,
) -> Optional[InferredColumnType]:
    if normalized == "YEAR":
        # Infer the logical SELECT expression result, not MySQL cursor metadata quirks.
        return InferredColumnType(data_type="BIGINT", type_family="numeric", source="function")

    if normalized in {"MONTH", "DAY", "DAYOFMONTH", "DAYOFWEEK", "DAYOFYEAR", "HOUR", "MINUTE", "SECOND"}:
        return InferredColumnType(data_type="BIGINT", type_family="numeric", source="function")

    if normalized in {"DATEDIFF", "TIMESTAMPDIFF"}:
        return InferredColumnType(data_type="BIGINT", type_family="numeric", source="function")

    if normalized in {"DATEFORMAT", "DAYNAME"}:
        return InferredColumnType(data_type="VARCHAR", type_family="string", source="function")

    if normalized in {"STRTODATE", "STRDATE"}:
        return InferredColumnType(data_type="DATETIME", type_family="datetime", source="function")

    if normalized == "DATE":
        return InferredColumnType(data_type="DATE", type_family="datetime", source="function")

    if normalized in {"TIME", "TIMEDIFF"}:
        return InferredColumnType(data_type="TIME", type_family="datetime", source="function")

    if normalized in {"DATEADD", "DATESUB", "ADDDATE", "SUBDATE"}:
        first_arg = expr.this if isinstance(expr.this, exp.Expression) else None
        if first_arg is None and expr.expressions:
            first_arg = expr.expressions[0]
        if isinstance(first_arg, exp.Expression):
            first_type = _infer_expression_type(first_arg, context)
            base = _base_type(first_type.data_type)
            if first_type.type_family in {"string", "unknown"} or base == "YEAR":
                return InferredColumnType(data_type="VARCHAR", type_family="string", source="function")
            if base == "DATE":
                return InferredColumnType(data_type="DATE", type_family="datetime", source="function")
            if base in {"DATETIME", "TIMESTAMP"}:
                return InferredColumnType(data_type="DATETIME", type_family="datetime", source="function")
            if base == "TIME":
                return InferredColumnType(data_type="TIME", type_family="datetime", source="function")
        return InferredColumnType(data_type="DATETIME", type_family="datetime", source="function")

    return None


def _function_type(name: str, expr: exp.Expression, context: SchemaContext) -> InferredColumnType:
    upper = name.upper()
    normalized = upper.replace("_", "")
    date_type = _date_function_type(normalized, expr, context)
    if date_type is not None:
        return date_type
    if normalized in {
        "CONCAT",
        "CONCATWS",
        "SUBSTR",
        "SUBSTRING",
        "SUBSTRINGINDEX",
        "LEFT",
        "RIGHT",
        "TRIM",
        "LTRIM",
        "RTRIM",
        "LOWER",
        "UPPER",
        "REPLACE",
        "REPEAT",
        "REVERSE",
    }:
        return _binary_preserving_string_type(expr, context)
    if normalized in {
        "UUID",
        "MD5",
        "SHA1",
        "SHA2",
        "SHA",
        "DAYNAME",
        "DATEFORMAT",
        "TIMETOSTR",
        "DATABASE",
        "SCHEMA",
        "CURRENTSCHEMA",
        "VERSION",
    }:
        return InferredColumnType(data_type="VARCHAR", type_family="string", source="function")
    if normalized in {
        "NOW",
        "CURRENTTIMESTAMP",
        "CURRENTDATE",
        "TSORDSTODATE",
        "STRDATE",
        "STRTODATE",
    }:
        return InferredColumnType(data_type="DATETIME", type_family="datetime", source="function")
    if normalized in {
        "JSONOBJECT",
        "JSONARRAY",
        "JSONEXTRACT",
        "JSONSET",
        "JSONINSERT",
        "JSONREPLACE",
        "JSONREMOVE",
        "JSONARRAYAGG",
        "JSONOBJECTAGG",
    }:
        return InferredColumnType(data_type="JSON", type_family="json", source="function")
    if normalized in {"JSONVALUE"}:
        return InferredColumnType(data_type="VARCHAR", type_family="string", source="function")
    if normalized in {
        "RAND",
        "ABS",
        "ROUND",
        "FLOOR",
        "CEIL",
        "CEILING",
        "DEGREES",
        "MOD",
        "DIV",
        "POWER",
        "SQRT",
        "LOG",
        "LOG10",
        "LN",
        "EXP",
        "PI",
        "SIN",
        "COS",
        "TAN",
        "ASIN",
        "ACOS",
        "ATAN",
        "ATAN2",
        "MONTH",
        "DAY",
        "DAYOFMONTH",
        "DAYOFWEEK",
        "DAYOFYEAR",
        "HOUR",
        "MINUTE",
        "SECOND",
        "DATEDIFF",
        "TIMESTAMPDIFF",
        "LENGTH",
        "CHARLENGTH",
        "STD",
        "STDDEV",
        "STDDEVPOP",
        "STDDEVSAMP",
        "VARIANCE",
        "VARSAMP",
        "ROWNUMBER",
        "RANK",
        "DENSERANK",
        "NTILE",
        "CUMEDIST",
        "PERCENTRANK",
        "BITAND",
        "BITOR",
        "BITXOR",
        "BITWISEANDAGG",
        "BITWISEORAGG",
        "BITWISEXORAGG",
    }:
        return InferredColumnType(data_type="NUMERIC", type_family="numeric", source="function")
    if normalized in {"COALESCE", "IFNULL"}:
        return _merge_mysql_common_types(
            [_infer_expression_type(child, context) for child in [expr.this, *(expr.expressions or [])]],
            source="conditional",
        )
    return InferredColumnType(data_type="UNKNOWN", type_family="unknown", source="function")


def _from_schema_column(column: Column) -> InferredColumnType:
    return InferredColumnType(
        data_type=column.data_type,
        type_family=column.category or _type_family(column.data_type),
        source=f"{column.table_name}.{column.name}",
    )


def _datatype_name(data_type_expr: Optional[exp.Expression]) -> str:
    if data_type_expr is None:
        return "UNKNOWN"
    try:
        return data_type_expr.sql().upper()
    except Exception:
        return str(data_type_expr).upper()


def _type_family(type_name: str) -> str:
    upper = (type_name or "").upper()
    base = upper.split("(", 1)[0].strip()
    if base in _NUMERIC_TYPES:
        return "numeric"
    if base in _STRING_TYPES:
        return "string"
    if base in _DATETIME_TYPES:
        return "datetime"
    if base in _BOOLEAN_TYPES:
        return "boolean"
    if base in _JSON_TYPES:
        return "json"
    if base in _BINARY_TYPES:
        return "binary"
    if base == "NULL":
        return "null"
    return "unknown"
