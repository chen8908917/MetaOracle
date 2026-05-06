from typing import Iterable, List, Optional, Sequence

from sqlglot import expressions as exp

from data_structures.column import Column
from data_structures.table import Table

from .parser import parse_query
from .schema_context import SchemaContext


def infer_column_names(
    sql: str,
    tables: Optional[Iterable[Table]] = None,
    dialect: Optional[str] = None,
) -> List[str]:
    """Infer SELECT result column names in output order."""

    query_expr = parse_query(sql, dialect=dialect)
    return _query_names(query_expr, list(tables or []))


def _query_names(query_expr: exp.Expression, tables: Sequence[Table]) -> List[str]:
    if isinstance(query_expr, exp.SetOperation):
        left = _unwrap_query(query_expr.this)
        return _query_names(left, tables)

    if not isinstance(query_expr, exp.Select):
        select_expr = query_expr.find(exp.Select)
        if select_expr is None:
            raise ValueError("DQL metadata inference currently requires a SELECT statement.")
        query_expr = select_expr

    context = SchemaContext(_tables_with_ctes(query_expr, tables)).bind_select(query_expr)
    names: List[str] = []

    for projection in query_expr.expressions or []:
        names.extend(_projection_names(projection, context))

    return names


def _unwrap_query(query_expr: exp.Expression) -> exp.Expression:
    if isinstance(query_expr, exp.Subquery):
        return query_expr.this
    return query_expr


def _tables_with_ctes(select_expr: exp.Select, base_tables: Sequence[Table]) -> List[Table]:
    tables = list(base_tables)
    with_expr = select_expr.args.get("with_") or select_expr.args.get("with")
    if not with_expr:
        return tables

    for cte in with_expr.expressions or []:
        cte_name = cte.alias
        cte_select = cte.this if isinstance(cte.this, exp.Select) else cte.this.find(exp.Select)
        if not cte_name or cte_select is None:
            continue

        context = SchemaContext(tables).bind_select(cte_select)
        column_names: List[str] = []
        for projection in cte_select.expressions or []:
            column_names.extend(_projection_names(projection, context))

        if column_names:
            tables.append(
                Table(
                    name=cte_name,
                    columns=[
                        Column(name, "UNKNOWN", "unknown", True, cte_name)
                        for name in column_names
                    ],
                    primary_key=column_names[0],
                    foreign_keys=[],
                )
            )
    return tables


def _projection_names(projection: exp.Expression, context: SchemaContext) -> List[str]:
    if isinstance(projection, exp.Alias):
        return [str(projection.alias)]

    if isinstance(projection, exp.Star):
        return _star_names(context)

    if isinstance(projection, exp.Column):
        if projection.name == "*":
            return _star_names(context)
        return [projection.name]

    alias = getattr(projection, "alias", None)
    if alias:
        return [str(alias)]

    name = getattr(projection, "name", None)
    if name and name != "*":
        return [str(name)]

    return [projection.sql()]


def _star_names(context: SchemaContext) -> List[str]:
    names: List[str] = []
    for table in context.visible_tables():
        names.extend(column.name for column in table.columns)
    return names or ["*"]
