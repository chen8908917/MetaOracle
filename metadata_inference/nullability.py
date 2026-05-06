import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from sqlglot import expressions as exp

from data_structures.column import Column
from data_structures.table import Table

from .column_names import infer_column_names
from .models import InferredColumnNullability
from .parser import parse_query
from .schema_context import SchemaContext


ColumnKey = Tuple[str, str]

_SAFE_NON_NULL_ON_NON_NULL_ARGS = {
    "ABS",
    "ATAN",
    "ATAN2",
    "CEIL",
    "CEILING",
    "CHARLENGTH",
    "CONCAT",
    "CONCATWS",
    "COS",
    "DEGREES",
    "EXP",
    "FLOOR",
    "LEFT",
    "LENGTH",
    "LOWER",
    "LTRIM",
    "RANDOM",
    "REPEAT",
    "REPLACE",
    "REVERSE",
    "RIGHT",
    "ROUND",
    "RTRIM",
    "SHA",
    "SHA1",
    "SIN",
    "SUBSTR",
    "SUBSTRING",
    "SUBSTRINGINDEX",
    "TAN",
    "TRIM",
    "UPPER",
}

_NON_NULL_ZERO_ARG_FUNCTIONS = {
    "PI",
    "UUID",
}

_TEMPORAL_PRIMARY_ARG_FUNCTIONS = {
    "DATE",
    "DATEFORMAT",
    "DAY",
    "DAYNAME",
    "DAYOFMONTH",
    "DAYOFWEEK",
    "DAYOFYEAR",
    "HOUR",
    "MINUTE",
    "MONTH",
    "SECOND",
    "TIME",
    "YEAR",
}

_TEMPORAL_ALL_ARG_FUNCTIONS = {
    "DATEDIFF",
    "TIMEDIFF",
}

_SHA2_VALID_LENGTHS = {"0", "224", "256", "384", "512"}
_TEMPORAL_BASE_TYPES = {"DATE", "TIME", "DATETIME", "TIMESTAMP"}
_DATE_LITERAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_LITERAL_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
_DATETIME_LITERAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$")
_TEMPORAL_DATE_KINDS = {"date", "datetime"}
_TEMPORAL_TIME_KINDS = {"time", "datetime"}
_SAFE_TEMPORAL_KINDS = {"date", "time", "datetime"}


def infer_column_nullability(
    sql: str,
    tables: Optional[Iterable[Table]] = None,
    dialect: Optional[str] = None,
    non_empty_tables: Optional[Iterable[str]] = None,
    assume_tables_non_empty: bool = False,
) -> List[InferredColumnNullability]:
    """Infer whether SELECT result columns may contain NULL values."""

    table_list = list(tables or [])
    known_non_empty = _known_non_empty_tables(
        table_list,
        non_empty_tables=non_empty_tables,
        assume_tables_non_empty=assume_tables_non_empty,
    )
    query_expr = parse_query(sql, dialect=dialect)
    return _query_nullability(
        query_expr,
        table_list,
        dialect=dialect,
        non_empty_tables=known_non_empty,
    )


def _known_non_empty_tables(
    tables: Sequence[Table],
    non_empty_tables: Optional[Iterable[str]],
    assume_tables_non_empty: bool,
) -> Set[str]:
    if assume_tables_non_empty:
        return {table.name.lower() for table in tables}
    return {table_name.lower() for table_name in (non_empty_tables or [])}


