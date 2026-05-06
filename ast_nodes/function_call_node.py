"""Implements scalar/aggregate function call AST nodes and parameter checks."""

#FunctionCallNode Class Definition - Function Call Node
from typing import Set, Optional, Tuple, List
import random
from .ast_node import ASTNode
from .column_reference_node import ColumnReferenceNode
from .literal_node import LiteralNode
from .arithmetic_node import ArithmeticNode
from .case_node import CaseNode
from data_structures.node_type import NodeType
from data_structures.function import Function
from data_structures.db_dialect import get_dialect_config

class FunctionCallNode(ASTNode):
    """Function Call Node - Enhanced，Add Parameter Type Validation"""

    def __init__(self, function: Function):
        super().__init__(NodeType.FUNCTION_CALL)
        self.function = function
        self.category = None
        self.metadata = {
            'function_name': function.name,
            'return_type': function.return_type,
            'is_aggregate': function.func_type == 'aggregate',  #Mark as aggregate function or not
            'func_type': function.func_type  #Save function type for checking
        }
        
    @property
    def data_type(self):
        """Accessor that provides the data_type property，Avoid AttributeError"""
        return self.metadata.get('return_type', 'unknown')

    def collect_table_aliases(self) -> Set[str]:
        """Collect all table aliases referenced in function parameters"""
        aliases = set()
        #Recursively collect table alias references for all parameter nodes
        for child in self.children:
            aliases.update(child.collect_table_aliases())
        return aliases

    def validate_columns(self, from_node: 'FromNode') -> Tuple[bool, List[str]]:
        """Verify that the column reference in the function parameter is valid"""
        if not from_node:
            return True, []
        errors = []
        for child in self.children:
            if hasattr(child, 'validate_columns'):
                valid, child_errors = child.validate_columns(from_node)
                if not valid:
                    errors.extend(child_errors)
            elif isinstance(child, ColumnReferenceNode):
                if not child.is_valid(from_node):
                    errors.append(f"Invalid column reference: {child.to_sql()}")
        return (len(errors) == 0, errors)

    def repair_columns(self, from_node: 'FromNode') -> None:
        """Fix invalid column references in function arguments"""
        if not from_node:
            return
        for i, child in enumerate(self.children):
            if hasattr(child, 'repair_columns'):
                child.repair_columns(from_node)
            elif isinstance(child, ColumnReferenceNode) and not child.is_valid(from_node):
                replacement = child.find_replacement(from_node)
                if replacement:
                    self.children[i] = replacement

    def add_child(self, child: ASTNode) -> bool:
        """Add function parameters and validate types

        Returns:
            bool: Parameter added successfully
        """
        #Check if the maximum number of parameters is reached
        if self.function.max_params is not None and len(self.children) >= self.function.max_params:
            return False

        #Parameter Type Validation
        param_index = len(self.children)
        if param_index < len(self.function.param_types):
            expected_type = self.function.param_types[param_index]
            if expected_type == 'datetime' and isinstance(child, LiteralNode):
                if str(child.data_type).lower() == 'date':
                    child = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
            
            #Special handling of the substring and round functions
            if self.function.name == 'SUBSTRING':
                if param_index == 1:  #Second parameter: start position
                    #Make sure it's a positive integer (PostgreSQL requires it to be of type Integer)
                    if isinstance(child, LiteralNode):
                        if isinstance(child.value, (int, float)):
                            if child.value <= 0:
                                child = LiteralNode(random.randint(1, 10), 'INT')
                            else:
                                #Make sure to use the integer type, not numeric/float
                                child = LiteralNode(int(child.value), 'INT')
                    elif isinstance(child, ColumnReferenceNode):
                        #Check if column is integer type
                        col_category = child.column.category
                        if col_category != 'int':
                            #Use integer face if column is not integer type
                            child = LiteralNode(random.randint(1, 10), 'INT')
                    elif not self._is_valid_param_type(child, expected_type):
                        child = LiteralNode(random.randint(1, 10), 'INT')
                elif param_index == 2:  #Third parameter: length
                    #Ensure non-negative integers (PostgreSQL requires integer types)
                    if isinstance(child, LiteralNode):
                        if isinstance(child.value, (int, float)):
                            if child.value < 0:
                                child = LiteralNode(random.randint(1, 20), 'INT')
                            else:
                                #Make sure to use the integer type, not numeric/float
                                child = LiteralNode(int(child.value), 'INT')
                    elif isinstance(child, ColumnReferenceNode):
                        #Check if column is integer type
                        col_category = child.column.category
                        if col_category != 'int':
                            #Use integer face if column is not integer type
                            child = LiteralNode(random.randint(1, 20), 'INT')
                    elif not self._is_valid_param_type(child, expected_type):
                        child = LiteralNode(random.randint(1, 20), 'INT')
                elif not self._is_valid_param_type(child, expected_type):
                    #First parameter or other parameter type mismatch
                    if expected_type == 'string':
                        child = LiteralNode(f'str_{random.randint(1, 100)}', 'STRING')
                    else:
                        return False
            elif self.function.name == 'DATE_FORMAT':
                #Strictly ensure that the second argument to the date_format function is a valid format string literal
                #This meets the standard usage requirements of MySQL
                if param_index == 1:  #Second parameter: format string
                    #Force standard MySQL date-time format strings
                    #Replace with a predefined format string literal regardless of the original parameter type
                    format_options = ['%Y-%m-%d', '%Y/%m/%d', '%Y%m%d', '%Y-%m-%d %H:%i:%s', '%H:%i:%s']
                    child = LiteralNode(random.choice(format_options), 'STRING')
            elif self.function.name == 'ROUND':
                if param_index == 0:  #First Parameter: Rounded Value
                    #Check if timestamp type, if yes convert to numeric type
                    from data_structures.db_dialect import get_dialect_config
                    dialect = get_dialect_config()
                    
                elif param_index == 1:  #Second parameter: number of decimal places
                    #PostgreSQL requires that the second argument to the round function must be an integer type
                    if isinstance(child, LiteralNode):
                        if isinstance(child.value, (int, float)):
                            #Convert to Integer and make sure the type is INT
                            child = LiteralNode(int(child.value), 'INT')
                    elif isinstance(child, ColumnReferenceNode):
                        #Check if column is integer type
                        col_category = child.column.category
                        if col_category != 'int':
                            #Use integer face if column is not integer type
                            child = LiteralNode(random.randint(0, 5), 'INT')
                    elif not self._is_valid_param_type(child, expected_type):
                        child = LiteralNode(random.randint(0, 5), 'INT')
                
            #Date_add, date_sub, adddate, subdate functions special handling
            elif self.function.name in ['DATE_ADD', 'DATE_SUB', 'ADDDATE', 'SUBDATE']:
                if param_index == 0:  #First parameter: datetime value
                    #Make sure it's a datetime type
                    if not self._is_valid_param_type(child, 'datetime'):
                        if isinstance(child, ColumnReferenceNode):
                            #Use date literal if not a column of datetime type
                            child = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                        elif isinstance(child, LiteralNode):
                            #Convert to date literal if literal is not datetime type
                            child = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                        else:
                            #Otherwise, use date literals
                            child = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                elif param_index == 1:  #Second parameter: time interval unit (e.g. day, month, etc.)
                    #Make sure it is a valid time interval unit
                    if isinstance(child, LiteralNode):
                        #Check if it is a valid time interval unit
                        valid_units = ['DAY', 'MONTH', 'YEAR', 'HOUR', 'MINUTE', 'SECOND']
                        if not any(unit in str(child.value).upper() for unit in valid_units):
                            #Use day if not a valid time interval unit
                            child = LiteralNode('DAY', 'STRING')
                    else:
                        #Non-literals parameter, use day as default
                        child = LiteralNode('DAY', 'STRING')
                elif param_index == 2:  #Third parameter: interval value
                    #Make sure it's a numeric type
                    if not self._is_valid_param_type(child, 'numeric'):
                        #Use random integer if not numeric type
                        child = LiteralNode(random.randint(1, 10), 'INT')
                
            #JSON correlation function special handling
            elif self.function.name in ['JSON_SET', 'JSON_INSERT', 'JSON_REPLACE', 'JSON_REMOVE', 'JSON_EXTRACT', 'JSON_VALUE','JSON_OBJECT','JSON_ARRAY']:
                if param_index == 0:  #First parameter: JSON value
                    #Make sure it is a valid JSON type
                    if isinstance(child, FunctionCallNode):
                        #If JSON_object () or JSON_array (), make sure they have parameters
                        if child.function.name == 'JSON_OBJECT' and len(child.children) == 0:
                            #JSON_object () requires at least one key-value pair
                            child.add_child(LiteralNode('key', 'STRING'))
                            child.add_child(LiteralNode('value', 'STRING'))
                        elif child.function.name == 'JSON_ARRAY' and len(child.children) == 0:
                            #JSON_array () requires at least one element
                            child.add_child(LiteralNode('element', 'STRING'))
                    elif not self._is_valid_param_type(child, 'json'):
                        #If not JSON type, create a simple JSON object
                        from data_structures.function import Function
                        json_obj_func = Function('JSON_OBJECT', 2,2,'json', ['string', 'string'], 'scalar')
                        json_obj_node = FunctionCallNode(json_obj_func)
                        json_obj_node.add_child(LiteralNode('key', 'STRING'))
                        json_obj_node.add_child(LiteralNode('value', 'STRING'))
                        child = json_obj_node
                elif param_index >= 1 and self.function.name in ['JSON_SET', 'JSON_INSERT', 'JSON_REPLACE']:
                    if param_index % 2 == 1:  #Odd Parameter Index: JSON Path
                        #Make sure it's a string type path
                        if not self._is_valid_param_type(child, 'string'):
                            #If not a string type, use the default path
                            child = LiteralNode('$.key', 'STRING')
                    else:  #Even Parameter Index: Value
                        #Can be of any type and does not require special handling
                        pass
                elif param_index >= 1 and self.function.name in ['JSON_EXTRACT', 'JSON_REMOVE']:
                    #Make sure it's a string type path
                    if not self._is_valid_param_type(child, 'string'):
                        #If not a string type, use the default path
                        child = LiteralNode('$.key', 'STRING')
                
            elif not self._is_valid_param_type(child, expected_type):
                #Type validation of other functions - make sure all functions get enough arguments
                #Create literals of matching types as fallbacks
                if expected_type == 'numeric':
                    child = LiteralNode(random.randint(1, 100), 'INT')
                elif expected_type == 'string':
                    child = LiteralNode(f'sample_{random.randint(1, 100)}', 'STRING')
                elif expected_type == 'datetime':
                    child = LiteralNode('2023-01-01 12:00:00', 'DATETIME')
                else:
                    #Defaults to a numeric type
                    child = LiteralNode(random.randint(1, 100), 'INT')

        super().add_child(child)
        return True

    def _is_valid_param_type(self, child: ASTNode, expected_type: str) -> bool:
        """Verify that the parameter types match

        Args:
            child: Parameter Node
            expected_type: Expected parameter type

        Returns:
            bool: Whether the parameter type is valid
        """
        if expected_type == 'any':
            #For aggregate functions, special treatment of geometry type columns
            if self.metadata.get('is_aggregate') and isinstance(child, ColumnReferenceNode):
                #Check if the data type of the column is geometric
                if child.column.data_type in ['GEOMETRY', 'POINT', 'LINESTRING', 'POLYGON']:
                    return False  #Aggregate functions do not support geometry types
            return True  #Non-aggregate functions or non-geometric types accept any type

        if isinstance(child, ColumnReferenceNode):
            #column reference node, checking column type
            col_category = child.column.category
            return col_category == expected_type or (expected_type == 'numeric' and col_category in ['int', 'float', 'decimal'])
        elif isinstance(child, LiteralNode):
            #literal node, checking data type
            if hasattr(child, 'data_type'):
                data_type = child.data_type.lower()
                if expected_type == 'numeric':
                    return data_type in ['int', 'float', 'decimal', 'numeric']
                elif expected_type == 'string':
                    return data_type in ['varchar', 'string', 'char']
                elif expected_type == 'datetime':
                    return data_type in ['date', 'datetime', 'timestamp']
                return data_type == expected_type
            #Returns False if there is no data_type attribute
                return data_type in ['int', 'float', 'decimal', 'numeric']
            elif expected_type == 'string':
                return data_type in ['varchar', 'string', 'char']
            elif expected_type == 'datetime':
                return data_type in ['date', 'datetime', 'timestamp']
            return data_type == expected_type
        elif isinstance(child, FunctionCallNode):
            #Function call node, check return type
            return child.metadata.get('return_type') == expected_type
        elif isinstance(child, ArithmeticNode):
            #Arithmetic expression node, the result is usually numeric
            return expected_type == 'numeric'
        elif isinstance(child, CaseNode):
            #Case expression, check result type
            result_type = child.metadata.get('result_type', 'unknown')
            return result_type == expected_type or expected_type == 'any'

        return False

    def to_sql(self) -> str:
        #Get current dialect configuration
        dialect = get_dialect_config()
        
        #Get dialect-specific function names
        function_name = dialect.get_function_name(self.function.name)
        #Function call parameter SQL
        args = [child.to_sql() for child in self.children]
        #Handle some functions specially
        if self.function.name == 'DATE_FORMAT' and dialect.get_function_name('DATE_FORMAT') == 'TO_CHAR':
            #In PostgreSQL, date_format is converted to TO_char with different parameter order
            if len(self.children) >= 2:
                # TO_CHAR(date, format)
                date_arg = self.children[0].to_sql()
                #Convert MySQL format to PostgreSQL format
                mysql_format = self.children[1].to_sql().strip("'")
                pg_format = mysql_format.replace('%Y', 'YYYY').replace('%m', 'MM').replace('%d', 'DD')
                pg_format = pg_format.replace('%H', 'HH24').replace('%i', 'MI').replace('%s', 'SS')
                return f"TO_CHAR({date_arg}, '{pg_format}')"
        
        #Special Handling count_distinct function
        if self.function.name == 'COUNT_DISTINCT':
            #Make sure there are parameters
            if self.children:
                arg_sql = self.children[0].to_sql()
                return f"COUNT(DISTINCT {arg_sql})"
        
        #Special Handling sum_distinct Function
        if self.function.name == 'SUM_DISTINCT':
            #Make sure there are parameters
            if self.children:
                arg_sql = self.children[0].to_sql()
                return f"SUM(DISTINCT {arg_sql})"
        
        #Special handling of the date_add and date_sub functions (using the interval syntax)

        
        
        #Special treatment group_concat function, add order BY clause
        if self.function.name == 'GROUP_CONCAT' and args:
            #Use first parameter as sorting basis for order BY clause
            order_by_arg = args[0]
            return f"GROUP_CONCAT({', '.join(args)} ORDER BY {order_by_arg})"
                
        if self.function.name in ['DATE_ADD', 'DATE_SUB', 'ADDDATE', 'SUBDATE'] and len(self.children) >= 3:
            date_expr = self.children[0].to_sql()
            interval_unit = self.children[1].to_sql()
            interval_value = self.children[2].to_sql()
            
            #Remove quotes from unit strings
            if interval_unit.startswith("'") and interval_unit.endswith("'"):
                interval_unit = interval_unit[1:-1]
            
            if self.function.name == 'DATE_ADD':
                return f"{date_expr} + INTERVAL {interval_value} {interval_unit}"
            else:  # DATE_SUB
                return f"{date_expr} - INTERVAL {interval_value} {interval_unit}"
        
        #Special handling of JSON related functions
        if self.function.name in ['JSON_SET', 'JSON_INSERT', 'JSON_REPLACE', 'JSON_REMOVE', 'JSON_EXTRACT', 'JSON_VALUE']:
            params_sql = []
            for i, child in enumerate(self.children):
                child_sql = child.to_sql()
                #For JSON path parameters, make sure they are string literals
                if (self.function.name in ['JSON_SET', 'JSON_INSERT', 'JSON_REPLACE'] and i % 2 == 1) or \
                   (self.function.name in ['JSON_EXTRACT', 'JSON_REMOVE'] and i >= 1) or \
                   (self.function.name == 'JSON_VALUE' and i == 1):
                    #Add quotes if not string literals
                    if not (child_sql.startswith("'") and child_sql.endswith("'")):
                        child_sql = f"'{child_sql}'"
                params_sql.append(child_sql)
            
            params_str = ', '.join(params_sql)
            return f"{self.function.name}({params_str})"

        #Window function special handling
        if self.function.func_type == 'window':
            
            window_parts = []
            partition_by = self.metadata['partition_by']
            if partition_by:
                window_parts.append(f"PARTITION BY {', '.join(partition_by)}")
            
            #For window functions that require order BY, add a default order BY clause if there is no order BY
            #Includes row_number, rank, dense_rank, lead, lag and other functions
            if not order_by and self.function.name in ['ROW_NUMBER', 'RANK', 'DENSE_RANK', 'NTILE', 'LEAD', 'LAG','PERCENT_RANK','CUME_DIST']:
                #Use constant expressions as sort basis, avoid using location references not supported by MySQL
                order_by = ['1=1']  #Use logical expressions instead of position references
                window_parts.append(f"ORDER BY {', '.join(order_by)}")
            elif order_by:
                window_parts.append(f"ORDER BY {', '.join(order_by)}")

            window_clause = f"OVER ({' '.join(window_parts)})"
            if args:
                return f"{function_name}({', '.join(args)}) {window_clause}"
            else:
                return f"{function_name}() {window_clause}"  #No Parameter Window Function
        if self.function.name in ['CONVERT']:
            return f"{function_name}({args[0]}, {args[1][1:-1]})"
        if self.function.name in ['CAST']:
            return f"{function_name}({args[0]} AS {args[1][1:-1]})"
        if self.function.name in ['DIV']:
            return f"{args[0]} {function_name} {args[1]}"
        if self.function.name in ['TRIM']:
            return f"{function_name}( BOTH {args[0]} FROM {args[1]})"
        if self.function.name in ['TIMESTAMPDIFF']:
            return f"{function_name}({args[0][1:-1]}, {args[1]}, {args[2]})"
        return f"{function_name}({', '.join(args)})"

    def collect_column_aliases(self) -> Set[str]:
        """Collect column aliases referenced in function parameters"""
        aliases = set()
        for child in self.children:
            aliases.update(child.collect_column_aliases())
        return aliases
