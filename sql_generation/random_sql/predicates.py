"""Predicate and subquery-condition generation for WHERE/HAVING clauses."""

import random
from typing import List, Optional

from ast_nodes import (
    ASTNode,
    ColumnReferenceNode,
    ComparisonNode,
    FromNode,
    LiteralNode,
    LogicalNode,
    SelectNode,
    SubqueryNode,
)
from data_structures.function import Function
from data_structures.table import Table
from sql_generation.random_sql.column_tracker import ColumnUsageTracker, get_random_column_with_tracker
from sql_generation.random_sql.expressions import create_complex_expression
from sql_generation.random_sql.type_utils import (
    ORDERABLE_CATEGORIES,
    get_comparison_operators,
    get_safe_comparison_category,
    map_return_type_to_category,
)


def create_boolean_constant_condition(always_true: bool = True) -> ComparisonNode:
    condition = ComparisonNode("=")
    condition.add_child(LiteralNode(1, "INT"))
    condition.add_child(LiteralNode(1 if always_true else 0, "INT"))
    return condition

def create_simple_where_condition(table: Table, alias: str) -> Optional[ASTNode]:
    """Create simple where conditions for subqueries
    
    Args:
        table: Table Objects
        alias: Table Alias
    
    Returns:
        ASTNode: WHERECondition Node
    """
    try:
        #Select a column
        col = table.get_random_column()
        col_ref = ColumnReferenceNode(col, alias)
        
        #Generate different criteria based on column type
        if col.category == 'numeric':
            #Comparison Criteria for Value Type Columns
            operators = ['=', '<', '>', '<=', '>=', '<>']
            operator = random.choice(operators)
            condition = ComparisonNode(operator)
            condition.add_child(col_ref)
            
            #Generate random values
            if col.data_type in ['INT', 'INTEGER', 'BIGINT', 'TINYINT', 'SMALLINT']:
                condition.add_child(LiteralNode(random.randint(0, 100), col.data_type))
            else:
                condition.add_child(LiteralNode(random.uniform(0, 100), col.data_type))
            
        elif col.category == 'string':
            #Comparison Criteria for String Type Columns
            operators = ['=', '<>', 'LIKE']
            operator = random.choice(operators)
            condition = ComparisonNode(operator)
            condition.add_child(col_ref)
            
            #Generate random strings
            if operator == 'LIKE':
                condition.add_child(LiteralNode(f"'sample%'", col.data_type))
            else:
                condition.add_child(LiteralNode(f"'sample_{random.randint(1, 100)}'", col.data_type))
            
        elif col.category == 'datetime':
            #Comparison Criteria for Date Time Type Columns
            operators = ['=', '<', '>', '<=', '>=', '<>']
            operator = random.choice(operators)
            condition = ComparisonNode(operator)
            condition.add_child(col_ref)
            
            #Generate Random Dates
            year = random.randint(2020, 2024)
            month = random.randint(1, 12)
            day = random.randint(1, 28)
            date_str = f'{year}-{month:02d}-{day:02d}'
            condition.add_child(LiteralNode(date_str, col.data_type))
            
        else:
            #Other types use IS null/IS not null to avoid invalid comparisons
            operator = random.choice(['IS NULL', 'IS NOT NULL'])
            condition = ComparisonNode(operator)
            condition.add_child(col_ref)
            
        return condition
    except Exception:
        return None