def _query_nullability(
    query_expr: exp.Expression,
    tables: Sequence[Table],
    dialect: Optional[str] = None,
    non_empty_tables: Optional[Set[str]] = None,
) -> List[InferredColumnNullability]:
    non_empty_tables = set(non_empty_tables or set())
    if isinstance(query_expr, exp.SetOperation):
        scoped_tables, scoped_non_empty = _tables_with_query_sources(
            query_expr,
            tables,
            dialect=dialect,
            non_empty_tables=non_empty_tables,
        )
        left = _query_nullability(
            _unwrap_query(query_expr.this),
            scoped_tables,
            dialect=dialect,
            non_empty_tables=scoped_non_empty,
        )
        right = _query_nullability(
            _unwrap_query(query_expr.expression),
            scoped_tables,
            dialect=dialect,
            non_empty_tables=scoped_non_empty,
        )
        if len(left) != len(right):
            raise ValueError(
                "Set operation branches must return the same number of columns "
                f"({len(left)} != {len(right)})."
            )
        return [
            InferredColumnNullability(
                is_nullable=left_item.is_nullable or right_item.is_nullable,
                source="setop",
            )
            for left_item, right_item in zip(left, right)
        ]

    if not isinstance(query_expr, exp.Select):
        select_expr = query_expr.find(exp.Select)
        if select_expr is None:
            raise ValueError("DQL metadata inference currently requires a SELECT statement.")
        query_expr = select_expr

    scoped_tables, scoped_non_empty = _tables_with_query_sources(
        query_expr,
        tables,
        dialect=dialect,
        non_empty_tables=non_empty_tables,
    )
    context = SchemaContext(scoped_tables).bind_select(query_expr)
    context.non_empty_tables = scoped_non_empty
    nullable_sources = _outer_join_nullable_sources(query_expr)
    where_not_null = _where_not_null_columns(query_expr, context)
    result: List[InferredColumnNullability] = []

    for projection in query_expr.expressions or []:
        result.extend(
            _projection_nullability(
                projection,
                context,
                nullable_sources=nullable_sources,
                where_not_null=where_not_null,
            )
        )

    return result


def _unwrap_query(query_expr: exp.Expression) -> exp.Expression:
    if isinstance(query_expr, exp.Subquery):
        return query_expr.this
    return query_expr


def _tables_with_query_sources(
    query_expr: exp.Expression,
    base_tables: Sequence[Table],
    dialect: Optional[str] = None,
    non_empty_tables: Optional[Set[str]] = None,
) -> Tuple[List[Table], Set[str]]:
    tables = list(base_tables)
    known_non_empty = set(non_empty_tables or set())
    with_expr = query_expr.args.get("with_") or query_expr.args.get("with")
    if with_expr:
        for cte in with_expr.expressions or []:
            cte_name = cte.alias
            cte_select = cte.this if isinstance(cte.this, exp.Select) else cte.this.find(exp.Select)
            if not cte_name or cte_select is None:
                continue

            names = infer_column_names(cte_select.sql(dialect=dialect), tables=tables, dialect=dialect)
            nullability = _query_nullability(
                cte_select,
                tables,
                dialect=dialect,
                non_empty_tables=known_non_empty,
            )
            if names and len(names) == len(nullability):
                tables.append(
                    Table(
                        name=cte_name,
                        columns=[
                            Column(name, "UNKNOWN", "unknown", item.is_nullable, cte_name)
                            for name, item in zip(names, nullability)
                        ],
                        primary_key=names[0],
                        foreign_keys=[],
                    )
                )
                if _query_guarantees_at_least_one_row(cte_select, known_non_empty):
                    known_non_empty.add(cte_name.lower())

    if isinstance(query_expr, exp.Select):
        from_expr = query_expr.args.get("from_")
        if from_expr is not None:
            _append_derived_table(
                tables,
                known_non_empty,
                from_expr.this,
                dialect=dialect,
            )
        for join_expr in query_expr.args.get("joins") or []:
            _append_derived_table(
                tables,
                known_non_empty,
                join_expr.this,
                dialect=dialect,
            )

    return tables, known_non_empty


def _append_derived_table(
    tables: List[Table],
    non_empty_tables: Set[str],
    source: Optional[exp.Expression],
    dialect: Optional[str] = None,
) -> None:
    if not isinstance(source, exp.Subquery):
        return

    alias = source.alias_or_name
    if not alias:
        return

    query_expr = _unwrap_query(source.this)
    names = _subquery_output_names(source, query_expr, tables, dialect=dialect)
    nullability = _query_nullability(
        query_expr,
        tables,
        dialect=dialect,
        non_empty_tables=non_empty_tables,
    )
    if not names or len(names) != len(nullability):
        return

    tables.append(
        Table(
            name=alias,
            columns=[
                Column(name, "UNKNOWN", "unknown", item.is_nullable, alias)
                for name, item in zip(names, nullability)
            ],
            primary_key=names[0],
            foreign_keys=[],
        )
    )
    if _query_guarantees_at_least_one_row(query_expr, non_empty_tables):
        non_empty_tables.add(alias.lower())


