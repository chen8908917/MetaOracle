"""Builds random SQL expressions with type-aware composition rules."""

import random
import re
from typing import List, Optional

from ast_nodes import (
    ASTNode,
    ColumnReferenceNode,
    ComparisonNode,
    FunctionCallNode,
    FromNode,
    LiteralNode,
    LogicalNode,
    SubqueryNode,
)
from data_structures.function import Function
from data_structures.table import Table
from sql_generation.random_sql.column_tracker import ColumnUsageTracker, get_random_column_with_tracker
from sql_generation.random_sql.geometry import (
    create_geohash_literal_node,
    create_geojson_literal_node,
    create_geometry_literal_node,
    create_wkb_literal_node,
    create_wkt_literal_node,
    get_required_geometry_type,
    is_geojson_function,
    is_geohash_function,
    is_geometry_type,
    is_wkt_function,
)
from sql_generation.random_sql.subqueries import create_select_subquery
from sql_generation.random_sql.type_utils import (
    ORDERABLE_CATEGORIES,
    adjust_expected_type_for_conditionals,
    adjust_expected_type_for_min_max,
    get_cast_types,
    get_comparison_operators,
    map_param_type_to_category,
    map_return_type_to_category,
    normalize_category,
)

def is_type_compatible(type1, type2):
    """Check if the two data types are compatible，Allow conversion between numeric types
    
    Parameter
    - type1: First data type
    - type2: Second data type
    
    Back
    - bool: Returns True if both types are compatible，False
    """
    #Use the category attribute of the column to determine type compatibility
    #Note: When type1 and type2 are Column objects, use their category property directly
    #When type1 and type2 are strings, this means they are data type names and we need to look up the corresponding columns from the table structure
    #But since this function is usually used in contexts that already have a Column object, we prefer to use the category property
    
    #Column information should be found from the tables global variable in the actual project
    #But for backwards compatibility, we keep the decision logic based on the data type string
    
    #Define type compatibility rules
    numeric_types = {'INT', 'BIGINT', 'SMALLINT', 'TINYINT', 'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC'}
    string_types = {'VARCHAR', 'CHAR', 'TEXT', 'LONGTEXT', 'MEDIUMTEXT', 'TINYTEXT'}
    datetime_types = {'DATE', 'DATETIME', 'TIMESTAMP', 'TIME'}
    
    #Extract base type (without parentheses and length information)
    base_type1 = type1.split('(')[0].upper() if type1 else 'UNKNOWN'
    base_type2 = type2.split('(')[0].upper() if type2 else 'UNKNOWN'
    
    #Loosening type matching rules
    #1. The type of the same type group is considered compatible
    if (base_type1 in numeric_types and base_type2 in numeric_types) or \
       (base_type1 in string_types and base_type2 in string_types) or \
       (base_type1 in datetime_types and base_type2 in datetime_types):
        return True
    
    #2. Exactly the same type is considered compatible
    if base_type1 == base_type2:
        return True
    
    return False

def create_compatible_literal(data_type):
    """Creating Literals for Compatible Types，Make sure the type matches and the quotes are handled correctly"""
    base_type = data_type.split('(')[0].upper()
    
    if base_type in {'INT', 'BIGINT', 'SMALLINT', 'TINYINT'}:
        #Integer Type: Returns a random integer value
        return LiteralNode(random.randint(1, 1000), data_type)
    elif base_type in {'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC'}:
        #Value Type: Returns a random floating-point value
        return LiteralNode(round(random.uniform(1.0, 100.0), 2), data_type)
    elif base_type in {'VARCHAR', 'CHAR', 'TEXT', 'STRING'}:
        #String type: Returns a plain text string, explicitly using the 'string' type to ensure that quotes are added correctly
        return LiteralNode(f"sample_{random.randint(1, 100)}", 'STRING')
    elif base_type == 'DATE':
        #Date Type: Returns a string in date format
        return LiteralNode(f"2023-01-01", data_type)
    elif base_type in {'DATETIME', 'TIMESTAMP','timestamp'}:
        #Datetime Type: Returns a string in datetime format
        return LiteralNode(f"2023-01-01 12:00:00", data_type)
    elif base_type == 'BOOLEAN':
        #Boolean: returns a Boolean value
        return LiteralNode(random.choice([True, False]), data_type)

    elif base_type == 'SET':
        #Set Type: Randomly select one from the allowed values
        set_values = re.findall(r"'([^']+)',?", data_type)
        if set_values:
            return LiteralNode("'" + random.choice(set_values) + "'", data_type)
        else:
            return LiteralNode("''", data_type)
    elif base_type == 'ENUM':
        #Enum Type: Randomly select one from the enum values
        enum_values = re.findall(r"'([^']+)',?", data_type)
        if enum_values:
            return LiteralNode("'" + random.choice(enum_values) + "'", data_type)
        else:
            return LiteralNode("NULL", data_type)
    elif base_type == 'BIT':
        #Bit Type: Generate Random Bit Value
        bit_count = re.search(r"BIT\((\d+)\)", data_type)
        if bit_count:
            bit_count = int(bit_count.group(1))
            max_value = 2 ** bit_count - 1
            return LiteralNode("b'" + bin(random.randint(0, max_value))[2:].zfill(bit_count) + "'", data_type)
        else:
            return LiteralNode("b'0'", data_type)
    elif base_type == 'YEAR':
        #Year Type: Generate a random year between 2000-2023
        return LiteralNode(str(random.randint(2000, 2023)), data_type)
    elif base_type in {'GEOMETRY', 'POINT'}:
        #Geometry type: generates simple point coordinates
        lat = round(random.uniform(-90, 90), 6)
        lng = round(random.uniform(-180, 180), 6)
        return LiteralNode(f"ST_GeomFromText('POINT({lat} {lng})')", data_type)
    elif base_type in ['BLOB', 'TINYBLOB', 'MEDIUMBLOB', 'LONGBLOB']:
        #Blob type: Generate random binary data (in hexadecimal)
        #To avoid invalid utf8mb4 character errors in MariaDB, use the convert function to ensure proper handling
        blob_size = random.randint(1, 510)  #Limit to 510 bytes to meet aggregate function requirements
        hex_data = ''.join(random.choice('0123456789ABCDEF') for _ in range(blob_size * 2))
        return LiteralNode(f"X'{hex_data}", data_type)
    else:
        #Default: Returns an integer
        return LiteralNode(random.randint(1, 100), 'INT')


def create_select_constant_literal() -> LiteralNode:
    literal_type = random.choice(['INT', 'STRING', 'DATETIME', 'JSON', 'BOOLEAN'])
    if literal_type == 'INT':
        return LiteralNode(random.randint(0, 100), 'INT')
    if literal_type == 'STRING':
        return LiteralNode(f'const_{random.randint(1, 100)}', 'STRING')
    if literal_type == 'DATETIME':
        return LiteralNode('2023-01-01 12:00:00', 'DATETIME')
    if literal_type == 'JSON':
        return LiteralNode('{"key":"value"}', 'JSON')
    return LiteralNode(random.choice([True, False]), 'BOOLEAN')

