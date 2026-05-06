"""Implements comparison AST nodes and operand type/shape checks."""

#ComparisonNode Class Definition - Comparison Expression Node
from .ast_node import ASTNode
from .column_reference_node import ColumnReferenceNode
from .literal_node import LiteralNode
from .function_call_node import FunctionCallNode
from .arithmetic_node import ArithmeticNode
from data_structures.node_type import NodeType
from typing import Set, Tuple, List

class ComparisonNode(ASTNode):
    """Compare Expression Node"""

    def __init__(self, operator: str):
        super().__init__(NodeType.COMPARISON)
        #Extend the list of operators to include more SQL standard operators
        self.supported_operators = {
            '=', '<>', '!=', '<', '>', '<=', '>=',
            'LIKE', 'NOT LIKE', 'RLIKE', 'REGEXP', 'NOT REGEXP',
            'IS NULL', 'IS NOT NULL', 'IN', 'NOT IN',
            'BETWEEN', 'NOT BETWEEN', 'EXISTS', 'NOT EXISTS'
        }
        
        #Verify that the operator supports
        if operator not in self.supported_operators:
            raise ValueError(f"Unsupported operator: {operator}")
        
        self.operator = operator
        self.metadata = {
            'operator': operator,
            'is_aggregate': False  #Comparison expression is not an aggregate
        }

    def to_sql(self) -> str:
        if len(self.children) == 0:
            return ""

        left = self.children[0].to_sql() if self.children else ""

        #Single Operand Operator
        if self.operator in ['IS NULL', 'IS NOT NULL']:
            return f"{left} {self.operator}"
        
        #Exists/not exists operator
        if self.operator in ['EXISTS', 'NOT EXISTS']:
            if len(self.children) >= 1:
                subquery_sql = self.children[0].to_sql()
                #Make sure the subquery is enclosed in parentheses
                if not (subquery_sql.startswith('(') and subquery_sql.endswith(')')):
                    subquery_sql = f"({subquery_sql})"
                return f"{self.operator} {subquery_sql}"
            return ""

        #Double Operator Operator
        if len(self.children) < 2:
            return f"{left} {self.operator}"
            
        right = self.children[1].to_sql()

        #IN/not IN Operator
        if self.operator in ['IN', 'NOT IN'] and right:
            #Check if the right side is already in subquery format
            if not (right.startswith('(') and right.endswith(')')):
                #If not a subquery, then it is assumed to be a list
                return f"{left} {self.operator} ({right})"
            else:
                #If it is already a subquery format, use directly
                return f"{left} {self.operator} {right}"

        #Between/not between operators
        if self.operator in ['BETWEEN', 'NOT BETWEEN'] and len(self.children) >= 3:
            right1 = self.children[1].to_sql()
            right2 = self.children[2].to_sql()
            return f"{left} {self.operator} {right1} AND {right2}"

        #Other Double Operator Operators
        #Check if the regexp operator needs to be adapted according to the dialect
        from data_structures.db_dialect import get_dialect_config
        dialect = get_dialect_config()
        operator = self.operator
        
        #PostgreSQL Adaptation: Convert regexp, not regexp, RLIKE and not RLIKE to ~ and! ~
        if dialect.name == 'POSTGRESQL':
            if operator == 'REGEXP' or operator == 'RLIKE':
                operator = '~'
            elif operator == 'NOT REGEXP' or operator == 'NOT RLIKE':
                operator = '!~'
        #PolarDB adaptation: PolarDB does not support RLIKE and not RLIKE operators, use like instead
        elif dialect.name == 'POLARDB':
            if operator == 'RLIKE':
                operator = 'LIKE'
            elif operator == 'NOT RLIKE':
                operator = 'NOT LIKE'
        
        return f"({left} {operator} {right})"

    def collect_table_aliases(self) -> Set[str]:
        """Collect table aliases referenced in comparison expressions"""
        aliases = set()
        for child in self.children:
            aliases.update(child.collect_table_aliases())
        return aliases

    def collect_column_aliases(self) -> Set[str]:
        """Collect column aliases referenced in comparison expressions"""
        aliases = set()
        for child in self.children:
            aliases.update(child.collect_column_aliases())
        return aliases

    def _is_type_compatible(self, left_type, right_type):
        """Check if the two data types are compatible"""
        #Ideally, you should use the category attribute of the Column object to determine type compatibility
        #but since this method is designed to receive type strings directly instead of Column objects
        #We temporarily reserve judgment logic based on data type string keywords
        
        #Define type compatibility rules
        numeric_types = {'INT', 'BIGINT', 'SMALLINT', 'TINYINT', 'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC'}
        string_types = {'VARCHAR', 'CHAR', 'TEXT', 'LONGTEXT', 'MEDIUMTEXT', 'TINYTEXT'}
        datetime_types = {'DATE', 'DATETIME', 'TIMESTAMP', 'TIME'}
        
        #Extract base type (without parentheses and length information)
        base_type1 = left_type.split('(')[0].upper() if left_type else 'UNKNOWN'
        base_type2 = right_type.split('(')[0].upper() if right_type else 'UNKNOWN'
        
        #Strict type matching: must belong to the same type group
        if (base_type1 in numeric_types and base_type2 in numeric_types) or \
           (base_type1 in string_types and base_type2 in string_types) or \
           (base_type1 in datetime_types and base_type2 in datetime_types) or \
           base_type1 == base_type2:
            return True
        
        return False
        
    def _get_node_type(self, node):
        """Gets the data type of the node"""
        if isinstance(node, ColumnReferenceNode):
            return node.column.data_type
        elif isinstance(node, LiteralNode):
            return node.data_type
        elif isinstance(node, FunctionCallNode):
            return node.metadata.get('return_type', '')
        elif hasattr(node, 'metadata') and 'data_type' in node.metadata:
            return node.metadata['data_type']
        return ''
        
    def validate_columns(self, from_node: 'FromNode') -> Tuple[bool, List[str]]:
        """Verify that the column reference in the comparison expression is valid，Include type compatibility checks"""
        errors = []
        
        #Validate column references for all child nodes first
        for child in self.children:
            if hasattr(child, 'validate_columns'):
                valid, child_errors = child.validate_columns(from_node)
                if not valid:
                    errors.extend(child_errors)
            elif isinstance(child, ColumnReferenceNode):
                if not child.is_valid(from_node):
                    errors.append(f"Invalid column reference: {child.to_sql()}")
        
        #For binary comparators, check type compatibility on the left and right sides
        if self.operator in ['=', '<>', '!=', '<', '>', '<=', '>=', 'LIKE', 'NOT LIKE', 'RLIKE', 'REGEXP', 'NOT REGEXP']:
            if len(self.children) >= 2:
                left_type = self._get_node_type(self.children[0])
                right_type = self._get_node_type(self.children[1])
                
                if left_type and right_type and not self._is_type_compatible(left_type, right_type):
                    errors.append(f"Type not matched: {self.children[0].to_sql()} ({left_type}) and, {self.children[1].to_sql()} ({right_type}) In Compare Actions {self.operator} Medium")
        
        return (len(errors) == 0, errors)

    def repair_columns(self, from_node: 'FromNode') -> None:
        """Fix invalid column references and incompatible types in compare expressions"""
        for i, child in enumerate(self.children):
            if hasattr(child, 'repair_columns'):
                child.repair_columns(from_node)
            elif isinstance(child, ColumnReferenceNode) and not child.is_valid(from_node):
                replacement = child.find_replacement(from_node)
                if replacement:
                    self.children[i] = replacement
        
        #Special handling of type compatibility issues between operators
        if self.operator in ['BETWEEN', 'NOT BETWEEN'] and len(self.children) >= 3:
            #Gets the type of the left column
            left_type = self._get_node_type(self.children[0])
            left_node = self.children[0]
            
            #Check if there is a valid type on the left
            if left_type:
                base_left_type = left_type.split('(')[0].upper()
                
                #Process two boundary values (between value1 and value2)
                for i in [1, 2]:
                    right_node = self.children[i]
                    right_type = self._get_node_type(right_node)
                    
                    #Check if the node on the right has a valid type and is not compatible with the type on the left
                    if right_type and not self._is_type_compatible(left_type, right_type):
                        from data_structures.db_dialect import get_dialect_config
                        dialect = get_dialect_config()
                        
                        #Type conversion based on database dialect
                        if dialect.name == 'POSTGRESQL':
                            from data_structures.function import Function
                            
                            #Process Date Time Type Conversion
                            datetime_types = {'DATE', 'DATETIME', 'TIMESTAMP'}
                            numeric_types = {'INT', 'INTEGER', 'BIGINT', 'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC'}
                            string_types = {'VARCHAR', 'TEXT', 'CHAR'}
                            
                            base_right_type = right_type.split('(')[0].upper()
                            
                            #On the left is the datetime type and on the right is the numeric type
                            if base_left_type in datetime_types and base_right_type in numeric_types and isinstance(right_node, LiteralNode):
                                #Converts an integer face to a date-dependent expression
                                #Create TO_date function call node
                                to_date_func = Function('TO_DATE', 'date', ['string', 'string'])
                                to_date_node = FunctionCallNode(to_date_func)
                                
                                #Add parameters for TO_date
                                to_date_node.add_child(LiteralNode('2023-01-01', 'DATE'))
                                to_date_node.add_child(LiteralNode('YYYY-MM-DD', 'STRING'))
                                
                                #Create + Arithmetic Expression Node
                                plus_node = ArithmeticNode('+')
                                plus_node.add_child(to_date_node)
                                
                                #Create interval expression
                                interval_literal = LiteralNode(f'{right_node.value} days', 'STRING')
                                plus_node.add_child(interval_literal)
                                
                                #Replace the original integer face
                                self.children[i] = plus_node
                            
                            #Conversion of number type to character type
                            elif ((base_left_type in numeric_types and base_right_type in string_types) or 
                                  (base_right_type in numeric_types and base_left_type in string_types)) and isinstance(right_node, LiteralNode):
                                #Convert character type to number type
                                cast_func = Function('CAST', 2, 2, ['any', 'string'], 'any', 'scalar')
                                cast_node = FunctionCallNode(cast_func)
                                cast_node.add_child(right_node)
                                #Add Target Data Type Parameter
                                target_type = 'INTEGER' if base_left_type in numeric_types else 'STRING'
                                cast_node.add_child(LiteralNode(target_type, 'STRING'))
                                self.children[i] = cast_node
                        else:
                            #Basic type conversion for other dialects such as MySQL, TIDB, etc.
                            #Try to create a literal that is compatible with the type on the left
                            if isinstance(right_node, LiteralNode):
                                try:
                                    #Try creating a new literal based on the type on the left
                                    if base_left_type == 'INT':
                                        new_value = int(right_node.value)
                                        self.children[i] = LiteralNode(new_value, 'INT')
                                    elif base_left_type in ['FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC']:
                                        new_value = float(right_node.value)
                                        self.children[i] = LiteralNode(new_value, 'FLOAT')
                                    elif base_left_type in ['VARCHAR', 'TEXT', 'CHAR']:
                                        new_value = str(right_node.value)
                                        self.children[i] = LiteralNode(new_value, 'VARCHAR')
                                    elif base_left_type in ['DATE', 'DATETIME', 'TIMESTAMP']:
                                        #Simply try to convert to a date string
                                        self.children[i] = LiteralNode('2023-01-01', base_left_type)
                                except:
                                    #Use a secure default if conversion fails
                                    if base_left_type in ['INT', 'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC']:
                                        self.children[i] = LiteralNode(0, 'INT')
                                    elif base_left_type in ['VARCHAR', 'TEXT', 'CHAR']:
                                        self.children[i] = LiteralNode('default_value', 'VARCHAR')
                                    elif base_left_type in ['DATE', 'DATETIME', 'TIMESTAMP']:
                                        self.children[i] = LiteralNode('2023-01-01', base_left_type)

        #Handle type compatibility issues with general binary comparison operators
        if self.operator in ['=', '<>', '!=', '<', '>', '<=', '>='] and len(self.children) >= 2:
            left_type = self._get_node_type(self.children[0])
            right_type = self._get_node_type(self.children[1])
            
            #Check if the types on the left and right are compatible
            if left_type and right_type and not self._is_type_compatible(left_type, right_type):
                #Get base type
                base_left_type = left_type.split('(')[0].upper() if left_type else ''
                base_right_type = right_type.split('(')[0].upper() if right_type else ''
                
                #Handle date time type vs. number type
                datetime_types = {'DATE', 'DATETIME', 'TIMESTAMP'}
                numeric_types = {'INT', 'INTEGER', 'BIGINT', 'FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC'}
                
                #If the datetime type is on the left and the numeric type is on the right
                if base_left_type in datetime_types and base_right_type in numeric_types and isinstance(self.children[1], LiteralNode):
                    #Convert right integer face to datetime related expression
                    from data_structures.db_dialect import get_dialect_config
                    dialect = get_dialect_config()
                    
                    if dialect.name == 'POSTGRESQL':
                        from data_structures.function import Function
                        
                        #Create TO_date function call node
                        to_date_func = Function('TO_DATE', 'date', ['string', 'string'])
                        to_date_node = FunctionCallNode(to_date_func)
                        
                        #Add parameters for TO_date
                        to_date_node.add_child(LiteralNode('2023-01-01', 'DATE'))
                        to_date_node.add_child(LiteralNode('YYYY-MM-DD', 'STRING'))
                        
                        #Create + Arithmetic Expression Node
                        plus_node = ArithmeticNode('+')
                        plus_node.add_child(to_date_node)
                        
                        #Create interval expression
                        interval_literal = LiteralNode(f'{self.children[1].value} days', 'STRING')
                        plus_node.add_child(interval_literal)
                        
                        #Replace the original integer face
                        self.children[1] = plus_node
                
                #If the datetime type is on the right and the numeric type is on the left
                elif base_right_type in datetime_types and base_left_type in numeric_types and isinstance(self.children[0], LiteralNode):
                    #Left integer face value converted to datetime related expression
                    from data_structures.db_dialect import get_dialect_config
                    dialect = get_dialect_config()
                    
                    if dialect.name == 'POSTGRESQL':
                        from data_structures.function import Function
                        
                        #Create TO_date function call node
                        to_date_func = Function('TO_DATE', 'date', ['string', 'string'])
                        to_date_node = FunctionCallNode(to_date_func)
                        
                        #Add parameters for TO_date
                        to_date_node.add_child(LiteralNode('2023-01-01', 'DATE'))
                        to_date_node.add_child(LiteralNode('YYYY-MM-DD', 'STRING'))
                        
                        #Create + Arithmetic Expression Node
                        plus_node = ArithmeticNode('+')
                        plus_node.add_child(to_date_node)
                        
                        #Create interval expression
                        interval_literal = LiteralNode(f'{self.children[0].value} days', 'STRING')
                        plus_node.add_child(interval_literal)
                        
                        #Replace the original integer face
                        self.children[0] = plus_node
                
                #Handling Integer Type to Character Type Comparisons
                elif (base_left_type in numeric_types and base_right_type in ['VARCHAR', 'TEXT', 'CHAR']) or \
                     (base_right_type in numeric_types and base_left_type in ['VARCHAR', 'TEXT', 'CHAR']):
                    #Detect Integer Type to Character Type Comparison
                    from data_structures.db_dialect import get_dialect_config
                    dialect = get_dialect_config()
                    
                    if dialect.name == 'POSTGRESQL':
                        #In PostgreSQL, add explicit type conversion
                        from data_structures.function import Function
                        
                        #On the right is the character type and on the left is the number type
                        if base_left_type in numeric_types and base_right_type in ['VARCHAR', 'TEXT', 'CHAR']:
                            #Convert string to numeric type
                            cast_func = Function('CAST', 2, 2, ['any', 'string'], 'any', 'scalar')
                            cast_node = FunctionCallNode(cast_func)
                            cast_node.add_child(self.children[1])
                            #Add Target Data Type Parameter
                            cast_node.add_child(LiteralNode('INTEGER', 'STRING'))
                            self.children[1] = cast_node
                        #On the left is the character type and on the right is the number type
                        elif base_right_type in numeric_types and base_left_type in ['VARCHAR', 'TEXT', 'CHAR']:
                            #Converts a number to a string type
                            cast_func = Function('CAST', 2, 2, ['any', 'string'], 'any', 'scalar')
                            cast_node = FunctionCallNode(cast_func)
                            cast_node.add_child(self.children[0])
                            #Add Target Data Type Parameter
                            cast_node.add_child(LiteralNode('STRING', 'STRING'))
                            self.children[0] = cast_node