def _subquery_output_names(
    source: exp.Subquery,
    query_expr: exp.Expression,
    tables: Sequence[Table],
    dialect: Optional[str] = None,
) -> List[str]:
    alias_expr = source.args.get("alias")
    alias_columns = getattr(alias_expr, "columns", None) or []
    if alias_columns:
        return [str(column.name) for column in alias_columns]
    return infer_column_names(query_expr.sql(dialect=dialect), tables=tables, dialect=dialect)


def _projection_nullability(
    projection: exp.Expression,
    context: SchemaContext,
    nullable_sources: Set[str],
    where_not_null: Set[ColumnKey],
) -> List[InferredColumnNullability]:
    if isinstance(projection, exp.Alias):
        return [
            _expression_nullability(
                projection.this,
                context,
                nullable_sources=nullable_sources,
                where_not_null=where_not_null,
            )
        ]

    if isinstance(projection, exp.Star):
        return _star_nullability(context, nullable_sources)

    if isinstance(projection, exp.Column) and projection.name == "*":
        return _star_nullability(context, nullable_sources)

    return [
        _expression_nullability(
            projection,
            context,
            nullable_sources=nullable_sources,
            where_not_null=where_not_null,
        )
    ]


def _expression_nullability(
    expr: Optional[exp.Expression],
    context: SchemaContext,
    nullable_sources: Set[str],
    where_not_null: Set[ColumnKey],
) -> InferredColumnNullability:
    if expr is None:
        return InferredColumnNullability(is_nullable=True, source="unknown")

    if isinstance(expr, exp.Alias):
        return _expression_nullability(expr.this, context, nullable_sources, where_not_null)

    if isinstance(expr, exp.Paren):
        return _expression_nullability(expr.this, context, nullable_sources, where_not_null)

    if isinstance(expr, exp.Null):
        return InferredColumnNullability(is_nullable=True, source="literal_null")

    if isinstance(expr, exp.Literal):
        return InferredColumnNullability(is_nullable=False, source="literal")

    if isinstance(expr, exp.Column):
        return _column_nullability(expr, context, nullable_sources, where_not_null)

    if isinstance(expr, exp.Subquery):
        return _scalar_subquery_nullability(expr, context)

    if isinstance(expr, exp.JSONValue):
        return _function_nullability("JSON_VALUE", expr, context, nullable_sources, where_not_null)

    if isinstance(expr, exp.Count):
        return InferredColumnNullability(is_nullable=False, source="aggregate")

    if isinstance(expr, exp.Nullif):
        return InferredColumnNullability(is_nullable=True, source="nullif")

    if isinstance(expr, exp.Coalesce):
        items = [expr.this, *(expr.expressions or [])]
        child_nullability = [
            _expression_nullability(item, context, nullable_sources, where_not_null)
            for item in items
            if isinstance(item, exp.Expression)
        ]
        if any(not item.is_nullable for item in child_nullability):
            return InferredColumnNullability(is_nullable=False, source="coalesce")
        return InferredColumnNullability(is_nullable=True, source="coalesce")

    if isinstance(expr, exp.If):
        true_item = _expression_nullability(
            expr.args.get("true"), context, nullable_sources, where_not_null
        )
        false_item = _expression_nullability(
            expr.args.get("false"), context, nullable_sources, where_not_null
        )
        return InferredColumnNullability(
            is_nullable=true_item.is_nullable or false_item.is_nullable,
            source="conditional",
        )

    if isinstance(expr, exp.Case):
        branch_items: List[InferredColumnNullability] = []
        for item in expr.args.get("ifs") or []:
            value = item.args.get("true")
            if isinstance(value, exp.Expression):
                branch_items.append(
                    _expression_nullability(value, context, nullable_sources, where_not_null)
                )
        default = expr.args.get("default")
        if isinstance(default, exp.Expression):
            branch_items.append(
                _expression_nullability(default, context, nullable_sources, where_not_null)
            )
        else:
            return InferredColumnNullability(is_nullable=True, source="case")
        if branch_items and all(not item.is_nullable for item in branch_items):
            return InferredColumnNullability(is_nullable=False, source="case")
        return InferredColumnNullability(is_nullable=True, source="case")

    if isinstance(expr, (exp.Div, exp.Mod, exp.IntDiv)):
        children = _expression_children(expr)
        if (
            len(children) >= 2
            and all(
                not _expression_nullability(child, context, nullable_sources, where_not_null).is_nullable
                for child in children[:2]
            )
            and _is_guaranteed_non_zero(children[1], context)
        ):
            return InferredColumnNullability(is_nullable=False, source="arithmetic")
        return InferredColumnNullability(is_nullable=True, source="arithmetic")

    if isinstance(expr, (exp.Add, exp.Sub, exp.Mul, exp.Neg)):
        children = _expression_children(expr)
        if children and all(
            not _expression_nullability(child, context, nullable_sources, where_not_null).is_nullable
            for child in children
        ):
            return InferredColumnNullability(is_nullable=False, source="arithmetic")
        return InferredColumnNullability(is_nullable=True, source="arithmetic")

    if isinstance(expr, exp.Anonymous):
        return _function_nullability(
            str(expr.this or ""),
            expr,
            context,
            nullable_sources,
            where_not_null,
        )

    if isinstance(expr, exp.Func):
        return _function_nullability(
            expr.sql_name(),
            expr,
            context,
            nullable_sources,
            where_not_null,
        )

    # Most functions and complex expressions are conservative until explicitly modeled.
    return InferredColumnNullability(is_nullable=True, source="expression")


