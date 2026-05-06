from typing import Dict, List, Optional, Union

from ast_nodes import ASTNode, FromNode, SubqueryNode
from data_structures.function import Function
from data_structures.table import Table
from sql_generation.random_sql import state as _state
from sql_generation.random_sql.column_tracker import ColumnUsageTracker


def get_tables():
    return _state.get_tables()


def set_tables(tables_list):
    _state.set_tables(tables_list)


def _get_subquery_depth() -> int:
    return _state.get_subquery_depth()


def _set_subquery_depth(depth: int) -> None:
    _state.set_subquery_depth(depth)


def create_select_subquery(tables: List[Table], functions: List[Function], current_depth: int = 0, max_depth: int = 2) -> SubqueryNode:
    from sql_generation.random_sql.subqueries import create_select_subquery as _create_select_subquery
    return _create_select_subquery(tables, functions, current_depth=current_depth, max_depth=max_depth)


def create_simple_where_condition(table: Table, alias: str) -> Optional[ASTNode]:
    from sql_generation.random_sql.predicates import create_simple_where_condition as _create_simple_where_condition
    return _create_simple_where_condition(table, alias)


def generate_create_table_sql(table: Table) -> str:
    from sql_generation.random_sql.ddl_dml import generate_create_table_sql as _generate_create_table_sql
    return _generate_create_table_sql(table)


def generate_insert_sql(table: Table, num_rows: int = 5, existing_primary_keys: dict = None, primary_key_values: list = None) -> str:
    from sql_generation.random_sql.ddl_dml import generate_insert_sql as _generate_insert_sql
    return _generate_insert_sql(table, num_rows=num_rows, existing_primary_keys=existing_primary_keys, primary_key_values=primary_key_values)


def create_sample_tables():
    from sql_generation.random_sql.samples import create_sample_tables as _create_sample_tables
    return _create_sample_tables()


def create_sample_functions():
    from sql_generation.random_sql.samples import create_sample_functions as _create_sample_functions
    return _create_sample_functions()


def generate_table_alias() -> str:
    from sql_generation.random_sql.joins import generate_table_alias as _generate_table_alias
    return _generate_table_alias()


def create_join_condition(main_table: Table, main_alias: str, join_table: Union[Table, 'SubqueryNode'], join_alias: str) -> ASTNode:
    from sql_generation.random_sql.joins import create_join_condition as _create_join_condition
    return _create_join_condition(main_table, main_alias, join_table, join_alias)


def is_type_compatible(type1, type2):
    from sql_generation.random_sql.expressions import is_type_compatible as _is_type_compatible
    return _is_type_compatible(type1, type2)


def create_compatible_literal(data_type):
    from sql_generation.random_sql.expressions import create_compatible_literal as _create_compatible_literal
    return _create_compatible_literal(data_type)


def ensure_boolean_expression(expr: ASTNode, tables: List[Table], functions: List[Function], from_node: FromNode, main_table: Table, main_alias: str, join_table: Optional[Table] = None, join_alias: Optional[str] = None) -> ASTNode:
    from sql_generation.random_sql.expressions import ensure_boolean_expression as _ensure_boolean_expression
    return _ensure_boolean_expression(expr, tables, functions, from_node, main_table, main_alias, join_table, join_alias)


def create_complex_expression(tables: List[Table], functions: List[Function], from_node: FromNode, main_table: Table, main_alias: str, join_table: Optional[Table] = None, join_alias: Optional[str] = None, max_depth: int = 3, depth: int = 0, column_tracker: Optional[ColumnUsageTracker] = None, for_select: bool = False) -> ASTNode:
    from sql_generation.random_sql.expressions import create_complex_expression as _create_complex_expression
    return _create_complex_expression(tables, functions, from_node, main_table, main_alias, join_table, join_alias, max_depth, depth, column_tracker, for_select)


