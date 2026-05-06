from typing import Optional

import sqlglot
from sqlglot import expressions as exp

from data_structures.db_dialect import get_current_dialect


def default_sqlglot_dialect() -> str:
    dialect = get_current_dialect()
    if dialect and dialect.name.upper() == "POSTGRESQL":
        return "postgres"
    return "mysql"


def parse_select(sql: str, dialect: Optional[str] = None) -> exp.Select:
    ast = sqlglot.parse_one(sql, read=dialect or default_sqlglot_dialect())
    select_expr = ast if isinstance(ast, exp.Select) else ast.find(exp.Select)
    if select_expr is None:
        raise ValueError("DQL metadata inference currently requires a SELECT statement.")
    return select_expr


def parse_query(sql: str, dialect: Optional[str] = None) -> exp.Expression:
    ast = sqlglot.parse_one(sql, read=dialect or default_sqlglot_dialect())
    if not isinstance(ast, (exp.Select, exp.SetOperation)):
        select_expr = ast.find(exp.Select)
        if select_expr is None:
            raise ValueError("DQL metadata inference currently requires a SELECT statement.")
        return select_expr
    return ast