def _scalar_subquery_nullability(
    expr: exp.Subquery,
    context: SchemaContext,
) -> InferredColumnNullability:
    query_expr = _unwrap_query(expr.this)
    non_empty_tables = set(getattr(context, "non_empty_tables", set()))
    if not _scalar_subquery_source_guarantees_non_empty(query_expr, non_empty_tables):
        return InferredColumnNullability(is_nullable=True, source="scalar_subquery")

    inner_nullability = _query_nullability(
        query_expr,
        list(context.tables.values()),
        non_empty_tables=non_empty_tables,
    )
    if not inner_nullability:
        return InferredColumnNullability(is_nullable=True, source="scalar_subquery")
    return InferredColumnNullability(
        is_nullable=inner_nullability[0].is_nullable,
        source="scalar_subquery",
    )


def _scalar_subquery_source_guarantees_non_empty(
    query_expr: exp.Expression,
    non_empty_tables: Set[str],
) -> bool:
    if not isinstance(query_expr, exp.Select):
        return False

    if query_expr.args.get("having") is not None:
        return False
    if query_expr.args.get("group") is not None:
        return False
    if query_expr.args.get("where") is not None:
        return False
    if query_expr.args.get("joins"):
        return False

    limit_expr = query_expr.args.get("limit")
    if _is_zero_limit(limit_expr):
        return False

    from_expr = query_expr.args.get("from_")
    if from_expr is None:
        return False

    return _source_guarantees_non_empty(from_expr.this, non_empty_tables)


def _query_guarantees_at_least_one_row(
    query_expr: exp.Expression,
    non_empty_tables: Set[str],
) -> bool:
    if not isinstance(query_expr, exp.Select):
        return False
    if query_expr.args.get("having") is not None:
        return False
    if query_expr.args.get("group") is not None:
        return False

    limit_expr = query_expr.args.get("limit")
    if _is_zero_limit(limit_expr):
        return False

    if (
        query_expr.args.get("from_") is None
        and not query_expr.args.get("joins")
        and query_expr.args.get("where") is None
    ):
        return True

    if any(_contains_aggregate(projection) for projection in query_expr.expressions or []):
        return True

    from_expr = query_expr.args.get("from_")
    return (
        from_expr is not None
        and not query_expr.args.get("joins")
        and query_expr.args.get("where") is None
        and _source_guarantees_non_empty(from_expr.this, non_empty_tables)
    )


