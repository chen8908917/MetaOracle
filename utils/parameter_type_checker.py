import sqlglot
from sqlglot.expressions import TableAlias, table_
from generate_random_sql import get_tables

class ParameterTypeChecker:
        """Docstring."""
    def __init__(self):
                """Docstring."""
        self.tables = get_tables()
        print(f"初始化表结构: {self.tables}")
        self.alias_map = {}
    
    def build_alias_map(self, ast):
                """Docstring."""
        if not ast:
            return
        
        #
        if self.alias_map:  
            self.alias_map.clear()
        print(self.alias_map)
        print(ast)
        self._collect_aliases(ast)
    
    def _collect_aliases(self, node):
                """Docstring."""
        if not node:
            return
        
        #
        #
        if isinstance(node , sqlglot.expressions.Alias):
            if hasattr(node, 'this') and hasattr(node, 'alias'):
                #
                original_expr = str(node.this)
                alias = getattr(node, 'alias').lower()
                #
                self.alias_map[alias] = original_expr
        
        #
        elif isinstance(node, sqlglot.expressions.Table):
            if hasattr(node,'alias') and hasattr(node,'this'):
                alias=str(node.alias)
                original_expr=str(node.this)
                self.alias_map[alias] = original_expr
            
            
        
        #
        if hasattr(node, 'args'):
            for child in node.args.values():
                if isinstance(child, (list, tuple)):
                    for item in child:
                        self._collect_aliases(item)
                else:
                    self._collect_aliases(child)
    
    def get_column_info(self, column_name):
                """Docstring."""
        print(self.alias_map)
        #
        column_name_lower = column_name.lower()
        
        #
        if 'distinct' in column_name_lower:
            column_name_lower = column_name_lower.replace('distinct', '').strip()
        
        #
        if '.' in column_name_lower:
            table_part, column_part = column_name_lower.split('.', 1)
            #
            if table_part in self.alias_map:
                actual_table = self.alias_map[table_part]
                column_to_check = f"{actual_table}.{column_part}"
            else:
                column_to_check = column_name_lower
        else:
            #
            if column_name_lower in self.alias_map:
                column_to_check = self.alias_map[column_name_lower]
            else:
                column_to_check = column_name_lower
        
        #
        column_info = {
            'name': column_to_check,
            'type': None,
            'has_nulls': False,
            'is_numeric': False
        }
        
        #
        self.tables = get_tables()

        if self.tables:

            found = False
            target_table = None
            target_column = column_to_check
            print(f"    检查列: {column_to_check}")
            #
            if '.' in column_to_check:
                table_part, column_part = column_to_check.split('.', 1)
                target_table = table_part
                target_column = column_part
            
            #
            if target_table:
                print(f"    目标表: {target_table}")
                for table in self.tables:
                    if table.name.lower() == target_table:
                        print(f"    目标列: {target_column}")
                        for column in table.columns:
                            if column.name == target_column:
                                column_info['type'] = column.data_type
                                column_info['has_nulls'] = column.is_nullable
                                column_info['is_numeric'] = column.category == 'numeric'
                                found = True
                                break
                        if found:
                            break
            
            #
            if not found:
                for table in self.tables:
                    for column in table.columns:
                        if column.name.lower() == column_to_check or (target_column and column.name.lower() == target_column):
                            column_info['type'] = column.data_type
                            column_info['has_nulls'] = column.is_nullable
                            column_info['is_numeric'] = column.category == 'numeric'
                            found = True
                            break
                    if found:
                        break
        
        return column_info
    
    def is_numeric_column(self, column_name):
                """Docstring."""
        print(f"    检查列名: {column_name}")
        column_info = self.get_column_info(column_name)
        print(f"    列信息: {column_info}")
        return column_info['is_numeric']
    
    def is_date_column(self, column_name):
                """Docstring."""
        column_info = self.get_column_info(column_name)
        if not column_info['type']:
            return False
        
        type_lower = column_info['type'].lower()
        return 'date' in type_lower and 'time' not in type_lower
    
    def is_datetime_column(self, column_name):
                """Docstring."""
        column_info = self.get_column_info(column_name)
        if not column_info['type']:
            return False
        
        type_lower = column_info['type'].lower()
        return ('datetime' in type_lower or 
                'timestamp' in type_lower or 
                ('date' in type_lower and 'time' in type_lower))
    
    def is_string_column(self, column_name):
                """Docstring."""
        column_info = self.get_column_info(column_name)
        
        #
        if column_info.get('is_numeric') is not None:
            return not column_info['is_numeric']
        
        #
        if not column_info['type']:
            return False
        
        type_lower = column_info['type'].lower()
        return any(keyword in type_lower for keyword in ['char', 'text', 'string'])
    
    def _get_function_return_type(self, func_node):
                """Docstring."""
        if not func_node:
            return 'any'
        
        func_class = func_node.__class__.__name__
        
        #
        func_name = func_class.upper()
        
        #
        numeric_functions = ['ABS', 'SQRT', 'POW', 'EXP', 'LN', 'LOG', 'LOG10', 'LOG2',
                           'SIN', 'COS', 'TAN', 'ASIN', 'ACOS', 'ATAN', 'COT',
                           'ROUND', 'TRUNCATE', 'CEIL', 'CEILING', 'FLOOR',
                           'SUM', 'AVG', 'MAX', 'MIN', 'COUNT', 'VARIANCE', 'STDDEV',
                           'MEDIAN', 'SUM_DISTINCT', 'COUNT_DISTINCT']
        
        #
        string_functions = ['LOWER', 'UPPER', 'CONCAT', 'LTRIM', 'RTRIM', 'TRIM',
                          'REPLACE', 'REPEAT', 'LPAD', 'RPAD', 'REVERSE', 'LENGTH',
                          'SUBSTRING', 'CHAR', 'ASCII', 'CONCAT_WS', 'FIND_IN_SET',
                          'RIGHT','LEFT']
        
        #
        date_functions = ['DATE', 'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND',
                        'DATEDIFF', 'TIMEDIFF', 'DATE_ADD', 'DATE_SUB', 'DATE_FORMAT',
                        'NOW', 'CURDATE', 'CURTIME', 'UNIX_TIMESTAMP', 'FROM_UNIXTIME']
        
        #
        datetime_functions = ['DATETIME', 'TIMESTAMP', 'FROM_UNIXTIME', 'UNIX_TIMESTAMP',
                            'NOW', 'SYSDATE', 'CURRENT_TIMESTAMP']
        
        if func_name in numeric_functions:
            return 'numeric'
        elif func_name in string_functions:
            return 'string'
        elif func_name in datetime_functions:
            return 'datetime'
        elif func_name in date_functions:
            return 'date'
        
        #
        return 'any'
    
    def is_numeric_parameter(self, param_node):
                """Docstring."""
        if not param_node:
            return False
        
        print(f"  is_numeric_parameter调用，参数节点类型: {type(param_node).__name__}")
        
        param_class = param_node.__class__.__name__
        
        #
        if param_class in ['Column', 'Ref', 'Identifier']:
            print(f"    参数类是Column/Ref，处理列引用")
            #
            full_column_name = str(param_node)
            print(f"    完整列引用: {full_column_name}")
            
            #
            result = self.is_numeric_column(full_column_name)
            print(f"    is_numeric_column返回: {result}")
            return result
        
        #
        #
        #
        func_name = param_class.upper()
        
        #
        all_functions = ['ABS', 'SQRT', 'POW', 'EXP', 'LN', 'LOG', 'LOG10', 'LOG2',
                        'SIN', 'COS', 'TAN', 'ASIN', 'ACOS', 'ATAN', 'COT',
                        'ROUND', 'TRUNCATE', 'CEIL', 'CEILING', 'FLOOR',
                        'SUM', 'AVG', 'MAX', 'MIN', 'COUNT', 'VARIANCE', 'STDDEV',
                        'MEDIAN', 'SUM_DISTINCT', 'COUNT_DISTINCT',
                        'LOWER', 'UPPER', 'CONCAT', 'LTRIM', 'RTRIM', 'TRIM',
                        'REPLACE', 'REPEAT', 'LPAD', 'RPAD', 'REVERSE', 'LENGTH',
                        'SUBSTRING', 'CHAR', 'ASCII', 'CONCAT_WS', 'FIND_IN_SET',
                        'DATE', 'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND',
                        'DATEDIFF', 'TIMEDIFF', 'DATE_ADD', 'DATE_SUB', 'DATE_FORMAT',
                        'NOW', 'CURDATE', 'CURTIME', 'UNIX_TIMESTAMP', 'FROM_UNIXTIME',
                        'DATETIME', 'TIMESTAMP', 'FROM_UNIXTIME', 'UNIX_TIMESTAMP',
                        'NOW', 'SYSDATE', 'CURRENT_TIMESTAMP']
        
        if func_name in all_functions:
            #
            return_type = self._get_function_return_type(param_node)
            
            if return_type == 'numeric':
                return True
            elif return_type == 'string' or return_type == 'date' or return_type == 'datetime':
                return False
            elif return_type == 'any':
                #
                if hasattr(param_node, 'args') and param_node.args:
                    #
                    first_arg_key = list(param_node.args.keys())[0]
                    first_arg = param_node.args[first_arg_key]
                    return self.is_numeric_parameter(first_arg)
        
        #
        if param_class == 'Neg':
            if hasattr(param_node, 'this'):
                return self.is_numeric_parameter(param_node.this)
        
        #
        if param_class in ['Number', 'Float', 'Integer']:
            return True
        #
        if param_class == 'Literal':
            if getattr(param_node, 'is_string', False):
                return False
            #
            try:
                float(param_node.this)
                return True
            except (TypeError, ValueError):
                return False
        
        #
        return False
    
    def is_string_parameter(self, param_node):
                """Docstring."""
        if not param_node:
            return False
        
        param_class = param_node.__class__.__name__
        
        #
        if param_class in ['Column', 'Ref', 'Identifier']:
            #
            full_column_name = str(param_node)
            
            #
            return self.is_string_column(full_column_name)
        
        #
        #
        if param_class == 'Anonymous':
            param_class = param_node.this
        func_name = param_class.upper()
        
        #
        all_functions = ['ABS', 'SQRT', 'POW', 'EXP', 'LN', 'LOG', 'LOG10', 'LOG2',
                        'SIN', 'COS', 'TAN', 'ASIN', 'ACOS', 'ATAN', 'COT',
                        'ROUND', 'TRUNCATE', 'CEIL', 'CEILING', 'FLOOR',
                        'SUM', 'AVG', 'MAX', 'MIN', 'COUNT', 'VARIANCE', 'STDDEV',
                        'MEDIAN', 'SUM_DISTINCT', 'COUNT_DISTINCT',
                        'LOWER', 'UPPER', 'CONCAT', 'LTRIM', 'RTRIM', 'TRIM',
                        'REPLACE', 'REPEAT', 'LPAD', 'RPAD', 'REVERSE', 'LENGTH',
                        'SUBSTRING', 'CHAR', 'ASCII', 'CONCAT_WS', 'FIND_IN_SET',
                        'DATE', 'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND',
                        'DATEDIFF', 'TIMEDIFF', 'DATE_ADD', 'DATE_SUB', 'DATE_FORMAT',
                        'NOW', 'CURDATE', 'CURTIME', 'UNIX_TIMESTAMP', 'FROM_UNIXTIME',
                        'DATETIME', 'TIMESTAMP', 'FROM_UNIXTIME', 'UNIX_TIMESTAMP',
                        'NOW', 'SYSDATE', 'CURRENT_TIMESTAMP']
        
        if func_name in all_functions:
            #
            return_type = self._get_function_return_type(param_node)
            
            if return_type == 'string':
                return True
            elif return_type == 'numeric' or return_type == 'date' or return_type == 'datetime':
                return False
            elif return_type == 'any':
                #
                if hasattr(param_node, 'args') and param_node.args:
                    #
                    first_arg_key = list(param_node.args.keys())[0]
                    first_arg = param_node.args[first_arg_key]
                    return self.is_string_parameter(first_arg)
        
        #
        if param_class in ['Literal', 'String']:
            return True
        
        #
        return False
    
    def is_datetime_parameter(self, param_node):
                """Docstring."""
        if not param_node:
            return False
        
        param_class = param_node.__class__.__name__
        
        #
        if param_class in ['Column', 'Ref', 'Identifier']:
            #
            full_column_name = str(param_node)
            
            #
            column_info = self.get_column_info(full_column_name)
            
            #
            if column_info.get('is_numeric') is True:
                return False
            
            #
            if column_info['type']:
                type_lower = column_info['type'].lower()
                return any(keyword in type_lower for keyword in ['date', 'time', 'datetime', 'timestamp'])
            else:
                #
                return True
        
        #
        #
        func_name = param_class.upper()
        
        #
        all_functions = ['ABS', 'SQRT', 'POW', 'EXP', 'LN', 'LOG', 'LOG10', 'LOG2',
                        'SIN', 'COS', 'TAN', 'ASIN', 'ACOS', 'ATAN', 'COT',
                        'ROUND', 'TRUNCATE', 'CEIL', 'CEILING', 'FLOOR',
                        'SUM', 'AVG', 'MAX', 'MIN', 'COUNT', 'VARIANCE', 'STDDEV',
                        'MEDIAN', 'SUM_DISTINCT', 'COUNT_DISTINCT',
                        'LOWER', 'UPPER', 'CONCAT', 'LTRIM', 'RTRIM', 'TRIM',
                        'REPLACE', 'REPEAT', 'LPAD', 'RPAD', 'REVERSE', 'LENGTH',
                        'SUBSTRING', 'CHAR', 'ASCII', 'CONCAT_WS', 'FIND_IN_SET',
                        'DATE', 'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND',
                        'DATEDIFF', 'TIMEDIFF', 'DATE_ADD', 'DATE_SUB', 'DATE_FORMAT',
                        'NOW', 'CURDATE', 'CURTIME', 'UNIX_TIMESTAMP', 'FROM_UNIXTIME',
                        'DATETIME', 'TIMESTAMP', 'FROM_UNIXTIME', 'UNIX_TIMESTAMP',
                        'NOW', 'SYSDATE', 'CURRENT_TIMESTAMP']
        
        if func_name in all_functions:
            #
            return_type = self._get_function_return_type(param_node)
            
            if return_type == 'date' or return_type == 'datetime':
                return True
            elif return_type == 'numeric' or return_type == 'string':
                return False
            elif return_type == 'any':
                #
                if hasattr(param_node, 'args') and param_node.args:
                    #
                    first_arg_key = list(param_node.args.keys())[0]
                    first_arg = param_node.args[first_arg_key]
                    return self.is_datetime_parameter(first_arg)
        
        #
        if param_class in ['Literal', 'String']:
            #
            if hasattr(param_node, 'this'):
                value = str(param_node.this)
                result = any(keyword in value for keyword in ['-', ':', ' '])
                return result
        
        #
        return False

#
global_parameter_checker = ParameterTypeChecker()
