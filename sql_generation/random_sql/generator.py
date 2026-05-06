"""Primary random SQL query generator and batch output pipeline."""

import os
import random
import re
import string
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from ast_nodes import (
    ASTNode,
    ArithmeticNode,
    CaseNode,
    ColumnReferenceNode,
    ComparisonNode,
    FromNode,
    FunctionCallNode,
    GroupByNode,
    LiteralNode,
    LogicalNode,
    OrderByNode,
    SetOperationNode,
    SubqueryNode,
    WithNode,
    LimitNode,
    SelectNode,
)

from data_structures.column import Column
from data_structures.function import Function
from data_structures.table import Table
from data_structures.dependency import Dependency
from data_structures.db_dialect import DBDialect, get_current_dialect, get_dialect_config, set_dialect

from sql_generation.random_sql import state as _state
from sql_generation.random_sql.column_tracker import ColumnUsageTracker, get_random_column_with_tracker
from sql_generation.random_sql.ddl_dml import generate_create_table_sql, generate_insert_sql
from sql_generation.random_sql.expressions import (
    create_expression_of_type,
    create_random_expression,
    ensure_boolean_expression,
)
from sql_generation.random_sql.joins import create_join_condition, generate_table_alias
from sql_generation.random_sql.predicates import create_where_condition
from sql_generation.random_sql.subqueries import create_select_subquery
from sql_generation.random_sql.samples import create_sample_functions, create_sample_tables
from sql_generation.random_sql.geometry import (
    create_geojson_literal_node,
    create_geohash_literal_node,
    create_geometry_literal_node,
    create_geometry_wkt,
    create_geometry_wkt_for_function,
    create_wkb_literal_node,
    create_wkt_literal_node,
    get_geometry_type_for_function,
    is_geojson_function,
    is_geohash_function,
    is_geometry_type,
    is_wkt_function,
)
from sql_generation.random_sql.io_utils import generate_index_sqls, save_sql_to_file
from sql_generation.random_sql.type_utils import (
    ORDERABLE_CATEGORIES,
    adjust_expected_type_for_conditionals,
    adjust_expected_type_for_min_max,
    get_cast_types,
    get_comparison_operators,
    get_full_column_identifier,
    get_safe_comparison_category,
    map_param_type_to_category,
    map_return_type_to_category,
    normalize_category,
)


def get_tables():
    return _state.get_tables()


def set_tables(tables_list):
    _state.set_tables(tables_list)


def _get_subquery_depth() -> int:
    return _state.get_subquery_depth()


def _set_subquery_depth(depth: int) -> None:
    _state.set_subquery_depth(depth)


def _create_select_constant_literal() -> LiteralNode:
    literal_type = random.choice(["INT", "STRING", "DATETIME", "JSON", "BOOLEAN"])
    if literal_type == "INT":
        return LiteralNode(random.randint(0, 100), "INT")
    if literal_type == "STRING":
        return LiteralNode(f"const_{random.randint(1, 100)}", "STRING")
    if literal_type == "DATETIME":
        return LiteralNode("2023-01-01 12:00:00", "DATETIME")
    if literal_type == "JSON":
        return LiteralNode('{"key":"value"}', "JSON")
    return LiteralNode(random.choice([True, False]), "BOOLEAN")