def _function_nullability(
    name: str,
    expr: exp.Expression,
    context: SchemaContext,
    nullable_sources: Set[str],
    where_not_null: Set[ColumnKey],
) -> InferredColumnNullability:
    normalized = (name or "").upper().replace("_", "")
    args = _function_args(expr)

    if normalized in _NON_NULL_ZERO_ARG_FUNCTIONS and not args:
        return InferredColumnNullability(is_nullable=False, source="function")

    if normalized == "TSORDSTODATE":
        if len(args) != 1:
            return InferredColumnNullability(is_nullable=True, source="function")
        if _all_args_non_nullable(args, context, nullable_sources, where_not_null) and _is_temporal_expression(
            args[0], context
        ):
            return InferredColumnNullability(is_nullable=False, source="function")
        return InferredColumnNullability(is_nullable=True, source="function")

    if normalized in _SAFE_NON_NULL_ON_NON_NULL_ARGS:
        if _all_args_non_nullable(args, context, nullable_sources, where_not_null):
            return InferredColumnNullability(is_nullable=False, source="function")
        return InferredColumnNullability(is_nullable=True, source="function")

    if normalized == "SHA2":
        if len(args) != 2:
            return InferredColumnNullability(is_nullable=True, source="function")
        if not _all_args_non_nullable(args, context, nullable_sources, where_not_null):
            return InferredColumnNullability(is_nullable=True, source="function")
        if _is_safe_sha2_length(args[1]):
            return InferredColumnNullability(is_nullable=False, source="function")
        return InferredColumnNullability(is_nullable=True, source="function")

    if normalized in _TEMPORAL_PRIMARY_ARG_FUNCTIONS:
        if not args:
            return InferredColumnNullability(is_nullable=True, source="function")
        if not _all_args_non_nullable(args, context, nullable_sources, where_not_null):
            return InferredColumnNullability(is_nullable=True, source="function")
        if _is_temporal_expression(args[0], context):
            return InferredColumnNullability(is_nullable=False, source="function")
        return InferredColumnNullability(is_nullable=True, source="function")

    if normalized == "DATEDIFF":
        if not _all_args_non_nullable(args, context, nullable_sources, where_not_null):
            return InferredColumnNullability(is_nullable=True, source="function")
        if _datediff_args_compatible(args, context):
            return InferredColumnNullability(is_nullable=False, source="function")
        return InferredColumnNullability(is_nullable=True, source="function")

    if normalized == "TIMEDIFF":
        if not _all_args_non_nullable(args, context, nullable_sources, where_not_null):
            return InferredColumnNullability(is_nullable=True, source="function")
        if _timediff_args_compatible(args, context):
            return InferredColumnNullability(is_nullable=False, source="function")
        return InferredColumnNullability(is_nullable=True, source="function")

    if normalized == "TIMESTAMPDIFF":
        if len(args) != 3:
            return InferredColumnNullability(is_nullable=True, source="function")
        left_expr = expr.args.get("expression")
        right_expr = expr.args.get("this")
        if not isinstance(left_expr, exp.Expression) or not isinstance(right_expr, exp.Expression):
            return InferredColumnNullability(is_nullable=True, source="function")
        if _expression_nullability(left_expr, context, nullable_sources, where_not_null).is_nullable:
            return InferredColumnNullability(is_nullable=True, source="function")
        if _expression_nullability(right_expr, context, nullable_sources, where_not_null).is_nullable:
            return InferredColumnNullability(is_nullable=True, source="function")
        if _timestampdiff_args_compatible(expr, context):
            return InferredColumnNullability(is_nullable=False, source="function")
        return InferredColumnNullability(is_nullable=True, source="function")

    return InferredColumnNullability(is_nullable=True, source="expression")


def _function_args(expr: exp.Expression) -> List[exp.Expression]:
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

    for value in expr.args.values():
        if isinstance(value, exp.Expression):
            add(value)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, exp.Expression):
                    add(child)
    return args


def _all_args_non_nullable(
    args: Sequence[exp.Expression],
    context: SchemaContext,
    nullable_sources: Set[str],
    where_not_null: Set[ColumnKey],
) -> bool:
    return bool(args) and all(
        not _expression_nullability(arg, context, nullable_sources, where_not_null).is_nullable
        for arg in args
    )


def _is_safe_sha2_length(expr: exp.Expression) -> bool:
    if not isinstance(expr, exp.Literal) or expr.is_string:
        return False
    return str(expr.this) in _SHA2_VALID_LENGTHS


def _is_temporal_expression(
    expr: exp.Expression,
    context: SchemaContext,
) -> bool:
    return _temporal_kind(expr, context) in _SAFE_TEMPORAL_KINDS