def ensure_boolean_expression(expr: ASTNode, tables: List[Table], functions: List[Function], 
                           from_node: FromNode, main_table: Table, main_alias: str, 
                           join_table: Optional[Table] = None, join_alias: Optional[str] = None) -> ASTNode:
    """Make sure the expression is of type Boolean，Convert to Boolean expression if not"""
    #If the expression itself is a comparison expression or a logical expression, it is considered to be of type Boolean
    if isinstance(expr, (ComparisonNode, LogicalNode)):
        return expr
    
    #For other types of expressions (such as column references, function calls, etc.), convert them to Boolean expressions
    #Select Tables and Columns
    
    if isinstance(expr, FunctionCallNode):
        #Use the passed in expression as a comparison column instead of getting it randomly from the table
        col = expr
        return_type = expr.metadata.get('return_type', '').upper()
        
        #For functions that return type any, specially handle cast and convert functions
        if return_type == 'ANY' and expr.children:
            #All necessary classes have been imported at the top of the file, no partial import required
            
            #Check if it is cast or convert function
            if expr.function.name in ['CAST', 'CONVERT'] and len(expr.children) == 2:
                #For cast and convert functions, the return type is determined by the second parameter (target data type)
                second_param = expr.children[1]
                if isinstance(second_param, LiteralNode):
                    #Get target data type
                    target_type = second_param.upper()
                    param_type = None
                    
                    #Set the return type based on the target data type
                    if target_type in {'INT', 'BIGINT', 'SMALLINT', 'TINYINT', 'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC'}:
                        param_type = 'numeric'
                    elif target_type in {'VARCHAR', 'CHAR', 'TEXT', 'LONGTEXT', 'MEDIUMTEXT', 'TINYTEXT', 'STRING', 'CHARACTER'}:
                        param_type = 'string'
                    elif target_type in {'DATE', 'DATETIME', 'TIMESTAMP', 'TIME'}:
                        param_type = 'datetime'
                    elif target_type in {'BOOLEAN', 'BOOL'}:
                        param_type = 'boolean'
                    elif target_type in {'JSON'}:
                        param_type = 'json'
                    elif target_type in {'BINARY', 'VARBINARY', 'BLOB', 'LONGBLOB', 'MEDIUMBLOB', 'TINYBLOB'}:
                        param_type = 'binary'
                    elif target_type in {'BOOLEAN', 'BOOL'}:
                        param_type = 'boolean'
                    else:
                        param_type = 'string'
            #For other functions with return type any (e.g. max, min), get the type of the first parameter
            else:
                first_param = expr.children[0]
                param_type = None
            
                if isinstance(first_param, ColumnReferenceNode):
                    #If the first argument is a column reference, use the type of the column directly
                    param_type = first_param.column.category
                    if param_type in ['int', 'float', 'decimal']:
                        param_type = 'numeric'
                elif isinstance(first_param, LiteralNode):
                    #If the first parameter is literal, judging by the data type
                    if hasattr(first_param, 'data_type'):
                        data_type = first_param.data_type.upper()
                        if data_type in ['INT', 'FLOAT', 'DECIMAL', 'NUMERIC', 'BIGINT', 'SMALLINT', 'TINYINT']:
                            param_type = 'numeric'
                        elif data_type in ['VARCHAR', 'STRING', 'CHAR', 'TEXT']:
                            param_type = 'string'
                        elif data_type in ['DATE', 'DATETIME', 'TIMESTAMP', 'TIME']:
                            param_type = 'datetime'
                        elif data_type in ['JSON']:
                            param_type = 'json'
                        elif data_type in ['BINARY', 'VARBINARY', 'BLOB', 'LONGBLOB', 'MEDIUMBLOB', 'TINYBLOB', 'GEOMETRY', 'POINT', 'LINESTRING', 'POLYGON']:
                            param_type = 'binary'
                        elif data_type in ['BOOLEAN', 'BOOL']:
                            param_type = 'boolean'
                elif isinstance(first_param, FunctionCallNode):
                    #If the first argument is a function call, use its return type
                    param_func_return_type = first_param.metadata.get('return_type', '').upper()
                    if param_func_return_type in {'INT', 'BIGINT', 'SMALLINT', 'TINYINT', 'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC'}:
                        param_type = 'numeric'
                    elif param_func_return_type in {'VARCHAR', 'CHAR', 'TEXT', 'LONGTEXT', 'MEDIUMTEXT', 'TINYTEXT'}:
                        param_type = 'string'
                    elif param_func_return_type in {'DATE', 'DATETIME', 'TIMESTAMP', 'TIME'}:
                        param_type = 'datetime'
                    elif param_func_return_type in {'JSON'}:
                        param_type = 'json'
                    elif param_func_return_type in {'BINARY', 'VARBINARY', 'BLOB', 'LONGBLOB', 'MEDIUMBLOB', 'TINYBLOB', 'GEOMETRY', 'POINT', 'LINESTRING', 'POLYGON'}:
                        param_type = 'binary'
                    elif param_func_return_type in {'BOOLEAN', 'BOOL'}:
                        param_type = 'boolean'
                    elif param_func_return_type in {'ANY'}:
                        #Recursively get the type of its first parameter if the internal function return type is also any
                        if first_param.children:
                            inner_first_param = first_param.children[0]
                            if isinstance(inner_first_param, ColumnReferenceNode):
                                #If the first parameter inside is a column reference, use the type of the column directly
                                param_type = inner_first_param.column.category
                                if param_type in ['int', 'float', 'decimal']:
                                    param_type = 'numeric'
                                elif param_type in ['string', 'char', 'text']:
                                    param_type = 'string'
                                elif param_type in ['datetime', 'time']:
                                    param_type = 'datetime'
                                elif param_type in ['binary']:
                                    param_type = 'binary'
                                elif param_type in ['json']:
                                    param_type = 'json'
                                elif param_type in ['boolean', 'bool']:
                                    param_type = 'boolean'
                                
                            elif isinstance(inner_first_param, LiteralNode):
                                #If the internal first parameter is literal, judging by the data type
                                if hasattr(inner_first_param, 'data_type'):
                                    data_type = inner_first_param.data_type.upper()
                                    if data_type in ['INT', 'FLOAT', 'DECIMAL', 'NUMERIC', 'BIGINT', 'SMALLINT', 'TINYINT']:
                                        param_type = 'numeric'
                                    elif data_type in ['VARCHAR', 'STRING', 'CHAR', 'TEXT']:
                                        param_type = 'string'
                                    elif data_type in ['DATE', 'DATETIME', 'TIMESTAMP', 'TIME']:
                                        param_type = 'datetime'
                                    elif data_type in ['JSON']:
                                        param_type = 'json'
                                    elif data_type in ['BINARY', 'VARBINARY', 'BLOB', 'LONGBLOB', 'MEDIUMBLOB', 'TINYBLOB', 'GEOMETRY', 'POINT', 'LINESTRING', 'POLYGON']:
                                        param_type = 'binary'
                                    elif data_type in ['BOOLEAN', 'BOOL']:
                                        param_type = 'boolean'
                            
                if param_type:
                    #Set the actual return type of the function call node
                    col.metadata['return_type'] = param_type
                    col.category = param_type
        else:
            #Handle functions with explicit return types
            if return_type in {'INT', 'BIGINT', 'SMALLINT', 'TINYINT', 'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC'}:
                col.category = 'numeric'
            elif return_type in {'VARCHAR', 'CHAR', 'TEXT', 'LONGTEXT', 'MEDIUMTEXT', 'TINYTEXT', 'STRING'}:
                col.category = 'string'
            elif return_type in {'DATE', 'DATETIME', 'TIMESTAMP', 'TIME'}:
                col.category = 'datetime'
            elif return_type in {'JSON'}:
                col.category = 'json'
            elif return_type in {'BINARY', 'VARBINARY', 'BLOB', 'LONGBLOB', 'MEDIUMBLOB', 'TINYBLOB', 'GEOMETRY', 'POINT', 'LINESTRING', 'POLYGON'}:
                col.category = 'binary'
            elif return_type in {'BOOLEAN', 'BOOL'}:
                col.category = 'boolean'
            else:
                col.category = 'string'

        if not getattr(col, 'category', None):
            col.category = 'string'

    elif type(expr).__name__ == 'ColumnReferenceNode':
        #Use incoming column references as comparison columns
        col = expr
        col.category = expr.column.category
        col.data_type = expr.column.data_type

    elif type(expr).__name__ == 'SubqueryNode':
        #For subqueries, assume it returns a single column and sets the appropriate type information
        col = expr
        if hasattr(expr, 'repair_columns'):
            expr.repair_columns(None)
        #Default assumes string type
        col.category = 'string'
        col.data_type = 'VARCHAR'
        #Try to get the actual type information from the column_alias_map of the subquery
        if hasattr(expr, 'column_alias_map') and expr.column_alias_map:
            #Get type information for the first column
            first_col_info = next(iter(expr.column_alias_map.values()))
            if len(first_col_info) >= 3:
                col.data_type = first_col_info[1]  #Data Types
                col.category = first_col_info[2]   #Categories
    
    elif type(expr).__name__ == 'LiteralNode':
        col = expr
        literal_type = getattr(expr, 'data_type', '')
        if literal_type:
            data_type = str(literal_type).upper()
            if data_type in {'INT', 'BIGINT', 'SMALLINT', 'TINYINT', 'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC'}:
                col.category = 'numeric'
            elif data_type in {'VARCHAR', 'STRING', 'CHAR', 'TEXT', 'LONGTEXT', 'MEDIUMTEXT', 'TINYTEXT'}:
                col.category = 'string'
            elif data_type in {'DATE', 'DATETIME', 'TIMESTAMP', 'TIME'}:
                col.category = 'datetime'
            elif data_type in {'JSON'}:
                col.category = 'json'
            elif data_type in {'BINARY', 'VARBINARY', 'BLOB', 'LONGBLOB', 'MEDIUMBLOB', 'TINYBLOB', 'GEOMETRY', 'POINT', 'LINESTRING', 'POLYGON'}:
                col.category = 'binary'
            elif data_type in {'BOOLEAN', 'BOOL'}:
                col.category = 'boolean'
            else:
                col.category = 'numeric'
        else:
            col.category = 'numeric'
    else:
        #For other types of expressions, use the default type
        col = expr
        #Default assumes string type
        col.category = 'string'
        col.data_type = 'VARCHAR'
    safe_category = normalize_category(col.category, col.data_type)
    #Select operator based on column type
    if safe_category in ['string', 'binary', 'json', 'boolean']:
        operator = random.choice(['=', '<>'])
    else:
        operator = random.choice(get_comparison_operators(safe_category))
    
    comp_node = ComparisonNode(operator)
    comp_node.add_child(expr)

    #Add right operand (ensure type compatibility)
    if safe_category == 'numeric':
        value = random.randint(0, 100)
        comp_node.add_child(LiteralNode(value, col.data_type))
    elif safe_category == 'string':
        value = f"sample_{random.randint(1, 100)}"
        #Explicitly use the 'string' type to ensure that strings are properly quoted
        comp_node.add_child(LiteralNode(value, 'STRING'))
    elif safe_category == 'datetime':
        #Generate datetime constant with time part
        year = 2023
        month = random.randint(1, 12)
        day = random.randint(1, 28)  #Simple handling to avoid month-end issues
        hour = random.randint(0, 23)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        
        #Build full datetime string
        value = f"'{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}'"
        
        #Ensure quotes are added with an explicit datetime type
        comp_node.add_child(LiteralNode(value, 'DATETIME'))
    elif safe_category == 'binary':
        #Generate random hex values
        hex_value = ''.join(random.choices('0123456789ABCDEF', k=8))
        comp_node.add_child(LiteralNode(f"X'{hex_value}'", 'BINARY'))
    elif safe_category == 'json':
        #Generate random JSON literals
        json_templates = [
            '{"key": "value"}',
            '{"id": ' + str(random.randint(1, 100)) + ', "name": "sample_' + str(random.randint(1, 100)) + '"}',
            '{"items": [' + ', '.join([str(random.randint(1, 10)) for _ in range(random.randint(1, 5))]) + ']}',
            '{"user": {"name": "test", "age": ' + str(random.randint(18, 65)) + ', "active": ' + str(random.choice([True, False])).lower() + '}}'
        ]
        json_value = random.choice(json_templates)
        comp_node.add_child(LiteralNode(json_value, 'JSON'))
    elif safe_category == 'boolean':
        comp_node.add_child(LiteralNode(random.choice([True, False]), 'BOOLEAN'))
    else:
        comp_node.add_child(LiteralNode(random.randint(1, 100), 'INT'))
        
    return comp_node