def generate_random_sql(tables: List[Table], functions: List[Function], current_depth: int = 0) -> str:
    """Generate random SQL queries"""
    use_cte = False
    #Get the current database dialect
    current_dialect = get_current_dialect()
    #Check if it's a Percona dialect
    #Now allows Percona to use the with query feature
    is_percona = current_dialect and 'PerconaDialect' == current_dialect.__class__.__name__
    #First try generating a CTE query, including Percona dialect
    if random.random() > 0.3:  #All dialects that support the with clause, including Percona, have the same probability of generating a query of type with
        use_cte = True
        with_node = WithNode()
        
        #Generate 1-2 CTEs
        num_ctes = random.randint(1, 2)
        for i in range(num_ctes):
            cte_name = f"cte_{random.randint(1, 999)}"
            cte_query = SelectNode()
            #Columns that initialize CTE queries use trackers
            cte_column_tracker = ColumnUsageTracker()
            cte_query.tables = tables
            cte_query.functions = functions
            #Save Column Tracker for later use
            cte_query.metadata = {'column_tracker': cte_column_tracker}
            
            #Select a table for CTE
            cte_table = random.choice(tables)
            cte_alias = generate_table_alias()
            
            #Create from clause
            cte_from = FromNode()
            cte_from.add_table(cte_table, cte_alias)
            cte_query.set_from_clause(cte_from)
            #Available Column Information for Column Tracker to Initialize CTE Query
            if cte_query.metadata and 'column_tracker' in cte_query.metadata:
                cte_column_tracker = cte_query.metadata['column_tracker']
                if hasattr(cte_column_tracker, 'initialize_from_from_node'):
                    cte_column_tracker.initialize_from_from_node(cte_from)
            
            #Add select expression
            num_columns = random.randint(2, 4)
            non_aggregate_columns = []  #Store non-aggregated columns
            has_aggregate_function = False  #Track whether an aggregate function is included
            for j in range(num_columns):
                #Add Randomly
                expr = create_random_expression([cte_table], functions, cte_from, cte_table, cte_alias, use_subquery=False,column_tracker=cte_column_tracker, for_select=True)
                cte_query.add_select_expression(expr, f"col_{j+1}")
                
            #New group BY clause Add logic: Mister into all expressions, then judge processing
            #Create GroupByNode
            cte_group_by = GroupByNode()
            #Check for the inclusion of aggregate functions
            has_aggregate = False
            
            if hasattr(cte_query, 'select_expressions'):
                try:
                    #Try traversing select_expressions
                    for expr, alias in cte_query.select_expressions:
                        #Check if the expression has a function property
                        if hasattr(expr, 'function'):
                            if getattr(expr.function, 'func_type', '') == 'aggregate':
                                has_aggregate = True
                except Exception as e:
                    print(f"Step Throughcte_query.select_expressionsError during: {e}")
            
            #Add group BY clause if there is an aggregate function
            if has_aggregate:
                #Collect all non-aggregated columns and add to group BY
                for expr, alias in cte_query.select_expressions:
                    if not (hasattr(expr, 'function') and getattr(expr.function, 'func_type', '') == 'aggregate'):
                        #Determine if it is a scalar function column or column reference
                        if (hasattr(expr, 'function') and getattr(expr.function, 'func_type', '') == 'scalar') or type(expr).__name__ == 'ColumnReferenceNode':
                            #Add expressions directly to group BY
                            cte_group_by.add_expression(expr)
                        #Judgment Window Function
                        elif hasattr(expr, 'function') and getattr(expr.function, 'func_type', '') == 'window':
                            if hasattr(expr, 'children'):
                                    for arg in expr.children:
                                        #Add to group BY if parameter is a column reference or scalar function
                                        if type(arg).__name__ == 'ColumnReferenceNode':
                                            cte_group_by.add_expression(arg)
                                        elif type(arg).__name__ == 'FunctionCallNode' and hasattr(arg.function, 'func_type') and arg.function.func_type == 'scalar':
                                            for child in arg.children:
                                                if type(child).__name__ == 'ColumnReferenceNode':
                                                    cte_group_by.add_expression(child)
                                            
                            if hasattr(expr, 'metadata'):
                                #Process partition_by
                                if expr.metadata.get('partition_by'):
                                    partition_by = expr.metadata.get('partition_by')
                                    #Try to get cte_from (assuming it is available in the parent scope)
                                    if 'cte_from' in locals() or 'cte_from' in globals():
                                        available_from_node = locals().get('cte_from') or globals().get('cte_from')
                                        
                                        for part_expr in partition_by:
                                            try:
                                                #Resolve table aliases and column names
                                                if '.' in part_expr:
                                                    alias_part, col_part = part_expr.split('.', 1)
                                                    #Clear possible quotes
                                                    alias_part = alias_part.strip('"\'')
                                                    col_part = col_part.strip('"\'')
                                                    
                                                    #Get a table object
                                                    table_ref = available_from_node.get_table_for_alias(alias_part)
                                                    if table_ref and hasattr(table_ref, 'get_column'):
                                                        #Get Column Object
                                                        col = table_ref.get_column(col_part)
                                                        if col:
                                                            #Create ColumnReferenceNode object
                                                            col_ref = ColumnReferenceNode(col, alias_part)
                                                            #Add to group BY
                                                            cte_group_by.add_expression(col_ref)
                                            except Exception as e:
                                                print(f"  Convertpartition_byError in expression: {e}")
                                
                                #Process order_by
                                if expr.metadata.get('order_by'):
                                    order_by = expr.metadata.get('order_by')
                                    #Try to get cte_from (assuming it is available in the parent scope)
                                    if 'cte_from' in locals() or 'cte_from' in globals():
                                        available_from_node = locals().get('cte_from') or globals().get('cte_from')
                                        
                                        #Process order_by expression
                                        main_expr = []
                                        for order in order_by:
                                            expr_parts = order.rsplit(' ', 1)
                                            if len(expr_parts) == 2 and expr_parts[1].upper() in ['ASC', 'DESC']:
                                                main_expr.append(expr_parts[0])
                                            else:
                                                main_expr.append(order)
                                        
                                        for part_expr in main_expr:
                                            try:
                                                #Resolve table aliases and column names
                                                if '.' in part_expr:
                                                    alias_part, col_part = part_expr.split('.', 1)
                                                    #Clear possible quotes
                                                    alias_part = alias_part.strip('"\'')
                                                    col_part = col_part.strip('"\'')
                                                    
                                                    #Get a table object
                                                    table_ref = available_from_node.get_table_for_alias(alias_part)
                                                    if table_ref and hasattr(table_ref, 'get_column'):
                                                        #Get Column Object
                                                        col = table_ref.get_column(col_part)
                                                        if col:
                                                            #Create ColumnReferenceNode object
                                                            col_ref = ColumnReferenceNode(col, alias_part)
                                                            #Add to group BY
                                                            cte_group_by.add_expression(col_ref)
                                            except Exception as e:
                                                print(f"  Convertorder_byError in expression: {e}")
                
                #Set group BY clause
                if cte_group_by.expressions:
                    cte_query.set_group_by_clause(cte_group_by)
            
            #Add where condition
            if random.random() > 0.5:
                #Ensure that the where condition only references columns that actually exist in the CTE
                #Ensure column_tracker exists (previously initialized)
                cte_column_tracker = cte_query.metadata.get('column_tracker')
                where = create_where_condition([cte_table], functions, cte_from, cte_table, cte_alias, use_subquery=False, column_tracker=cte_column_tracker)
                cte_query.set_where_clause(where)
                
                #Validate and fix column references in where condition
                if hasattr(cte_query, 'validate_all_columns'):
                    valid, errors = cte_query.validate_all_columns()
                    if not valid and hasattr(cte_query, 'repair_invalid_columns'):
                        cte_query.repair_invalid_columns()
            
            #Add CTE to with clause
            with_node.add_cte(cte_name, cte_query, num_columns)
        
        #Generate main query using CTE and actual table
        main_query = SelectNode()
        main_query.tables = tables
        main_query.functions = functions
        
        main_from = FromNode()
        
        #Create a virtual table to represent all CTEs
        cte_tables = []
        for cte_name, cte_query, cte_num_columns in with_node.ctes:
            #Create virtual table
            #Try to extract actual column information from cte_query
            columns = []
            
            #Check if cte_query has the select_expressions property
            if hasattr(cte_query, 'select_expressions') and cte_query.select_expressions:
                #Traverse select_expressions to extract column information
                for j, (expr, alias) in enumerate(cte_query.select_expressions):
                    #Default Value
                    col_name = alias or f"col_{j+1}"
                    data_type = "INT"
                    category = "numeric"
                    is_nullable = False
                    
                    #Try to get the actual type information from the expression
                    if hasattr(expr, 'metadata') and expr.metadata:
                        if 'data_type' in expr.metadata:
                            data_type = expr.metadata['data_type']
                        if 'category' in expr.metadata:
                            category = expr.metadata['category']
                        elif data_type:
                            category = map_return_type_to_category(data_type)
                        if 'is_nullable' in expr.metadata:
                            is_nullable = expr.metadata['is_nullable']
                    elif isinstance(expr, SubqueryNode):
                        if expr.column_alias_map:
                            _, data_type, category = next(iter(expr.column_alias_map.values()))
                        else:
                            data_type = "INT"
                            category = "numeric"
                    elif hasattr(expr, 'column'):
                        #If it is a column reference, use the information from the original column
                        column = expr.column
                        if hasattr(column, 'data_type'):
                            data_type = column.data_type
                        if hasattr(column, 'category'):
                            category = column.category
                        if hasattr(column, 'is_nullable'):
                            is_nullable = column.is_nullable
                    elif hasattr(expr, 'function'):
                        #If it is a function call, infer from the function type
                        func = expr.function
                        if hasattr(func, 'return_type'):
                            data_type = func.return_type
                        if hasattr(func, 'return_category'):
                            category = func.return_category
                        elif data_type:
                            category = map_return_type_to_category(data_type)
                    
                    #Create column
                    columns.append(Column(
                        name=col_name,
                        data_type=data_type,
                        category=category,
                        is_nullable=is_nullable,
                        table_name=cte_name
                    ))
            else:
                #Fallback to default method if actual information is not available
                columns = [Column(f"col_{j+1}", "INT", "numeric", False, cte_name) for j in range(cte_num_columns)]
            
            #Create CTE virtual table
            cte_table = Table(
                name=cte_name,
                columns=columns,
                primary_key=columns[0].name if columns else "col_1",
                foreign_keys=[]
            )
            #Add the column_alias_map attribute so that column trackers can correctly identify and track the columns of these dummy tables
            cte_table.column_alias_map = {}
            for col in columns:
                cte_table.column_alias_map[col.name] = (col.name, col.data_type, col.category)
            cte_tables.append(cte_table)
        
        #Merge CTE dummy and original tables
        combined_tables = tables + cte_tables
        tables = combined_tables
        
    
    #Randomly determine whether to generate collection actions
    if random.random() > 0.7 and current_depth == 0:  
        #30% probability of generating a set operation, and only in the top-level query generation
        #Select the collection action type, including intersect and except
        dialect = get_current_dialect()
        operation_types = ['UNION', 'UNION ALL']
        if hasattr(dialect, 'supports_intersect_operator'):
            if dialect.supports_intersect_operator():
                operation_types.append('INTERSECT')
        elif dialect.name == 'POSTGRESQL':
            operation_types.append('INTERSECT')
        if hasattr(dialect, 'supports_except_operator'):
            if dialect.supports_except_operator():
                operation_types.append('EXCEPT')
        elif dialect.name == 'POSTGRESQL':
            operation_types.append('EXCEPT')
        operation_type = random.choice(operation_types)
        
        #Create Collection Action Node
        set_op_node = SetOperationNode(operation_type)
        
        #Generate 2-3 queries that participate in the collection operation
        num_queries = random.randint(2, 3)
        for i in range(num_queries):
            #Generate a query (limit depth, avoid overcomplication)
            select_node = SelectNode()
            select_node.tables = tables
            select_node.functions = functions
            #Initialize columns using trackers
            column_tracker = ColumnUsageTracker()
            select_node.metadata = {'column_tracker': column_tracker}
            
            #Randomly decide whether to use distinct
            if random.random() > 0.8:
                select_node.distinct = True
            
            #Select main table
            main_table = random.choice(tables)
            main_alias = generate_table_alias()
            
            #Create from clause
            from_node = FromNode()
            from_node.add_table(main_table, main_alias)
            select_node.set_from_clause(from_node)
            #Initialize available column information for column trackers
            
            
            #Add connection table randomly (simplified, no more than 1 connection)
            has_join = False
            join_table = None
            join_alias = None
            if random.random() > 0.5 and i == 0:  #The first query may have connections, other queries are as simple as possible
                #Select a different table to connect
                available_tables = [t for t in tables if t.name != main_table.name]
                if available_tables:
                    join_table = random.choice(available_tables)
                    join_alias = generate_table_alias()
                    
                    #Randomly select connection type
                    join_type = random.choice(['INNER', 'LEFT','RIGHT','CROSS'])
                    #Try to create reasonable connection conditions
                    join_condition = create_join_condition(main_table, main_alias, join_table, join_alias)
                    from_node.add_join(join_type, join_table, join_alias, join_condition)
                    has_join = True
                    select_node.set_from_clause(from_node)
            if select_node.metadata and 'column_tracker' in select_node.metadata:
                column_tracker = select_node.metadata['column_tracker']
                if hasattr(column_tracker, 'initialize_from_from_node'):
                    column_tracker.initialize_from_from_node(from_node)
            #Generate select clause - ensure the number and type of columns are compatible for all queries
            if i == 0:  #The first query determines the number and type of columns
                num_columns = 2 + random.randint(0, 2)  #2/4 Column
                for j in range(num_columns):
                    expr_node = create_random_expression(
                        tables, functions, from_node, main_table, main_alias, 
                        join_table if has_join else None, join_alias if has_join else None, 
                        use_subquery=False,  #Do not use subqueries in collection operations
                        column_tracker=column_tracker,
                        for_select=True
                    )
                    
                    #Generate Alias
                    alias = f"col_{j+1}"  #Use unified aliases for easy collection operations
                    select_node.add_select_expression(expr_node, alias)
            else:  #Subsequent queries need to exactly match the number of columns and the column type of the first query
                first_query = set_op_node.queries[0]
                #Make sure the number of columns is the same as the first query
                for j in range(len(first_query.select_expressions)):
                    #Get column information from first query
                    first_expr, _ = first_query.select_expressions[j]
                    expr_type = first_expr.metadata.get('category', 'any')
                    
                    #Create expressions of the same type
                    expr_node = create_expression_of_type(
                        expr_type, tables, functions, from_node, main_table, main_alias,
                        join_table if has_join else None, join_alias if has_join else None,
                        column_tracker= column_tracker
                    )
                    
                    #Use Uniform Alias
                    alias = f"col_{j+1}"
                    select_node.add_select_expression(expr_node, alias)
            
            #Generate where clause (simplify to avoid being too complicated)
            if random.random() > 0.6:
                #Get column_tracker from select_node (if present)
                select_column_tracker = select_node.metadata.get('column_tracker') if hasattr(select_node, 'metadata') else None
                where_node = create_where_condition(
                    tables, functions, from_node, main_table, main_alias,
                    join_table if has_join else None, join_alias if has_join else None,
                    use_subquery=False,  #Do not use subqueries in collection operations
                    column_tracker=select_column_tracker
                )
                select_node.set_where_clause(where_node)
            
            #Add order BY and limit only to the first query (order BY and limit for collection operations usually apply to final results)
            if i == 0:
                #Add random order BY clause
                if random.random() > 0.7:
                    order_by = OrderByNode()
                    #Select Columns to Sort
                    col = main_table.get_random_column()
                    col_ref = ColumnReferenceNode(col, main_alias)
                    
                    #Check if distinct is used and if so, make sure the columns for order BY are in the select list
                    if select_node.distinct:
                        #Check if it is already in the select list
                        in_select = False
                        for selected_expr, selected_alias in select_node.select_expressions:
                            if hasattr(selected_expr, 'to_sql') and selected_expr.to_sql() == col_ref.to_sql():
                                in_select = True
                                break
                        
                        #Add if not in select list
                        if not in_select:
                            select_node.add_select_expression(col_ref, col.name)
                    
                    order_by.add_expression(col_ref, random.choice(['ASC', 'DESC']))
                    select_node.set_order_by_clause(order_by)
                
                #Add limit clause randomly
                if random.random() > 0.7:
                    select_node.set_limit_clause(LimitNode(random.randint(1, 5)))
            #Check each subquery for an aggregate function and add a group BY clause
            #Save external select_node reference
            outer_select_node = select_node
            for i, expr_item in enumerate(outer_select_node.select_expressions):
                group_by = GroupByNode()
                #Check for the inclusion of aggregate functions
                has_aggregate = False
                try:
                    expr, alias = expr_item
                    if hasattr(expr, 'function') and hasattr(expr.function, 'func_type') and expr.function.func_type == 'aggregate':
                        has_aggregate = True
                        
                except (TypeError, ValueError):
                    pass
                if hasattr(select_node, 'select_expressions'):
                    try:
                        #Try traversing select_expressions
                        expressions_count = 0
                        for expr, alias in select_node.select_expressions:
                            expressions_count += 1
                            #Check if the expression has a function property
                            if hasattr(expr, 'function'):
                                if getattr(expr.function, 'func_type', '') == 'aggregate':
                                    has_aggregate = True
                    except Exception as e:
                        print(f"Step Throughselect_expressionsError during: {e}")
                else:
                    print("Warning: select_node has no select_expressions attribute")
                #Add group BY clause if there is an aggregate function
                if has_aggregate:
                    added_group_columns = set()
                    #Collect all non-aggregated columns and add to group BY
                    for expr, alias in select_node.select_expressions:
                        if not (hasattr(expr, 'function') and expr.function.func_type == 'aggregate'):
                            #Determine if it is a scalar function column
                            if (hasattr(expr, 'function') and expr.function.func_type == 'scalar') or type(expr).__name__=='ColumnReferenceNode':
                                    #Number of group BY expressions before record addition
                                    before_count = len(group_by.expressions)
                                    #Add expressions directly to group BY
                                    group_by.add_expression(expr)
                                    #Number of group BY expressions after record addition
                                    after_count = len(group_by.expressions)
                            #Judgment Window Function
                            if hasattr(expr, 'function') and expr.function.func_type == 'window':
                                #Handles the parameters of the window function, added to group BY
                                before_count = len(group_by.expressions)
                                if hasattr(expr, 'children'):
                                    for arg in expr.children:
                                        #Add to group BY if parameter is a column reference or scalar function
                                        if type(arg).__name__ == 'ColumnReferenceNode':
                                            group_by.add_expression(arg)
                                        elif type(arg).__name__ == 'FunctionCallNode' and hasattr(arg.function, 'func_type') and arg.function.func_type == 'scalar':
                                            for child_arg in arg.children:
                                                if type(child_arg).__name__ == 'ColumnReferenceNode':
                                                    group_by.add_expression(child_arg)
                                after_count = len(group_by.expressions)
                                if hasattr(expr,'metadata'):
                                    if expr.metadata.get('partition_by'):
                                        partition_by=expr.metadata.get('partition_by')
                                        before_count = len(group_by.expressions)
                                        
                                        #Try to get from_node (assuming it is available in the parent scope)
                                        if 'from_node' in locals() or 'from_node' in globals():
                                            available_from_node = locals().get('from_node') or globals().get('from_node')
                                            
                                            for part_expr in partition_by:
                                                try:
                                                    #Parsing table aliases and column names (format: table_alias.column_name)
                                                    if '.' in part_expr:
                                                        alias_part, col_part = part_expr.split('.', 1)
                                                        #Clear possible quotes
                                                        alias_part = alias_part.strip('"\'')
                                                        col_part = col_part.strip('"\'')
                                                        
                                                        #Get a table object
                                                        table_ref = available_from_node.get_table_for_alias(alias_part)
                                                        if table_ref and hasattr(table_ref, 'get_column'):
                                                            #Get Column Object
                                                            col = table_ref.get_column(col_part)
                                                            if col:
                                                                #Create ColumnReferenceNode object
                                                                col_ref = ColumnReferenceNode(col, alias_part)
                                                                #Add to group BY
                                                                group_by.add_expression(col_ref)
                                                                
                                                except Exception as e:
                                                    print(f"  Convertpartition_byError in expression: {e}")
                                        
                                        after_count = len(group_by.expressions)
                                    if expr.metadata.get('order_by'):
                                        order_by=expr.metadata.get('order_by')
                                        before_count = len(group_by.expressions)
                                        for order in order_by:
                                            expr_parts = order.rsplit(' ', 1)
                                        if len(expr_parts) == 2 and expr_parts[1].upper() in ['ASC', 'DESC']:
                                            main_expr = expr_parts[0]
                                            main_expr = [main_expr]
                                            sort_direction = expr_parts[1]
                                        else:
                                            main_expr = order_by
                                            sort_direction = None
                                        #Try to get from_node (assuming it is available in the parent scope)
                                        if 'from_node' in locals() or 'from_node' in globals():
                                            available_from_node = locals().get('from_node') or globals().get('from_node')
                                            
                                            for part_expr in main_expr:
                                                try:
                                                    #Parsing table aliases and column names (format: table_alias.column_name)
                                                    if '.' in part_expr:
                                                        alias_part, col_part = part_expr.split('.', 1)
                                                        #Clear possible quotes
                                                        alias_part = alias_part.strip('"\'')
                                                        col_part = col_part.strip('"\'')
                                                        
                                                        #Get a table object
                                                        table_ref = available_from_node.get_table_for_alias(alias_part)
                                                        if table_ref and hasattr(table_ref, 'get_column'):
                                                            #Get Column Object
                                                            col = table_ref.get_column(col_part)
                                                            if col:
                                                                #Create ColumnReferenceNode object
                                                                col_ref = ColumnReferenceNode(col, alias_part)
                                                                #Add to group BY
                                                                group_by.add_expression(col_ref)
                                                    else:
                                                        print(f"  Alarms: Unable to Analyzeorder_byExpression Format: {part_expr}")
                                                except Exception as e:
                                                    print(f"  Convertorder_byError in expression: {e}")
                                        else:
                                            print("  Warning: the from_node object is not available，Cannot convert order_by to ColumnReferenceNode")
                                        
                                        after_count = len(group_by.expressions)
                            

                            #Check if select_node has the order_by_clause property
                            if hasattr(select_node, 'order_by_clause') and select_node.order_by_clause:
                                #Traversing expressions in order_by_clause
                                for expr, direction in select_node.order_by_clause.expressions:
                                    expr=[expr.to_sql()]
                                    #These expressions can be processed here as needed
                                    if 'from_node' in locals() or 'from_node' in globals():
                                            available_from_node = locals().get('from_node') or globals().get('from_node')
                                            for part_expr in expr:
                                                try:
                                                    #Parsing table aliases and column names (format: table_alias.column_name)
                                                    if '.' in part_expr:
                                                        alias_part, col_part = part_expr.split('.', 1)
                                                        #Clear possible quotes
                                                        alias_part = alias_part.strip('"\'')
                                                        col_part = col_part.strip('"\'')
                                                        
                                                        #Get a table object
                                                        table_ref = available_from_node.get_table_for_alias(alias_part)
                                                        if table_ref and hasattr(table_ref, 'get_column'):
                                                            #Get Column Object
                                                            col = table_ref.get_column(col_part)
                                                            if col:
                                                                #Create ColumnReferenceNode object
                                                                col_ref = ColumnReferenceNode(col, alias_part)
                                                                #Add to group BY
                                                                group_by.add_expression(col_ref)
                                                    else:
                                                        print(f"  Alarms: Unable to Analyzeorder_byExpression Format: {part_expr}")
                                                except Exception as e:
                                                    print(f"  Convertorder_byError in expression: {e}")
                                    else:
                                            print("  Warning: the from_node object is not available，Cannot convert order_by to ColumnReferenceNode")
                                        
            #Set group BY clause
            if group_by.expressions:
                select_node.group_by_clause = group_by
            #Add query to collection action
            set_op_node.add_query(select_node)
    
        #Back to collection operations SQL
        if use_cte:
            return f'{with_node.to_sql()} {set_op_node.to_sql()}'
        else:
            return set_op_node.to_sql()
    
    #Create select node
    select_node = SelectNode()
    #Initialize columns using trackers
    column_tracker = ColumnUsageTracker()
    #Randomly set the distinct attribute, 50% probability to use distinct
    if random.random() < 0.5:
        select_node.distinct = True
    select_node.tables = tables
    select_node.functions = functions
    #Save Column Tracker for later use
    select_node.metadata = {'column_tracker': column_tracker}

    #Create from clause
    from_node = FromNode()
    sql_keywords = {'use', 'select', 'from', 'where', 'group', 'by', 'order', 'limit', 'join', 'on', 'as'}


    #Use subquery based on current depth and maximum depth
    use_subquery = current_depth < _get_subquery_depth() and random.random() > 0.3
    main_alias = ''
    main_table = None

    if use_subquery and len(tables) >= 1:
        #Create subquery as main table
        subquery_select = SelectNode()

        subquery_table = random.choice(tables)
        subquery_select.tables = [subquery_table]
        
        #Generate unique internal aliases for subqueries
        subquery_inner_alias = 's' + str(random.randint(100, 999))
        
        #Generate from clause for subquery
        subquery_from = FromNode()
        subquery_from.add_table(subquery_table, subquery_inner_alias)
        subquery_select.set_from_clause(subquery_from)
        
        #Generate select expressions for subqueries (may contain aggregate functions)
        subquery_num_cols = random.randint(2, 4)  #Ensure there are at least 2 select expressions
        subquery_non_aggregate = []
        subquery_has_aggregate = False
        
        for _ in range(subquery_num_cols):
            if random.random() > 0.4 and functions:
                #Add Aggregate Function
                agg_funcs = [f for f in functions if f.func_type == 'aggregate']
                if agg_funcs:
                    func = random.choice(agg_funcs)
                    func_node = FunctionCallNode(func)
                    param_count = func.min_params
                    if func.max_params is not None and func.max_params > func.min_params:
                        param_count = random.randint(func.min_params, func.max_params)
                    def build_literal_for_type(expected_type):
                        if expected_type == 'numeric':
                            return LiteralNode(random.randint(1, 100), 'INT')
                        if expected_type == 'string':
                            return LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                        if expected_type == 'datetime':
                            return LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                        if expected_type == 'json':
                            return LiteralNode('{"key": "value"}', 'JSON')
                        if expected_type == 'binary':
                            return create_geometry_literal_node(func.name)
                        if expected_type == 'boolean':
                            return LiteralNode(random.choice([True, False]), 'BOOLEAN')
                        return LiteralNode(random.randint(1, 100), 'INT')

                    for param_index in range(param_count):
                        col_ref = None
                        expected_types = func.param_types if hasattr(func, 'param_types') else ['any']
                        raw_expected_type = expected_types[param_index] if param_index < len(expected_types) else 'any'
                        expected_type = map_param_type_to_category(raw_expected_type)
                        expected_type = adjust_expected_type_for_min_max(func.name, param_index, expected_type)
                        expected_type = adjust_expected_type_for_conditionals(func.name, param_index, expected_type)
                        
                        matching_columns = []
                        for col in subquery_table.columns:
                            col_category = normalize_category(col.category, col.data_type)
                            if expected_type == 'any' or col_category == expected_type:
                                matching_columns.append(col)
                        
                        if matching_columns:
                            available_matching_columns = []
                            for col_candidate in matching_columns:
                                if not column_tracker.is_column_used(subquery_inner_alias, col_candidate.name):
                                    available_matching_columns.append(col_candidate)
                            
                            if available_matching_columns:
                                col = random.choice(available_matching_columns)
                                column_tracker.mark_column_as_used(subquery_inner_alias, col.name)
                            else:
                                col = random.choice(matching_columns)
                            
                            col_ref = ColumnReferenceNode(col, subquery_inner_alias)
                        else:
                            if expected_type == 'any':
                                col = get_random_column_with_tracker(subquery_table, subquery_inner_alias, column_tracker, for_select=True)
                                col_ref = ColumnReferenceNode(col, subquery_inner_alias)
                            else:
                                col_ref = build_literal_for_type(expected_type)
                        
                        added = func_node.add_child(col_ref)
                        if not added:
                            func_node.add_child(build_literal_for_type(expected_type))
                    
                    alias_suffix = random.randint(1, 1000)
                    subquery_select.add_select_expression(func_node, f'{func.name.lower()}_{alias_suffix}')
                    subquery_has_aggregate = True
            else:
                #Add Normal Column
                col = get_random_column_with_tracker(subquery_table, subquery_inner_alias, column_tracker, for_select=True)
                col_ref = ColumnReferenceNode(col, subquery_inner_alias)
                subquery_select.add_select_expression(col_ref, col.name)
                subquery_non_aggregate.append(col_ref)

        #If there is an aggregate function, add the group BY clause
        if subquery_has_aggregate:
            if not subquery_non_aggregate:
                col = get_random_column_with_tracker(subquery_table, subquery_inner_alias, column_tracker, for_select=True)
                col_ref = ColumnReferenceNode(col, subquery_inner_alias)
                subquery_non_aggregate.append(col_ref)
            
            subquery_group_by = GroupByNode()
            for col_ref in subquery_non_aggregate:
                subquery_group_by.add_expression(col_ref)
            
            subquery_select.set_group_by_clause(subquery_group_by)

        #Generate a where clause for the subquery (optional)
        if random.random() > 0.5:
            col = subquery_table.get_random_column()
            col_ref = ColumnReferenceNode(col, subquery_inner_alias)
            safe_category = get_safe_comparison_category(col)
            operators = get_comparison_operators(safe_category)
            operators.extend(['IS NULL', 'IS NOT NULL'])
            operator = random.choice(operators)
            comp_node = ComparisonNode(operator)
            comp_node.add_child(col_ref)
            
            if operator not in ['IS NULL', 'IS NOT NULL']:
                if safe_category == 'numeric':
                    comp_node.add_child(LiteralNode(random.randint(0, 100), col.data_type))
                elif safe_category == 'string':
                    comp_node.add_child(LiteralNode(f"'sample_{random.randint(1, 100)}'", col.data_type))
                elif safe_category == 'datetime':
                    #Generate random datetime with hours, minutes and seconds
                    hours = random.randint(0, 23)
                    minutes = random.randint(0, 59)
                    seconds = random.randint(0, 59)
                    datetime_str = f"'2023-01-01 {hours:02d}:{minutes:02d}:{seconds:02d}'"
                    comp_node.add_child(LiteralNode(datetime_str, col.data_type))
                elif safe_category == 'binary':
                    #Generate appropriate binary literals for the binary type, using hexadecimal representation
                    binary_len = random.randint(1, 10)  #Randomly generate 1-10 bytes of binary data
                    hex_str = ''.join(random.choices('0123456789ABCDEF', k=binary_len*2))
                    comp_node.add_child(LiteralNode(f"X'{hex_str}'", col.data_type))
                elif safe_category == 'json':
                    comp_node.add_child(LiteralNode('{"key": "value"}', 'JSON'))
                elif safe_category == 'boolean':
                    comp_node.add_child(LiteralNode(random.choice([True, False]), 'BOOLEAN'))
            subquery_select.set_where_clause(comp_node)

        #Add random order BY clause
        if random.random() > 0.4:
            order_by = OrderByNode()
            if subquery_has_aggregate and subquery_non_aggregate:
                #If there is a group BY clause, select from the group BY column
                col_ref = random.choice(subquery_non_aggregate)
            else:
                #Otherwise select a random column
                col = subquery_table.get_random_column()
                col_ref = ColumnReferenceNode(col, subquery_inner_alias)
            order_by.add_expression(col_ref, random.choice(['ASC', 'DESC']))
            subquery_select.set_order_by_clause(order_by)

        #Add limit clause randomly
        if random.random() > 0.5:
            subquery_select.set_limit_clause(LimitNode(random.randint(1, 10)))

        #Generate aliases for subqueries
        base_sub_alias = 'subq'
        main_alias = base_sub_alias if base_sub_alias not in sql_keywords else 'sub' + str(random.randint(0, 9))

        #Create a subquery node and add it to the from clause
        subquery_node = SubqueryNode(subquery_select, main_alias)
        from_node.add_table(subquery_node, main_alias)
        main_table = subquery_table  #Save main table information for later processing
        #Store current depth information
        subquery_node.metadata['depth'] = current_depth + 1
    else:
        main_table = random.choice(tables)
        base_alias = main_table.name[:3].lower()
        main_alias = base_alias if base_alias not in sql_keywords else main_table.name[:2].lower() + str(random.randint(0, 9))
        from_node.add_table(main_table, main_alias)

    #Add Connection Randomly
    if random.random() > 0.3 and len(tables) > 1:
        join_table = random.choice([t for t in tables if t.name != main_table.name])
        #Generate secure connection table aliases to avoid SQL keyword conflicts
        base_join_alias = join_table.name[:3].lower()
        join_alias = base_join_alias if base_join_alias not in sql_keywords else join_table.name[:2].lower() + str(random.randint(0, 9))

        #Create connection conditions (with type checks and conversions)
        fk = next((fk for fk in join_table.foreign_keys if fk["ref_table"] == main_table.name), None)
        if fk:
            #Get the actual column object instead of creating a new one
            join_col = join_table.get_column(fk["column"])
            main_col = main_table.get_column(fk["ref_column"])
            
            if join_col and main_col:
                left_col_ref = ColumnReferenceNode(join_col, join_alias)
                right_col_ref = ColumnReferenceNode(main_col, main_alias)
                
                #Check if the column types match
                if join_col.data_type.lower() != main_col.data_type.lower():
                    #Type mismatch for explicit conversion
                    #All necessary classes have been imported at the top of the file, no partial import required
                    
                    #Determine the conversion function (cast function is used here as an example)
                    #In practical applications, it may be necessary to select the appropriate conversion function based on the database dialect and specific type
                    if main_col.category == 'numeric' and join_col.category == 'string':
                        #String to Numeric
                        cast_func = Function('CAST', 2, 2, ['any', 'string'], 'numeric', 'scalar')
                        cast_node = FunctionCallNode(cast_func)
                        cast_node.add_child(left_col_ref)
                        cast_node.add_child(LiteralNode(main_col.data_type, 'NONE'))
                        left_col_ref = cast_node
                    elif main_col.category == 'string' and join_col.category == 'numeric':
                        #Numeric Conversion String
                        cast_func = Function('CAST', 2, 2, ['any', 'string'], 'string', 'scalar')
                        cast_node = FunctionCallNode(cast_func)
                        cast_node.add_child(left_col_ref)
                        cast_node.add_child(LiteralNode(main_col.data_type, 'NONE'))
                        left_col_ref = cast_node
                    elif main_col.category == 'datetime' and join_col.category == 'string':
                        #String to datetime
                        cast_func = Function('CAST', 2, 2, ['any', 'string'], 'datetime', 'scalar')
                        cast_node = FunctionCallNode(cast_func)
                        cast_node.add_child(left_col_ref)
                        cast_node.add_child(LiteralNode(main_col.data_type, 'NONE'))
                        left_col_ref = cast_node
                    
                #Create Connection Criteria
                condition = ComparisonNode("=")
                condition.add_child(left_col_ref)
                condition.add_child(right_col_ref)
            else:
                #Fallback to original implementation if unable to get actual column objects
                left_col = ColumnReferenceNode(
                    Column(fk["column"], "", "numeric", False, join_table.name),
                    join_alias
                )
                right_col = ColumnReferenceNode(
                    Column(fk["ref_column"], "", "numeric", False, main_table.name),
                    main_alias
                )
                condition = ComparisonNode("=")
                condition.add_child(left_col)
                condition.add_child(right_col)

            from_node.add_join(
                random.choice(["INNER", "LEFT", "RIGHT", "CROSS"]),
                join_table,
                join_alias,
                condition
            )

    select_node.set_from_clause(from_node)
        #Initialize available column information for column trackers
    if select_node.metadata and 'column_tracker' in select_node.metadata:
        column_tracker = select_node.metadata['column_tracker']
        if hasattr(column_tracker, 'initialize_from_from_node'):
            column_tracker.initialize_from_from_node(from_node)


    #Verify that all column referenced aliases are valid
    valid, errors = select_node.validate_all_columns()
    if not valid:
        #Fix invalid column references if validation fails
        select_node.repair_invalid_columns()
        #Verify again
        valid, errors = select_node.validate_all_columns()
        
    #Add select expression

    num_columns = random.randint(1, 5)
    non_aggregate_columns = []  #Store non-aggregated columns
    has_aggregate_function = False  #Track whether an aggregate function is included
    used_aliases = set()  #Used to track used column aliases
    for _ in range(num_columns):
        if random.random() > 0.3 and functions:  #30% probability of using the function
            func = random.choice(functions)
            func_node = FunctionCallNode(func)

            #Adding Parameters to a Function
            #Ensure the number of parameters is within the valid range
            param_count = func.min_params
            if func.max_params is not None and func.max_params > func.min_params and not func.name.startswith('ST_'):
                param_count = random.randint(func.min_params, func.max_params)
            for param_idx in range(param_count):
                #Select the appropriate column based on the function parameter type
                expected_type = map_param_type_to_category(func.param_types[param_idx]) if param_idx < len(func.param_types) else 'any'
                expected_type = adjust_expected_type_for_min_max(func.name, param_idx, expected_type)
                expected_type = adjust_expected_type_for_conditionals(func.name, param_idx, expected_type)
                col_ref = None

                #Select columns based on main table type
                if use_subquery:
                    #Choose from column aliases for subqueries
                    subquery_node = from_node.table_references[0]
                    if hasattr(subquery_node, 'column_alias_map'):
                        #Gets the column alias of the subquery
                        valid_aliases = list(subquery_node.column_alias_map.keys())
                        tables_to_choose_with_aliases = []
                        for ref in from_node.table_references:
                            if isinstance(ref, Table):
                                tables_to_choose_with_aliases.append((ref, from_node.get_alias_for_table(ref)))
                        if not tables_to_choose_with_aliases and main_table and main_alias:
                            tables_to_choose_with_aliases = [(main_table, main_alias)]
                        #Special handling of date_format and concat functions
                        #Unify the special logic of the three functions
                        #1. special handling OF the substring function
                        if func.name == 'SUBSTRING':
                            #The first parameter must be a string type
                            if param_idx == 0:
                                #Prefer column aliases of string type
                                string_aliases = []
                                for alias in valid_aliases:
                                    _, _, category = subquery_node.column_alias_map[alias]
                                    if category == 'string':
                                        string_aliases.append(alias)
                                
                                if string_aliases:
                                    alias = random.choice(string_aliases)
                                    col_name, data_type, category = subquery_node.column_alias_map[alias]
                                    col = Column(alias, data_type, category, False, main_alias)
                                    col_ref = ColumnReferenceNode(col, main_alias)
                                else:
                                    #No string type columns, use literal strings
                                    col_ref = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                            #Second, the three parameters must be numeric types (position and length)
                            elif param_idx in [1, 2]:
                                #Generate a reasonable integer value
                                value = random.randint(1, 20) if param_idx == 1 else random.randint(1, 10)
                                col_ref = LiteralNode(value, 'INT')
                        
                        #2. Special handling of the date_format/TO_char function
                        elif (func.name == 'DATE_FORMAT' or func.name == 'TO_CHAR'):
                            #First parameter: datetime column
                            if param_idx == 0:
                                #Fix: Use correct table and alias selection (make sure table is in from clause)
                                if tables_to_choose_with_aliases:
                                    table, alias = random.choice(tables_to_choose_with_aliases)
                                    #Find Columns of Date Type
                                    date_columns = [col for col in table.columns if col.category == 'datetime']
                                    if date_columns:
                                        #Get column tracker
                                        column_tracker = select_node.metadata.get('column_tracker')
                                        if column_tracker:
                                            #Filter out unused date columns
                                            available_date_columns = []
                                            for col in date_columns:
                                                col_identifier = f"{alias}.{col.name}"
                                                if not column_tracker.is_column_used(col_identifier):
                                                    available_date_columns.append(col)
                                            
                                            if available_date_columns:
                                                col = random.choice(available_date_columns)
                                                #Mark Column Used
                                                col_identifier = f"{alias}.{col.name}"
                                                column_tracker.mark_column_used(col_identifier)
                                            else:
                                                col = random.choice(date_columns)
                                        else:
                                            col = random.choice(date_columns)
                                        col_ref = ColumnReferenceNode(col, alias)
                                    else:
                                        #Fix: Use date literal when there is no date type column
                                        col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                                else:
                                    #No tables available, use date literal
                                    col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                            #Second parameter: format string literal
                            elif param_idx == 1 and hasattr(func, 'format_string_required') and func.format_string_required:
                                #The second parameter is the format string
                                #Select the correct format according to the function type
                                if func.name == 'TO_CHAR':
                                    #PostgreSQL TO_char format
                                    format_strings = ['YYYY-MM-DD', 'YYYY-MM-DD HH24:MI:SS', 'DD-MON-YYYY', 'HH24:MI:SS']
                                else:
                                    #MySQL date_format format
                                    format_strings = ['%Y-%m-%d', '%Y-%m-%d %H:%i:%s', '%d-%b-%Y', '%H:%i:%s']
                                #Use the string type to ensure that the quotation marks are added correctly
                                col_ref = LiteralNode(random.choice(format_strings), 'STRING')
                        
                        #3. concat function special handling: make sure all parameters are of string type
                        elif func.name == 'CONCAT' and expected_type == 'string':
                            #Prefer column aliases of string type
                            string_aliases = []
                            for alias in valid_aliases:
                                _, _, category = subquery_node.column_alias_map[alias]
                                if category == 'string':
                                    string_aliases.append(alias)
                            
                            if string_aliases:
                                alias = random.choice(string_aliases)
                                col_name, data_type, category = subquery_node.column_alias_map[alias]
                                col = Column(alias, data_type, category, False, main_alias)
                                col_ref = ColumnReferenceNode(col, main_alias)
                            else:
                                #No string type columns, use literal strings
                                col_ref = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                        
                        #4. NTILE function special treatment: ensure that the parameter is a positive integer, nested functions are not allowed
                        elif func.name == 'NTILE':
                            #Generate a random integer between 1-100 as a parameter
                            col_ref = LiteralNode(random.randint(1, 100), 'INT')
                        
                        #5. Special handling of the nth_value function: the second argument must be a positive integer
                        elif func.name == 'NTH_VALUE' and param_idx == 1:
                            #Generate a random integer between 1-10 as a parameter
                            col_ref = LiteralNode(random.randint(1, 10), 'INT')
                        
                        #6. cast/convert function special handling: make sure the second parameter is a valid data type name
                        elif func.name in ['CAST', 'CONVERT']:
                            #The first argument can be any expression
                            if param_idx == 0:
                                #Preferred Column Reference
                                if tables_to_choose_with_aliases:
                                    table, alias = random.choice(tables_to_choose_with_aliases)
                                    col = table.get_random_column()
                                    #Get column tracker
                                    column_tracker = select_node.metadata.get('column_tracker')
                                    
                                    if column_tracker:
                                        col_identifier = f"{alias}.{col.name}"
                                        if not column_tracker.is_column_used(col_identifier):
                                            column_tracker.mark_column_used(col_identifier)
                                    
                                    col_ref = ColumnReferenceNode(col, alias)
                                else:
                                    #No tables available, use literal
                                    col_ref = LiteralNode(random.randint(1, 100), 'INT')
                            #The second parameter must be a valid data type name
                            elif param_idx == 1:
                                #Define some common data types
                                data_types = get_cast_types()
                                #Randomly select a data type
                                data_type = random.choice(data_types)
                                if data_type == 'CHAR':
                                    #The varchar type requires a length to be specified
                                    length = random.randint(1, 255)
                                    data_type = f"{data_type}({length})"
                                
                                #Create a LiteralNode of type string
                                col_ref = LiteralNode(data_type, "STRING")
                        
                        #7. special handling OF datetime function: arguments must BE integers from 1-6
                        elif func.name == 'DATETIME':
                            #Generate a random integer between 1-6 as a parameter
                            col_ref = LiteralNode(random.randint(1, 6), 'INT')
                        
                        #8. lead/lag function special handling: the second parameter must be an integer constant
                        elif func.name in ['LEAD', 'LAG']:
                            if param_idx == 1:  #Second parameter: offset
                                #Generate a random integer between 1-10 as offset
                                col_ref = LiteralNode(random.randint(1, 10), 'INT')
                            elif param_idx == 2:  #Third parameter: default value
                                #The default value can be null or compatible with the first parameter type
                                if random.random() < 0.5:
                                    col_ref = LiteralNode('NULL', 'NULL')
                                else:
                                    #Select a value that is compatible with the first parameter type
                                    col_ref = LiteralNode(random.randint(1, 100), 'INT')
                            else:  #First Parameter: Column Reference
                                #Preferred Column Reference
                                if tables_to_choose_with_aliases:
                                    table, alias = random.choice(tables_to_choose_with_aliases)
                                    col = table.get_random_column()
                                    #Get column tracker
                                    column_tracker = select_node.metadata.get('column_tracker')
                                    
                                    if column_tracker:
                                        col_identifier = f"{alias}.{col.name}"
                                        if not column_tracker.is_column_used(col_identifier):
                                            column_tracker.mark_column_used(col_identifier)
                                    
                                    col_ref = ColumnReferenceNode(col, alias)
                                else:
                                    #No tables available, use literal
                                    col_ref = LiteralNode(random.randint(1, 100), 'INT')
                        
                        elif func.name in ['TIMESTAMPDIFF'] and param_idx == 0:
                            
                            data_type = random.choice(['YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND'])
                            col_ref = LiteralNode(data_type, 'STRING')
                        elif func.name == 'ST_Transform' and param_idx == 1:
                            col_ref = LiteralNode(4326, 'INT')
                        elif func.name in ['JSON_VALUE', 'JSON_REMOVE', 'JSON_EXTRACT', 'JSON_SET','JSON_INSERT', 'JSON_REPLACE'] and param_idx == 1:
                            #First parameter: JSON key
                            literal = LiteralNode('$.key', 'STRING')
                            func_node.add_child(literal)
                        elif expected_type == 'string' and is_geohash_function(func.name):
                            col_ref = create_geohash_literal_node()
                        elif expected_type == 'string' and func.name.startswith('ST_') and is_wkt_function(func.name):
                            col_ref = create_wkt_literal_node(func.name)
                        elif expected_type == 'json':
                            json_aliases = [alias for alias in valid_aliases if subquery_node.column_alias_map[alias][2] == 'json']
                            if json_aliases:
                                alias = random.choice(json_aliases)
                                col_name, data_type, category = subquery_node.column_alias_map[alias]
                                col = Column(alias, data_type, category, False, main_alias)
                                col_ref = ColumnReferenceNode(col, main_alias)
                            else:
                                col_ref = LiteralNode('{"type":"Point","coordinates":[0,0]}', 'JSON')
                        elif expected_type == 'binary' and func.name.startswith('ST_'):
                            if 'FromWKB' in func.name:
                                col_ref = create_wkb_literal_node(func.name)
                            else:
                                binary_aliases = [alias for alias in valid_aliases if subquery_node.column_alias_map[alias][2] == 'binary']
                                if binary_aliases:
                                    alias = random.choice(binary_aliases)
                                    col_name, data_type, category = subquery_node.column_alias_map[alias]
                                    col = Column(alias, data_type, category, False, main_alias)
                                    col_ref = ColumnReferenceNode(col, main_alias)
                                else:
                                    col_ref = create_geometry_literal_node(func.name)
                        elif expected_type == 'boolean':
                            boolean_aliases = [alias for alias in valid_aliases if subquery_node.column_alias_map[alias][2] == 'boolean']
                            if boolean_aliases:
                                alias = random.choice(boolean_aliases)
                                col_name, data_type, category = subquery_node.column_alias_map[alias]
                                col = Column(alias, data_type, category, False, main_alias)
                                col_ref = ColumnReferenceNode(col, main_alias)
                            else:
                                col_ref = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                        elif valid_aliases:
                            #Try to find columns of matching type
                            matching_aliases = []
                            for alias in valid_aliases:
                                _, data_type, category = subquery_node.column_alias_map[alias]
                                if expected_type == 'any' or category == expected_type or (expected_type == 'numeric' and category in ['int', 'float', 'decimal']):
                                    matching_aliases.append(alias)

                            if matching_aliases:
                                alias = random.choice(matching_aliases)
                                col_name, data_type, category = subquery_node.column_alias_map[alias]
                                #Create a column reference that references a subquery column alias
                                col = Column(alias, data_type, category, False, main_alias)
                                col_ref = ColumnReferenceNode(col, main_alias)
                            else:
                                #No columns of matching type, use fallback scheme
                                if expected_type == 'numeric':
                                    col_ref = LiteralNode(random.randint(1, 100), 'INT')
                                elif expected_type == 'string':
                                    col_ref = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                                elif expected_type == 'datetime':
                                    col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                                elif expected_type == 'json':
                                    col_ref = LiteralNode('{"type":"Point","coordinates":[0,0]}', 'JSON')
                                elif expected_type == 'binary':
                                    col_ref = create_wkb_literal_node(func.name) if func.name.startswith('ST_') and 'FromWKB' in func.name else create_geometry_literal_node(func.name)
                                elif expected_type == 'boolean':
                                    col_ref = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                                else:
                                    alias = random.choice(valid_aliases)
                                    col_name, data_type, category = subquery_node.column_alias_map[alias]
                                    col = Column(alias, data_type, category, False, main_alias)
                                    col_ref = ColumnReferenceNode(col, main_alias)
                    else:
                        #Fallback scenario
                        col = main_table.get_random_column()
                        col_ref = ColumnReferenceNode(col, main_alias)
                else:
                        #Select columns from normal table
                        #Fix: Use only tables actually contained in the from clause
                        available_tables = []
                        for ref in from_node.table_references:
                            if isinstance(ref, Table):
                                available_tables.append((ref, from_node.get_alias_for_table(ref)))
                            elif isinstance(ref, SubqueryNode):
                                available_tables.append((ref, ref.alias))
                        
                        tables_to_choose_with_aliases = available_tables if available_tables else [(main_table, main_alias)]
                        #Preserve the correspondence between tables and aliases, do not create tables_to_choose variables separately
                        
                        #Special handling of date_format and concat functions
                        #Unify the special logic of the three functions
                        #1. special handling OF the substring function
                        if func.name == 'SUBSTRING':
                            #The first parameter must be a string type
                            if param_idx == 0:
                                #Prefer columns of string type
                                string_columns = []
                                for table, alias in tables_to_choose_with_aliases:
                                    for col in table.columns:
                                        if col.category == 'string':
                                            string_columns.append((table, col, alias))
                                
                                #Get column tracker
                                column_tracker = select_node.metadata.get('column_tracker')
                                
                                if string_columns:
                                    #Use column tracker to select unused columns
                                    if column_tracker:
                                        #Filter out unused columns
                                        available_string_columns = []
                                        for table, col, alias in string_columns:
                                            col_identifier = f"{alias}.{col.name}"
                                            if not column_tracker.is_column_used(col_identifier):
                                                available_string_columns.append((table, col, alias))
                                        
                                        if available_string_columns:
                                            table, col, alias = random.choice(available_string_columns)
                                            #Mark Column Used
                                            col_identifier = f"{alias}.{col.name}"
                                            column_tracker.mark_column_used(col_identifier)
                                            col_ref = ColumnReferenceNode(col, alias)
                                        else:
                                            #Fallback to random selection if no unused columns
                                            table, col, alias = random.choice(string_columns)
                                            col_ref = ColumnReferenceNode(col, alias)
                                    else:
                                        table, col, alias = random.choice(string_columns)
                                        col_ref = ColumnReferenceNode(col, alias)
                                else:
                                    #No string type columns, use literal strings
                                    col_ref = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                            #Second, the three parameters must be numeric types (position and length)
                            elif param_idx in [1, 2]:
                                #Generate a reasonable integer value
                                value = random.randint(1, 20) if param_idx == 1 else random.randint(1, 10)
                                col_ref = LiteralNode(value, 'INT')
                        
                        #2. Special handling of the date_format/TO_char function
                        elif (func.name == 'DATE_FORMAT' or func.name == 'TO_CHAR'):
                            #First parameter: datetime column
                            if param_idx == 0:
                                #Preferred column for datetime type
                                datetime_columns = []
                                for table, alias in tables_to_choose_with_aliases:
                                    for col in table.columns:
                                        if col.category == 'datetime':
                                            datetime_columns.append((table, col, alias))
                                
                                #Get column tracker
                                column_tracker = select_node.metadata.get('column_tracker')
                                
                                if datetime_columns:
                                    #Use column tracker to select unused columns
                                    if column_tracker:
                                        #Filter out unused columns
                                        available_datetime_columns = []
                                        for table, col, alias in datetime_columns:
                                            col_identifier = f"{alias}.{col.name}"
                                            if not column_tracker.is_column_used(col_identifier):
                                                available_datetime_columns.append((table, col, alias))
                                        
                                        if available_datetime_columns:
                                            table, col, alias = random.choice(available_datetime_columns)
                                            #Mark Column Used
                                            col_identifier = f"{alias}.{col.name}"
                                            column_tracker.mark_column_used(col_identifier)
                                            col_ref = ColumnReferenceNode(col, alias)
                                        else:
                                            #Fallback to random selection if no unused columns
                                            table, col, alias = random.choice(datetime_columns)
                                            col_ref = ColumnReferenceNode(col, alias)
                                    else:
                                        table, col, alias = random.choice(datetime_columns)
                                        col_ref = ColumnReferenceNode(col, alias)
                                else:
                                    #No datetime type column, use date literal
                                    col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                            #Second parameter: format string literal
                            elif param_idx == 1 and hasattr(func, 'format_string_required') and func.format_string_required:
                                #Provide a valid date format string for the date_format and TO_char functions
                                #MySQL date_format is in percentile format
                                #TO_char for PostgreSQL uses a format without a percent sign
                                if func.name == 'TO_CHAR':
                                    #PostgreSQL TO_char format
                                    format_strings = ['YYYY-MM-DD', 'YYYY-MM-DD HH24:MI:SS', 'DD-MON-YYYY', 'HH24:MI:SS']
                                else:
                                    #MySQL date_format format
                                    format_strings = ['%Y-%m-%d', '%Y-%m-%d %H:%i:%s', '%d-%b-%Y', '%H:%i:%s']
                                #Use the string type to ensure that quotation marks are added correctly and do not add single quotation marks directly to values
                                col_ref = LiteralNode(random.choice(format_strings), 'STRING')
                        
                        #3. concat function special handling: make sure all parameters are of string type
                        elif func.name == 'CONCAT' and expected_type == 'string':
                            #Prefer columns of string type
                            string_columns = []
                            for table, alias in tables_to_choose_with_aliases:
                                for col in table.columns:
                                    if col.category == 'string':
                                        string_columns.append((table, col, alias))
                            
                            #Get column tracker
                            column_tracker = select_node.metadata.get('column_tracker')
                            
                            if string_columns:
                                #Use column tracker to select unused columns
                                if column_tracker:
                                    #Filter out unused columns
                                    available_string_columns = []
                                    for table, col, alias in string_columns:
                                        col_identifier = f"{alias}.{col.name}"
                                        if not column_tracker.is_column_used(col_identifier):
                                            available_string_columns.append((table, col, alias))
                                    
                                    if available_string_columns:
                                        table, col, alias = random.choice(available_string_columns)
                                        #Mark Column Used
                                        column_tracker.mark_column_as_used(alias, col.name)
                                        col_ref = ColumnReferenceNode(col, alias)
                                    else:
                                        #Fallback to random selection if no unused columns
                                        table, col, alias = random.choice(string_columns)
                                        col_ref = ColumnReferenceNode(col, alias)
                                else:
                                    table, col, alias = random.choice(string_columns)
                                    col_ref = ColumnReferenceNode(col, alias)
                            else:
                                #No string type columns, use literal strings
                                col_ref = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                        
                        #4. NTILE function special treatment: ensure that the parameter is a positive integer, nested functions are not allowed
                        elif func.name == 'NTILE':
                            #Generate a random integer between 1-100 as a parameter
                            col_ref = LiteralNode(random.randint(1, 100), 'INT')
                        
                        #5. Special handling of the nth_value function: the second argument must be a positive integer
                        elif func.name == 'NTH_VALUE' and param_idx == 1:
                            #Generate a random integer between 1-10 as a parameter
                            col_ref = LiteralNode(random.randint(1, 10), 'INT')
                        
                        #6. cast/convert function special handling: make sure the second parameter is a valid data type name
                        elif func.name in ['CAST', 'CONVERT']:
                            #The first argument can be any expression
                            if param_idx == 0:
                                #Preferred Column Reference
                                if tables_to_choose_with_aliases:
                                    table, alias = random.choice(tables_to_choose_with_aliases)
                                    col = table.get_random_column()
                                    #Get column tracker
                                    column_tracker = select_node.metadata.get('column_tracker')
                                    
                                    if column_tracker:
                                        col_identifier = f"{alias}.{col.name}"
                                        if not column_tracker.is_column_used(col_identifier):
                                            column_tracker.mark_column_used(col_identifier)
                                    
                                    col_ref = ColumnReferenceNode(col, alias)
                                else:
                                    #No tables available, use literal
                                    col_ref = LiteralNode(random.randint(1, 100), 'INT')
                            #The second parameter must be a valid data type name
                            elif param_idx == 1:
                                #Define some common data types
                                data_types = get_cast_types()
                                #Randomly select a data type
                                data_type = random.choice(data_types)
                                if data_type == 'CHAR':
                                    #The varchar type requires a length to be specified
                                    length = random.randint(1, 255)
                                    data_type = f"{data_type}({length})"
                                
                                #Create a LiteralNode of type string
                                col_ref = LiteralNode(data_type, "STRING")
                        
                        #7. special handling OF datetime function: arguments must BE integers from 1-6
                        elif func.name == 'DATETIME':
                            #Generate a random integer between 1-6 as a parameter
                            col_ref = LiteralNode(random.randint(1, 6), 'INT')
                        
                        #8. lead/lag function special handling: the second parameter must be an integer constant
                        elif func.name in ['LEAD', 'LAG']:
                            if param_idx == 1:  #Second parameter: offset
                                #Generate a random integer between 1-10 as offset
                                col_ref = LiteralNode(random.randint(1, 10), 'INT')
                            elif param_idx == 2:  #Third parameter: default value
                                #The default value can be null or compatible with the first parameter type
                                if random.random() < 0.5:
                                    col_ref = LiteralNode('NULL', 'NULL')
                                else:
                                    #Select a value that is compatible with the first parameter type
                                    col_ref = LiteralNode(random.randint(1, 100), 'INT')
                            else:  #First Parameter: Column Reference
                                #Preferred Column Reference
                                if tables_to_choose_with_aliases:
                                    table, alias = random.choice(tables_to_choose_with_aliases)
                                    col = table.get_random_column()
                                    #Get column tracker
                                    column_tracker = select_node.metadata.get('column_tracker')
                                    
                                    if column_tracker:
                                        col_identifier = f"{alias}.{col.name}"
                                        if not column_tracker.is_column_used(col_identifier):
                                            column_tracker.mark_column_used(col_identifier)
                                    
                                    col_ref = ColumnReferenceNode(col, alias)
                                else:
                                    #No tables available, use literal
                                    col_ref = LiteralNode(random.randint(1, 100), 'INT')
                        
                        
                        elif func.name in ['TIMESTAMPDIFF'] and param_idx == 0:

                            data_type = random.choice(['YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND'])
                            col_ref = LiteralNode(data_type, 'STRING')
                        elif func.name == 'ST_Transform' and param_idx == 1:
                            col_ref = LiteralNode(4326, 'INT')
                        elif func.name in ['JSON_VALUE', 'JSON_REMOVE', 'JSON_EXTRACT', 'JSON_SET','JSON_INSERT', 'JSON_REPLACE'] and param_idx == 1:
                            #First parameter: JSON key
                            literal = LiteralNode('$.key', 'STRING')
                            func_node.add_child(literal)
                        elif expected_type == 'string' and is_geohash_function(func.name):
                            col_ref = create_geohash_literal_node()
                        elif expected_type == 'string' and func.name.startswith('ST_') and is_wkt_function(func.name):
                            col_ref = create_wkt_literal_node(func.name)
                        elif expected_type == 'json':
                            json_columns = []
                            for table, alias in tables_to_choose_with_aliases:
                                for col in table.columns:
                                    if col.category == 'json':
                                        json_columns.append((table, col, alias))
                            if json_columns:
                                table, col, alias = random.choice(json_columns)
                                col_ref = ColumnReferenceNode(col, alias)
                            else:
                                col_ref = LiteralNode('{"type":"Point","coordinates":[0,0]}', 'JSON')
                        elif expected_type == 'binary' and func.name.startswith('ST_'):
                            if 'FromWKB' in func.name:
                                col_ref = create_wkb_literal_node(func.name)
                            else:
                                geometry_columns = []
                                for table, alias in tables_to_choose_with_aliases:
                                    for col in table.columns:
                                        if is_geometry_type(col.data_type):
                                            geometry_columns.append((table, col, alias))
                                if geometry_columns:
                                    table, col, alias = random.choice(geometry_columns)
                                    col_ref = ColumnReferenceNode(col, alias)
                                else:
                                    col_ref = create_geometry_literal_node(func.name)
                        elif expected_type == 'boolean':
                            boolean_columns = []
                            for table, alias in tables_to_choose_with_aliases:
                                for col in table.columns:
                                    if col.category == 'boolean':
                                        boolean_columns.append((table, col, alias))
                            if boolean_columns:
                                table, col, alias = random.choice(boolean_columns)
                                col_ref = ColumnReferenceNode(col, alias)
                            else:
                                col_ref = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                        else:
                            #Try to find columns of matching type
                            matching_columns = []
                            for table, alias in tables_to_choose_with_aliases:
                                for col in table.columns:
                                    if expected_type == 'any' or col.category == expected_type or (expected_type == 'numeric' and col.category in ['int', 'float', 'decimal']):
                                        matching_columns.append((table, col, alias))

                            #Get column tracker
                            column_tracker = select_node.metadata.get('column_tracker')

                            if matching_columns:
                                #Use column tracker to select unused columns
                                if column_tracker:
                                    #Filter out unused columns
                                    available_matching_columns = []
                                    for table, col, alias in matching_columns:
                                        col_identifier = f"{alias}.{col.name}"
                                        if not column_tracker.is_column_used(col_identifier):
                                            available_matching_columns.append((table, col, alias))
                                    
                                    if available_matching_columns:
                                        table, col, alias = random.choice(available_matching_columns)
                                        #Mark Column Used
                                        column_tracker.mark_column_as_used(alias, col.name)
                                        col_ref = ColumnReferenceNode(col, alias)
                                    else:
                                        #Fallback to random selection if no unused columns
                                        table, col, alias = random.choice(matching_columns)
                                        col_ref = ColumnReferenceNode(col, alias)
                                else:
                                    table, col, alias = random.choice(matching_columns)
                                    col_ref = ColumnReferenceNode(col, alias)
                            else:
                                #No columns of matching type, use fallback scheme
                                if expected_type == 'numeric':
                                    col_ref = LiteralNode(random.randint(1, 100), 'INT')
                                elif expected_type == 'string':
                                    col_ref = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                                elif expected_type == 'datetime':
                                    col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                                elif expected_type == 'json':
                                    col_ref = LiteralNode('{"type":"Point","coordinates":[0,0]}', 'JSON')
                                elif expected_type == 'binary':
                                    col_ref = create_wkb_literal_node(func.name) if func.name.startswith('ST_') and 'FromWKB' in func.name else create_geometry_literal_node(func.name)
                                elif expected_type == 'boolean':
                                    col_ref = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                                else:
                                    table, alias = random.choice(tables_to_choose_with_aliases)
                                    col = table.get_random_column()
                                    col_ref = ColumnReferenceNode(col, alias)
                #Make sure aggregate functions always have parameters
                if func.func_type == 'aggregate':
                    #Enhanced Parameter Guarantee Mechanism
                    if not col_ref:
                        if use_subquery:
                            subquery_node = from_node.table_references[0]
                            if hasattr(subquery_node, 'column_alias_map') and subquery_node.column_alias_map:
                                valid_aliases = list(subquery_node.column_alias_map.keys())
                                candidate_aliases = valid_aliases
                                if expected_type != 'any':
                                    candidate_aliases = []
                                    for alias in valid_aliases:
                                        _, data_type, category = subquery_node.column_alias_map[alias]
                                        if normalize_category(category, data_type) == expected_type:
                                            candidate_aliases.append(alias)
                                if candidate_aliases:
                                    alias = random.choice(candidate_aliases)
                                    col_name, data_type, category = subquery_node.column_alias_map[alias]
                                    col = Column(alias, data_type, category, False, main_alias)
                                    col_ref = ColumnReferenceNode(col, main_alias)
                                else:
                                    if expected_type == 'numeric':
                                        col_ref = LiteralNode(random.randint(1, 100), 'INT')
                                    elif expected_type == 'string':
                                        col_ref = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                                    elif expected_type == 'datetime':
                                        col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                                    elif expected_type == 'json':
                                        col_ref = LiteralNode('{"type":"Point","coordinates":[0,0]}', 'JSON')
                                    elif expected_type == 'binary':
                                        col_ref = create_wkb_literal_node(func.name) if func.name.startswith('ST_') and 'FromWKB' in func.name else create_geometry_literal_node(func.name)
                                    elif expected_type == 'boolean':
                                        col_ref = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                                    else:
                                        col_ref = LiteralNode(random.randint(1, 100), 'INT')
                            else:
                                #Subquery has no column alias mapping, use main table column directly
                                if expected_type != 'any':
                                    matching = [col for col in main_table.columns if normalize_category(col.category, col.data_type) == expected_type]
                                    if matching:
                                        col = random.choice(matching)
                                        col_ref = ColumnReferenceNode(col, main_alias)
                                    elif expected_type == 'numeric':
                                        col_ref = LiteralNode(random.randint(1, 100), 'INT')
                                    elif expected_type == 'string':
                                        col_ref = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                                    elif expected_type == 'datetime':
                                        col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                                    elif expected_type == 'json':
                                        col_ref = LiteralNode('{"type":"Point","coordinates":[0,0]}', 'JSON')
                                    elif expected_type == 'binary':
                                        col_ref = create_wkb_literal_node(func.name) if func.name.startswith('ST_') and 'FromWKB' in func.name else create_geometry_literal_node(func.name)
                                    elif expected_type == 'boolean':
                                        col_ref = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                                else:
                                    col = main_table.get_random_column()
                                    col_ref = ColumnReferenceNode(col, main_alias)
                        else:
                            #Select columns from available tables
                            if tables_to_choose:
                                #Make sure the selected table and alias are valid in the from clause
                                valid_table_found = False
                                while not valid_table_found and tables_to_choose:
                                    table = random.choice(tables_to_choose)
                                    alias = main_alias if table == main_table else join_alias
                                    #Verify that the alias is defined in the from clause
                                    if from_node.get_table_for_alias(alias):
                                        if expected_type != 'any':
                                            matching = [c for c in table.columns if normalize_category(c.category, c.data_type) == expected_type]
                                            if matching:
                                                col = random.choice(matching)
                                                col_ref = ColumnReferenceNode(col, alias)
                                            elif expected_type == 'numeric':
                                                col_ref = LiteralNode(random.randint(1, 100), 'INT')
                                            elif expected_type == 'string':
                                                col_ref = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                                            elif expected_type == 'datetime':
                                                col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                                            elif expected_type == 'json':
                                                col_ref = LiteralNode('{"type":"Point","coordinates":[0,0]}', 'JSON')
                                            elif expected_type == 'binary':
                                                col_ref = create_wkb_literal_node(func.name) if func.name.startswith('ST_') and 'FromWKB' in func.name else create_geometry_literal_node(func.name)
                                            elif expected_type == 'boolean':
                                                col_ref = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                                        else:
                                            col = table.get_random_column()
                                            col_ref = ColumnReferenceNode(col, alias)
                                        valid_table_found = True
                                    else:
                                        #Remove the table from the selection list if the alias is not valid
                                        tables_to_choose.remove(table)
                                #If all tables are invalid, use the main table
                                if not valid_table_found and main_table:
                                    alias = main_alias
                                    col = main_table.get_random_column()
                                    col_ref = ColumnReferenceNode(col, alias)
                            else:
                                #No tables available, create literal parameters
                                if expected_type == 'numeric':
                                    col_ref = LiteralNode(random.randint(1, 100), 'INT')
                                elif expected_type == 'string':
                                    col_ref = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                                elif expected_type == 'datetime':
                                    col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                                elif expected_type == 'json':
                                    col_ref = LiteralNode('{"type":"Point","coordinates":[0,0]}', 'JSON')
                                elif expected_type == 'binary':
                                    col_ref = create_wkb_literal_node(func.name) if func.name.startswith('ST_') and 'FromWKB' in func.name else create_geometry_literal_node(func.name)
                                elif expected_type == 'boolean':
                                    col_ref = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                                else:
                                    #Defaults to a numeric type
                                    col_ref = LiteralNode(random.randint(1, 100), 'INT')
                    #Ultimate Guarantee: Use literals directly if all column reference schemes fail
                    if not col_ref:
                        if expected_type == 'numeric':
                            col_ref = LiteralNode(random.randint(1, 100), 'INT')
                        elif expected_type == 'string':
                            col_ref = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                        elif expected_type == 'datetime':
                            col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                        elif expected_type == 'json':
                            col_ref = LiteralNode('{"type":"Point","coordinates":[0,0]}', 'JSON')
                        elif expected_type == 'binary':
                            col_ref = create_wkb_literal_node(func.name) if func.name.startswith('ST_') and 'FromWKB' in func.name else create_geometry_literal_node(func.name)
                        elif expected_type == 'boolean':
                            col_ref = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                        else:
                            #Defaults to a numeric type
                            col_ref = LiteralNode(random.randint(1, 100), 'INT')

                #Add parameters and check if the types match
                added = func_node.add_child(col_ref)
                if not added:
                    #If the types do not match, try to find columns of other matching types
                    found_matching_column = False
                    #Try to find columns of matching type from available tables
                    for _ in range(3):  #3 attempts to find columns of matching type
                        try:
                            #Choose from the available tables
                            tables_to_try = available_tables if available_tables else [(main_table, main_alias)]
                            table, alias = random.choice(tables_to_try)
                            #Gets the column that matches the expected type
                            matching_cols = []
                            for c in table.columns:
                                #Simple type matching logic
                                if (expected_type == 'numeric' and c.category == 'numeric') or \
                                   (expected_type == 'string' and c.category == 'string') or \
                                   (expected_type == 'datetime' and c.category in ['datetime', 'date', 'timestamp']) or \
                                   (expected_type == 'binary' and c.category == 'binary') or \
                                   (expected_type == 'json' and c.category == 'json') or \
                                   (expected_type == 'boolean' and c.category == 'boolean') or \
                                   expected_type == 'any':
                                    matching_cols.append(c)
                            
                            if matching_cols:
                                matched_col = random.choice(matching_cols)
                                matched_col_ref = ColumnReferenceNode(matched_col, alias)
                                #Try adding columns of matching type again
                                if func_node.add_child(matched_col_ref):
                                    found_matching_column = True
                                    break
                        except Exception:
                            #If something went wrong during the lookup, keep trying
                            continue
                    
                    #Use literals if no columns of the matching type are found
                    if not found_matching_column:
                        if expected_type == 'numeric':
                            literal = LiteralNode(random.randint(1, 100), 'INT')
                            func_node.add_child(literal)
                        elif expected_type == 'string':
                            literal = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                            func_node.add_child(literal)
                        elif expected_type == 'datetime':
                            literal = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                            func_node.add_child(literal)
                        elif expected_type == 'json':
                            literal = LiteralNode('{"type":"Point","coordinates":[0,0]}', 'JSON')
                            func_node.add_child(literal)
                        elif expected_type == 'binary':
                            literal = create_wkb_literal_node(func.name) if func.name.startswith('ST_') and 'FromWKB' in func.name else create_geometry_literal_node(func.name)
                            func_node.add_child(literal)
                        elif expected_type == 'boolean':
                            literal = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                            func_node.add_child(literal)
                        else:
                            #Last fallback scenario, using legacy column references
                            func_node.children.append(col_ref)

                #Special Safeguards: Ensure that the function has sufficient parameters
                #Handling the concat function
                if func.name == 'CONCAT' and len(func_node.children) < func.min_params:
                    #Add missing string literal parameter
                    while len(func_node.children) < func.min_params:
                        literal = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                        func_node.add_child(literal)

                #If the function is not an aggregate function, add a column reference to the list of non-aggregate columns
                if func.func_type != 'aggregate':
                    if col_ref is not None:
                        non_aggregate_columns.append(col_ref)

            #Deduplication using an external used_aliases collection
            counter = 1
            base_alias = f"col_{counter}"
            current_alias = base_alias
            counter += 1
            # ，
            max_attempts = 1000
            attempts = 0
            while current_alias in used_aliases and attempts < max_attempts:
                current_alias = f"{base_alias}_{counter}"
                counter += 1
                attempts += 1
            #If the maximum number of attempts is reached, use a random string as the alias
            if attempts >= max_attempts:
                current_alias = f"{base_alias}_{random.randint(1000, 9999)}"
            used_aliases.add(current_alias)
            #Set the flag whenever an aggregate function is added, regardless of the parameter type of the aggregate function
            select_node.add_select_expression(func_node, current_alias)
            if func.func_type == 'aggregate':
                has_aggregate_function = True
            #Ensure that the flag is also set correctly when the aggregate function parameter is a subquery column
            if func.func_type == 'aggregate' and use_subquery:
                has_aggregate_function = True
        else:  #Otherwise use simple columns
            #Select columns based on main table type
            #Get column tracker
            column_tracker = select_node.metadata.get('column_tracker')
            literal_selected = False

            if random.random() < 0.2:
                col_ref = _create_select_constant_literal()
                literal_selected = True
            elif use_subquery:
                #Choose from column aliases for subqueries
                subquery_node = from_node.table_references[0]
                if hasattr(subquery_node, 'column_alias_map'):
                    #Gets the column alias of the subquery
                    valid_aliases = list(subquery_node.column_alias_map.keys())
                    if valid_aliases:
                        #Use column tracker to select unused columns
                        if column_tracker:
                            #Filter out unused columns
                            available_aliases = []
                            for alias in valid_aliases:
                                col_name, data_type, category = subquery_node.column_alias_map[alias]
                                col_identifier = f"{main_alias}.{alias}"
                                if not column_tracker.is_column_used(col_identifier):
                                    available_aliases.append(alias)
                            
                            if available_aliases:
                                alias = random.choice(available_aliases)
                                col_name, data_type, category = subquery_node.column_alias_map[alias]
                                #Create a column reference that references a subquery column alias
                                col = Column(alias, data_type, category, False, main_alias)
                                #Mark Column Used
                                col_identifier = f"{main_alias}.{alias}"
                                column_tracker.mark_column_as_filter(main_alias, alias)
                                col_ref = ColumnReferenceNode(col, main_alias)
                            else:
                                #Fallback to random selection if no unused columns
                                alias = random.choice(valid_aliases)
                                col_name, data_type, category = subquery_node.column_alias_map[alias]
                                col = Column(alias, data_type, category, False, main_alias)
                                col_ref = ColumnReferenceNode(col, main_alias)
                        else:
                            alias = random.choice(valid_aliases)
                            col_name, data_type, category = subquery_node.column_alias_map[alias]
                            col = Column(alias, data_type, category, False, main_alias)
                            col_ref = ColumnReferenceNode(col, main_alias)
                    else:
                        #Fallback scenario
                        col = main_table.get_random_column()
                        col_ref = ColumnReferenceNode(col, main_alias)
                else:
                    #Fallback scenario
                    col = main_table.get_random_column()
                    col_ref = ColumnReferenceNode(col, main_alias)
            else:
                #Select columns from normal table
                #Fix: Use only tables actually contained in the from clause
                available_tables = []
                for ref in from_node.table_references:
                    if isinstance(ref, Table):
                        available_tables.append((ref, from_node.get_alias_for_table(ref)))
                    elif isinstance(ref, SubqueryNode):
                        available_tables.append((ref, ref.alias))
                
                tables_to_choose_with_aliases = available_tables if available_tables else [(main_table, main_alias)]
                
                #Use column tracker to select unused columns
                if column_tracker:
                    #Filter out unused columns
                    available_columns = []
                    for table, alias in tables_to_choose_with_aliases:
                        for col in table.columns:
                            col_identifier = f"{alias}.{col.name}"
                            if not column_tracker.is_column_used(col_identifier):
                                available_columns.append((table, col, alias))
                    
                    if available_columns:
                        table, col, alias = random.choice(available_columns)
                        #Mark Column Used
                        col_identifier = f"{alias}.{col.name}"
                        column_tracker.mark_column_used(col_identifier)
                        col_ref = ColumnReferenceNode(col, alias)
                    else:
                        #Fallback to random selection if no unused columns
                        table, alias = random.choice(tables_to_choose_with_aliases)
                        col = table.get_random_column()
                        col_ref = ColumnReferenceNode(col, alias)
                else:
                    table, alias = random.choice(tables_to_choose_with_aliases)
                    col = table.get_random_column()
                    col_ref = ColumnReferenceNode(col, alias)
            #Add alias deduplication logic for simple columns
            base_alias = "const_value" if literal_selected else col.name
            current_alias = base_alias
            counter = 1
            while current_alias in used_aliases:
                current_alias = f"{base_alias}_{counter}"
                counter += 1
            used_aliases.add(current_alias)
            select_node.add_select_expression(col_ref, current_alias)
            if col_ref is not None:
                non_aggregate_columns.append(col_ref)

    #randomly adding a where clause,
    # col_ref
    if use_subquery:
            #Choose from column aliases for subqueries
            subquery_node = from_node.table_references[0]
            if hasattr(subquery_node, 'column_alias_map'):
                #Gets the column alias of the subquery
                valid_aliases = list(subquery_node.column_alias_map.keys())
                if valid_aliases:
                    alias = random.choice(valid_aliases)
                    col_name, data_type, category = subquery_node.column_alias_map[alias]
                    #Create a column reference that references a subquery column alias
                    #Create subquery column references with correct column names and aliases
                    col = Column(alias, data_type, category, False, main_alias)
                    col_ref = ColumnReferenceNode(col, main_alias)
                else:
                    #Fallback scenario
                    #Choose from the tables actually contained in the from clause
                    available_tables = []
                    for ref in from_node.table_references:
                        if isinstance(ref, Table):
                            available_tables.append((ref, from_node.get_alias_for_table(ref)))
                        elif isinstance(ref, SubqueryNode):
                            available_tables.append((ref, ref.alias))
                    
                    tables_to_choose_with_aliases = available_tables if available_tables else [(main_table, main_alias)]
                    
                    table, alias = random.choice(tables_to_choose_with_aliases)
                    col = table.get_random_column()
                    col_ref = ColumnReferenceNode(col, alias)
            else:
                #Fallback scenario
                #Choose from the tables actually contained in the from clause
                available_tables = []
                for ref in from_node.table_references:
                    if isinstance(ref, Table):
                        available_tables.append((ref, from_node.get_alias_for_table(ref)))
                    elif isinstance(ref, SubqueryNode):
                        available_tables.append((ref, ref.alias))
                
                tables_to_choose_with_aliases = available_tables if available_tables else [(main_table, main_alias)]
                
                table, alias = random.choice(tables_to_choose_with_aliases)
                col = table.get_random_column()
                col_ref = ColumnReferenceNode(col, alias)
    else:
            #Choose from the tables actually contained in the from clause
            available_tables = []
            for ref in from_node.table_references:
                if isinstance(ref, Table):
                    available_tables.append((ref, from_node.get_alias_for_table(ref)))
                elif isinstance(ref, SubqueryNode):
                    available_tables.append((ref, ref.alias))
            
            tables_to_choose_with_aliases = available_tables if available_tables else [(main_table, main_alias)]
            
            table, alias = random.choice(tables_to_choose_with_aliases)
            col = table.get_random_column()
            col_ref = ColumnReferenceNode(col, alias)
    #Add the where clause only if random.random () > 0.2
    if random.random() > 0.2:
        #Use the create_where_condition function to generate where conditions, support rich conditions such as subqueries
        where_node = create_where_condition(
            tables, functions, from_node, main_table, main_alias,
            join_table if 'join_table' in locals() else None, 
            join_alias if 'join_alias' in locals() else None,
            use_subquery=use_subquery,
            column_tracker=select_node.metadata.get('column_tracker')
        )
        select_node.set_where_clause(where_node)

    #Add group BY clause if there is an aggregate function
    #Use the unified flag has_aggregate_function to trigger group BY generation
    if has_aggregate_function:
        group_by = GroupByNode()
        #Initialize collection of added columns
        added_columns = set()
        #Add 0-1 additional randomized columns (only output columns from existing tables and sub-queries in the query)
        additional_groups = random.randint(0, 1)
        available_columns = []

        #For subqueries, add only the columns (column aliases) of the subquery output
        if use_subquery and hasattr(from_node.table_references[0], 'column_alias_map'):
            subquery_node = from_node.table_references[0]
            for alias, (col_name, data_type, category) in subquery_node.column_alias_map.items():
                #Create a virtual list to show the output column of the sub-query, using the alias as the column name
                #Create subquery column references with correct column names and aliases
                col = Column(alias, data_type, category, False, main_alias)
                available_columns.append((col, main_alias))
        else:
            #Add columns for main table and join table
            if 'main_table' in locals():
                for col in main_table.columns:
                    available_columns.append((col, main_alias))
            if 'join_table' in locals():
                for col in join_table.columns:
                    available_columns.append((col, join_alias))
        


        #Add having clause
        if random.random() > 0.5:
            if random.random() < 0.2:
                having_node = ComparisonNode('=')
                having_node.add_child(LiteralNode(1, 'INT'))
                having_node.add_child(LiteralNode(1 if random.random() < 0.5 else 0, 'INT'))
                select_node.set_having_clause(having_node)
            else:
                agg_funcs = [f for f in functions if f.func_type == 'aggregate']
                if agg_funcs:
                    agg_func = random.choice(agg_funcs)
                    func_node = FunctionCallNode(agg_func)
                    column_tracker = select_node.metadata.get('column_tracker')
                    numeric_required = agg_func.name in [
                        'SUM', 'AVG', 'STD', 'STDDEV', 'STDDEV_POP', 'STDDEV_SAMP',
                        'VARIANCE', 'VAR_SAMP', 'VAR_POP', 'SUM_DISTINCT',
                        'BIT_AND', 'BIT_OR', 'BIT_XOR'
                    ]
                    param_added = False

                    if use_subquery and hasattr(from_node.table_references[0], 'column_alias_map'):
                        subquery_node = from_node.table_references[0]
                        valid_aliases = list(subquery_node.column_alias_map.keys())
                        if valid_aliases:
                            candidate_aliases = valid_aliases
                            if numeric_required:
                                candidate_aliases = [
                                    alias for alias in valid_aliases
                                    if normalize_category(
                                        subquery_node.column_alias_map[alias][2],
                                        subquery_node.column_alias_map[alias][1],
                                    ) == 'numeric'
                                ]
                                if not candidate_aliases:
                                    func_node.add_child(LiteralNode(random.randint(1, 100), 'INT'))
                                    param_added = True

                            if not param_added:
                                if column_tracker:
                                    available_aliases = []
                                    for alias in candidate_aliases:
                                        col_name, data_type, category = subquery_node.column_alias_map[alias]
                                        col_identifier = f"{main_alias}.{alias}"
                                        if not column_tracker.is_column_used(col_identifier):
                                            available_aliases.append(alias)

                                    if available_aliases:
                                        alias = random.choice(available_aliases)
                                    else:
                                        alias = random.choice(candidate_aliases)
                                else:
                                    alias = random.choice(candidate_aliases)

                                col_name, data_type, category = subquery_node.column_alias_map[alias]
                                col = Column(alias, data_type, category, False, main_alias)
                                if column_tracker:
                                    column_tracker.mark_column_as_filter(main_alias, alias)
                                func_node.add_child(ColumnReferenceNode(col, main_alias))
                                param_added = True
                        else:
                            col = main_table.get_random_column()
                            func_node.add_child(ColumnReferenceNode(col, main_alias))
                            param_added = True
                    else:
                        valid_columns = main_table.columns
                        if agg_func.name in ['SUM', 'AVG']:
                            valid_columns = [col for col in main_table.columns if col.category == 'numeric']
                        elif agg_func.name in ['MAX', 'MIN']:
                            valid_columns = [col for col in main_table.columns if col.category in ['numeric', 'datetime', 'string']]
                        elif agg_func.name == 'COUNT':
                            valid_columns = main_table.columns
                        else:
                            valid_columns = [col for col in main_table.columns if col.category == 'numeric']

                        if numeric_required and not valid_columns:
                            func_node.add_child(LiteralNode(random.randint(1, 100), 'INT'))
                            param_added = True
                        if not param_added and column_tracker:
                            available_columns = []
                            for col in valid_columns:
                                col_identifier = f"{main_alias}.{col.name}"
                                if not column_tracker.is_column_used(col_identifier):
                                    available_columns.append(col)

                            if available_columns:
                                col = random.choice(available_columns)
                                column_tracker.mark_column_as_filter(main_alias, col.name)
                                func_node.add_child(ColumnReferenceNode(col, main_alias))
                                param_added = True
                            elif valid_columns:
                                col = random.choice(valid_columns)
                                func_node.add_child(ColumnReferenceNode(col, main_alias))
                                param_added = True
                        elif not param_added:
                            if valid_columns:
                                col = random.choice(valid_columns)
                            else:
                                col = main_table.get_random_column()
                            func_node.add_child(ColumnReferenceNode(col, main_alias))
                            param_added = True

                    agg_return_category = map_return_type_to_category(agg_func.return_type)
                    operators = get_comparison_operators(agg_return_category)
                    operators.extend(['IS NULL', 'IS NOT NULL'])
                    operator = random.choice(operators)
                    having_node = ComparisonNode(operator)
                    having_node.add_child(func_node)

                    if operator not in ['IS NULL', 'IS NOT NULL']:
                        if agg_return_category == 'numeric':
                            literal_value = random.randint(0, 10)
                            literal_type = 'INT'
                            if agg_func.name == 'COUNT':
                                literal_value = random.randint(0, 5)
                            elif agg_func.name in ['AVG', 'SUM']:
                                literal_type = 'DECIMAL'
                                literal_value = round(random.uniform(0, 10), 2)
                            having_node.add_child(LiteralNode(literal_value, literal_type))
                        elif agg_return_category == 'datetime':
                            having_node.add_child(LiteralNode('2023-01-01 12:00:00', 'DATETIME'))
                        elif agg_return_category == 'string':
                            having_node.add_child(LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING'))
                        elif agg_return_category == 'json':
                            having_node.add_child(LiteralNode('{"key": "value"}', 'JSON'))
                        elif agg_return_category == 'binary':
                            hex_value = ''.join(random.choices('0123456789ABCDEF', k=8))
                            having_node.add_child(LiteralNode(f"X'{hex_value}'", 'BINARY'))
                        elif agg_return_category == 'boolean':
                            having_node.add_child(LiteralNode(random.choice([True, False]), 'BOOLEAN'))
                        else:
                            having_node.add_child(LiteralNode(random.randint(0, 10), 'INT'))

                    select_node.set_having_clause(having_node)
            select_node.set_having_clause(having_node)

    #Add random order BY clause
    if random.random() > 0.4:
        order_by = OrderByNode()
        #Check for group BY clause
        if has_aggregate_function and select_node.group_by_clause:
            #There is a group BY clause, only group BY columns or aggregate functions can be selected
            valid_order_columns = []
            
            #Add group BY column
            if hasattr(select_node.group_by_clause, 'expressions'):
                valid_order_columns.extend(select_node.group_by_clause.expressions)
            
            #Add Aggregate Function
            for expr, _ in select_node.select_expressions:
                if hasattr(expr, 'metadata') and expr.metadata.get('is_aggregate', False):
                    valid_order_columns.append(expr)
            
            #Ensure there is at least one valid order BY column
            if valid_order_columns:
                #Select from active columns
                expr = random.choice(valid_order_columns)
                order_by.add_expression(expr, random.choice(["ASC", "DESC"]))
                select_node.set_order_by_clause(order_by)
        elif not (has_aggregate_function and select_node.group_by_clause) and use_subquery and hasattr(from_node.table_references[0], 'column_alias_map'):
            #Choose from column aliases for subqueries
            subquery_node = from_node.table_references[0]
            valid_aliases = list(subquery_node.column_alias_map.keys())
            if valid_aliases:
                alias = random.choice(valid_aliases)
                col_name, data_type, category = subquery_node.column_alias_map[alias]
                #Create subquery column references with correct column names and aliases
                col = Column(alias, data_type, category, False, main_alias)
                expr = ColumnReferenceNode(col, main_alias)
                
                #Check if distinct is used and if so, make sure the columns for order BY are in the select list
                if select_node.distinct:
                    #Check if it is already in the select list
                    in_select = False
                    for selected_expr, selected_alias in select_node.select_expressions:
                        if hasattr(selected_expr, 'to_sql') and selected_expr.to_sql() == expr.to_sql():
                            in_select = True
                            break
                    
                    #Add if not in select list
                    if not in_select:
                        select_node.add_select_expression(expr, alias)
                
                order_by.add_expression(expr, random.choice(["ASC", "DESC"]))
                select_node.set_order_by_clause(order_by)
        elif not (has_aggregate_function and select_node.group_by_clause):
            #Select columns from main table
            col = main_table.get_random_column()
            expr = ColumnReferenceNode(col, main_alias)
            
            #Check if distinct is used and if so, make sure the columns for order BY are in the select list
            if select_node.distinct:
                #Check if it is already in the select list
                in_select = False
                for selected_expr, selected_alias in select_node.select_expressions:
                    if hasattr(selected_expr, 'to_sql') and selected_expr.to_sql() == expr.to_sql():
                        in_select = True
                        break
                
                #Add if not in select list
                if not in_select:
                    select_node.add_select_expression(expr, col.name)
            
            order_by.add_expression(expr, random.choice(["ASC", "DESC"]))
            select_node.set_order_by_clause(order_by)

    #Add limit clause randomly
    if random.random() > 0.5 and not has_aggregate_function:
        select_node.set_limit_clause(LimitNode(random.randint(1, 10)))

    #Add lock clause randomly (~ 30% probability)
    if random.random() > 0.7:
        # 
        lock_modes = ['update', 'share', 'no key update', 'key share']
        selected_mode = random.choice(lock_modes)
        select_node.set_for_update(selected_mode)

    # SQL
    valid, errors = select_node.validate_all_columns()
    if not valid:
        select_node.repair_invalid_columns()
    #Simplified column reference handler - removed column validity check
    def validate_column_references(node, available_tables, used_aliases):
        # FROM，
        if isinstance(node, SubqueryNode):
            if hasattr(node, 'repair_columns'):
                node.repair_columns(None)
            return
        # 
        for child in getattr(node, 'children', []):
            validate_column_references(child, available_tables, used_aliases)

        # 
        if hasattr(node, 'table_alias') and hasattr(node, 'column'):
            # ，
            table_alias = node.table_alias
            if table_alias not in available_tables and available_tables:
                # ：
                new_alias = list(available_tables.keys())[0]
                node.table_alias = new_alias

    # SQL
    def fix_all_function_params(select_node, main_table, join_table=None, main_alias=None, join_alias=None):
    # 
        available_tables = {}
        if main_table and main_alias:
            available_tables[main_alias] = main_table
        if join_table and join_alias:
            available_tables[join_alias] = join_table

        # （ON）
        validate_column_references(select_node, available_tables, {})

        # ON
        if hasattr(select_node, 'from_clause') and hasattr(select_node.from_clause, 'joins'):
            for join in select_node.from_clause.joins:
                condition = join.get('condition')
                if condition:
                    validate_column_references(condition, available_tables, {})


        # 

    # GROUP BYSELECT - only_full_group_by
    # ，only_full_group_by
    # has_aggregate_function
    if has_aggregate_function:
        # SELECT
        all_agg = all(hasattr(expr, 'function') and expr.function.func_type == 'aggregate' for expr, _ in select_node.select_expressions)
        
        if not all_agg:
            # 1:  - GROUP BY
            if not hasattr(select_node, 'group_by_clause') or not select_node.group_by_clause:
                # GROUP BY
                select_node.group_by_clause = GroupByNode()
                
    # GROUP BY
    group_by = getattr(select_node, 'group_by_clause', None)
    if group_by:
        # GROUP BY
        group_by.expressions = []
        # GROUP BY
        for expr, alias in select_node.select_expressions:
                        if not (hasattr(expr, 'function') and expr.function.func_type == 'aggregate'):
                            #Determine if it is a scalar function column
                            if (hasattr(expr, 'function') and expr.function.func_type == 'scalar') or type(expr).__name__=='ColumnReferenceNode':
                                    #Number of group BY expressions before record addition
                                    before_count = len(group_by.expressions)
                                    #Add expressions directly to group BY
                                    group_by.add_expression(expr)
                                    #Number of group BY expressions after record addition
                                    after_count = len(group_by.expressions)
                            #Judgment Window Function
                            if hasattr(expr, 'function') and expr.function.func_type == 'window':
                                if hasattr(expr, 'children'):
                                    for arg in expr.children:
                                        #Add to group BY if parameter is a column reference or scalar function
                                        if type(arg).__name__ == 'ColumnReferenceNode':
                                            group_by.add_expression(arg)
                                        elif type(arg).__name__ == 'FunctionCallNode' and hasattr(arg.function, 'func_type') and arg.function.func_type == 'scalar':
                                            for child in arg.children:
                                                if type(child).__name__ == 'ColumnReferenceNode':
                                                    group_by.add_expression(child)
                                if hasattr(expr,'metadata'):
                                    if expr.metadata.get('partition_by'):
                                        partition_by=expr.metadata.get('partition_by')
                                        before_count = len(group_by.expressions)
                                        
                                        #Try to get from_node (assuming it is available in the parent scope)
                                        if 'from_node' in locals() or 'from_node' in globals():
                                            available_from_node = locals().get('from_node') or globals().get('from_node')
                                            
                                            for part_expr in partition_by:
                                                try:
                                                    #Parsing table aliases and column names (format: table_alias.column_name)
                                                    if '.' in part_expr:
                                                        alias_part, col_part = part_expr.split('.', 1)
                                                        #Clear possible quotes
                                                        alias_part = alias_part.strip('"\'')
                                                        col_part = col_part.strip('"\'')
                                                         
                                                        #Get a table object
                                                        table_ref = available_from_node.get_table_for_alias(alias_part)
                                                        if table_ref and hasattr(table_ref, 'get_column'):
                                                            #Get Column Object
                                                            col = table_ref.get_column(col_part)
                                                            if col:
                                                                #Create ColumnReferenceNode object
                                                                col_ref = ColumnReferenceNode(col, alias_part)
                                                                #Add to group BY
                                                                group_by.add_expression(col_ref)
                                                                
                                                except Exception as e:
                                                    print(f"  Convertpartition_byError in expression: {e}")
                                        
                                        after_count = len(group_by.expressions)
                                    if expr.metadata.get('order_by'):
                                        order_by=expr.metadata.get('order_by')
                                        before_count = len(group_by.expressions)
                                        for order in order_by:
                                            expr_parts = order.rsplit(' ', 1)
                      
                                        if len(expr_parts) == 2 and expr_parts[1].upper() in ['ASC', 'DESC']:
                                            main_expr = expr_parts[0]
                                            main_expr = [main_expr]
                
                                            sort_direction = expr_parts[1]
                                        else:
                                            main_expr = order_by
                                            sort_direction = None
                                        #Try to get from_node (assuming it is available in the parent scope)
                                        if 'from_node' in locals() or 'from_node' in globals():
                                            available_from_node = locals().get('from_node') or globals().get('from_node')
                                            
                                            for part_expr in main_expr:
                                                try:
                                                    #Parsing table aliases and column names (format: table_alias.column_name)
                                                    #Parsing table aliases and column names (format: table_alias.column_name)
                                                    if '.' in part_expr:
                                                        alias_part, col_part = part_expr.split('.', 1)
                                                        #Clear possible quotes
                                                        alias_part = alias_part.strip('"\'')
                                                        col_part = col_part.strip('"\'')
                                                        
                                                        #Get a table object
                                                        table_ref = available_from_node.get_table_for_alias(alias_part)
                                                        if table_ref and hasattr(table_ref, 'get_column'):
                                                            #Get Column Object
                                                            col = table_ref.get_column(col_part)
                                                            if col:
                                                                #Create ColumnReferenceNode object
                                                                col_ref = ColumnReferenceNode(col, alias_part)
                                                                #Add to group BY
                                                                group_by.add_expression(col_ref)
                                                        else:
                                                            # ：，
                                                            # ：ORDER BY subq.max_email
                                                            virtual_col = Column(col_part, 'subquery', 'VARCHAR(255)', False, alias_part)
                                                            virtual_col_ref = ColumnReferenceNode(virtual_col, alias_part)
                                                            group_by.add_expression(virtual_col_ref)
                                                    else:
                                                        print(f"  Alarms: Unable to Analyzeorder_byExpression Format: {part_expr}")
                                                except Exception as e:
                                                    print(f"  Convertorder_byError in expression: {e}")
                                        else:
                                            print("  Warning: the from_node object is not available，Cannot convert order_by to ColumnReferenceNode")
                                        
                                        after_count = len(group_by.expressions)
                                        
                                        
                                        
                            #Check if select_node has the order_by_clause property
                            if hasattr(select_node, 'order_by_clause') and select_node.order_by_clause:
                                #Traversing expressions in order_by_clause
                                for expr, direction in select_node.order_by_clause.expressions:
          
                                    expr=[expr.to_sql()]
                                    #These expressions can be processed here as needed
                                    if 'from_node' in locals() or 'from_node' in globals():
                                            available_from_node = locals().get('from_node') or globals().get('from_node')
                                            for part_expr in expr:
                                                try:
                                                    #Parsing table aliases and column names (format: table_alias.column_name)
                                                    if '.' in part_expr:
                                                        alias_part, col_part = part_expr.split('.', 1)
                                                        #Clear possible quotes
                                                        alias_part = alias_part.strip('"\'')
                                                        col_part = col_part.strip('"\'')
                                                         
                                                        #Get a table object
                                                        table_ref = available_from_node.get_table_for_alias(alias_part)
                                                        if table_ref and hasattr(table_ref, 'get_column'):
                                                            #Get Column Object
                                                            col = table_ref.get_column(col_part)
                                                            if col:
                                                                #Create ColumnReferenceNode object
                                                                col_ref = ColumnReferenceNode(col, alias_part)
                                                                #Add to group BY
                                                                group_by.add_expression(col_ref)
                                                        else:
                                                            # ：，
                                                            # ：ORDER BY subq.max_email
                                                            virtual_col = Column(col_part, 'subquery', 'VARCHAR(255)', False, alias_part)
                                                            virtual_col_ref = ColumnReferenceNode(virtual_col, alias_part)
                                                            group_by.add_expression(virtual_col_ref)
                                                    else:
                                                        print(f"  Alarms: Unable to Analyzeorder_byExpression Format: {part_expr}")
                                                except Exception as e:
                                                    print(f"  Convertorder_byError in expression: {e}")
                                    else:
                                            print("  Warning: the from_node object is not available，Cannot convert order_by to ColumnReferenceNode")
                    
    
    # ，
    fix_all_function_params(select_node, main_table, join_table if 'join_table' in locals() else None, main_alias, join_alias if 'join_alias' in locals() else None)
    # 
    try:
        fix_all_function_params(select_node, main_table, join_table, main_alias, join_alias)
    except Exception as e:
        pass
    if use_cte:
        return f'{with_node.to_sql()} {select_node.to_sql()}'
    else:
        return select_node.to_sql()

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
    """：SQL（、）

    Parameter
    - subquery_depth: 
    - total_insert_statements: 
    - num_queries: 
    - query_type: ，'default'generate_random_sql()，'aggregate'generate_random_sql_with_aggregate()
    - use_database_tables: ，False
    - db_config: ，use_database_tablesTrue
    """
    
    # 
    resolved_db_config = db_config or {}
    if use_database_tables:
        required_keys = ["host", "port", "database", "user", "password", "dialect"]
        missing_keys = [k for k in required_keys if resolved_db_config.get(k) in (None, "")]
        if missing_keys:
            raise ValueError(
                "use_database_tables=True requires db_config keys: "
                f"{', '.join(required_keys)}; missing: {', '.join(missing_keys)}"
            )

        # DatabaseMetadataFetcher
        from database_metadata_fetcher import DatabaseMetadataFetcher

        #Create Database Metadata Acquirer
        fetcher = DatabaseMetadataFetcher(
            host=resolved_db_config["host"],
            port=resolved_db_config["port"],
            database=resolved_db_config["database"],
            user=resolved_db_config["user"],
            password=resolved_db_config["password"],
            dialect=resolved_db_config["dialect"],
        )
        
        # 
        if fetcher.connect():
            tables = fetcher.get_all_tables_info()
            fetcher.disconnect()
            print(f"Retrieved from database{len(tables)}Structural information of tables")
            
            # Markdown
            if tables:
                # generated_sql
                os.makedirs(output_dir, exist_ok=True)
                md_file_path = os.path.join(output_dir, "database_tables_info.md")
                
                try:
                    with open(md_file_path, 'w', encoding='utf-8') as md_file:
                        md_file.write("# \n")
                        md_file.write(f"\n## Database Connection Information\n")
                        md_file.write(f"- **Main Chassis**: {resolved_db_config['host']}\n")
                        md_file.write(f"- **Port**: {resolved_db_config['port']}\n")
                        md_file.write(f"- **Database**: {resolved_db_config['database']}\n")
                        md_file.write(f"- **dialect**: {resolved_db_config['dialect']}\n")
                        md_file.write(f"- **tables_count**: {len(tables)}\n")
                        
                        md_file.write(f"\n## Table Details\n\n")
                        
                        for table in tables:
                            md_file.write(f"### {table.name}\n")
                            md_file.write(f"- ****: {table.primary_key if table.primary_key else ''}\n")
                            
                            # 
                            md_file.write("\n|  |  |  |  |\n")
                            md_file.write("|------|---------|------|---------|\n")
                            for col in table.columns:
                                md_file.write(f"| {col.name} | {col.data_type} | {col.category} | {'' if col.is_nullable else ''} |\n")
                            
                            # 
                            if table.foreign_keys:
                                md_file.write("\n#### \n")
                                for fk in table.foreign_keys:
                                    md_file.write(f"- `{fk['column']}` -> `{fk['ref_table']}.{fk['ref_column']}`\n")
                            
                            md_file.write("\n")
                    
                    print(f"Database table structure information saved to: {md_file_path}")
                except Exception as e:
                    print(f"Failed to save database table structure information: {e}")
        else:
            print("Database connection failed.，Use sample table structure")
            tables = create_sample_tables()
    else:
        # 
        tables = create_sample_tables()
    
    functions = create_sample_functions()
    _set_subquery_depth(subquery_depth)
    
    #Set global table structure information
    set_tables(tables)
    set_tables(tables)
    
    #Record if database table is used
    is_using_database_tables = use_database_tables and len(tables) > 0 and tables[0].name != "users"
    
    
    #Generate build tables and insert statements only when database tables are not used
    if not is_using_database_tables:
        #Generate Table Building Statements
        create_sqls = []
        for table in tables:
            create_sql = generate_create_table_sql(table)
            create_sqls.append(create_sql)

        #Generate Insert Statement
        insert_sqls = []
        #Store primary key values for each table for foreign key references
        primary_keys_dict = {}
        #Calculate the number of inserted rows per table (the total number of inserted statements is evenly distributed to each table)
        num_tables = len(tables)
        insert_rows_per_table = total_insert_statements // num_tables
        remainder = total_insert_statements % num_tables

        # 
        table_insert_rows = {}

        #Generate primary key values for all tables first
        for i, table in enumerate(tables):
            #Generate primary key value for table
            primary_key_values = set()
            #Allocate the number of inserted rows, the first remainder table allocates 1 more row
            num_rows = insert_rows_per_table + (1 if i < remainder else 0)
            table_insert_rows[table.name] = num_rows
            for _ in range(num_rows):
                while True:
                    val = random.randint(1, 10000)
                    if val not in primary_key_values:
                        primary_key_values.add(val)
                        break
            primary_keys_dict[table.name] = list(primary_key_values)

        #Generate insert statements in the correct order (insert referenced tables first)
        #Here a simple topological sort is used to determine the insertion order of the table
        visited = set()
        def topological_sort(table_name):
            if table_name in visited:
                return
            visited.add(table_name)
            table = next(t for t in tables if t.name == table_name)
            #Process all referenced tables first
            for fk in table.foreign_keys:
                ref_table = fk["ref_table"]
                if ref_table not in visited:
                    topological_sort(ref_table)
            #Generate Insert Statements for Current Table
            num_rows = table_insert_rows[table.name]
            insert_sql = generate_insert_sql(table, num_rows=num_rows, existing_primary_keys=primary_keys_dict, primary_key_values=primary_keys_dict[table.name])
            insert_sqls.append(insert_sql)

        #Topological sorting of all tables and generation of insertion statements
        for table in tables:
            if table.name not in visited:
                topological_sort(table.name)

        #Generate index statement
        from data_structures.db_dialect import get_current_dialect
        dialect = get_current_dialect()
        index_sqls = generate_index_sqls(tables, dialect)
        
        #Composite Table Building, Insertion and Indexing Statements
        schema_sql = "\n\n".join(create_sqls + insert_sqls + index_sqls)
        schema_filepath = save_sql_to_file(
            schema_sql,
            output_dir=output_dir,
            file_type="schema",
            database_name=database_name,
        )
    else:
        #Do not generate build and insert statements when using database tables
        print("Use database table structure，Skip Table Building and Insert Statement Generation")
        schema_filepath = "[Working with Database Tables，No schema file generated]"
    
    #Generate and write query statements in batches to reduce memory usage
    batch_size = 1000  #Number of queries per batch
    query_filepath = save_sql_to_file(
        "",
        output_dir=output_dir,
        file_type="query",
        database_name=database_name,
    )  #Create an empty file and write to use database;
    
    #Save index SQL to query file
    if not is_using_database_tables:
        #Generate an index statement (if not already generated)
        if 'index_sqls' not in locals():
            from data_structures.db_dialect import get_current_dialect
            dialect = get_current_dialect()
            index_sqls = generate_index_sqls(tables, dialect)
        #Write index SQL to query file
        if index_sqls:
            index_sql_content = "\n\n".join(index_sqls)
            #Add Delimiter
            
            #Also save the index SQL to the indexes.sql file
            #Create indexes.sql file path
            indexes_file_path = os.path.join(output_dir, "indexes.sql")
            #Write use test statement and index SQL
            with open(indexes_file_path, "a", encoding="utf-8") as f:
                #Get the current database dialect
                from data_structures.db_dialect import get_current_dialect
                dialect = get_current_dialect()
                #Write use statement
                use_db_sql = dialect.get_use_database_sql(database_name)
                if use_db_sql:
                    f.write(use_db_sql)
                    if not use_db_sql.endswith("\n"):
                        f.write("\n")
                #Write Index SQL
                f.write(index_sql_content)
    
    #Error log file path
    error_log_path = os.path.join(output_dir, "query_generation_errors.log")
    
    #Open error log file for writing
    with open(error_log_path, "w", encoding="utf-8") as error_log:
        error_log.write(f"# SQLQuery Generate Error Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        error_log.write(f"# Target number of queries: {num_queries}\n")
        error_log.write("\n")
    
    for i in range(0, num_queries, batch_size):
        #Calculate the number of queries for the current batch
        current_batch_size = min(batch_size, num_queries - i)
        
        #Generate query statements for the current batch
        batch_queries = []
        #statistical information
        success_count = 0
        fail_count = 0
        error_types = {}
        
        
        for j in range(current_batch_size):
            retry_count = 0
            max_retries = 10  #Increase the maximum number of retries and increase the success rate
            success = False
            error_info = None
            error_type = None
            
            #Initialize error-related variables to avoid undefined errors
            error_type = "UnknownError"
            error_message = ""
            e = Exception("Maximum number of retries reached but no specific exception captured")
            
            while retry_count < max_retries:
                try:
                    sql = generate_random_sql(tables, functions)
                    batch_queries.append(sql)
                    success = True
                    success_count += 1
                    
                    #Print log once for every 100 queries generated
                    if (i + j + 1) % 100 == 0:
                        pass
                    break  #Generation successful, jump out of the retry loop
                except Exception as e:
                    retry_count += 1
                    #Log error information without immediately updating error type statistics
                    error_type = type(e).__name__
                    error_message = str(e)[:100]  #Limit error message length
                    error_info = f"{error_type}: {error_message}"
                    
                    #Print logs every 3 retries to avoid too many logs
                    #Errors removed Retry print
            
            if not success:
                fail_count += 1
                
                #Update error type statistics only when the query finally fails (only once per failed query)
                error_types[error_type] = error_types.get(error_type, 0) + 1
                
                #Write error log with detailed error information
                with open(error_log_path, "a", encoding="utf-8") as error_log:
                    error_log.write(f"[{i+j+1}/{num_queries}] Build Failed:\n")
                    error_log.write(f"  Error Type: {error_type}\n")
                    error_log.write(f"  Error Message: {error_message}\n")
                    error_log.write(f"  Number of Retries: {max_retries}\n")
                    error_log.write("\n")
            
            #Print progress and statistics once per 100 queries generated
            if (i + j + 1) % 100 == 0:
                pass
            
            #Progress reminder
            if (i + j + 1) % 5000 == 0:
                print(f"Generated {i + j + 1}/{num_queries} query statements")
        
        #Writes the current batch of query statements to a file
        batch_sql = "\n\n".join(batch_queries)
        save_sql_to_file(
            batch_sql,
            output_dir=output_dir,
            file_type="query",
            mode="a",
            database_name=database_name,
        )
        
        #Log batch completion information to the error log
        with open(error_log_path, "a", encoding="utf-8") as error_log:
            error_log.write(f"=== Batch {i//batch_size + 1} Completed ===\n")
            error_log.write(f"Total Batch Queries: {current_batch_size}\n")
            error_log.write(f"Successfully Generated!: {success_count}\n")
            error_log.write(f"Build Failed: {fail_count}\n")
            error_log.write(f"Error Type Statistics: {error_types}\n")
            error_log.write("\n")
        
        #Print Batch Completion Information
        print(f"=== Batch {i//batch_size + 1} Completed ===")
        print(f"Total Batch Queries: {current_batch_size}")
        print(f"Successfully Generated!: {success_count}")
        print(f"Build Failed: {fail_count}")
        print(f"Error Type Statistics: {error_types}")
        
        #Add separator if not last batch
        if i + current_batch_size < num_queries:
            pass
        #Empty batch list, free memory
        batch_queries = []
    #Log final statistics to the error log
    with open(error_log_path, "a", encoding="utf-8") as error_log:
        total_success = len([line for line in open(query_filepath, 'r', encoding='utf-8') if line.strip()])
        total_fail = num_queries - total_success
        error_log.write("=== Final stats = = =\n")
        error_log.write(f"Target number of queries: {num_queries}\n")
        error_log.write(f"Successfully Generated!: {total_success}\n")
        error_log.write(f"Build Failed: {total_fail}\n")
        error_log.write(f"Generation rate: {(total_success/num_queries)*100:.2f}%\n")
        error_log.write(f"\nGenerate Log Created Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    #Print final result information
    if not is_using_database_tables:
        print(f"Schema SQLSaved to: {schema_filepath}")
    else:
        print("Use database table structure，No schema file generated")
    print(f"Query SQLSaved to: {query_filepath}")
    print(f"Error log saved to: {error_log_path}")
    print(f"Target number of queries: {num_queries}")
    print(f"Actual Generated Quantity: {len(batch_queries) + (i if i > 0 else 0)}")
    print(f"Generation rate: {(len(batch_queries) + (i if i > 0 else 0))/num_queries*100:.2f}%")