def _temporal_kind(
    expr: exp.Expression,
    context: SchemaContext,
) -> Optional[str]:
    if isinstance(expr, exp.Paren):
        return _temporal_kind(expr.this, context)

    if isinstance(expr, exp.Column):
        column = context.resolve_column(expr)
        return _temporal_kind_from_type_name(column.data_type) if column is not None else None

    if isinstance(expr, exp.Cast):
        type_expr = expr.args.get("to")
        return _temporal_kind_from_type_name(type_expr.sql()) if type_expr is not None else None

    if isinstance(expr, exp.Literal) and expr.is_string:
        literal = str(expr.this)
        if _DATETIME_LITERAL_RE.match(literal):
            return "datetime"
        if _DATE_LITERAL_RE.match(literal):
            return "date"
        if _TIME_LITERAL_RE.match(literal):
            return "time"
        return None

    if isinstance(expr, exp.Anonymous):
        return _anonymous_temporal_result_kind(expr, context)

    if isinstance(expr, exp.Func):
        return _named_temporal_result_kind(expr, context)

    return None


def _anonymous_temporal_result_kind(expr: exp.Anonymous, context: SchemaContext) -> Optional[str]:
    normalized = str(expr.this or "").upper().replace("_", "")
    if normalized == "DATE":
        args = _function_args(expr)
        return "date" if args and _is_temporal_expression(args[0], context) else None
    if normalized == "TIME":
        args = _function_args(expr)
        return "time" if args and _is_temporal_expression(args[0], context) else None
    if normalized == "TSORDSTODATE":
        args = _function_args(expr)
        return _temporal_kind(args[0], context) if args else None
    if normalized in {"STRTODATE", "DATEADD", "DATESUB", "SUBDATE"}:
        return "datetime"
    if normalized == "TIMEDIFF":
        return "time"
    return None


def _named_temporal_result_kind(expr: exp.Func, context: SchemaContext) -> Optional[str]:
    normalized = expr.sql_name().upper().replace("_", "")
    if normalized == "DATE":
        args = _function_args(expr)
        return "date" if args and _is_temporal_expression(args[0], context) else None
    if normalized == "TIME":
        args = _function_args(expr)
        return "time" if args and _is_temporal_expression(args[0], context) else None
    if normalized == "TSORDSTODATE":
        args = _function_args(expr)
        return _temporal_kind(args[0], context) if args else None
    if normalized in {"STRTODATE", "DATEADD", "DATESUB", "SUBDATE"}:
        return "datetime"
    if normalized == "TIMEDIFF":
        return "time"
    return None


def _is_temporal_base_type(type_name: str) -> bool:
    return _base_type_name(type_name) in _TEMPORAL_BASE_TYPES


def _base_type_name(type_name: str) -> str:
    return (type_name or "").upper().split("(", 1)[0].strip()


def _temporal_kind_from_type_name(type_name: str) -> Optional[str]:
    base_type = _base_type_name(type_name)
    if base_type == "DATE":
        return "date"
    if base_type == "TIME":
        return "time"
    if base_type in {"DATETIME", "TIMESTAMP"}:
        return "datetime"
    if base_type == "YEAR":
        return "year"
    return None


def _datediff_args_compatible(
    args: Sequence[exp.Expression],
    context: SchemaContext,
) -> bool:
    if len(args) != 2:
        return False
    left_kind = _temporal_kind(args[0], context)
    right_kind = _temporal_kind(args[1], context)
    return left_kind in _TEMPORAL_DATE_KINDS and right_kind in _TEMPORAL_DATE_KINDS


def _timediff_args_compatible(
    args: Sequence[exp.Expression],
    context: SchemaContext,
) -> bool:
    if len(args) != 2:
        return False
    left_kind = _temporal_kind(args[0], context)
    right_kind = _temporal_kind(args[1], context)
    return (
        left_kind in _SAFE_TEMPORAL_KINDS
        and right_kind in _SAFE_TEMPORAL_KINDS
        and left_kind == right_kind
    )