def create_complex_expression(tables: List[Table], functions: List[Function],
                           from_node: FromNode, main_table: Table, main_alias: str,
                           join_table: Optional[Table] = None, join_alias: Optional[str] = None,
                           max_depth: int = 3, depth: int = 0, column_tracker: Optional[ColumnUsageTracker] = None, for_select: bool = False) -> ASTNode:
    """Create complex expression nesting，Ensure the generated logical expression contains only subexpressions of Boolean type"""
    
    #Avoid nesting expressions too deep
    if depth >= max_depth:
        expr = create_random_expression(tables, functions, from_node, main_table, main_alias, 
                                       join_table, join_alias, use_subquery=True, column_tracker=column_tracker, for_select=for_select)
        #Make sure to return a Boolean expression
        return ensure_boolean_expression(expr, tables, functions, from_node, main_table, main_alias, 
                                       join_table, join_alias)
        
    #Recursively create nested expressions
    if random.random() < 0.4:
        #Create a logical expression combining multiple simple expressions
        operator = random.choice(['AND', 'OR'])
        logic_node = LogicalNode(operator)
        
        #Add 2-3 subexpressions
        sub_expr_count = random.randint(2, 3)
        
        for i in range(sub_expr_count):
            #Recursively create subexpressions
            sub_expr = create_complex_expression(tables, functions, from_node, main_table, main_alias, 
                                                join_table, join_alias, depth + 1, max_depth, column_tracker=column_tracker, for_select=False)
            #Ensure the subexpression is of type Boolean
            logic_node.add_child(sub_expr)
        
        return logic_node
    else:
        #Create base expression
        expr = create_random_expression(tables, functions, from_node, main_table, main_alias, 
                                       join_table, join_alias, use_subquery=True, column_tracker=column_tracker, for_select=for_select)
        #Make sure to return a Boolean expression
        result = ensure_boolean_expression(expr, tables, functions, from_node, main_table, main_alias, 
                                       join_table, join_alias)
        return result

