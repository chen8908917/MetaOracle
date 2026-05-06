"""Subquery generation helpers with depth and correlation controls."""

import random
from typing import List, Optional

from ast_nodes import (
    ColumnReferenceNode,
    FromNode,
    FunctionCallNode,
    LimitNode,
    LiteralNode,
    OrderByNode,
    SelectNode,
    SubqueryNode,
)
from data_structures.function import Function
from data_structures.table import Table
from sql_generation.random_sql.geometry import (
    create_geometry_literal_node,
    create_wkb_literal_node,
    is_geometry_type,
)

def create_select_subquery(tables: List[Table], functions: List[Function], 
                          current_depth: int = 0, max_depth: int = 2) -> SubqueryNode:
    """Create subquery expression in select clause
    
    Args:
        tables: List of available tables
        functions: List of available functions
        current_depth: Current Subquery Depth
        max_depth: Maximum Allowed Subquery Depth
    
    Returns:
        SubqueryNode: Subquery nodes available for select clauses
    """
    if current_depth >= max_depth or not tables:
        return None
    
    #Create select node for subquery
    subquery_select = SelectNode()
    subquery_select.tables = tables
    subquery_select.functions = functions
    
    #Select a table for the subquery
    subquery_table = random.choice(tables)
    
    #Generate from clause for subquery
    subquery_from = FromNode()
    subquery_inner_alias = 's' + str(random.randint(100, 999))
    subquery_from.add_table(subquery_table, subquery_inner_alias)
    subquery_select.set_from_clause(subquery_from)
    
    #Generate select expressions for subqueries (simple single-column query)
    subquery_col = subquery_table.get_random_column()

    subquery_expr = ColumnReferenceNode(subquery_col, subquery_inner_alias)
    
    #50% chance of using an aggregate function in a subquery
    is_aggregate = False
    if random.random() > 0.5 and functions:
        agg_funcs = [f for f in functions if f.func_type == 'aggregate']
        if agg_funcs:
            func = random.choice(agg_funcs)
            func_node = FunctionCallNode(func)
            
            current_params = 0
            min_params = func.min_params
            max_params = func.max_params
            
            if max_params is None:
                max_params = current_params + 3
            
            def build_param(param_type: str):
                param_type = (param_type or "").lower()
                if param_type in ["column", "any", "unknown"]:
                    return subquery_expr
                if param_type == "binary":
                    geom_cols = [col for col in subquery_table.columns if is_geometry_type(col.data_type)]
                    if geom_cols:
                        return ColumnReferenceNode(random.choice(geom_cols), subquery_inner_alias)
                    if "FromWKB" in func.name:
                        return create_wkb_literal_node(func.name)
                    return create_geometry_literal_node(func.name)
                if param_type == "numeric":
                    return LiteralNode(random.randint(1, 100), "INT")
                if param_type == "string":
                    return LiteralNode(f"sample_{random.randint(1, 100)}", "STRING")
                if param_type == "datetime":
                    return LiteralNode("2023-01-01 12:00:00", "DATETIME")
                if param_type == "json":
                    return LiteralNode('{"type":"Point","coordinates":[0,0]}', "JSON")
                if param_type == "boolean":
                    return LiteralNode(random.choice([True, False]), "BOOLEAN")
                return subquery_expr
            
            while current_params < min_params or (current_params < max_params and random.random() > 0.5):
                if current_params < len(func.param_types):
                    param_type = func.param_types[current_params]
                else:
                    param_type = func.param_types[0] if func.param_types else "column"
            
                new_param = build_param(param_type)
                func_node.add_child(new_param)
                current_params += 1
            
            subquery_expr = func_node
            is_aggregate = True
    
    #Ensure that the subquery selection column uses the subquery's own alias and avoid referencing the outer alias
    if isinstance(subquery_expr, ColumnReferenceNode):
        subquery_expr = ColumnReferenceNode(subquery_col, subquery_inner_alias)
    elif hasattr(subquery_expr, 'repair_columns'):
        subquery_expr.repair_columns(subquery_from)

    subquery_select.add_select_expression(subquery_expr, 'subq_col')
    
    #Force limit 1 and order BY clauses when subqueries are not aggregate functions
    if not is_aggregate:
        #Add the order BY clause, using the expression in the select clause
        from ast_nodes.order_by_node import OrderByNode
        #Gets the first expression in the select clause as the sort by
        if hasattr(subquery_select, 'select_expressions') and subquery_select.select_expressions:
            order_by_node = OrderByNode()
            order_by_node.add_expression(ColumnReferenceNode(subquery_col, subquery_inner_alias))
            subquery_select.set_order_by_clause(order_by_node)

        #Add limit 1 clause
        from ast_nodes.limit_node import LimitNode
        limit_node = LimitNode(1)
        subquery_select.set_limit_clause(limit_node)
    
    
    #Create subquery nodes (use empty strings as aliases, make sure no AS clauses are added)
    subquery_node = SubqueryNode(subquery_select, '')
    
    #Set Sub Query Depth Information
    subquery_node.metadata['depth'] = current_depth + 1
    
    #Validate the validity of subqueries
    valid, errors = subquery_select.validate_all_columns()
    if not valid:
        #Attempted to fix invalid column references
        subquery_select.repair_invalid_columns()
        #Verify again
        valid, errors = subquery_select.validate_all_columns()
        
        #Returns None if still invalid
        if not valid:
            return None
    
    return subquery_node