def _timestampdiff_args_compatible(
    expr: exp.Expression,
    context: SchemaContext,
) -> bool:
    left_expr = expr.args.get("expression")
    right_expr = expr.args.get("this")
    if not isinstance(left_expr, exp.Expression) or not isinstance(right_expr, exp.Expression):
        return False
    left_kind = _temporal_kind(left_expr, context)
    right_kind = _temporal_kind(right_expr, context)
    return left_kind in _SAFE_TEMPORAL_KINDS and right_kind in _SAFE_TEMPORAL_KINDS


def _source_guarantees_non_empty(
    source: Optional[exp.Expression],
    non_empty_tables: Set[str],
) -> bool:
    if isinstance(source, exp.Table):
        names = _source_names(source)
        return bool(names) and any(name in non_empty_tables for name in names)
    if isinstance(source, exp.Subquery):
        alias = source.alias_or_name
        if alias and alias.lower() in non_empty_tables:
            return True
        return _query_guarantees_at_least_one_row(_unwrap_query(source.this), non_empty_tables)
    return False


def _is_zero_limit(limit_expr: Optional[exp.Expression]) -> bool:
    if limit_expr is None:
        return False
    value = limit_expr.args.get("expression")
    return isinstance(value, exp.Literal) and not value.is_string and str(value.this) == "0"


def _contains_aggregate(expr: exp.Expression) -> bool:
    if isinstance(expr, (exp.Count, exp.AggFunc)):
        return True

    for node in expr.iter_expressions():
        if isinstance(node, exp.Subquery):
            continue
        if isinstance(node, (exp.Count, exp.AggFunc)):
            return True
        if _contains_aggregate(node):
            return True
    return False


def _column_nullability(
    column_expr: exp.Column,
    context: SchemaContext,
    nullable_sources: Set[str],
    where_not_null: Set[ColumnKey],
) -> InferredColumnNullability:
    column = context.resolve_column(column_expr)
    if column is None:
        return InferredColumnNullability(is_nullable=True, source="column_unknown")

    key = (column.table_name.lower(), column.name.lower())
    if key in where_not_null:
        return InferredColumnNullability(is_nullable=False, source="where_not_null")

    table_ref = (column_expr.table or "").lower()
    table_name = column.table_name.lower()
    if table_ref in nullable_sources or table_name in nullable_sources:
        return InferredColumnNullability(is_nullable=True, source="outer_join")

    return InferredColumnNullability(is_nullable=column.is_nullable, source="column")


def _star_nullability(
    context: SchemaContext,
    nullable_sources: Set[str],
) -> List[InferredColumnNullability]:
    result: List[InferredColumnNullability] = []
    for table in context.visible_tables():
        table_is_nullable = table.name.lower() in nullable_sources
        for column in table.columns:
            result.append(
                InferredColumnNullability(
                    is_nullable=column.is_nullable or table_is_nullable,
                    source="star",
                )
            )
    return result or [InferredColumnNullability(is_nullable=True, source="star_unknown")]


def _outer_join_nullable_sources(select_expr: exp.Select) -> Set[str]:
    nullable_sources: Set[str] = set()
    from_expr = select_expr.args.get("from_")
    left_names = _source_names(from_expr.this) if from_expr is not None else set()

    for join_expr in select_expr.args.get("joins") or []:
        side = (join_expr.args.get("side") or "").upper()
        right_names = _source_names(join_expr.this)
        if side == "LEFT":
            nullable_sources.update(right_names)
        elif side == "RIGHT":
            nullable_sources.update(left_names)
        elif side == "FULL":
            nullable_sources.update(left_names)
            nullable_sources.update(right_names)
        left_names.update(right_names)

    return nullable_sources


def _source_names(source: Optional[exp.Expression]) -> Set[str]:
    if isinstance(source, exp.Table):
        names = set()
        if source.name:
            names.add(source.name.lower())
        if source.alias_or_name:
            names.add(source.alias_or_name.lower())
        return names
    if isinstance(source, exp.Subquery):
        alias = source.alias_or_name
        return {alias.lower()} if alias else set()
    return set()


def _where_not_null_columns(select_expr: exp.Select, context: SchemaContext) -> Set[ColumnKey]:
    where_expr = select_expr.args.get("where")
    if where_expr is None:
        return set()
    return _predicate_implied_not_null_columns(where_expr.this, context)