def create_in_subquery(tables: List[Table], functions: List[Function], 
                      from_node: FromNode, main_table: Table, main_alias: str, 
                      join_table: Optional[Table] = None, join_alias: Optional[str] = None, 
                      column_tracker: Optional[ColumnUsageTracker] = None) -> ASTNode:
    """Create IN/not IN subquery，Includes multiple anti-join forms"""
    if random.random() < 0.3 and len(tables) > 1:
        #Select a different table for the subquery
        subquery_table = random.choice([t for t in tables if t != main_table])
        
        #Create subquery
        subquery = SelectNode()
        subquery.tables = [subquery_table]
        subquery.functions = functions
        
        #Add simple select expression
        subquery_col = subquery_table.get_random_column('numeric')
        subquery_expr = ColumnReferenceNode(subquery_col, 'subq')
        subquery.add_select_expression(subquery_expr)
        
        #Create from clause
        subquery_from = FromNode()
        subquery_from.add_table(subquery_table, 'subq')
        subquery.set_from_clause(subquery_from)
        
        #Add a where condition (optional)
        if random.random() > 0.5:
            subquery_category = get_safe_comparison_category(subquery_col)
            if subquery_category in ORDERABLE_CATEGORIES:
                subquery_where = ComparisonNode('>')
                subquery_where.add_child(ColumnReferenceNode(subquery_col, 'subq'))
                if subquery_category == 'numeric':
                    subquery_where.add_child(LiteralNode(random.randint(0, 50), 'INT'))
                else:
                    subquery_where.add_child(LiteralNode('2023-01-01 12:00:00', 'DATETIME'))
                subquery.set_where_clause(subquery_where)
        
        #Left column reference - use column tracker to select columns not used in select, having and on
        main_col = get_random_column_with_tracker(main_table, main_alias, column_tracker, for_select=False)
        left_col_ref = ColumnReferenceNode(main_col, main_alias)
        
        #Right subquery
        subquery_node = SubqueryNode(subquery, '')
        
        #Randomly select subquery formats
        subquery_form = random.random()
        #Randomly select IN/not IN form
        comp_node = ComparisonNode('IN' if random.random() < 0.5 else 'NOT IN')
        comp_node.add_child(left_col_ref)
        comp_node.add_child(subquery_node)
        return comp_node
    else:
        #Fallback to Simple Comparison
        return create_where_condition(tables, functions, from_node, main_table, main_alias, join_table, join_alias, column_tracker=column_tracker)

def create_exists_subquery(tables: List[Table], functions: List[Function], 
                           from_node: FromNode, main_table: Table, main_alias: str, 
                           join_table: Optional[Table] = None, join_alias: Optional[str] = None, 
                           column_tracker: Optional[ColumnUsageTracker] = None) -> ASTNode:
    """Create exists/not exists subquery，Ensure that only the columns actually selected in the sub-query are referenced"""
    if random.random() < 0.2 and len(tables) > 1:
        #Select Association Table
        rel_table = random.choice(tables)
        #Create related subquery
        subquery = SelectNode()
        subquery.tables = [rel_table]  #Only contain tables that are actually added to the from clause
        subquery.functions = functions
        
        #Refer to the from clause generation process in generate_random_sql
        #Create from clause
        subquery_from = FromNode()
        
        #Generate secure table aliases to avoid SQL keyword conflicts
        sql_keywords = {'use', 'select', 'from', 'where', 'group', 'by', 'order', 'limit', 'join', 'on', 'as'}
        base_rel_alias = rel_table.name[:3].lower()
        rel_alias = base_rel_alias if base_rel_alias not in sql_keywords else rel_table.name[:2].lower() + str(random.randint(0, 9))
        #Add an association table to the subquery's from clause
        subquery_from.add_table(rel_table, rel_alias)
        subquery.set_from_clause(subquery_from)
        
        #Select Columns in the Correlation Table - Use the Column Tracker to select columns that are not used in select, having, and on
        rel_col = get_random_column_with_tracker(rel_table, rel_alias, column_tracker, for_select=True)
        
        #Add a select expression, use the random columns in the associated table and set the alias
        if rel_col:
            subquery_expr = ColumnReferenceNode(rel_col, rel_alias)
            #Set the column alias to ensure that the column returned by the sub-query has an explicit reference
            subquery.add_select_expression(subquery_expr, rel_col.name)
        else:
            #If no columns are found, use the default constant
            subquery_expr = LiteralNode(1, 'INT')
            subquery.add_select_expression(subquery_expr, 'default_col')
        
        #Create where criteria (associated criteria for related subqueries)
        where_node = ComparisonNode('=')
        
        if rel_col:
            left_col_ref = ColumnReferenceNode(rel_col, rel_alias)
            
            #Select right operand according to column type (use constant directly)
            if rel_col.category == 'numeric':
                #Numeric type: Direct use of numeric constants
                numeric_value = random.randint(0, 100)
                where_node.add_child(left_col_ref)
                where_node.add_child(LiteralNode(numeric_value, rel_col.data_type))
            elif rel_col.category == 'string':
                #String type: use string constants directly
                string_value = f"sample_{random.randint(1, 100)}"
                where_node.add_child(left_col_ref)
                where_node.add_child(LiteralNode(string_value, 'STRING'))
            elif rel_col.category == 'datetime':
                #Datetime Type: Generates a datetime constant with a time part
                #Ensure that explicit datetime types are used to ensure that quotation marks are added correctly
                year = 2023
                month = random.randint(1, 12)
                day = random.randint(1, 28)  #Simple handling to avoid month-end issues
                hour = random.randint(0, 23)
                minute = random.randint(0, 59)
                second = random.randint(0, 59)
                
                #Build full datetime string
                datetime_value = f"'{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}'"
                
                #Ensure quotes are added with an explicit datetime type
                datetime_type = 'DATETIME'  #Explicitly use datetime type to ensure quotation marks are added
                where_node.add_child(left_col_ref)
                where_node.add_child(LiteralNode(datetime_value, datetime_type))
            else:
                #Other types: Direct use of default string constants
                default_value = "default_value"
                where_node.add_child(left_col_ref)
                where_node.add_child(LiteralNode(default_value, 'STRING'))
        else:
            #If no suitable columns are found, use the default criteria
            where_node.add_child(LiteralNode(1, 'INT'))
            where_node.add_child(LiteralNode(1, 'INT'))
        
        if where_node.children:
            subquery.set_where_clause(where_node)
        
        #Validate column references inside subqueries to ensure nonexistent columns are referenced
        valid, invalid_columns = subquery.validate_all_columns()
        if not valid and invalid_columns:
            #Simplify the where condition if there is an invalid column reference
            where_node = ComparisonNode('=')
            where_node.add_child(LiteralNode(1, 'INT'))
            where_node.add_child(LiteralNode(1, 'INT'))
            subquery.set_where_clause(where_node)
        
        #Note: exists/not exists subqueries should not have aliases
        subquery_node = SubqueryNode(subquery, '')
        
        #Randomly select subquery formats
        subquery_form = random.random()
        #Randomly select exists/not exists format
        exists_node = ComparisonNode('EXISTS' if random.random() < 0.5 else 'NOT EXISTS')
        exists_node.add_child(subquery_node)
        return exists_node
    else:
        return create_where_condition(tables, functions, from_node, main_table, main_alias, join_table, join_alias, column_tracker=column_tracker)