def create_random_expression(tables: List[Table], functions: List[Function], 
                           from_node: FromNode, main_table: Table, main_alias: str, 
                           join_table: Optional[Table] = None, join_alias: Optional[str] = None, 
                           use_subquery: bool = True, column_tracker: ColumnUsageTracker = None, for_select: bool=False) -> ASTNode:
    """Create Random Expression"""
    if random.random() > 0.3 and functions:  #70% probability to use columns, 30% probability to use functions
        func = random.choice(functions)
        func_node = FunctionCallNode(func)
        
        #Handle aggregate functions like min/max specially to ensure the return type is the same as the parameter type
        if func.name in ['MIN', 'MAX'] and func.return_type == 'any':
            #First preset to numeric, then update according to parameter type
            func_node.metadata['category'] = 'numeric'
        else:
            #Set type information for function expressions
            func_node.metadata['category'] = map_return_type_to_category(func.return_type)
        
        #Set the necessary window clause information for the window function
        if func.func_type == 'window':
            #Randomly select whether to add a partition BY clause
            if random.random() > 0.3:
                #Select a table to partition
                tables_to_choose = [main_table] + ([join_table] if join_table else [])
                if tables_to_choose:
                    table = random.choice(tables_to_choose)
                    alias = main_alias if table == main_table else join_alias
                    #Select a column for partitioning
                    col = table.get_random_column()
                    func_node.metadata['partition_by'] = [f"{alias}.{col.name}"]
            
            #For window functions that require order BY, always add the order BY clause
            if func.name in ['ROW_NUMBER', 'RANK', 'DENSE_RANK', 'NTILE', 'LEAD', 'LAG','PERCENT_RANK','CUME_DIST','FIRST_VALUE','LAST_VALUE']:
                #Select a table to sort
                tables_to_choose = [main_table] + ([join_table] if join_table else [])
                if tables_to_choose:
                    table = random.choice(tables_to_choose)
                    alias = main_alias if table == main_table else join_alias
                    #Select a column to sort by
                    col = table.get_random_column()
                    #Random Selection Sort Direction
                    direction = 'ASC' if random.random() > 0.5 else 'DESC'
                    func_node.metadata['order_by'] = [f"{alias}.{col.name} {direction}"]
                else:
                    #fallback scheme, sorting by constant expression
                    func_node.metadata['order_by'] = ['1=1']
        
        #Adding Parameters to a Function
        param_count = func.min_params
        if func.max_params is not None and func.max_params > func.min_params and not func.name.startswith('ST_'):
            param_count = random.randint(func.min_params, func.max_params)
        
        #Save the type of the first parameter for aggregation functions such as min/max
        first_param_category = None
        
        for param_idx in range(param_count):
            expected_type = map_param_type_to_category(func.param_types[param_idx]) if param_idx < len(func.param_types) else 'any'
            expected_type = adjust_expected_type_for_min_max(func.name, param_idx, expected_type)
            expected_type = adjust_expected_type_for_conditionals(func.name, param_idx, expected_type)
            #Unify the special logic of the three functions
            #1. special handling OF the substring function: make sure the parameter type IS correct
            if func.name == 'SUBSTRING':
                #The first parameter must be a string type
                if param_idx == 0:
                    #Force first argument to string type
                    tables_to_choose = [main_table] + ([join_table] if join_table else [])
                    if tables_to_choose:
                        #Try to find columns of string type
                        all_string_cols = []
                        for table in tables_to_choose:
                            string_cols = [col for col in table.columns if col.category == 'string']
                            all_string_cols.extend(string_cols)
                        
                        if all_string_cols:
                            #Direct selection of available columns
                            col = random.choice(all_string_cols)
                            table = [t for t in tables_to_choose if col in t.columns][0]
                            alias = main_alias if table == main_table else join_alias
                            #Record columns are used in select
                            if column_tracker:
                                column_tracker.mark_column_as_select(alias, col.name)
                            col_ref = ColumnReferenceNode(col, alias)
                            func_node.add_child(col_ref)
                        else:
                            #No string columns available, use string literal
                            literal = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                            func_node.add_child(literal)
                    else:
                        #No tables available, use string literal
                        literal = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                        func_node.add_child(literal)
                #Second, the three parameters must be numeric types (position and length)
                elif param_idx in [1, 2]:
                    #Generate a reasonable integer value
                    #For positional parameters, use a random number between 1 and 20
                    #For the length parameter, use a random number between 1 and 10
                    value = random.randint(1, 20) if param_idx == 1 else random.randint(1, 10)
                    literal = LiteralNode(value, 'INT')
                    func_node.add_child(literal)

            #2. Special handling of the date_format/TO_char function
            elif (func.name == 'DATE_FORMAT' or func.name == 'TO_CHAR'):
                #First parameter: datetime column
                if param_idx == 0:
                    #Force first parameter to be datetime type
                    tables_to_choose = [main_table] + ([join_table] if join_table else [])
                    if tables_to_choose:
                        #Try to find columns of datetime type
                        all_datetime_cols = []
                        for table in tables_to_choose:
                            datetime_cols = [col for col in table.columns if col.category == 'datetime']
                            all_datetime_cols.extend(datetime_cols)
                        
                        if all_datetime_cols:
                            #Direct selection of available columns
                            col = random.choice(all_datetime_cols)
                            table = [t for t in tables_to_choose if col in t.columns][0]
                            alias = main_alias if table == main_table else join_alias
                            #Record columns are used in select
                            if column_tracker:
                                column_tracker.mark_column_as_select(alias, col.name)
                            col_ref = ColumnReferenceNode(col, alias)
                            func_node.add_child(col_ref)
                        else:
                            #No datetime column, use date literal
                            literal = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                            func_node.add_child(literal)
                    else:
                        #No tables available, use date literal
                        literal = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                        func_node.add_child(literal)
                #Second parameter: format string literal
                elif param_idx == 1:
                    #The second parameter must be a format string
                    if func.name == 'TO_CHAR':
                        #PostgreSQL TO_char format
                        format_strings = ['YYYY-MM-DD', 'YYYY-MM-DD HH24:MI:SS', 'DD-MON-YYYY', 'HH24:MI:SS']
                    else:
                        #MySQL date_format format
                        format_strings = ['%Y-%m-%d', '%Y-%m-%d %H:%i:%s', '%d-%b-%Y', '%H:%i:%s']
                    #Use the string type to ensure that the quotation marks are added correctly
                    literal = LiteralNode(random.choice(format_strings), 'STRING')
                    func_node.add_child(literal)

            #3. concat function special handling: make sure all parameters are of string type
            elif func.name == 'CONCAT' and expected_type == 'string':
                #Mandatory parameter is string type
                tables_to_choose = [main_table] + ([join_table] if join_table else [])
                if tables_to_choose:
                    #Try to find columns of string type
                    all_string_cols = []
                    for table in tables_to_choose:
                        string_cols = [col for col in table.columns if col.category == 'string']
                        all_string_cols.extend(string_cols)
                    
                    if all_string_cols:
                        #Direct selection of available columns
                        col = random.choice(all_string_cols)
                        table = [t for t in tables_to_choose if col in t.columns][0]
                        alias = main_alias if table == main_table else join_alias
                        #Record columns are used in select
                        if column_tracker:
                            column_tracker.mark_column_as_select(alias, col.name)
                        col_ref = ColumnReferenceNode(col, alias)
                        func_node.add_child(col_ref)
                    else:
                        #No string columns available, use string literal
                        literal = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                        func_node.add_child(literal)
                else:
                    #No tables available, use string literal
                    literal = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                    func_node.add_child(literal)
            
            #4. NTILE function special treatment: ensure that the parameter is a positive integer, nested functions are not allowed
            elif func.name == 'NTILE':
                #Generate a random integer between 1-100 as a parameter
                literal = LiteralNode(random.randint(1, 100), 'INT')
                func_node.add_child(literal)
            elif func.name == 'NTH_VALUE' and param_idx == 1:
                #Generate a random integer between 1-100 as a parameter
                literal = LiteralNode(random.randint(1, 10), 'INT')
                func_node.add_child(literal)
            #6. cast function special handling: make sure the second parameter is a valid data type name
            elif func.name in ['CAST', 'CONVERT']:
                #The first argument can be any expression
                if param_idx == 0:
                    #Processing with General Parameters
                    tables_to_choose = [main_table] + ([join_table] if join_table else [])
                    if tables_to_choose:
                        table = random.choice(tables_to_choose)
                        alias = main_alias if table == main_table else join_alias
                        
                        #50% probability of using column references, 50% probability of using literals
                        if True:
                            col = table.get_random_column()
                            #Record columns are used in select
                            if column_tracker:
                                column_tracker.mark_column_as_select(alias, col.name)
                            col_ref = ColumnReferenceNode(col, alias)
                            func_node.add_child(col_ref)

                    else:
                        #No tables available, use literal
                        literal = LiteralNode(random.randint(1, 100), 'INT')
                        func_node.add_child(literal)
                #The second parameter must be a valid data type name
                elif param_idx == 1:
                    #Define some common data types
                    data_types = get_cast_types()
                    
                    data_type = random.choice(data_types)
                    if data_type == 'CHAR':
                        #Char type requires a specified length
                        length = random.randint(1, 255)
                        data_type = f"{data_type}({length})"
                    #Randomly select a data type
                    
                    #Create a special LiteralNode using type 'none' to avoid quotation marks
                    literal = LiteralNode(data_type, "STRING")
                    func_node.add_child(literal)

            #Datetime function special handling: arguments must be integers of 1-6
            elif func.name == 'DATETIME':
                #Generate a random integer between 1-6 as a parameter
                literal = LiteralNode(random.randint(1, 6), 'INT')
                func_node.add_child(literal)
            
            #Lead function special handling: the second argument must be an integer constant
            elif func.name in ['LEAD', 'LAG']:
                if param_idx == 1:  #Second parameter: offset
                    #Generate a random integer between 1-10 as offset
                    literal = LiteralNode(random.randint(1, 10), 'INT')
                    func_node.add_child(literal)
                elif param_idx == 2:  #Third parameter: default value
                    #The default value can be null or compatible with the first parameter type
                    if random.random() < 0.5:
                        literal = LiteralNode('NULL', 'NULL')
                        func_node.add_child(literal)
                    else:
                        #Select a value that is compatible with the first parameter type
                        #Processing is simplified here, using integer constants
                        literal = LiteralNode(random.randint(1, 100), 'INT')
                        func_node.add_child(literal)
                else:  #First Parameter: Column Reference
                    #Use regular parameter processing, but make sure it is a column reference
                    tables_to_choose = [main_table] + ([join_table] if join_table else [])
                    if tables_to_choose:
                        table = random.choice(tables_to_choose)
                        alias = main_alias if table == main_table else join_alias
                        col = table.get_random_column()
                        #Record columns are used in select
                        if column_tracker:
                            column_tracker.mark_column_as_select(alias, col.name)
                        col_ref = ColumnReferenceNode(col, alias)
                        func_node.add_child(col_ref)
                    else:
                        #No tables available, use literal
                        literal = LiteralNode(random.randint(1, 100), 'INT')
                        func_node.add_child(literal)
            
            elif func.name in ['TIMESTAMPDIFF'] and param_idx == 0:
                #First Parameter: Time Units
                literal = LiteralNode(random.choice(['YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND']), 'STRING')
                func_node.add_child(literal)
            elif func.name == 'ST_Transform' and param_idx == 1:
                func_node.add_child(LiteralNode(4326, 'INT'))
            
            elif func.name in ['JSON_VALUE', 'JSON_REMOVE', 'JSON_EXTRACT', 'JSON_SET','JSON_INSERT', 'JSON_REPLACE'] and param_idx == 1:
                #First parameter: JSON key
                literal = LiteralNode('$.key', 'STRING')
                func_node.add_child(literal)
            elif func.name.upper() == 'ST_GEOHASH':
                if param_idx == 0:
                    func_node.add_child(LiteralNode(random.uniform(-180, 180), 'DOUBLE'))
                elif param_idx == 1:
                    func_node.add_child(LiteralNode(random.uniform(-90, 90), 'DOUBLE'))
                else:
                    func_node.add_child(LiteralNode(random.randint(1, 12), 'INT'))
            elif expected_type == 'string' and is_geohash_function(func.name):
                func_node.add_child(create_geohash_literal_node())
            elif expected_type in {'string', 'json'} and is_geojson_function(func.name):
                func_node.add_child(create_geojson_literal_node(func.name))
            elif expected_type == 'string' and func.name.startswith('ST_') and is_wkt_function(func.name):
                func_node.add_child(create_wkt_literal_node(func.name))
            else:
                #General Parameter Handling
                #Select Tables and Columns
                tables_to_choose = [main_table] + ([join_table] if join_table else [])
                if tables_to_choose:
                    table = random.choice(tables_to_choose)
                    alias = main_alias if table == main_table else join_alias
                    if expected_type == 'binary' and func.name.startswith('ST_'):
                        if get_required_geometry_type(func.name):
                            func_node.add_child(create_geometry_literal_node(func.name))
                            continue
                        if 'FromWKB' in func.name:
                            func_node.add_child(create_wkb_literal_node(func.name))
                            continue
                        geometry_candidates = []
                        for candidate_table in tables_to_choose:
                            candidate_alias = main_alias if candidate_table == main_table else join_alias
                            if candidate_alias is None:
                                continue
                            for candidate_col in candidate_table.columns:
                                if is_geometry_type(candidate_col.data_type):
                                    geometry_candidates.append((candidate_alias, candidate_col))
                        if geometry_candidates:
                            geom_alias, geom_col = random.choice(geometry_candidates)
                            if column_tracker:
                                column_tracker.mark_column_as_select(geom_alias, geom_col.name)
                            func_node.add_child(ColumnReferenceNode(geom_col, geom_alias))
                        else:
                            func_node.add_child(create_geometry_literal_node(func.name))
                        continue
                    
                    #30% probability of generating nested functions as parameters (only one layer of nesting is supported)
                    #But the second argument to the cast function must be a data type name, not a nested function
                    #and aggregate functions and functions with special handling cannot be used as inner functions
                    #List of special handlers to exclude
                    special_functions = ['SUBSTRING', 'DATE_FORMAT', 'TO_CHAR', 'CONCAT', 'NTILE', 'NTH_VALUE', 
                                         'CAST', 'CONVERT', 'DATETIME', 'LEAD', 'LAG', 'TIMESTAMPDIFF', 'DATE', 'YEAR', 'MONTH', 'DAY', 'DATEDIFF', 'TRIM',
                                         'JSON_VALUE', 'JSON_REMOVE', 'JSON_EXTRACT', 'JSON_SET','JSON_INSERT', 'JSON_REPLACE', 'IFNULL','CUME_DIST'
                                         ]
                    if (random.random() < 0.3 and functions and not (func.name == 'CAST' and param_idx == 1)):
                        #Filter out functions whose return type is compatible with the expected parameter type, and exclude aggregate functions and special handling functions
                        if func.func_type == 'aggregate':
                            special_functions.extend(['FIRST_VALUE', 'LAST_VALUE'])
                            special_functions.extend(['ROW_NUMBER', 'RANK', 'DENSE_RANK', 'NTILE', 'CUME_DIST', 
                                               'PERCENT_RANK', 'LAG', 'LEAD', 'NTH_VALUE', 'FIRST_VALUE', 'LAST_VALUE'])
                        elif func.func_type == 'window' or func.name == 'LOG':
                        #Add all window functions to the special_functions list
                            special_functions.extend(['ROW_NUMBER', 'RANK', 'DENSE_RANK', 'NTILE', 'CUME_DIST', 
                                               'PERCENT_RANK', 'LAG', 'LEAD', 'NTH_VALUE', 'FIRST_VALUE', 'LAST_VALUE'])
                        #Make sure the current window function is also added
                            if func.name not in special_functions:
                                special_functions.append(func.name)
                        elif func.func_type == 'scalar':
                            special_functions.extend(['ROW_NUMBER', 'RANK', 'DENSE_RANK', 'NTILE', 'CUME_DIST', 
                                               'PERCENT_RANK', 'LAG', 'LEAD', 'NTH_VALUE', 'FIRST_VALUE', 'LAST_VALUE'])
                        
                        compatible_funcs = []
                        for f in functions:
                            #Ensure that the function return type is compatible with the expected parameter type and is not an aggregate function or special handling function
                            if ((f.return_type == expected_type or f.return_type == 'any' or 
                                 expected_type == 'any') and f.func_type != 'aggregate' and f.name not in special_functions):
                                compatible_funcs.append(f)
                        
                        if compatible_funcs:
                            #Select a compatible function
                            nested_func = random.choice(compatible_funcs)
                            nested_func_node = FunctionCallNode(nested_func)
                            
                            #Set type information for function expressions
                            nested_func_node.metadata['category'] = map_return_type_to_category(nested_func.return_type)
                            
                            #Add parameters to nested functions (Note: Nested function parameters can no longer be functions, only columns or literals)
                            nested_param_count = nested_func.min_params
                            if (nested_func.max_params is not None and nested_func.max_params > nested_func.min_params
                                    and not nested_func.name.startswith('ST_')):
                                nested_param_count = random.randint(nested_func.min_params, nested_func.max_params)
                            
                            for nested_param_idx in range(nested_param_count):
                                #Use an external expected parameter type to select internal parameters when the nested function return type is' any '
                                if nested_func.return_type == 'any':
                                    #Expected parameter type using external function
                                    nested_expected_type = expected_type
                                else:
                                    #Use Nested Functions Own Parameter Types
                                    nested_expected_type = map_param_type_to_category(nested_func.param_types[nested_param_idx])
                                if nested_expected_type == 'binary' and nested_func.name.startswith('ST_'):
                                    if 'FromWKB' in nested_func.name:
                                        nested_func_node.add_child(create_wkb_literal_node(nested_func.name))
                                        continue
                                    if get_required_geometry_type(nested_func.name):
                                        nested_func_node.add_child(create_geometry_literal_node(nested_func.name))
                                        continue
                                    geometry_candidates = []
                                    for candidate_table in tables_to_choose:
                                        candidate_alias = main_alias if candidate_table == main_table else join_alias
                                        if candidate_alias is None:
                                            continue
                                        for candidate_col in candidate_table.columns:
                                            if is_geometry_type(candidate_col.data_type):
                                                geometry_candidates.append((candidate_alias, candidate_col))
                                    if geometry_candidates:
                                        geom_alias, geom_col = random.choice(geometry_candidates)
                                        if column_tracker:
                                            column_tracker.mark_column_as_select(geom_alias, geom_col.name)
                                        nested_func_node.add_child(ColumnReferenceNode(geom_col, geom_alias))
                                    else:
                                        nested_func_node.add_child(create_geometry_literal_node(nested_func.name))
                                    continue
                                
                                #Select column parameters for nested functions
                                if nested_func.name == 'ST_Transform' and nested_param_idx == 1:
                                    nested_func_node.add_child(LiteralNode(4326, 'INT'))
                                    continue
                                if nested_expected_type == 'string' and is_geohash_function(nested_func.name):
                                    nested_func_node.add_child(create_geohash_literal_node())
                                    continue
                                if nested_expected_type in {'string', 'json'} and is_geojson_function(nested_func.name):
                                    nested_func_node.add_child(create_geojson_literal_node(nested_func.name))
                                    continue
                                if (nested_expected_type == 'string' and nested_func.name.startswith('ST_')
                                        and is_wkt_function(nested_func.name)):
                                    nested_func_node.add_child(create_wkt_literal_node(nested_func.name))
                                    continue
                                if nested_expected_type == 'any' or not tables_to_choose:
                                    nested_col = table.get_random_column()
                                else:
                                    nested_matching_columns = [col for col in table.columns if col.category == nested_expected_type]
                                    if nested_matching_columns:
                                        nested_col = random.choice(nested_matching_columns) 
                                    else:
                                        #No matching columns, generating a literal that matches the expected type
                                        if nested_expected_type == 'numeric':
                                            #Generate random number literals
                                            nested_func_node.add_child(LiteralNode(random.randint(1, 100), 'INT'))
                                            continue
                                        elif nested_expected_type == 'string':
                                            #Generate random string literals
                                            nested_func_node.add_child(LiteralNode(f'sample_{random.randint(1, 100)}', 'VARCHAR'))
                                            continue
                                        elif nested_expected_type == 'datetime':
                                            #Generate random datetime literals
                                            nested_func_node.add_child(LiteralNode('2023-01-01 12:00:00', 'DATETIME'))
                                            continue
                                        elif nested_expected_type == 'json':
                                            #Generate random JSON literals
                                            nested_func_node.add_child(LiteralNode('{"key": "value"}', 'JSON'))
                                            continue
                                        elif nested_expected_type == 'binary':
                                            if nested_func.name.startswith('ST_') and 'FromWKB' in nested_func.name:
                                                nested_func_node.add_child(create_wkb_literal_node(nested_func.name))
                                            else:
                                                func_name = nested_func.name if nested_func.name.startswith('ST_') else None
                                                nested_func_node.add_child(create_geometry_literal_node(func_name))
                                            continue
                                        else:
                                            #Other types, use integer face value by default
                                            nested_func_node.add_child(LiteralNode(random.randint(1, 100), 'INT'))
                                            continue
                                
                                nested_col_ref = ColumnReferenceNode(nested_col, alias)
                                nested_func_node.add_child(nested_col_ref)
                            
                            #Adding a Nested Function Node as a Parameter to a Parent Function
                            func_node.add_child(nested_func_node)
                            #Continue to next parameter
                            continue
                    
                    #Direct selection of available columns
                    if expected_type == 'json':
                        json_columns = [col for col in table.columns if col.category == 'json']
                        if json_columns:
                            col = random.choice(json_columns)
                        else:
                            func_node.add_child(LiteralNode('{"type":"Point","coordinates":[0,0]}', 'JSON'))
                            continue
                    elif expected_type == 'boolean':
                        boolean_columns = [col for col in table.columns if col.category == 'boolean']
                        if boolean_columns:
                            col = random.choice(boolean_columns)
                        else:
                            func_node.add_child(LiteralNode(random.choice([True, False]), 'BOOLEAN'))
                            continue
                    elif expected_type == 'any' or not tables_to_choose:
                        col = table.get_random_column()
                    else:
                        matching_columns = [col for col in table.columns if col.category == expected_type]
                        if matching_columns:
                            col = random.choice(matching_columns)
                        else:
                            if expected_type == 'numeric':
                                func_node.add_child(LiteralNode(random.randint(1, 100), 'INT'))
                                continue
                            elif expected_type == 'string':
                                func_node.add_child(LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING'))
                                continue
                            elif expected_type == 'datetime':
                                func_node.add_child(LiteralNode('2023-01-01 12:00:00', 'DATETIME'))
                                continue
                            elif expected_type == 'json':
                                func_node.add_child(LiteralNode('{"type":"Point","coordinates":[0,0]}', 'JSON'))
                                continue
                            elif expected_type == 'binary':
                                func_node.add_child(create_wkb_literal_node(func.name) if func.name.startswith('ST_') and 'FromWKB' in func.name else create_geometry_literal_node(func.name))
                                continue
                            elif expected_type == 'boolean':
                                func_node.add_child(LiteralNode(random.choice([True, False]), 'BOOLEAN'))
                                continue
                            col = table.get_random_column()
                    #Record columns are used in select
                    if column_tracker:
                        column_tracker.mark_column_as_select(alias, col.name)
                    col_ref = ColumnReferenceNode(col, alias)
                    #Ensure parameters are added successfully
                    if not func_node.add_child(col_ref):
                        #Use literal if column reference addition fails
                        if expected_type == 'numeric':
                            literal = LiteralNode(random.randint(1, 100), 'INT')
                        elif expected_type == 'string':
                            literal = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                        elif expected_type == 'datetime':
                            literal = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                        elif expected_type == 'json':
                            literal = LiteralNode('{"key": "value"}', 'JSON')
                        elif expected_type == 'binary':
                            lat = round(random.uniform(-90, 90), 6)
                            lng = round(random.uniform(-180, 180), 6)
                            literal = LiteralNode(f"ST_GeomFromText('POINT({lat} {lng})')", 'BINARY')
                        elif expected_type == 'boolean':
                            literal = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                        else:
                            literal = LiteralNode(random.randint(1, 100), 'INT')
                        func_node.add_child(literal)
                    
                    #Record the type of the first parameter
                    if param_idx == 0 and func.name in ['MIN', 'MAX'] and func.return_type == 'any':
                        first_param_category = col.category
                else:
                    #No tables available, use literal
                    if expected_type == 'numeric':
                        literal = LiteralNode(random.randint(1, 100), 'INT')
                    elif expected_type == 'string':
                        literal = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                    elif expected_type == 'datetime':
                        literal = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                    elif expected_type == 'json':
                        literal = LiteralNode('{"key": "value"}', 'JSON')
                    elif expected_type == 'binary':
                        lat = round(random.uniform(-90, 90), 6)
                        lng = round(random.uniform(-180, 180), 6)
                        literal = LiteralNode(f"ST_GeomFromText('POINT({lat} {lng})')", 'BINARY')
                    elif expected_type == 'boolean':
                        literal = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                    else:
                        literal = LiteralNode(random.randint(1, 100), 'INT')
                    func_node.add_child(literal)
                    
                    #Record the type of the first parameter (if it is literal)
                    if param_idx == 0 and func.name in ['MIN', 'MAX'] and func.return_type == 'any':
                        if expected_type == 'numeric':
                            first_param_category = 'numeric'
                        elif expected_type == 'string':
                            first_param_category = 'string'
                        else:
                            first_param_category = 'numeric'
        
        #For the min/max function, update the return type based on the type of the first parameter
        if func.name in ['MIN', 'MAX'] and func.return_type == 'any' and first_param_category:
            func_node.metadata['category'] = first_param_category
        
        return func_node
    elif random.random() >0.5:
        #Pass only aggregate functions to subqueries
        agg_funcs = [f for f in functions if f.func_type == 'aggregate']
        return create_select_subquery(tables, agg_funcs)
    else:
        #Use simple column references
        if for_select and random.random() < 0.2:
            literal = create_select_constant_literal()
            literal_data_type = getattr(literal, 'data_type', 'INT')
            literal.metadata['category'] = normalize_category(literal_data_type, literal_data_type)
            return literal
        tables_to_choose = [main_table] + ([join_table] if join_table else [])
        if tables_to_choose:
            table = random.choice(tables_to_choose)
            alias = main_alias if table == main_table else join_alias
            #Use the column tracker to select columns that are not used in select, having, and on
            col = get_random_column_with_tracker(table, alias, column_tracker, for_select)
            col_ref = ColumnReferenceNode(col, alias)
            #Set type information for column references
            col_ref.metadata['category'] = col.category
            return col_ref
        else:
            #Fallback scheme, using literals
            literal = LiteralNode(random.randint(1, 100), 'INT')
            #Set type information for literals
            literal.metadata['category'] = 'numeric'
            return literal

def create_expression_of_type(expr_type: str, tables: List[Table], functions: List[Function], 
                             from_node: FromNode, main_table: Table, main_alias: str, 
                             join_table: Optional[Table] = None, join_alias: Optional[str] = None, 
                             column_tracker: Optional[ColumnUsageTracker] = None) -> ASTNode:
    """Create a specific type of expression"""
    #Prefer columns of matching type
    tables_to_choose = [main_table] + ([join_table] if join_table else [])
    for table in tables_to_choose:
        matching_columns = [col for col in table.columns if col.category == expr_type]
        if matching_columns:
            alias = main_alias if table == main_table else join_alias
            col = random.choice(matching_columns)
            #Tags column used in select
            if column_tracker:
                column_tracker.mark_column_as_select(alias, col.name)
            col_ref = ColumnReferenceNode(col, alias)
            return col_ref
    
    #If there are no columns of matching type, create a function expression of matching type
    if expr_type == 'numeric':
        #Find functions that return numeric types
        numeric_funcs = [f for f in functions if f.return_type == 'numeric' or f.return_type == 'any']
        if numeric_funcs:
            func = random.choice(numeric_funcs)
            func_node = FunctionCallNode(func)
            
            #Add sufficient number of parameters
            #Special handling of three functions
            if func.name == 'SUBSTRING':
                #Special handling of the substring function: the first parameter is a string type, the second and third parameters are numeric types
                #First parameter: string type
                string_columns = []
                for table in tables_to_choose:
                    string_columns.extend([col for col in table.columns if col.category == 'string'])
                
                if string_columns:
                    col = random.choice(string_columns)
                    table = [t for t in tables_to_choose if col in t.columns][0]
                    alias = main_alias if table == main_table else join_alias
                    #Tags column used in select
                    if column_tracker:
                        column_tracker.mark_column_as_select(alias, col.name)
                    col_ref = ColumnReferenceNode(col, alias)
                else:
                    #No string type columns, use literal strings
                    col_ref = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                func_node.add_child(col_ref)
                
                #Second, three parameters: value type
                for i in range(1, func.min_params):
                    #Position parameters (1-20) and length parameters (1-10)
                    value = random.randint(1, 20) if i == 1 else random.randint(1, 10)
                    literal = LiteralNode(value, 'INT')
                    func_node.add_child(literal)
            elif func.name in ['DATE_FORMAT', 'TO_CHAR']:
                #Date_format/TO_char function special handling: the first parameter is the datetime type, the second parameter is the format string
                #First parameter: datetime type
                datetime_columns = []
                for table in tables_to_choose:
                    datetime_columns.extend([col for col in table.columns if col.category == 'datetime'])
                
                if datetime_columns:
                    col = random.choice(datetime_columns)
                    table = [t for t in tables_to_choose if col in t.columns][0]
                    alias = main_alias if table == main_table else join_alias
                    #Tags column used in select
                    if column_tracker:
                        column_tracker.mark_column_as_select(alias, col.name)
                    col_ref = ColumnReferenceNode(col, alias)
                else:
                    #No datetime type column, use date literal
                    col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                func_node.add_child(col_ref)
                
                #Second parameter: format string
                if func.min_params >= 2:
                    if func.name == 'TO_CHAR':
                        #PostgreSQL TO_char format
                        format_strings = ['YYYY-MM-DD', 'YYYY-MM-DD HH24:MI:SS', 'DD-MON-YYYY', 'HH24:MI:SS']
                    else:
                        #MySQL date_format format
                        format_strings = ['%Y-%m-%d', '%Y-%m-%d %H:%i:%s', '%d-%b-%Y', '%H:%i:%s']
                    literal = LiteralNode(random.choice(format_strings), 'STRING')
                    func_node.add_child(literal)
            elif func.name == 'CONCAT':
                #Concat function special handling: make sure all parameters are of string type
                for param_idx in range(func.min_params):
                    string_columns = []
                    for table in tables_to_choose:
                        string_columns.extend([col for col in table.columns if col.category == 'string'])
                    if string_columns:
                        col = random.choice(string_columns)
                        table = [t for t in tables_to_choose if col in t.columns][0]
                        alias = main_alias if table == main_table else join_alias
                        if column_tracker:
                            column_tracker.mark_column_as_select(alias, col.name)
                        col_ref = ColumnReferenceNode(col, alias)
                    else:
                        col_ref = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                    func_node.add_child(col_ref)
            #NTILE function special handling: make sure the parameter is a positive integer
            elif func.name == 'NTILE':
                #Generate a random integer between 1-100 as a parameter
                literal = LiteralNode(random.randint(1, 100), 'INT')
                func_node.add_child(literal)
            #Nth_value function special handling: second argument must be a positive integer
            elif func.name == 'NTH_VALUE' and func.min_params >= 2:
                #First Parameter: Column Reference
                if tables_to_choose:
                    table = random.choice(tables_to_choose)
                    alias = main_alias if table == main_table else join_alias
                    col = table.get_random_column()
                    if column_tracker:
                        column_tracker.mark_column_as_select(alias, col.name)
                    col_ref = ColumnReferenceNode(col, alias)
                    func_node.add_child(col_ref)
                else:
                    literal = LiteralNode(random.randint(1, 100), 'INT')
                    func_node.add_child(literal)
                #Second parameter: a random integer between 1-10
                literal = LiteralNode(random.randint(1, 10), 'INT')
                func_node.add_child(literal)
            #Cast/convert function special handling: make sure the second parameter is a valid data type name
            elif func.name in ['CAST', 'CONVERT']:
                #First argument: any expression (column reference used here)
                if tables_to_choose:
                    table = random.choice(tables_to_choose)
                    alias = main_alias if table == main_table else join_alias
                    col = table.get_random_column()
                    if column_tracker:
                        column_tracker.mark_column_as_select(alias, col.name)
                    col_ref = ColumnReferenceNode(col, alias)
                    func_node.add_child(col_ref)
                else:
                    literal = LiteralNode(random.randint(1, 100), 'INT')
                    func_node.add_child(literal)
                
                #Second parameter: valid data type name
                data_types = get_cast_types()
                data_type = random.choice(data_types)
                if data_type == 'CHAR':
                    length = random.randint(1, 255)
                    data_type = f"{data_type}({length})"
                literal = LiteralNode(data_type, "STRING")
                func_node.add_child(literal)
            #Datetime function special handling: arguments must be integers of 1-6
            elif func.name == 'DATETIME':
                literal = LiteralNode(random.randint(1, 6), 'INT')
                func_node.add_child(literal)
            #Lead/lag function special handling
            elif func.name in ['LEAD', 'LAG']:
                #First Parameter: Column Reference
                if tables_to_choose:
                    table = random.choice(tables_to_choose)
                    alias = main_alias if table == main_table else join_alias
                    col = table.get_random_column()
                    if column_tracker:
                        column_tracker.mark_column_as_select(alias, col.name)
                    col_ref = ColumnReferenceNode(col, alias)
                    func_node.add_child(col_ref)
                else:
                    literal = LiteralNode(random.randint(1, 100), 'INT')
                    func_node.add_child(literal)
                
                #Second parameter: a random integer between 1-10 as offset
                if func.min_params >= 2:
                    literal = LiteralNode(random.randint(1, 10), 'INT')
                    func_node.add_child(literal)
                
                #Third parameter: default (optional)
                if func.min_params >= 3:
                    if random.random() < 0.5:
                        literal = LiteralNode('NULL', 'NULL')
                    else:
                        literal = LiteralNode(random.randint(1, 100), 'INT')
                    func_node.add_child(literal)
            #Date/year/month/day/DATEDIFF function special handling: parameter should be datetime type
            elif func.name in ['DATE', 'YEAR', 'MONTH', 'DAY', 'DATEDIFF']:
                datetime_columns = []
                for table in tables_to_choose:
                    datetime_columns.extend([col for col in table.columns if col.category == 'datetime'])
                
                if datetime_columns:
                    col = random.choice(datetime_columns)
                    table = [t for t in tables_to_choose if col in t.columns][0]
                    alias = main_alias if table == main_table else join_alias
                    if column_tracker:
                        column_tracker.mark_column_as_select(alias, col.name)
                    col_ref = ColumnReferenceNode(col, alias)
                else:
                    #No datetime column, use date literal
                    col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                func_node.add_child(col_ref)
            #TimestampDiff function special handling: the first parameter is the unit of time
            elif func.name == 'TIMESTAMPDIFF' and func.min_params >= 3:
                #First Parameter: Time Units
                literal = LiteralNode(random.choice(['YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND']), 'STRING')
                func_node.add_child(literal)
                
                #Second, three parameters: datetime type
                for i in range(1, 3):
                    datetime_columns = []
                    for table in tables_to_choose:
                        datetime_columns.extend([col for col in table.columns if col.category == 'datetime'])
                    
                    if datetime_columns:
                        col = random.choice(datetime_columns)
                        table = [t for t in tables_to_choose if col in t.columns][0]
                        alias = main_alias if table == main_table else join_alias
                        if column_tracker:
                            column_tracker.mark_column_as_select(alias, col.name)
                        col_ref = ColumnReferenceNode(col, alias)
                    else:
                        col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                    func_node.add_child(col_ref)
            #JSON correlation function special handling: the second parameter is the JSON path
            elif func.name in ['JSON_VALUE', 'JSON_REMOVE', 'JSON_EXTRACT', 'JSON_SET', 'JSON_INSERT', 'JSON_REPLACE'] and func.min_params >= 2:
                #First parameter: column reference (assuming JSON type column)
                if tables_to_choose:
                    table = random.choice(tables_to_choose)
                    alias = main_alias if table == main_table else join_alias
                    col = table.get_random_column()
                    if column_tracker:
                        column_tracker.mark_column_as_select(alias, col.name)
                    col_ref = ColumnReferenceNode(col, alias)
                    func_node.add_child(col_ref)
                else:
                    literal = LiteralNode('{"key": "value"}', 'STRING')
                    func_node.add_child(literal)
                
                #Second parameter: JSON path
                literal = LiteralNode('$.key', 'STRING')
                func_node.add_child(literal)
            else:
                #Other functions use generic logic
                for param_idx in range(func.min_params):
                    expected_type = map_param_type_to_category(func.param_types[param_idx]) if param_idx < len(func.param_types) else 'any'
                    expected_type = adjust_expected_type_for_min_max(func.name, param_idx, expected_type)
                    expected_type = adjust_expected_type_for_conditionals(func.name, param_idx, expected_type)
                    if func.name == 'ST_Transform' and param_idx == 1:
                        func_node.add_child(LiteralNode(4326, 'INT'))
                        continue
                    if expected_type == 'string' and is_geohash_function(func.name):
                        func_node.add_child(create_geohash_literal_node())
                        continue
                    if expected_type in {'string', 'json'} and is_geojson_function(func.name):
                        func_node.add_child(create_geojson_literal_node(func.name))
                        continue
                    if expected_type == 'string' and func.name.startswith('ST_') and is_wkt_function(func.name):
                        func_node.add_child(create_wkt_literal_node(func.name))
                        continue
                    if expected_type == 'binary' and func.name.startswith('ST_'):
                        if get_required_geometry_type(func.name):
                            func_node.add_child(create_geometry_literal_node(func.name))
                            continue
                        if 'FromWKB' in func.name:
                            func_node.add_child(create_wkb_literal_node(func.name))
                            continue
                        geometry_candidates = []
                        for candidate_table in tables_to_choose:
                            candidate_alias = main_alias if candidate_table == main_table else join_alias
                            if candidate_alias is None:
                                continue
                            for candidate_col in candidate_table.columns:
                                if is_geometry_type(candidate_col.data_type):
                                    geometry_candidates.append((candidate_alias, candidate_col))
                        if geometry_candidates:
                            geom_alias, geom_col = random.choice(geometry_candidates)
                            if column_tracker:
                                column_tracker.mark_column_as_select(geom_alias, geom_col.name)
                            func_node.add_child(ColumnReferenceNode(geom_col, geom_alias))
                        else:
                            func_node.add_child(create_geometry_literal_node(func.name))
                        continue
                    if expected_type == 'any':
                        table = random.choice(tables_to_choose)
                        alias = main_alias if table == main_table else join_alias
                        col = get_random_column_with_tracker(table, alias, column_tracker, for_select=True)
                        if column_tracker:
                            column_tracker.mark_column_as_select(alias, col.name)
                        func_node.add_child(ColumnReferenceNode(col, alias))
                        continue
                    candidates = []
                    for candidate_table in tables_to_choose:
                        candidate_alias = main_alias if candidate_table == main_table else join_alias
                        if candidate_alias is None:
                            continue
                        for candidate_col in candidate_table.columns:
                            if candidate_col.category == expected_type:
                                candidates.append((candidate_alias, candidate_col))
                    if candidates:
                        alias, col = random.choice(candidates)
                        if column_tracker:
                            column_tracker.mark_column_as_select(alias, col.name)
                        func_node.add_child(ColumnReferenceNode(col, alias))
                    else:
                        if expected_type == 'numeric':
                            literal = LiteralNode(random.randint(1, 100), 'INT')
                        elif expected_type == 'string':
                            literal = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                        elif expected_type == 'datetime':
                            literal = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                        elif expected_type == 'json':
                            literal = LiteralNode('{"key": "value"}', 'JSON')
                        elif expected_type == 'binary':
                            literal = create_geometry_literal_node(func.name)
                        elif expected_type == 'boolean':
                            literal = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                        else:
                            literal = LiteralNode(random.randint(1, 100), 'INT')
                        func_node.add_child(literal)
            
            return func_node
    elif expr_type == 'string':
        #Find functions that return a string type
        string_funcs = [f for f in functions if f.return_type == 'string']
        if string_funcs:
            func = random.choice(string_funcs)
            func_node = FunctionCallNode(func)
            
            #Add sufficient number of parameters
            #Special handling of three functions
            if func.name == 'SUBSTRING':
                #Special handling of the substring function: the first parameter is a string type, the second and third parameters are numeric types
                #First parameter: string type
                string_columns = []
                for table in tables_to_choose:
                    string_columns.extend([col for col in table.columns if col.category == 'string'])
                
                if string_columns:
                    col = random.choice(string_columns)
                    table = [t for t in tables_to_choose if col in t.columns][0]
                    alias = main_alias if table == main_table else join_alias
                    col_ref = ColumnReferenceNode(col, alias)
                else:
                    #No string type columns, use literal strings
                    col_ref = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                func_node.add_child(col_ref)
                
                #Second, three parameters: value type
                for i in range(1, func.min_params):
                    #Position parameters (1-20) and length parameters (1-10)
                    value = random.randint(1, 20) if i == 1 else random.randint(1, 10)
                    literal = LiteralNode(value, 'INT')
                    func_node.add_child(literal)
            elif func.name in ['DATE_FORMAT', 'TO_CHAR']:
                #Date_format/TO_char function special handling: the first parameter is the datetime type, the second parameter is the format string
                #First parameter: datetime type
                datetime_columns = []
                for table in tables_to_choose:
                    datetime_columns.extend([col for col in table.columns if col.category == 'datetime'])
                
                if datetime_columns:
                    col = random.choice(datetime_columns)
                    table = [t for t in tables_to_choose if col in t.columns][0]
                    alias = main_alias if table == main_table else join_alias
                    col_ref = ColumnReferenceNode(col, alias)
                else:
                    #No datetime type column, use date literal
                    col_ref = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                func_node.add_child(col_ref)
                
                #Second parameter: format string
                if func.min_params >= 2:
                    if func.name == 'TO_CHAR':
                        #PostgreSQL TO_char format
                        format_strings = ['YYYY-MM-DD', 'YYYY-MM-DD HH24:MI:SS', 'DD-MON-YYYY', 'HH24:MI:SS']
                    else:
                        #MySQL date_format format
                        format_strings = ['%Y-%m-%d', '%Y-%m-%d %H:%i:%s', '%d-%b-%Y', '%H:%i:%s']
                    literal = LiteralNode(random.choice(format_strings), 'STRING')
                    func_node.add_child(literal)
            elif func.name == 'CONCAT':
                #Concat function special handling: make sure all parameters are of string type
                for param_idx in range(func.min_params):
                    string_columns = []
                    for table in tables_to_choose:
                        string_columns.extend([col for col in table.columns if col.category == 'string'])
                    if string_columns:
                        col = random.choice(string_columns)
                        table = [t for t in tables_to_choose if col in t.columns][0]
                        alias = main_alias if table == main_table else join_alias
                        if column_tracker:
                            column_tracker.mark_column_as_select(alias, col.name)
                        col_ref = ColumnReferenceNode(col, alias)
                    else:
                        col_ref = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                    func_node.add_child(col_ref)
            elif func.name.upper() == 'ST_GEOHASH':
                func_node.add_child(LiteralNode(random.uniform(-180, 180), 'DOUBLE'))
                func_node.add_child(LiteralNode(random.uniform(-90, 90), 'DOUBLE'))
                func_node.add_child(LiteralNode(random.randint(1, 12), 'INT'))
            else:
                #Other functions use generic logic
                for param_idx in range(func.min_params):
                    expected_type = map_param_type_to_category(func.param_types[param_idx]) if param_idx < len(func.param_types) else 'any'
                    expected_type = adjust_expected_type_for_min_max(func.name, param_idx, expected_type)
                    expected_type = adjust_expected_type_for_conditionals(func.name, param_idx, expected_type)
                    if func.name == 'ST_Transform' and param_idx == 1:
                        func_node.add_child(LiteralNode(4326, 'INT'))
                        continue
                    if expected_type == 'string' and is_geohash_function(func.name):
                        func_node.add_child(create_geohash_literal_node())
                        continue
                    if expected_type in {'string', 'json'} and is_geojson_function(func.name):
                        func_node.add_child(create_geojson_literal_node(func.name))
                        continue
                    if expected_type == 'string' and func.name.startswith('ST_') and is_wkt_function(func.name):
                        func_node.add_child(create_wkt_literal_node(func.name))
                        continue
                    if expected_type == 'binary' and func.name.startswith('ST_'):
                        if get_required_geometry_type(func.name):
                            func_node.add_child(create_geometry_literal_node(func.name))
                            continue
                        if 'FromWKB' in func.name:
                            func_node.add_child(create_wkb_literal_node(func.name))
                            continue
                        geometry_candidates = []
                        for candidate_table in tables_to_choose:
                            candidate_alias = main_alias if candidate_table == main_table else join_alias
                            if candidate_alias is None:
                                continue
                            for candidate_col in candidate_table.columns:
                                if is_geometry_type(candidate_col.data_type):
                                    geometry_candidates.append((candidate_alias, candidate_col))
                        if geometry_candidates:
                            geom_alias, geom_col = random.choice(geometry_candidates)
                            if column_tracker:
                                column_tracker.mark_column_as_select(geom_alias, geom_col.name)
                            func_node.add_child(ColumnReferenceNode(geom_col, geom_alias))
                        else:
                            func_node.add_child(create_geometry_literal_node(func.name))
                        continue
                    if expected_type == 'any':
                        table = random.choice(tables_to_choose)
                        alias = main_alias if table == main_table else join_alias
                        col = get_random_column_with_tracker(table, alias, column_tracker, for_select=True)
                        if column_tracker:
                            column_tracker.mark_column_as_select(alias, col.name)
                        func_node.add_child(ColumnReferenceNode(col, alias))
                        continue
                    candidates = []
                    for candidate_table in tables_to_choose:
                        candidate_alias = main_alias if candidate_table == main_table else join_alias
                        if candidate_alias is None:
                            continue
                        for candidate_col in candidate_table.columns:
                            if candidate_col.category == expected_type:
                                candidates.append((candidate_alias, candidate_col))
                    if candidates:
                        alias, col = random.choice(candidates)
                        if column_tracker:
                            column_tracker.mark_column_as_select(alias, col.name)
                        func_node.add_child(ColumnReferenceNode(col, alias))
                    else:
                        if expected_type == 'numeric':
                            literal = LiteralNode(random.randint(1, 100), 'INT')
                        elif expected_type == 'string':
                            literal = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                        elif expected_type == 'datetime':
                            literal = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                        elif expected_type == 'json':
                            literal = LiteralNode('{"key": "value"}', 'JSON')
                        elif expected_type == 'binary':
                            literal = create_geometry_literal_node(func.name)
                        elif expected_type == 'boolean':
                            literal = LiteralNode(random.choice([True, False]), 'BOOLEAN')
                        else:
                            literal = LiteralNode(random.randint(1, 100), 'INT')
                        func_node.add_child(literal)
            
            return func_node
    
    #Final fallback scheme, using literals of matching type
    if expr_type == 'numeric':
        return LiteralNode(random.randint(1, 100), 'INT')
    elif expr_type == 'string':
        return LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
    elif expr_type == 'datetime':
        return LiteralNode('2023-01-01 12:00:00', 'DATETIME')
    elif expr_type == 'json':
        return LiteralNode('{"key": "value"}', 'JSON')
    elif expr_type == 'binary':
        lat = round(random.uniform(-90, 90), 6)
        lng = round(random.uniform(-180, 180), 6)
        return LiteralNode(f"ST_GeomFromText('POINT({lat} {lng})')", 'BINARY')
    elif expr_type == 'boolean':
        return LiteralNode(random.choice([True, False]), 'BOOLEAN')
    else:
        return LiteralNode(random.randint(1, 100), 'INT')