def _predicate_implied_not_null_columns(
    predicate: Optional[exp.Expression],
    context: SchemaContext,
) -> Set[ColumnKey]:
    if predicate is None:
        return set()

    if isinstance(predicate, exp.Paren):
        return _predicate_implied_not_null_columns(predicate.this, context)

    if isinstance(predicate, exp.And):
        return _predicate_implied_not_null_columns(
            predicate.this, context
        ) | _predicate_implied_not_null_columns(predicate.expression, context)

    if isinstance(predicate, exp.Or):
        return _predicate_implied_not_null_columns(
            predicate.this, context
        ) & _predicate_implied_not_null_columns(predicate.expression, context)

    if _is_is_not_null(predicate):
        column_expr = predicate.this.this
        if isinstance(column_expr, exp.Column):
            key = _resolved_column_key(column_expr, context)
            return {key} if key else set()

    if isinstance(predicate, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
        return _predicate_operand_column_keys(predicate.this, context) | _predicate_operand_column_keys(
            predicate.expression, context
        )

    if isinstance(predicate, exp.Between):
        return (
            _predicate_operand_column_keys(predicate.this, context)
            | _predicate_operand_column_keys(predicate.args.get("low"), context)
            | _predicate_operand_column_keys(predicate.args.get("high"), context)
        )

    if isinstance(predicate, exp.In):
        return _predicate_operand_column_keys(predicate.this, context)

    return set()


def _is_is_not_null(predicate: exp.Expression) -> bool:
    if not isinstance(predicate, exp.Not):
        return False
    inner = predicate.this
    return (
        isinstance(inner, exp.Is)
        and isinstance(inner.this, exp.Column)
        and isinstance(inner.expression, exp.Null)
    )


def _resolved_column_key(column_expr: exp.Column, context: SchemaContext) -> Optional[ColumnKey]:
    column = context.resolve_column(column_expr)
    if column is None:
        return None
    return (column.table_name.lower(), column.name.lower())


def _expression_column_keys(
    expr: Optional[exp.Expression],
    context: SchemaContext,
) -> Set[ColumnKey]:
    if expr is None:
        return set()

    keys: Set[ColumnKey] = set()
    for node in expr.walk():
        if isinstance(node, exp.Column):
            key = _resolved_column_key(node, context)
            if key:
                keys.add(key)
    return keys


def _predicate_operand_column_keys(
    expr: Optional[exp.Expression],
    context: SchemaContext,
) -> Set[ColumnKey]:
    """Return columns that are directly constrained non-null by a predicate operand.

    This is intentionally narrower than `_expression_column_keys`. A comparison like
    `func(col) = 1` does not generally imply that `col` itself is non-null because
    some functions can still yield a non-null value when one of their arguments is
    NULL. We therefore only treat direct column operands as predicate-implied
    non-null here.
    """

    while isinstance(expr, (exp.Paren, exp.Alias)):
        expr = expr.this

    if isinstance(expr, exp.Column):
        key = _resolved_column_key(expr, context)
        return {key} if key else set()

    return set()


def _expression_children(expr: exp.Expression) -> List[exp.Expression]:
    children: List[exp.Expression] = []
    for value in expr.args.values():
        if isinstance(value, exp.Expression):
            children.append(value)
        elif isinstance(value, list):
            children.extend(item for item in value if isinstance(item, exp.Expression))
    return children


def _is_guaranteed_non_zero(
    expr: Optional[exp.Expression],
    context: SchemaContext,
) -> bool:
    if expr is None:
        return False

    if isinstance(expr, exp.Paren):
        return _is_guaranteed_non_zero(expr.this, context)

    if isinstance(expr, exp.Neg):
        return _is_guaranteed_non_zero(expr.this, context)

    if isinstance(expr, exp.Literal) and not expr.is_string:
        try:
            return float(str(expr.this)) != 0.0
        except ValueError:
            return False

    if isinstance(expr, exp.Column):
        return False

    if isinstance(expr, exp.Anonymous):
        normalized = str(expr.this or "").upper().replace("_", "")
        args = _function_args(expr)
        if normalized == "ABS" and len(args) == 1:
            return _is_guaranteed_non_zero(args[0], context)
        return False

    if isinstance(expr, exp.Abs):
        return _is_guaranteed_non_zero(expr.this, context)

    return False