def create_where_condition(tables: List[Table], functions: List[Function], 
                          from_node: FromNode, main_table: Table, main_alias: str, 
                          join_table: Optional[Table] = None, join_alias: Optional[str] = None, 
                          use_subquery: bool = True, column_tracker: Optional[ColumnUsageTracker] = None) -> ASTNode:
    """Create where condition，Multiple condition types supported"""
    constant_roll = random.random()
    if constant_roll < 0.05:
        return create_boolean_constant_condition(always_true=True)
    if constant_roll < 0.10:
        return create_boolean_constant_condition(always_true=False)

    #Filter out aggregate and window functions to ensure they are not included in the where condition
    non_aggregate_functions = [f for f in functions if f.func_type != 'aggregate' and f.func_type != 'window']
    
    #Select condition type based on probability
    condition_type = random.random()
    

    #15% probability of using subquery conditions (IN/not IN or exists/not exists)
    if use_subquery and condition_type < 0.15:
        #50% probability using IN/not IN subquery, 50% probability using exists/not exists subquery
        if random.random() < 0.5:
            return create_in_subquery(tables, non_aggregate_functions, from_node, main_table, main_alias, join_table, join_alias, column_tracker)
        else:
            return create_exists_subquery(tables, non_aggregate_functions, from_node, main_table, main_alias, join_table, join_alias, column_tracker)
    
    #15% chance to use subquery with any/all (new verb 1)
    elif use_subquery and condition_type < 0.3:
        #Select Tables and Columns
        tables_to_choose = [main_table] + ([join_table] if join_table else [])
        table = random.choice(tables_to_choose)
        alias = main_alias if table == main_table else join_alias
        
        #Prefer numeric columns
        numeric_cols = []
        if column_tracker:
            available_columns = column_tracker.get_available_columns(table, alias)
            numeric_cols = [col for col in available_columns if get_safe_comparison_category(col) in ORDERABLE_CATEGORIES]
        else:
            numeric_cols = [col for col in table.columns if get_safe_comparison_category(col) in ORDERABLE_CATEGORIES]
            
        if numeric_cols:
            col = random.choice(numeric_cols)
            if column_tracker:
                column_tracker.mark_column_as_used(alias, col.name)
            safe_category = get_safe_comparison_category(col)
            
            col_ref = ColumnReferenceNode(col, alias)
            
            #Create subquery
            subquery = SelectNode()
            subquery_table = random.choice([t for t in tables if t != table]) if len(tables) > 1 else table
            safe_category = get_safe_comparison_category(col)
            subquery_col = subquery_table.get_random_column(safe_category)
            subquery.add_select_expression(ColumnReferenceNode(subquery_col, 'subq'))
            subquery_from = FromNode()
            subquery_from.add_table(subquery_table, 'subq')
            subquery.set_from_clause(subquery_from)
            
            #Select any/all operator and compare operator
            any_all = random.choice(['ANY', 'ALL'])
            #Select the appropriate comparison operator for the binary type
            operator = random.choice(get_comparison_operators(safe_category))
            
            comp_node = ComparisonNode(f'{operator} {any_all}')
            comp_node.add_child(col_ref)
            comp_node.add_child(SubqueryNode(subquery, ''))
            
            return comp_node
        
        #Fallback to Simple Comparison if no numeric columns
        return create_where_condition(
            tables, non_aggregate_functions, from_node, main_table, main_alias,
            join_table, join_alias, use_subquery=False, column_tracker=column_tracker
        )
    
    #15% chance of using complex nested expressions
    elif condition_type < 0.45:
        return create_complex_expression(tables, non_aggregate_functions, from_node, main_table, main_alias, join_table, join_alias, column_tracker=column_tracker, for_select=False)
    
    #15% chance OF using between conditions
    elif condition_type < 0.6:
        #Select Tables and Columns
        tables_to_choose = [main_table] + ([join_table] if join_table else [])
        table = random.choice(tables_to_choose)
        alias = main_alias if table == main_table else join_alias
        
        #Prefer numeric or date columns
        numeric_cols = []
        if column_tracker:
            #Get unused numeric or date type columns
            available_columns = column_tracker.get_available_columns(table, alias)
            numeric_cols = [col for col in available_columns if get_safe_comparison_category(col) in ['numeric', 'datetime']]
        else:
            #Use all numeric or date type columns if no tracker
            numeric_cols = [col for col in table.columns if get_safe_comparison_category(col) in ['numeric', 'datetime']]
            
        if numeric_cols:
            col = random.choice(numeric_cols)
            if column_tracker:
                column_tracker.mark_column_as_used(alias, col.name)
            safe_category = get_safe_comparison_category(col)
            
            col_ref = ColumnReferenceNode(col, alias)
            
            #Create between conditions
            between_node = ComparisonNode('BETWEEN' if random.random() < 0.5 else 'NOT BETWEEN')
            between_node.add_child(col_ref)
            
            #Add low and high values
            if safe_category == 'numeric':
                low_value = random.randint(0, 50)
                high_value = low_value + random.randint(10, 50)
                low_node = LiteralNode(low_value, col.data_type)
                high_node = LiteralNode(high_value, col.data_type)
                
                #Add low and high values directly
                between_node.add_child(low_node)
                between_node.add_child(high_node)
            elif safe_category == 'datetime':
                #Generate a full datetime string containing year, month, day, hour, minute, second
                start_datetime = f"2023-{random.randint(1, 12):02d}-{random.randint(1, 28):02d} {random.randint(0, 23):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"
                #Ensure the end datetime is greater than the start datetime
                end_month = random.randint(1, 12)
                end_day = random.randint(1, 28)
                end_hour = random.randint(0, 23)
                end_minute = random.randint(0, 59)
                end_second = random.randint(0, 59)
                end_datetime = f"2023-{end_month:02d}-{end_day:02d} {end_hour:02d}:{end_minute:02d}:{end_second:02d}"
                
                #Ensure quotation marks are added with an explicit 'datetime' type
                start_node = LiteralNode(start_datetime, 'DATETIME')
                end_node = LiteralNode(end_datetime, 'DATETIME')
                
                #Add start and end values directly
                between_node.add_child(start_node)
                between_node.add_child(end_node)
            
            return between_node
        else:
            #If there are no columns of numeric or date type, fall back to fit other types of conditions
            col = get_random_column_with_tracker(table, alias, column_tracker, for_select=False)
            col_ref = ColumnReferenceNode(col, alias)
            
            #Select the appropriate operator based on the column type
            if col.category == 'string':
                operator = random.choice(['=', '<>', 'LIKE', 'NOT LIKE'])
                comp_node = ComparisonNode(operator)
                comp_node.add_child(col_ref)
                
                if operator in ['LIKE', 'NOT LIKE']:
                    patterns = [
                        f"sample_{random.randint(1, 100)}",
                        f"%sample_{random.randint(1, 100)}",
                        f"sample_{random.randint(1, 100)}%",
                        f"%sample_{random.randint(1, 100)}%"
                    ]
                    selected_pattern = random.choice(patterns)
                    comp_node.add_child(LiteralNode(selected_pattern, 'STRING'))
                else:
                    sample_value = f"sample_{random.randint(1, 100)}"
                    comp_node.add_child(LiteralNode(sample_value, 'STRING'))
            else:
                #For other types, such as geometry, use the IS null/IS not null operator
                operator = random.choice(['IS NULL', 'IS NOT NULL'])
                comp_node = ComparisonNode(operator)
                comp_node.add_child(col_ref)
                
                #IS null/IS not null does not require right operand
                if operator not in ['IS NULL', 'IS NOT NULL']:
                    #For safety, use string literals as defaults
                    sample_value = f"sample_{random.randint(1, 100)}"
                    comp_node.add_child(LiteralNode(sample_value, 'STRING'))
            
            return comp_node
    
    #15% chance to use Enhanced Regular Expression Pattern (New Predicate 2)
    elif condition_type < 0.75 and join_table:
        #Select Tables and Columns
        tables_to_choose = [main_table, join_table]
        table = random.choice(tables_to_choose)
        alias = main_alias if table == main_table else join_alias
        
        #Preferred string column
        string_cols = []
        if column_tracker:
            #Get unused string columns
            available_columns = column_tracker.get_available_columns(table, alias)
            string_cols = [col for col in available_columns if col.category == 'string']
        else:
            #Use all string columns if no tracker
            string_cols = [col for col in table.columns if col.category == 'string']
            
        if string_cols:
            col = random.choice(string_cols)
            if column_tracker:
                column_tracker.mark_column_as_used(alias, col.name)
            col_ref = ColumnReferenceNode(col, alias)
            
            #Random Selection Operator
            operator = random.choice(['LIKE', 'NOT LIKE', 'RLIKE', 'REGEXP', 'NOT REGEXP'])
            
            comp_node = ComparisonNode(operator)
            comp_node.add_child(col_ref)
            
            #Add Enhanced Regular Expression Mode
            if operator in ['RLIKE', 'REGEXP', 'NOT REGEXP']:
                #More complex regular expression patterns
                complex_patterns = [
                    r'[a-zA-Z0-9]{5,10}',
                    r'[A-Z][a-z]{2,4}[0-9]{2}',
                    r'[0-9]{3}-[0-9]{2}-[0-9]{4}',
                    r'[a-z]+@[a-z]+\.[a-z]{2,3}',
                    r'^sample_\d+$',
                    r'.*[0-9]{3}.*'
                ]
                selected_pattern = random.choice(complex_patterns)
            else:
                patterns = [
                    f"sample_{random.randint(1, 100)}",
                    f"%sample_{random.randint(1, 100)}",
                    f"sample_{random.randint(1, 100)}%",
                    f"%sample_{random.randint(1, 100)}%"
                ]
                selected_pattern = random.choice(patterns)
                
            #Ensure string literals are identified with the correct data type
            string_type = 'STRING'
            pattern_node = LiteralNode(selected_pattern, string_type)
            
            comp_node.add_child(pattern_node)
            
            return comp_node
        
        #Fallback to simple comparison if no string columns
        return create_where_condition(
            tables, non_aggregate_functions, from_node, main_table, main_alias,
            join_table, join_alias, use_subquery=False, column_tracker=column_tracker
        )
            
        if string_cols:
            col = random.choice(string_cols)
            if column_tracker:
                column_tracker.mark_column_as_used(alias, col.name)
            col_ref = ColumnReferenceNode(col, alias)
            
            #Random Selection Operator
            operator = random.choice(['LIKE', 'NOT LIKE', 'RLIKE', 'REGEXP', 'NOT REGEXP'])
            
            comp_node = ComparisonNode(operator)
            comp_node.add_child(col_ref)
            
            #Add a Pattern
            patterns = [
                f"sample_{random.randint(1, 100)}",
                f"%sample_{random.randint(1, 100)}",
                f"sample_{random.randint(1, 100)}%",
                f"%sample_{random.randint(1, 100)}%",
                f"[a-z]{{3,5}}" if operator in ['RLIKE', 'REGEXP', 'NOT REGEXP'] else None
            ]
            #Filter None values
            valid_patterns = [p for p in patterns if p is not None]
            selected_pattern = random.choice(valid_patterns)
            #Ensure that string literals are identified with the correct data type and that quotation marks are handled correctly
            string_type = 'STRING'  #Ensure quotation marks are added explicitly using the string type
            pattern_node = LiteralNode(selected_pattern, string_type)
            
            comp_node.add_child(pattern_node)
            
            return comp_node
    
    #15% chance of using null safety comparison (new verb 3)
    elif condition_type < 0.9:
        #Select Tables and Columns
        tables_to_choose = [main_table] + ([join_table] if join_table else [])
        table = random.choice(tables_to_choose)
        alias = main_alias if table == main_table else join_alias
        col = get_random_column_with_tracker(table, alias, column_tracker, for_select=False)
        safe_category = get_safe_comparison_category(col)
        
        #Avoid unsupported null safety comparison operators and use a combination of standard comparison operators and IS null
        #Choose a different comparison method depending on whether the right side is null or not
        if random.random() < 0.5:
            #Use IS null when right is null
            comp_node = ComparisonNode('IS NULL')
            comp_node.add_child(ColumnReferenceNode(col, alias))
            return comp_node
        else:
            #Use the standard comparison operator when specific values are on the right
            operator = random.choice(get_comparison_operators(safe_category))
            comp_node = ComparisonNode(operator)
            comp_node.add_child(ColumnReferenceNode(col, alias))
        
        #Randomly select null or specific value for right operand
        if random.random() < 0.5:
            #Null on the right
            comp_node.add_child(LiteralNode(None, 'NULL'))
        else:
            #Specific values on the right
            if safe_category == 'numeric':
                value = random.randint(0, 100)
                comp_node.add_child(LiteralNode(value, col.data_type))
            elif safe_category == 'string':
                value = f"sample_{random.randint(1, 100)}"
                comp_node.add_child(LiteralNode(value, 'STRING'))
            elif safe_category == 'datetime':
                year = 2023
                month = random.randint(1, 12)
                day = random.randint(1, 28)
                datetime_value = f"{year:04d}-{month:02d}-{day:02d}"
                comp_node.add_child(LiteralNode(datetime_value, 'DATE'))
            elif safe_category == 'binary':
                #Generate a random hexadecimal value for the binary type
                hex_value = ''.join(random.choices('0123456789ABCDEF', k=8))
                comp_node.add_child(LiteralNode(f"X'{hex_value}'", 'BINARY'))
            elif safe_category == 'json':
                comp_node.add_child(LiteralNode('{"key": "value"}', 'JSON'))
            elif safe_category == 'boolean':
                comp_node.add_child(LiteralNode(random.choice([True, False]), 'BOOLEAN'))
        
        return comp_node
    
    #10% chance of using multi-column range comparisons (new verb 4)
    else:
        #Multi-column range comparison can only be used if there is a join table
        if join_table:
            #Select two related numeric columns to ensure selection via column tracker
                main_numeric_cols = []
                join_numeric_cols = []
                
                #Get available numeric columns using a column tracker
                if column_tracker:
                    main_available_columns = column_tracker.get_available_columns(main_table, main_alias)
                    main_numeric_cols = [col for col in main_available_columns if get_safe_comparison_category(col) == 'numeric']
                    
                    join_available_columns = column_tracker.get_available_columns(join_table, join_alias)
                    join_numeric_cols = [col for col in join_available_columns if get_safe_comparison_category(col) == 'numeric']
                else:
                    #If there is no column tracker, use all numeric columns
                    main_numeric_cols = [col for col in main_table.columns if get_safe_comparison_category(col) == 'numeric']
                join_numeric_cols = [col for col in join_table.columns if get_safe_comparison_category(col) == 'numeric']
                
                if main_numeric_cols and join_numeric_cols:
                    #Create multi-column range comparisons (e.g.: (a, b) between (x, y) and (p, q))
                    logic_node = LogicalNode('AND')
                    
                    #Select 2-3 to compare columns
                    num_pairs = random.randint(2, 3)
                    for _ in range(num_pairs):
                        main_col = random.choice(main_numeric_cols)
                        join_col = random.choice(join_numeric_cols)
                        if column_tracker:
                            column_tracker.mark_column_as_used(main_alias, main_col.name)
                            column_tracker.mark_column_as_used(join_alias, join_col.name)
                        
                        between_node = ComparisonNode('BETWEEN')
                        between_node.add_child(ColumnReferenceNode(join_col, join_alias))
                        
                        low_value = random.randint(0, 30)
                        high_value = low_value + random.randint(10, 50)
                        
                        between_node.add_child(LiteralNode(low_value, join_col.data_type))
                        between_node.add_child(LiteralNode(high_value, join_col.data_type))
                        
                        logic_node.add_child(between_node)
                    
                    return logic_node
        
        #Default: Use simple comparison criteria
        #Select Tables and Columns
        tables_to_choose = [main_table] + ([join_table] if join_table else [])
        table = random.choice(tables_to_choose)
        alias = main_alias if table == main_table else join_alias
        col = get_random_column_with_tracker(table, alias, column_tracker, for_select=False)
        col_ref = ColumnReferenceNode(col, alias)
        safe_category = get_safe_comparison_category(col)
        is_string_category = str(col.category).lower() == 'string' or map_return_type_to_category(col.data_type) == 'string'
        #Select operator based on column type
        if safe_category == 'string':
            if is_string_category:
                operator = random.choice(['=', '<>', 'LIKE', 'NOT LIKE', 'IS NULL', 'IS NOT NULL'])
            else:
                operator = random.choice(['=', '<>', 'IS NULL', 'IS NOT NULL'])
        elif safe_category == 'binary':
            #Binary types use the equals, not equals or IS null/IS not null operator
            operator = random.choice(['=', '<>', 'IS NULL', 'IS NOT NULL'])
        else:
            operators = get_comparison_operators(safe_category)
            operators.extend(['IS NULL', 'IS NOT NULL'])
            operator = random.choice(operators)
        comp_node = ComparisonNode(operator)
        comp_node.add_child(col_ref)
        
        #Add right operand (ensure type compatibility)
        if operator not in ['IS NULL', 'IS NOT NULL']:
            if safe_category == 'numeric':
                numeric_value = random.randint(0, 100)
                #Create numeric literals compatible with column types
                right_node = LiteralNode(numeric_value, col.data_type)
                comp_node.add_child(right_node)
            elif safe_category == 'binary':
                #Generate compatible hexadecimal values for binary types
                hex_value = ''.join(random.choices('0123456789ABCDEF', k=8))
                right_node = LiteralNode(f"X'{hex_value}'", 'BINARY')
                comp_node.add_child(right_node)
            elif safe_category == 'string':
                #Create string literals compatible with column types
                if operator in ['LIKE', 'NOT LIKE']:
                    #Generate patterns with wildcards
                    patterns = [
                        f"sample_{random.randint(1, 100)}",
                        f"%sample_{random.randint(1, 100)}",
                        f"sample_{random.randint(1, 100)}%",
                        f"%sample_{random.randint(1, 100)}%"
                    ]
                    selected_pattern = random.choice(patterns)
                    #Ensure string literals are wrapped in quotes correctly
                    right_node = LiteralNode(selected_pattern, 'STRING')
                else:
                    string_value = f"sample_{random.randint(1, 100)}"
                    #Explicitly use the 'string' type to ensure that strings are properly quoted
                    right_node = LiteralNode(string_value, 'STRING')
                
                comp_node.add_child(right_node)
            elif safe_category == 'datetime':
                #Create datetime literals that are compatible with column types and use proper formatting to avoid syntax errors
                from data_structures.db_dialect import get_dialect_config
                dialect = get_dialect_config()
                
                #Generate more specific datetime values, including time sections
                #Use imported random modules directly
                year = 2023
                month = random.randint(1, 12)
                day = random.randint(1, 28)  #Simple handling to avoid month-end issues
                hour = random.randint(0, 23)
                minute = random.randint(0, 59)
                second = random.randint(0, 59)
                
                #Build full datetime string
                datetime_value = f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
                
                #Make sure the quotes are added correctly using an explicit datetime type
                #Use explicit type even if col.data_type is not a standard date/datetime/timestamp
                datetime_type = 'DATETIME'  #Explicitly use datetime type to ensure quotation marks are added
                right_node = LiteralNode(datetime_value, datetime_type)
                
                comp_node.add_child(right_node)
            elif safe_category == 'json':
                comp_node.add_child(LiteralNode('{"key": "value"}', 'JSON'))
            elif safe_category == 'boolean':
                comp_node.add_child(LiteralNode(random.choice([True, False]), 'BOOLEAN'))
        return comp_node