def create_random_expression(tables: List[Table], functions: List[Function], from_node: FromNode, main_table: Table, main_alias: str, join_table: Optional[Table] = None, join_alias: Optional[str] = None, use_subquery: bool = True, column_tracker: ColumnUsageTracker = None, for_select: bool = False) -> ASTNode:
    from sql_generation.random_sql.expressions import create_random_expression as _create_random_expression
    return _create_random_expression(tables, functions, from_node, main_table, main_alias, join_table, join_alias, use_subquery, column_tracker, for_select)


def create_expression_of_type(expr_type: str, tables: List[Table], functions: List[Function], from_node: FromNode, main_table: Table, main_alias: str, join_table: Optional[Table] = None, join_alias: Optional[str] = None, use_subquery: bool = True, column_tracker: ColumnUsageTracker = None, for_select: bool = False) -> ASTNode:
    from sql_generation.random_sql.expressions import create_expression_of_type as _create_expression_of_type
    return _create_expression_of_type(expr_type, tables, functions, from_node, main_table, main_alias, join_table, join_alias, use_subquery, column_tracker, for_select)


def create_in_subquery(tables: List[Table], functions: List[Function], from_node: FromNode, main_table: Table, main_alias: str, join_table: Optional[Table] = None, join_alias: Optional[str] = None, column_tracker: Optional[ColumnUsageTracker] = None) -> ASTNode:
    from sql_generation.random_sql.predicates import create_in_subquery as _create_in_subquery
    return _create_in_subquery(tables, functions, from_node, main_table, main_alias, join_table, join_alias, column_tracker)


def create_exists_subquery(tables: List[Table], functions: List[Function], from_node: FromNode, main_table: Table, main_alias: str, join_table: Optional[Table] = None, join_alias: Optional[str] = None, column_tracker: Optional[ColumnUsageTracker] = None) -> ASTNode:
    from sql_generation.random_sql.predicates import create_exists_subquery as _create_exists_subquery
    return _create_exists_subquery(tables, functions, from_node, main_table, main_alias, join_table, join_alias, column_tracker)


def create_where_condition(tables: List[Table], functions: List[Function], from_node: FromNode, main_table: Table, main_alias: str, join_table: Optional[Table] = None, join_alias: Optional[str] = None, use_subquery: bool = True, column_tracker: Optional[ColumnUsageTracker] = None) -> ASTNode:
    from sql_generation.random_sql.predicates import create_where_condition as _create_where_condition
    return _create_where_condition(tables, functions, from_node, main_table, main_alias, join_table, join_alias, use_subquery, column_tracker)


def generate_random_sql(tables: List[Table], functions: List[Function], current_depth: int = 0) -> str:
    from sql_generation.random_sql.generator import generate_random_sql as _generate_random_sql
    return _generate_random_sql(tables, functions, current_depth=current_depth)


def generate_index_sqls(tables, dialect):
    from sql_generation.random_sql.io_utils import generate_index_sqls as _generate_index_sqls
    return _generate_index_sqls(tables, dialect)


def save_sql_to_file(
    sql: str,
    output_dir: str = "generated_sql",
    file_type: str = "all",
    mode: str = "w",
    database_name: str = "test",
) -> str:
    from sql_generation.random_sql.io_utils import save_sql_to_file as _save_sql_to_file
    return _save_sql_to_file(
        sql,
        output_dir=output_dir,
        file_type=file_type,
        mode=mode,
        database_name=database_name,
    )


def Generate(
    subquery_depth: int = 3,
    total_insert_statements: int = 100,
    num_queries: int = 15,
    query_type: str = 'default',
    use_database_tables: bool = False,
    db_config: Optional[Dict] = None,
    output_dir: str = "generated_sql",
    database_name: str = "test",
):
    from sql_generation.random_sql.generator import Generate as _Generate
    return _Generate(
        subquery_depth=subquery_depth,
        total_insert_statements=total_insert_statements,
        num_queries=num_queries,
        query_type=query_type,
        use_database_tables=use_database_tables,
        db_config=db_config,
        output_dir=output_dir,
        database_name=database_name,
    )
