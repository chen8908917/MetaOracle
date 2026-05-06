"""Implements SELECT AST nodes, clause assembly, and semantic checks."""

from typing import List, Tuple, Dict, Optional, Set
import random
from .ast_node import ASTNode
from .from_node import FromNode
from .group_by_node import GroupByNode
from .order_by_node import OrderByNode
from .limit_node import LimitNode
from .function_call_node import FunctionCallNode
from .column_reference_node import ColumnReferenceNode
from .comparison_node import ComparisonNode
from .literal_node import LiteralNode
from .subquery_node import SubqueryNode
from data_structures.db_dialect import get_current_dialect
from data_structures.node_type import NodeType
from data_structures.column import Column
from data_structures.table import Table
from data_structures.function import Function
#Import ColumnUsageTracker and get_random_column_with_tracker to track column usage
from data_structures.column_usage_tracker import ColumnUsageTracker, get_random_column_with_tracker

class SelectNode(ASTNode):
    """SELECTStatement Node"""

    def __init__(self):
        super().__init__(NodeType.SELECT)
        self.distinct = False
        self.select_expressions: List[Tuple[ASTNode, str]] = []  # (expression, alias)
        self.from_clause: Optional[FromNode] = None
        self.where_clause: Optional[ASTNode] = None
        self.group_by_clause: Optional[GroupByNode] = None
        self.having_clause: Optional[ASTNode] = None
        self.order_by_clause: Optional[OrderByNode] = None
        self.limit_clause: Optional[LimitNode] = None
        self.for_update: Optional[str] = None  #Multiple locking modes are supported: 'update', 'share', 'no key update', 'key share'
        self.tables: List[Table] = []  #Associated Table Information
        self.functions: List[Function] = []  #Available functions
        self.column_tracker: Optional[ColumnUsageTracker] = None  #Column Usage Tracker

    def add_select_expression(self, expr_node: ASTNode, alias: str = "") -> None:
        #Check if the alias is a duplicate
        used_aliases = self.get_select_column_aliases()
        base_alias = alias if alias else f"col_{len(self.select_expressions) + 1}"
        final_alias = base_alias
        #print (f "Add select expression: {expr_node.to_sql ()} Alias: {final_alias}")
        count = 1
        
        #Handle duplicate aliases
        while final_alias in used_aliases:
            final_alias = f"{base_alias}_{count}"
            count += 1
        #print (f "Final select expression alias: {final_alias}")
        self.select_expressions.append((expr_node, final_alias))
        self.add_child(expr_node)

    def get_expression_alias_map(self) -> Dict[str, ASTNode]:
        """Create expression-to-alias mapping"""
        return {alias: expr for expr, alias in self.select_expressions if alias}

    def get_alias_for_expression(self, expr_node: ASTNode) -> Optional[str]:
        """Gets the alias for the expression"""
        for expr, alias in self.select_expressions:
            if expr == expr_node:
                return alias
        return None

    def get_select_column_aliases(self) -> Set[str]:
        """Get all column aliases defined in the select clause"""
        aliases = set()
        for i, (_, alias) in enumerate(self.select_expressions):
            #Include auto-generated default aliases
            aliases.add(alias if alias else f"col_{i + 1}")
        return aliases

    def set_from_clause(self, from_node: FromNode) -> None:
        self.from_clause = from_node
        if from_node:
            self.add_child(from_node)
            #Verify table reference in from clause
            if hasattr(from_node, 'validate_table_references'):
                valid, errors = from_node.validate_table_references()
                if not valid and hasattr(from_node, 'repair_table_references'):
                    from_node.repair_table_references()

    def set_where_clause(self, where_node: ASTNode) -> None:
        #Key check 1: Make sure the where clause does not contain a window function
        if where_node.contains_window_function():
            #Create a simple where condition override
            col_node = self._get_random_column_reference()
            if col_node:
                where_node = ComparisonNode('IS NOT NULL')
                where_node.add_child(col_node)

        #Key check 2: Make sure the where clause does not contain an aggregate function (SQL syntax rule)
        if where_node.contains_aggregate_function():
            #Create a simple where condition override (without an aggregate function)
            col_node = self._get_random_column_reference()
            if col_node:
                #Using Simple Comparison Operators and Literals
                operator = random.choice(['=', '<>', '<', '>', '<=', '>=', 'IS NOT NULL'])
                where_node = ComparisonNode(operator)
                where_node.add_child(col_node)
                
                #Add right operand (if needed)
                if operator not in ['IS NULL', 'IS NOT NULL']:
                    if col_node.column.category == 'numeric':
                        where_node.add_child(LiteralNode(random.randint(0, 100), col_node.column.data_type))
                    elif col_node.column.category == 'string':
                        where_node.add_child(LiteralNode(f"sample_{random.randint(1, 100)}", 'STRING'))
                    elif col_node.column.category == 'datetime':
                        where_node.add_child(LiteralNode('2023-01-01', col_node.column.data_type))

        #Key Check 3: Make sure the where clause returns a Boolean type
        #All necessary classes have been imported at the top of the file, no partial import required
        
        #If the where clause is a function call, check if the return type is boolean
        if isinstance(where_node, FunctionCallNode):
            return_type = where_node.metadata.get('return_type', 'unknown')
            if return_type.lower() != 'boolean' and return_type.lower() != 'bool':
                #The return type is not boolean and needs to be wrapped as a comparison expression
                operator = random.choice(['=', '<>', '!='])
                new_where_node = ComparisonNode(operator)
                new_where_node.add_child(where_node)
                
                #Create appropriate literals based on return type
                #Ideally, you should use the global table structure information and the category attribute of the Column object to determine the type
                #However, since this method directly processes the return type string, it temporarily retains the judgment based on the keyword
                if return_type.lower() in ['string', 'text', 'varchar', 'char']:
                    new_where_node.add_child(LiteralNode(f"sample_value", 'STRING'))
                elif return_type.lower() in ['numeric', 'int', 'integer', 'float', 'decimal']:
                    new_where_node.add_child(LiteralNode(random.randint(0, 100), 'INT'))
                elif return_type.lower() in ['date', 'datetime', 'timestamp']:
                    new_where_node.add_child(LiteralNode('2023-01-01', 'DATE'))
                else:
                    #Use string type by default
                    new_where_node.add_child(LiteralNode(f"sample_value", 'STRING'))
                
                where_node = new_where_node

        self.where_clause = where_node
        if where_node:
            self.add_child(where_node)

    def set_group_by_clause(self, group_by_node: GroupByNode) -> None:
        self.group_by_clause = group_by_node
        if group_by_node:
            self.add_child(group_by_node)

    def set_having_clause(self, having_node: ASTNode) -> None:
        #Key check: Make sure the having clause does not contain window functions
        if having_node and having_node.contains_window_function():
            #Create a simple having condition override (using an aggregate function)
            count_func = next(f for f in self.functions if f.name == "COUNT")
            func_node = FunctionCallNode(count_func)
            col_ref = self._get_random_column_reference()
            if col_ref:
                func_node.add_child(col_ref)
            else:
                #Use count (*) if column references are not available
                func_node.add_child(LiteralNode('*', "STRING"))
            having_node = ComparisonNode('>')
            having_node.add_child(func_node)
            having_node.add_child(LiteralNode(0, "INT"))

        #Verifying the legitimacy of the having clause
        if not self._is_valid_having_clause(having_node):
            #Create a legal having condition
            if self.group_by_clause and hasattr(self.group_by_clause,
                                                'expressions') and self.group_by_clause.expressions:
                #Create conditions using expressions in group BY
                expr = random.choice(self.group_by_clause.expressions)
                having_node = ComparisonNode(random.choice(['=', '<>', '<', '>']))
                having_node.add_child(expr)
                having_node.add_child(LiteralNode(random.randint(1, 100), "INT"))
            else:
                #Create a condition based on an aggregate function
                count_func = next(f for f in self.functions if f.name == "COUNT")
                func_node = FunctionCallNode(count_func)
                col_ref = self._get_random_column_reference()
                if col_ref:
                    func_node.add_child(col_ref)
                else:
                    #Use count (*) if column references are not available
                    func_node.add_child(LiteralNode('*', "STRING"))
                having_node = ComparisonNode('>')
                having_node.add_child(func_node)
                having_node.add_child(LiteralNode(0, "INT"))

        self.having_clause = having_node
        if having_node:
            self.add_child(having_node)

    def _is_valid_having_clause(self, having_node: ASTNode) -> bool:
        """Verify that the having clause is legal"""
        if not having_node:
            return True

        #The having clause must contain an aggregate function or reference a column in group BY
        has_aggregate = having_node.contains_aggregate_function()

        if not has_aggregate and self.group_by_clause and hasattr(self.group_by_clause, 'expressions'):
            #Get all column references in group BY
            group_by_columns = set()
            for expr in self.group_by_clause.expressions:
                group_by_columns.update(expr.get_referenced_columns())

            #Gets all column references in the having clause
            having_columns = having_node.get_referenced_columns()

            #Check if all columns in having are in group BY
            if not having_columns.issubset(group_by_columns):
                return False

        return has_aggregate or (self.group_by_clause and hasattr(self.group_by_clause, 'expressions') and len(
            self.group_by_clause.expressions) > 0)

    def _get_random_column_reference(self) -> Optional[ColumnReferenceNode]:
        """Get a random column reference, including derived columns from subqueries."""
        if not self.from_clause or not hasattr(self.from_clause, 'get_all_aliases'):
            print("[SelectNode] Could not get table alias mapping, return None")
            return None

        aliases = list(self.from_clause.get_all_aliases())
        if not aliases:
            print("[SelectNode] Table alias mapping is empty, return None")
            return None

        table_alias = random.choice(aliases)
        table_ref = self.from_clause.get_table_for_alias(table_alias)
        if not table_ref:
            print(f"[SelectNode] No table reference found for alias: {table_alias}, return None")
            return None

        if isinstance(table_ref, Table):
            if self.column_tracker:
                print(f"[SelectNode] Use column tracker to select columns from {table_alias}")
                column = get_random_column_with_tracker(
                    table_ref,
                    table_alias,
                    self.column_tracker,
                    for_select=True,
                )
                if column:
                    print(f"[SelectNode] Successfully selected column via tracker: {table_alias}.{column.name}")
                    return ColumnReferenceNode(column, table_alias)
                print("[SelectNode] Column tracker failed; fallback logic will be used")
            else:
                print("[SelectNode] No column tracker set, use original logic")

            column = random.choice(table_ref.columns)
            print(f"[SelectNode] Use fallback logic to select columns: {table_alias}.{column.name}")
            return ColumnReferenceNode(column, table_alias)

        if isinstance(table_ref, SubqueryNode):
            valid_aliases = list(table_ref.column_alias_map.keys())
            if not valid_aliases:
                print(f"[SelectNode] Subquery has no output aliases: {table_alias}, return None")
                return None

            alias = random.choice(valid_aliases)
            _, data_type, category = table_ref.column_alias_map[alias]
            virtual_col = Column(alias, data_type, category, False, table_alias)
            print(f"[SelectNode] Use subquery output column: {table_alias}.{alias}")
            return ColumnReferenceNode(virtual_col, table_alias)

        print(f"[SelectNode] Unsupported table reference type for alias: {table_alias}, return None")
        return None

    def set_order_by_clause(self, order_by_node: OrderByNode) -> None:
        self.order_by_clause = order_by_node
        if order_by_node:
            self.add_child(order_by_node)

    def set_limit_clause(self, limit_node: LimitNode) -> None:
        self.limit_clause = limit_node
        if limit_node:
            self.add_child(limit_node)
    
    def set_for_update(self, mode) -> None:
        """Set Lock Mode
        Parameter
            mode: Block mode，Optional values: 'update', 'share', 'no key update', 'key share'
        """
        valid_modes = ['update', 'share', 'no key update', 'key share']
        if mode in valid_modes:
            self.for_update = mode
        else:
            #Use for update by default
            self.for_update = 'update'

    def to_sql(self) -> str:
        parts = []

        #Select section - make sure there is at least one expression
        select_parts = []
        for expr, alias in self.select_expressions:
            expr_sql = expr.to_sql()
            #Use auto-generated aliases (if there are no explicit aliases)
            if alias:
                select_parts.append(f"{expr_sql} AS {alias}")
            else:
                #Generate default alias for expressions without aliases
                idx = self.select_expressions.index((expr, alias)) + 1
                default_alias = f"col_{idx}"
                select_parts.append(f"{expr_sql} AS {default_alias}")

        #Prevent empty select clause
        if not select_parts:
            select_parts.append("1 AS col_1")  #Add default expression to avoid syntax errors

        distinct_str = "DISTINCT " if self.distinct else ""
        parts.append(f"SELECT {distinct_str}{', '.join(select_parts)}")

        #From section
        if self.from_clause:
            parts.append(f"FROM {self.from_clause.to_sql()}")
        else:
            parts.append("FROM DUAL")

        #Where section
        if self.where_clause:
            where_sql = self.where_clause.to_sql()
            if where_sql:  #Add valid conditions only
                parts.append(f"WHERE {where_sql}")

        #Group BY section (make sure it's not empty)
        if self.group_by_clause:
            group_by_sql = self.group_by_clause.to_sql()
            if group_by_sql.strip():  #Filter empty group BY
                parts.append(f"GROUP BY {group_by_sql}")

        #Having section - add only when group BY is available
        if self.having_clause and self.group_by_clause:
            having_sql = self.having_clause.to_sql()
            if having_sql:  #Add valid conditions only
                parts.append(f"HAVING {having_sql}")

        #Order BY section
        if self.order_by_clause:
            order_by_sql = self.order_by_clause.to_sql()
            if order_by_sql:  #Add valid sort only
                parts.append(f"ORDER BY {order_by_sql}")

        #Limit section
        if self.limit_clause:
            parts.append(f"LIMIT {self.limit_clause.to_sql()}")
            
        #Lock Mode Section
        if self.for_update:
            #Get the current database dialect instance
            current_dialect = get_current_dialect()
            dialect_name = current_dialect.name.lower()
            lock_clause = ""
            #Check if it is a Percona dialect
            is_percona = 'percona' in dialect_name or (hasattr(current_dialect, '__class__') and 'percona' in current_dialect.__class__.__name__.lower())
            
            #For Percona 5.7, only for update and lock IN share mode are supported, and advanced locking modes such as for NO key update are not supported
            if is_percona or dialect_name in ['mysql', 'mariadb', 'tidb', 'oceanbase', 'polardb']:
                #Percona/MySQL/MariaDB/PolarDB and other dialects only support for update and lock IN share mode
                if self.for_update == 'share':
                    #Check if the current dialect supports share lock mode
                    if hasattr(current_dialect, 'supports_share_lock_mode'):
                        if current_dialect.supports_share_lock_mode():
                            lock_clause = "LOCK IN SHARE MODE"
                        #Do not add a lock clause if share lock mode is not supported
                    else:
                        #If the dialect does not implement this method, lock IN share mode is added by default
                        lock_clause = "LOCK IN SHARE MODE"
                elif self.for_update == 'key share':
                    #For key share mode, use lock in share mode as an alternative in unsupported dialects
                    if hasattr(current_dialect, 'supports_share_lock_mode'):
                        if current_dialect.supports_share_lock_mode():
                            lock_clause = "LOCK IN SHARE MODE"
                        #Do not add a lock clause if share lock mode is not supported
                    else:
                        #If the dialect does not implement this method, lock IN share mode is added by default
                        lock_clause = "LOCK IN SHARE MODE"
                elif self.for_update == 'no key update':
                    #For no key update mode, use for update as an alternative in unsupported dialects
                    lock_clause = "FOR UPDATE"
                else:
                    #For update mode, use for update
                    lock_clause = "FOR UPDATE"
            else:
                #Other dialects like PostgreSQL support all modes
                lock_clause = f"FOR {self.for_update.upper()}"
                
            if lock_clause:
                parts.append(lock_clause)
                
        return " ".join(parts)

    def collect_table_aliases(self) -> Set[str]:
        """Collect all table aliases referenced in select statements"""
        aliases = set()

        #Collect table aliases in select expressions
        for expr, _ in self.select_expressions:
            aliases.update(expr.collect_table_aliases())

        #Collect table aliases in the where clause
        if self.where_clause:
            aliases.update(self.where_clause.collect_table_aliases())

        #Collect table aliases in group BY clause
        if self.group_by_clause:
            aliases.update(self.group_by_clause.collect_table_aliases())

        #Collect table aliases in having clause
        if self.having_clause:
            aliases.update(self.having_clause.collect_table_aliases())

        #Collect table aliases in order BY clause
        if self.order_by_clause:
            aliases.update(self.order_by_clause.collect_table_aliases())

        return aliases

    def get_defined_aliases(self) -> Set[str]:
        """Get all table aliases defined in this select statement（Include subqueries）"""
        aliases = set()

        #Get a defined table alias from the from clause
        if self.from_clause and hasattr(self.from_clause, 'get_defined_aliases'):
            aliases.update(self.from_clause.get_defined_aliases())

        return aliases

    def validate_all_columns(self) -> Tuple[bool, List[str]]:
        """Verify that all column references are valid"""
        errors = []

        if not self.from_clause:
            return (False, ["Missing from clause"])

        #Collect all referenced table aliases
        referenced_aliases = set()
        for expr, _ in self.select_expressions:
            referenced_aliases.update(expr.collect_table_aliases())

        #Collect table aliases defined in the from clause
        defined_aliases = self.from_clause.get_all_aliases()
        #Check if a referenced table alias is not defined in the from clause
        undefined_aliases = referenced_aliases - defined_aliases
        if undefined_aliases:
            errors.extend([f"I’m here.SELECTTable alias referenced in clause'{alias}'Not inFROMDefinition in clause" for alias in undefined_aliases])

        #Validate select Expression
        for expr, _ in self.select_expressions:
            if hasattr(expr, 'validate_columns'):
                valid, expr_errors = expr.validate_columns(self.from_clause)
                if not valid:
                    errors.extend(expr_errors)
            elif isinstance(expr, ColumnReferenceNode):
                if not expr.is_valid(self.from_clause):
                    errors.append(f"Invalid column reference: {expr.to_sql()}")

        #Verify where clause
        if self.where_clause and hasattr(self.where_clause, 'validate_columns'):
            #Checks if the where clause contains subqueries
            has_subquery = False
            subquery_node = None
            subquery_nodes = []
            
            #Check if it is an exists/not exists subquery
            if hasattr(self.where_clause, 'operator') and self.where_clause.operator in ['EXISTS', 'NOT EXISTS']:
                has_subquery = True
                if len(self.where_clause.children) > 0:
                    subquery_node = self.where_clause.children[0]
                    subquery_nodes = [subquery_node]
            #Check if it is a subquery in the comparison operator (e.g. < >, =, <, >, etc.)
            elif hasattr(self.where_clause, 'children'):
                for child in self.where_clause.children:
                    if isinstance(child, SubqueryNode):
                        has_subquery = True
                        subquery_node = child
                        subquery_nodes.append(child)
                #Allow multiple subqueries without premature exit
            
            #If a subquery is included, let the subquery validate its own internal column references
            if has_subquery and subquery_nodes:
                for sq in subquery_nodes:
                    if hasattr(sq, 'validate_inner_columns'):
                        valid, where_errors = sq.validate_inner_columns()
                        if not valid:
                            errors.extend(where_errors)
                #Continue to validate parts other than subqueries to avoid missing outer column references
                for child in self.where_clause.children:
                    if isinstance(child, SubqueryNode):
                        continue
                    if hasattr(child, 'validate_columns'):
                        valid, child_errors = child.validate_columns(self.from_clause)
                        if not valid:
                            errors.extend(child_errors)
                    elif isinstance(child, ColumnReferenceNode):
                        if not child.is_valid(self.from_clause):
                            errors.append(f"Invalid column reference: {child.to_sql()}")
            else:
                #General where clause validation
                valid, where_errors = self.where_clause.validate_columns(self.from_clause)
                if not valid:
                    errors.extend(where_errors)

        #Verify group BY clause
        if self.group_by_clause:
            for expr in self.group_by_clause.expressions:
                if hasattr(expr, 'validate_columns'):
                    valid, expr_errors = expr.validate_columns(self.from_clause)
                    if not valid:
                        errors.extend(expr_errors)
                elif isinstance(expr, ColumnReferenceNode):
                    if not expr.is_valid(self.from_clause):
                        errors.append(f"Invalid column reference: {expr.to_sql()}")

        #Validate having clause
        if self.having_clause:
            if hasattr(self.having_clause, 'validate_columns'):
                valid, having_errors = self.having_clause.validate_columns(self.from_clause)
                if not valid:
                    errors.extend(having_errors)
            elif isinstance(self.having_clause, ColumnReferenceNode):
                if not self.having_clause.is_valid(self.from_clause):
                    errors.append(f"Invalid column reference: {self.having_clause.to_sql()}")

        #Verify order BY clause
        if self.order_by_clause:
            for expr, _ in self.order_by_clause.expressions:
                if hasattr(expr, 'validate_columns'):
                    valid, expr_errors = expr.validate_columns(self.from_clause)
                    if not valid:
                        errors.extend(expr_errors)
                elif isinstance(expr, ColumnReferenceNode):
                    if not expr.is_valid(self.from_clause):
                        errors.append(f"Invalid column reference: {expr.to_sql()}")

        #Validate column references in ON clause
        if hasattr(self.from_clause, 'joins'):
            for join in self.from_clause.joins:
                condition = join.get('condition')
                if condition and hasattr(condition, 'validate_columns'):
                    valid, join_errors = condition.validate_columns(self.from_clause)
                    if not valid:
                        errors.extend([f"JOINCondition Error: {err}" for err in join_errors])

        return (len(errors) == 0, errors)

    def repair_invalid_columns(self) -> None:
        """Fix all invalid column references"""
        if not self.from_clause:
            return

        #Fix duplicate column aliases
        aliases = []
        alias_count = {}
        new_select_expressions = []
        for i, (expr, alias) in enumerate(self.select_expressions):
            #Generate default alias for expressions without explicit aliases
            current_alias = alias if alias else f"col_{i + 1}"
            
            #Check if the alias is a duplicate
            if current_alias in alias_count:
                #Generate a new unique alias
                alias_count[current_alias] += 1
                new_alias = f"{current_alias}_{alias_count[current_alias]}"
            else:
                alias_count[current_alias] = 1
                new_alias = current_alias
            
            new_select_expressions.append((expr, new_alias))
            aliases.append(new_alias)
        
        #Update select expression
        self.select_expressions = new_select_expressions

        #Fix select Expression
        for i, (expr, alias) in enumerate(self.select_expressions):
            if hasattr(expr, 'repair_columns'):
                expr.repair_columns(self.from_clause)
            elif isinstance(expr, ColumnReferenceNode) and hasattr(expr, 'is_valid') and not expr.is_valid(self.from_clause):
                replacement = expr.find_replacement(self.from_clause)
                if replacement:
                    self.select_expressions[i] = (replacement, alias)

        #Fix where clause
        if self.where_clause and hasattr(self.where_clause, 'repair_columns'):
            #Checks if the where clause contains subqueries, similar to the logic in validate_all_columns
            has_subquery = False
            subquery_node = None
            
            #Check if it is an exists/not exists subquery
            if hasattr(self.where_clause, 'operator') and self.where_clause.operator in ['EXISTS', 'NOT EXISTS']:
                has_subquery = True
                if len(self.where_clause.children) > 0:
                    subquery_node = self.where_clause.children[0]
            #Check if it is a subquery in the comparison operator (e.g. < >, =, <, >, etc.)
            elif hasattr(self.where_clause, 'children'):
                for child in self.where_clause.children:
                    if isinstance(child, SubqueryNode):
                        has_subquery = True
                        subquery_node = child
                        break
            
            #If a subquery is included, let the subquery fix its own internal column references
            if has_subquery and subquery_node and hasattr(subquery_node, 'repair_columns'):
                #Important: Pass None as the from_node parameter to ensure that the repair_columns method of the subquery is completely isolated
                #Use the subquery's own from clause for internal column reference repair, do not use the external query's from clause
                subquery_node.repair_columns(None)
                #For the rest of the where clause (not the subquery part), still use the external from_clause to fix it
                remaining_children = [child for child in self.where_clause.children if child != subquery_node]
                for child in remaining_children:
                    if hasattr(child, 'repair_columns'):
                        child.repair_columns(self.from_clause)
                    elif isinstance(child, ColumnReferenceNode) and hasattr(child, 'is_valid') and not child.is_valid(self.from_clause):
                        if hasattr(child, 'find_replacement'):
                            replacement = child.find_replacement(self.from_clause)
                            if replacement:
                                for i, c in enumerate(self.where_clause.children):
                                    if c == child:
                                        self.where_clause.children[i] = replacement
                                        break
            else:
                #General where clause repair
                self.where_clause.repair_columns(self.from_clause)

        #Fix group BY clause
        if self.group_by_clause:
            for i, expr in enumerate(self.group_by_clause.expressions):
                if hasattr(expr, 'repair_columns'):
                    expr.repair_columns(self.from_clause)
                elif isinstance(expr, ColumnReferenceNode) and hasattr(expr, 'is_valid') and not expr.is_valid(self.from_clause):
                    replacement = expr.find_replacement(self.from_clause)
                    if replacement:
                        self.group_by_clause.expressions[i] = replacement

        #Fix having clause
        if self.having_clause:
            if hasattr(self.having_clause, 'repair_columns'):
                self.having_clause.repair_columns(self.from_clause)
            elif isinstance(self.having_clause, ColumnReferenceNode) and hasattr(self.having_clause, 'is_valid') and not self.having_clause.is_valid(self.from_clause):
                replacement = self.having_clause.find_replacement(self.from_clause)
                if replacement:
                    self.having_clause = replacement

        #Fix order BY clause
        if self.order_by_clause:
            repaired_order_by = []
            for expr, direction in self.order_by_clause.expressions:
                if hasattr(expr, 'repair_columns'):
                    expr.repair_columns(self.from_clause)
                    repaired_order_by.append((expr, direction))
                elif isinstance(expr, ColumnReferenceNode) and hasattr(expr, 'is_valid') and not expr.is_valid(self.from_clause):
                    replacement = expr.find_replacement(self.from_clause)
                    if replacement:
                        repaired_order_by.append((replacement, direction))
                else:
                    repaired_order_by.append((expr, direction))
            self.order_by_clause.expressions = repaired_order_by

        #Fix column references in ON clause
        if hasattr(self.from_clause, 'joins'):
            for join in self.from_clause.joins:
                condition = join.get('condition')
                if condition and hasattr(condition, 'repair_columns'):
                    condition.repair_columns(self.from_clause)
    
    def contains_window_function(self) -> bool:
        """Check to include window functions"""
        #Check select expression
        for expr, _ in self.select_expressions:
            if hasattr(expr, 'contains_window_function') and expr.contains_window_function():
                return True
        
        #Check where clause
        if self.where_clause and hasattr(self.where_clause, 'contains_window_function') and self.where_clause.contains_window_function():
            return True
        
        #Check having clause
        if self.having_clause and hasattr(self.having_clause, 'contains_window_function') and self.having_clause.contains_window_function():
            return True
        
        return False
        
    def contains_aggregate_function(self) -> bool:
        """Check for the inclusion of aggregate functions"""
        #Check select expression
        for expr, _ in self.select_expressions:
            if hasattr(expr, 'contains_aggregate_function') and expr.contains_aggregate_function():
                return True
            #Check Function Call Node
            if isinstance(expr, FunctionCallNode) and expr.metadata.get('func_type') == 'aggregate':
                return True
        
        #Check having clause
        if self.having_clause:
            if hasattr(self.having_clause, 'contains_aggregate_function') and self.having_clause.contains_aggregate_function():
                return True
            #Check Function Call Node
            if isinstance(self.having_clause, FunctionCallNode) and self.having_clause.metadata.get('func_type') == 'aggregate':
                return True
        
        return False
        
    def get_referenced_columns(self) -> Set[str]:
        """Get all referenced columns"""
        columns = set()
        #Collect column references in select expressions
        for expr, _ in self.select_expressions:
            if hasattr(expr, 'get_referenced_columns'):
                columns.update(expr.get_referenced_columns())
        
        #Collect column references in where clause
        if self.where_clause and hasattr(self.where_clause, 'get_referenced_columns'):
            columns.update(self.where_clause.get_referenced_columns())
        
        #Collect column references in the group BY clause
        if self.group_by_clause:
            for expr in self.group_by_clause.expressions:
                if hasattr(expr, 'get_referenced_columns'):
                    columns.update(expr.get_referenced_columns())
        
        #Collect column references in having clause
        if self.having_clause and hasattr(self.having_clause, 'get_referenced_columns'):
            columns.update(self.having_clause.get_referenced_columns())
        
        #Collect column references in order BY clause
        if self.order_by_clause:
            for expr in self.order_by_clause.expressions:
                if hasattr(expr, 'get_referenced_columns'):
                    columns.update(expr.get_referenced_columns())
        
        return columns
