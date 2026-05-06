"""JOIN construction logic and join-condition generation strategies."""

import random
import string
from typing import Optional, Union

from ast_nodes import (
    ASTNode,
    ColumnReferenceNode,
    ComparisonNode,
    FunctionCallNode,
    LiteralNode,
    LogicalNode,
    FromNode,
    SelectNode,
    SubqueryNode,
)
from data_structures.column import Column
from data_structures.db_dialect import DBDialectFactory
from data_structures.table import Table
from sql_generation.random_sql.expressions import create_compatible_literal, is_type_compatible
from sql_generation.random_sql.type_utils import (
    ORDERABLE_CATEGORIES,
    get_safe_comparison_category,
    normalize_category,
)


def create_boolean_constant_join_condition(always_true: bool = True) -> ComparisonNode:
    condition = ComparisonNode("=")
    condition.add_child(LiteralNode(1, "INT"))
    condition.add_child(LiteralNode(1 if always_true else 0, "INT"))
    return condition

def generate_table_alias() -> str:
    """Generate unique table aliases"""
    sql_keywords = {'use', 'select', 'from', 'where', 'group', 'by', 'order', 'limit', 'join', 'on', 'as'}
    #Generate aliases using random strings to avoid keyword conflicts
    base_alias = ''.join(random.choices(string.ascii_lowercase, k=3))
    #Add random numbers to ensure uniqueness
    alias = base_alias + str(random.randint(1, 99))
    return alias

def create_join_condition(main_table: Table, main_alias: str, join_table: Union[Table, 'SubqueryNode'], join_alias: str) -> ASTNode:
    """Create Connection Criteria，Supports multiple advanced connection types，Make sure the type matches"""
    constant_roll = random.random()
    if constant_roll < 0.05:
        return create_boolean_constant_join_condition(always_true=True)
    if constant_roll < 0.10:
        return create_boolean_constant_join_condition(always_true=False)

    #Handling subqueries as join tables
    is_subquery_join = hasattr(join_table, 'column_alias_map')
    
    #Get the current database dialect
    current_dialect = DBDialectFactory.get_current_dialect()
    
    #Check if the current dialect supports the use of subqueries in ON conditions
    supports_subqueries_in_join = True
    if hasattr(current_dialect, 'supports_subqueries_in_join_condition'):
        supports_subqueries_in_join = current_dialect.supports_subqueries_in_join_condition()
    
    #Connection Condition Type Probability Distribution
    condition_types = ['fk', 'simple_eq', 'composite', 'range', 'like', 'null_check', 'in_condition', 'exists_condition', 'expression_based']
    weights = [0.1, 0.1, 0.1, 0.05, 0.1, 0.1, 0.15, 0.2, 0.1]
    
    #For subquery connections, select the condition type based on dialect support
    if is_subquery_join:
        if supports_subqueries_in_join:
            condition_type = random.choices(['simple_eq', 'in_condition', 'exists_condition', 'expression_based'], 
                                          weights=[0.3, 0.25, 0.25, 0.2], k=1)[0]
        else:
            #Force simple_eq when subquery connection conditions are not supported
            condition_type = 'simple_eq'
    else:
        if not supports_subqueries_in_join:
            #For non-subquery connections, also avoid condition types that contain subqueries
            condition_types_no_subquery = [t for t in condition_types if t not in ['in_condition', 'exists_condition']]
            weights_no_subquery = [weights[i] for i, t in enumerate(condition_types) if t in condition_types_no_subquery]
            #Normalized weight
            total_weight = sum(weights_no_subquery)
            weights_no_subquery = [w / total_weight for w in weights_no_subquery]
            condition_type = random.choices(condition_types_no_subquery, weights=weights_no_subquery, k=1)[0]
        else:
            condition_type = random.choices(condition_types, weights=weights, k=1)[0]
    
    log_message = (
        f"[Join condition selection] Table1: {main_table.name}({main_alias}), "
        f"Table2: {('subquery' if is_subquery_join else join_table.name)}({join_alias}), "
        f"selected condition type: {condition_type}\\n"
    )
    
    
    
    if condition_type == 'fk' and not is_subquery_join:
        #Try to find a foreign key relationship
        fk = next((fk for fk in join_table.foreign_keys if fk["ref_table"] == main_table.name), None)
        if fk:
            #There is a foreign key relationship, use a foreign key to connect
            #Find the actual columns Get the correct data type
            fk_column = next((col for col in join_table.columns if col.name == fk["column"]), None)
            ref_column = next((col for col in main_table.columns if col.name == fk["ref_column"]), None)
            
            #Use actual column type instead of hard-coded 'numeric'
            left_col = ColumnReferenceNode(
                fk_column if fk_column else Column(
                    fk["column"], 
                    "", 
                    fk.get("data_type", "INT"), 
                    False, 
                    join_table.name
                ),
                join_alias
            )
            right_col = ColumnReferenceNode(
                ref_column if ref_column else Column(
                    fk["ref_column"], 
                    "", 
                    fk.get("ref_data_type", "INT"), 
                    False, 
                    main_table.name
                ),
                main_alias
            )
            condition = ComparisonNode("=")
            condition.add_child(left_col)
            condition.add_child(right_col)
            return condition
        else:
            #Fallback to Simple Equal Connection
            log_message = f"[] in_condition: ，simple_eq\n"
            condition_type = 'simple_eq'
    
    if condition_type == 'simple_eq':
        #Simply Equal Connection Conditions - Ensure Type Match
        left_col = None
        right_col = None
        
        #Try to find compatible column pairs
        max_attempts = 10
        attempts = 0
        
        while attempts < max_attempts:
            
            #Select a random column from the main table
            left_col_candidate = main_table.get_random_column()
            
            #Select the appropriate right column based on the connection table type
            if is_subquery_join:
                #Select columns from column alias mappings for subqueries
                valid_aliases = list(join_table.column_alias_map.keys())
                selected_alias = random.choice(valid_aliases)
                col_name, data_type, category = join_table.column_alias_map[selected_alias]
                
                #If the main table is an orders table and the column is user_id, ensure that the subquery column is also of numeric type
                if main_table.name == 'orders' and left_col_candidate.name == 'user_id':
                    #Filter subquery columns of numeric type
                    numeric_aliases = [alias for alias, (_, dt, cat) in join_table.column_alias_map.items() 
                                       if cat == 'numeric' or dt.startswith(('INT', 'BIGINT', 'DECIMAL'))]
                    if numeric_aliases:
                        selected_alias = random.choice(numeric_aliases)
                        col_name, data_type, category = join_table.column_alias_map[selected_alias]
                
                #Create subquery column reference
                right_col_candidate = Column(selected_alias, join_table.alias, data_type, False, join_table.alias)
            else:
                #General Table Connection
                right_col_candidate = join_table.get_random_column()
            if is_type_compatible(left_col_candidate.data_type, right_col_candidate.data_type):
                left_col = ColumnReferenceNode(left_col_candidate, main_alias)
                right_col = ColumnReferenceNode(right_col_candidate, join_alias)
                break
            
            
            attempts += 1
        
        #If no compatible column pairs are found, look for the first compatible column pair in both tables
        if left_col is None or right_col is None:
            if is_subquery_join:
                #Subquery connection: Traverse each column of the main table and try to find subquery columns with compatible types
                for col1 in main_table.columns:
                    #If the main table is an orders table and the column is user_id, look for subquery columns of numeric type first
                    if main_table.name == 'orders' and col1.name == 'user_id':
                        numeric_aliases = [alias for alias, (_, dt, cat) in join_table.column_alias_map.items() 
                                          if cat == 'numeric' or dt.startswith(('INT', 'BIGINT', 'DECIMAL'))]
                        if numeric_aliases:
                            selected_alias = random.choice(numeric_aliases)
                            col_name, data_type, category = join_table.column_alias_map[selected_alias]
                            left_col = ColumnReferenceNode(col1, main_alias)
                            right_col_candidate = Column(selected_alias, join_table.alias, data_type, False, join_table.alias)
                            right_col = ColumnReferenceNode(right_col_candidate, join_alias)
                            break
                    
                    #Otherwise try all subquery columns
                    for alias, (col_name, data_type, category) in join_table.column_alias_map.items():
                        if is_type_compatible(col1.data_type, data_type):
                            left_col = ColumnReferenceNode(col1, main_alias)
                            right_col_candidate = Column(alias, join_table.alias, data_type, False, join_table.alias)
                            right_col = ColumnReferenceNode(right_col_candidate, join_alias)
                            break
                    if left_col and right_col:
                        break
            else:
                #General Table Connection
                for col1 in main_table.columns:
                    for col2 in join_table.columns:
                        if is_type_compatible(col1.data_type, col2.data_type):
                            left_col = ColumnReferenceNode(col1, main_alias)
                            right_col = ColumnReferenceNode(col2, join_alias)
                            break
                    if left_col and right_col:
                        break
            
            #Use the first column of the table as a last resort, but try type conversion
            if left_col is None or right_col is None:
                left_col = ColumnReferenceNode(main_table.columns[0], main_alias)
                if is_subquery_join:
                    #Subquery Connection: Select a subquery column of numeric type for the main table column of numeric type
                    if main_table.columns[0].category == 'numeric':
                        numeric_aliases = [alias for alias, (_, dt, cat) in join_table.column_alias_map.items() 
                                          if cat == 'numeric' or dt.startswith(('INT', 'BIGINT', 'DECIMAL'))]
                        if numeric_aliases:
                            selected_alias = random.choice(numeric_aliases)
                            col_name, data_type, category = join_table.column_alias_map[selected_alias]
                            right_col_candidate = Column(selected_alias, join_table.alias, data_type, False, join_table.alias)
                            right_col = ColumnReferenceNode(right_col_candidate, join_alias)
                        else:
                            #Use numeric literals if subquery has no numeric columns
                            right_col = create_compatible_literal(main_table.columns[0].data_type)
                    else:
                        #Non-numeric type, select any subquery column
                        valid_aliases = list(join_table.column_alias_map.keys())
                        selected_alias = random.choice(valid_aliases)
                        col_name, data_type, category = join_table.column_alias_map[selected_alias]
                        right_col_candidate = Column(selected_alias, join_table.alias, data_type, False, join_table.alias)
                        right_col = ColumnReferenceNode(right_col_candidate, join_alias)
                else:
                    #For numeric types, use numeric literals instead of column references
                    if main_table.columns[0].category == 'numeric' and join_table.columns[0].category != 'numeric':
                        right_col = create_compatible_literal(main_table.columns[0].data_type)
                    else:
                        right_col = ColumnReferenceNode(join_table.columns[0], join_alias)
        
        condition = ComparisonNode("=")
        condition.add_child(left_col)
        condition.add_child(right_col)
        return condition
    
    elif condition_type == 'composite':
        #Composite connection conditions (and combination)
        composite = LogicalNode("AND")
        
        #First condition (equal connection) - make sure the type matches
        left_col1 = None
        right_col1 = None
        
        #Try to find compatible column pairs
        max_attempts = 10
        attempts = 0
        
        while attempts < max_attempts:
            left_col_candidate = main_table.get_random_column()
            right_col_candidate = join_table.get_random_column()
            
            if is_type_compatible(left_col_candidate.data_type, right_col_candidate.data_type):
                left_col1 = ColumnReferenceNode(left_col_candidate, main_alias)
                right_col1 = ColumnReferenceNode(right_col_candidate, join_alias)
                break
            
            attempts += 1
        
        #If no compatible column pairs are found, look for the first compatible column pair in both tables
        if left_col1 is None or right_col1 is None:
            for col1 in main_table.columns:
                for col2 in join_table.columns:
                    if is_type_compatible(col1.data_type, col2.data_type):
                        left_col1 = ColumnReferenceNode(col1, main_alias)
                        right_col1 = ColumnReferenceNode(col2, join_alias)
                        break
                if left_col1 and right_col1:
                    break
            
            #Use the first column of the table as a last resort, but try type conversion
            if left_col1 is None or right_col1 is None:
                left_col1 = ColumnReferenceNode(main_table.columns[0], main_alias)
                #For numeric types, use numeric literals instead of column references
                if main_table.columns[0].category == 'numeric' and join_table.columns[0].category != 'numeric':
                    right_col1 = create_compatible_literal(main_table.columns[0].data_type)
                else:
                    right_col1 = ColumnReferenceNode(join_table.columns[0], join_alias)
        
        cond1 = ComparisonNode("=")
        cond1.add_child(left_col1)
        cond1.add_child(right_col1)
        composite.add_child(cond1)
        
        #The second condition (possibly other compare operations) - make sure the type matches
        operators = ["<", ">", "<=", ">=", "!="]
        op = random.choice(operators)
        left_col2 = None
        right_col2 = None
        
        attempts = 0
        while attempts < max_attempts:
            left_col_candidate = main_table.get_random_column()
            right_col_candidate = join_table.get_random_column()
            
            if is_type_compatible(left_col_candidate.data_type, right_col_candidate.data_type):
                left_col2 = ColumnReferenceNode(left_col_candidate, main_alias)
                right_col2 = ColumnReferenceNode(right_col_candidate, join_alias)
                break
            
            attempts += 1
        
        #If no compatible column pairs are found, look for the first compatible column pair in both tables
        if left_col2 is None or right_col2 is None:
            for col1 in main_table.columns:
                for col2 in join_table.columns:
                    if is_type_compatible(col1.data_type, col2.data_type):
                        left_col2 = ColumnReferenceNode(col1, main_alias)
                        right_col2 = ColumnReferenceNode(col2, join_alias)
                        break
                if left_col2 and right_col2:
                    break
            
            #Use the first column of the table as a last resort, but try type conversion
            if left_col2 is None or right_col2 is None:
                left_col2 = ColumnReferenceNode(main_table.columns[0], main_alias)
                #For numeric types, use numeric literals instead of column references
                if main_table.columns[0].category == 'numeric' and join_table.columns[0].category != 'numeric':
                    right_col2 = create_compatible_literal(main_table.columns[0].data_type)
                else:
                    right_col2 = ColumnReferenceNode(join_table.columns[0], join_alias)
        
        cond2 = ComparisonNode(op)
        cond2.add_child(left_col2)
        cond2.add_child(right_col2)
        composite.add_child(cond2)
        return composite
    
    elif condition_type == 'range':
        #Range connection conditions (use between operator of ComparisonNode) - make sure type matches
        left_col = None
        right_col_low = None
        right_col_high = None
        
        #Try to find compatible columns
        max_attempts = 10
        attempts = 0
        
        while attempts < max_attempts:
            left_col_candidate = main_table.get_random_column()
            
            #Prefer columns of numeric or date type
            if left_col_candidate.category not in ['numeric', 'datetime']:
                attempts += 1
                continue
            
            #Look for two right columns that are compatible with the left column type
            right_col_low_candidate = None
            right_col_high_candidate = None
            
            #First find a column that is compatible with the column type on the left
            for _ in range(5):
                candidate = join_table.get_random_column()
                if is_type_compatible(left_col_candidate.data_type, candidate.data_type):
                    right_col_low_candidate = candidate
                    break
            
            if right_col_low_candidate:
                #Find another column that is compatible with the left column type (can be the same column)
                for _ in range(5):
                    candidate = join_table.get_random_column()
                    if is_type_compatible(left_col_candidate.data_type, candidate.data_type):
                        right_col_high_candidate = candidate
                        break
            
            if right_col_low_candidate and right_col_high_candidate:
                left_col = ColumnReferenceNode(left_col_candidate, main_alias)
                right_col_low = ColumnReferenceNode(right_col_low_candidate, join_alias)
                right_col_high = ColumnReferenceNode(right_col_high_candidate, join_alias)
                break
            
            attempts += 1
        
        #If no compatible columns are found, look for the first compatible column pair in both tables
        if left_col is None or right_col_low is None or right_col_high is None:
            #Try to find compatible columns for left_col
            for col1 in main_table.columns:
                for col2 in join_table.columns:
                    if is_type_compatible(col1.data_type, col2.data_type):
                        left_col = ColumnReferenceNode(col1, main_alias)
                        right_col_low = ColumnReferenceNode(col2, join_alias)
                        #Try to find another compatible column or use the same column
                        for col3 in join_table.columns:
                            if is_type_compatible(col1.data_type, col3.data_type):
                                right_col_high = ColumnReferenceNode(col3, join_alias)
                                break
                        if right_col_high is None:
                            right_col_high = right_col_low
                        break
                if left_col and right_col_low and right_col_high:
                    break
            
            #Use the first column of the table as a last resort, but try type conversion
            if left_col is None or right_col_low is None or right_col_high is None:
                left_col = ColumnReferenceNode(main_table.columns[0], main_alias)
                #For non-comparable or incompatible types, use literals instead of column references
                left_fallback_category = get_safe_comparison_category(main_table.columns[0])
                right_fallback_category = get_safe_comparison_category(join_table.columns[0])
                if left_fallback_category in ORDERABLE_CATEGORIES and left_fallback_category != right_fallback_category:
                    right_col_low = create_compatible_literal(main_table.columns[0].data_type)
                    right_col_high = create_compatible_literal(main_table.columns[0].data_type)
                else:
                    right_col_low = ColumnReferenceNode(join_table.columns[0], join_alias)
                    right_col_high = ColumnReferenceNode(join_table.columns[0], join_alias)
        
        #Create between expressions
        between_expr = ComparisonNode("BETWEEN")
        between_expr.add_child(left_col)
        between_expr.add_child(right_col_low)
        between_expr.add_child(right_col_high)
        return between_expr
    
    elif condition_type == 'like':
        #Like Pattern Matching Connection
        #Select the appropriate string column
        string_col_main = None
        for col in main_table.columns:
            if col.data_type.startswith('VARCHAR') or col.data_type == 'TEXT':
                string_col_main = col
                break
        
        string_col_join = None
        for col in join_table.columns:
            if col.data_type.startswith('VARCHAR') or col.data_type == 'TEXT':
                string_col_join = col
                break
        
        if string_col_main and string_col_join:
            left_col = ColumnReferenceNode(string_col_main, main_alias)
            right_col = ColumnReferenceNode(string_col_join, join_alias)
            condition = ComparisonNode("LIKE")
            condition.add_child(left_col)
            condition.add_child(right_col)
            return condition
        else:
            #Fallback to Simple Equal Connection
            condition_type = 'simple_eq'
            left_col = ColumnReferenceNode(
                main_table.get_random_column(),
                main_alias
            )
            right_col = ColumnReferenceNode(
                join_table.get_random_column(),
                join_alias
            )
            condition = ComparisonNode("=")
            condition.add_child(left_col)
            condition.add_child(right_col)
            return condition
    
    elif condition_type == 'null_check':
        #Null Check Connection Condition
        composite = LogicalNode("AND")
        
        #First condition (equal connection) - make sure the type matches
        left_col1 = None
        right_col1 = None
        
        #Try to find compatible column pairs
        max_attempts = 10
        attempts = 0
        
        while attempts < max_attempts:
            left_col_candidate = main_table.get_random_column()
            right_col_candidate = join_table.get_random_column()
            
            if is_type_compatible(left_col_candidate.data_type, right_col_candidate.data_type):
                left_col1 = ColumnReferenceNode(left_col_candidate, main_alias)
                right_col1 = ColumnReferenceNode(right_col_candidate, join_alias)
                break
            
            attempts += 1
        
        #If no compatible column pairs are found, look for the first compatible column pair in both tables
        if left_col1 is None or right_col1 is None:
            for col1 in main_table.columns:
                for col2 in join_table.columns:
                    if is_type_compatible(col1.data_type, col2.data_type):
                        left_col1 = ColumnReferenceNode(col1, main_alias)
                        right_col1 = ColumnReferenceNode(col2, join_alias)
                        break
                if left_col1 and right_col1:
                    break
            
            #Use the first column of the table as a last resort, but try type conversion
            if left_col1 is None or right_col1 is None:
                left_col1 = ColumnReferenceNode(main_table.columns[0], main_alias)
                #For numeric types, use numeric literals instead of column references
                if main_table.columns[0].category == 'numeric' and join_table.columns[0].category != 'numeric':
                    right_col1 = create_compatible_literal(main_table.columns[0].data_type)
                else:
                    right_col1 = ColumnReferenceNode(join_table.columns[0], join_alias)
        
        cond1 = ComparisonNode("=")
        cond1.add_child(left_col1)
        cond1.add_child(right_col1)
        composite.add_child(cond1)
        
        #Second condition (null check)
        null_col = ColumnReferenceNode(
            join_table.get_random_column(),
            join_alias
        )
        #IS null/IS not null operator using ComparisonNode
        null_op = "IS NOT NULL" if random.random() > 0.5 else "IS NULL"
        cond2 = ComparisonNode(null_op)
        cond2.add_child(null_col)
        composite.add_child(cond2)
          
        return composite
    
    elif condition_type == 'in_condition':
        #IN Subquery Connection Criteria
        #Prefer columns of numeric type
        numeric_cols_main = [col for col in main_table.columns if col.category == 'numeric']
        if numeric_cols_main:
            selected_col_main = random.choice(numeric_cols_main)
            left_col = ColumnReferenceNode(selected_col_main, main_alias)
            
            #Create IN condition
            in_condition = ComparisonNode('IN')
            in_condition.add_child(left_col)
            
            #Create subquery
            subquery = SelectNode()
            
            #Select tables and columns for subqueries
            if is_subquery_join:
                #For subquery connections, use join_table as the subquery table
                subquery_table = join_table
                #Generate secure table aliases
                sql_keywords = {'use', 'select', 'from', 'where', 'group', 'by', 'order', 'limit', 'join', 'on', 'as'}
                base_alias = 'sub' + str(random.randint(0, 99))
                sub_alias = base_alias if base_alias not in sql_keywords else base_alias + str(random.randint(0, 9))
            else:
                #For regular table joins, use join_table
                subquery_table = join_table
                #Generate secure table aliases
                sql_keywords = {'use', 'select', 'from', 'where', 'group', 'by', 'order', 'limit', 'join', 'on', 'as'}
                base_alias = subquery_table.name[:3].lower()
                sub_alias = base_alias if base_alias not in sql_keywords else base_alias + str(random.randint(0, 9))
            
            #Create from clause
            sub_from = FromNode()
            sub_from.add_table(subquery_table, sub_alias)
            subquery.set_from_clause(sub_from)
            
            #Select type-compatible columns from the sub-query table
            compatible_cols = [col for col in subquery_table.columns if is_type_compatible(selected_col_main.data_type, col.data_type)]
            if compatible_cols:
                selected_col_sub = random.choice(compatible_cols)
                sub_col_ref = ColumnReferenceNode(selected_col_sub, sub_alias)
                subquery.add_select_expression(sub_col_ref, selected_col_sub.name)
            else:
                #If there are no compatible columns, use the column of the first numeric type
                numeric_cols_sub = [col for col in subquery_table.columns if col.category == 'numeric']
                if numeric_cols_sub:
                    selected_col_sub = random.choice(numeric_cols_sub)
                    sub_col_ref = ColumnReferenceNode(selected_col_sub, sub_alias)
                    subquery.add_select_expression(sub_col_ref, selected_col_sub.name)
                else:
                        #Fallback to Simple Equal Connection
                        condition_type = 'simple_eq'
                    
            
            #Add a where condition to the subquery to limit the number of results
            if selected_col_sub.category == 'numeric':
                where_cond = ComparisonNode('BETWEEN')
                where_cond.add_child(ColumnReferenceNode(selected_col_sub, sub_alias))
                where_cond.add_child(LiteralNode(1, selected_col_sub.data_type))
                where_cond.add_child(LiteralNode(100, selected_col_sub.data_type))
                subquery.set_where_clause(where_cond)
            
            #Add subquery to IN condition
            in_condition.add_child(SubqueryNode(subquery, ''))
            return in_condition
        else:
            #Fallback to Simple Equal Connection
            condition_type = 'simple_eq'
    
    elif condition_type == 'exists_condition':
        #Exists Subquery Connection Criteria
        exists_node = ComparisonNode('EXISTS')
        
        #Create related subquery
        subquery = SelectNode()
        
        #Select Association Table
        if is_subquery_join:
            #For subquery connections, use join_table as the association table
            rel_table = join_table
            #Generate secure table aliases
            sql_keywords = {'use', 'select', 'from', 'where', 'group', 'by', 'order', 'limit', 'join', 'on', 'as'}
            base_rel_alias = 'rel' + str(random.randint(0, 99))
            rel_alias = base_rel_alias if base_rel_alias not in sql_keywords else base_rel_alias + str(random.randint(0, 9))
        else:
            #For regular table joins, use join_table
            rel_table = join_table
            #Generate secure table aliases
            sql_keywords = {'use', 'select', 'from', 'where', 'group', 'by', 'order', 'limit', 'join', 'on', 'as'}
            base_rel_alias = rel_table.name[:3].lower()
            rel_alias = base_rel_alias if base_rel_alias not in sql_keywords else base_rel_alias + str(random.randint(0, 9))
        
        #Create from clause
        sub_from = FromNode()
        sub_from.add_table(rel_table, rel_alias)
        subquery.set_from_clause(sub_from)
        
        #Select a column for select
        rel_col = rel_table.get_random_column()
        if rel_col:
            sub_col_ref = ColumnReferenceNode(rel_col, rel_alias)
            subquery.add_select_expression(sub_col_ref, rel_col.name)
        else:
            #Fallback to Simple Equal Connection
            condition_type = 'simple_eq'
            
        
        #Create where association criteria
        where_cond = LogicalNode('AND')
        
        #Found pairs of columns available for association
        max_attempts = 10  #Increase number of attempts
        attempts = 0
        join_condition_created = False
        
        #First try to find column pairs of compatible types (optimization strategy)
        compatible_pairs_found = False
        compatible_pairs = []
        
        #Preprocessing: Find all types of compatible column pairs
        if not is_subquery_join:
            for main_col in main_table.columns:
                for rel_col in rel_table.columns:
                    if is_type_compatible(main_col.data_type, rel_col.data_type):
                        compatible_pairs.append((main_col, rel_col))
        
        if compatible_pairs:
            compatible_pairs_found = True
        else:
            pass
        
        while attempts < max_attempts:
            if compatible_pairs_found and attempts < len(compatible_pairs):
                #Use preprocessed compatible column pairs
                main_col_candidate, rel_col_candidate = compatible_pairs[attempts]
            else:
                #Randomly select columns
                main_col_candidate = main_table.get_random_column()
                rel_col_candidate = rel_table.get_random_column()
            
            if is_type_compatible(main_col_candidate.data_type, rel_col_candidate.data_type):
                #Create Equal Comparison Criteria
                eq_cond = ComparisonNode('=')
                eq_cond.add_child(ColumnReferenceNode(main_col_candidate, main_alias))
                eq_cond.add_child(ColumnReferenceNode(rel_col_candidate, rel_alias))
                where_cond.add_child(eq_cond)
                join_condition_created = True
                break
            
            attempts += 1
        
        if not join_condition_created:
            #Fallback to Simple Equal Connection
            log_message = f"[] exists_condition: （{attempts}），simple_eq\n"
            condition_type = 'simple_eq'
            #Set a flag indicating that reprocessing is required
            needs_retry = True
        else:
            needs_retry = False
        
        if needs_retry:
            #If reprocessing is required, set the condition type to simple_eq
            #The default fallback logic that follows handles this situation
            pass
        else:
            #Set the where clause of the subquery
            subquery.set_where_clause(where_cond)
            
            #Add subquery to exists criteria
            exists_node.add_child(SubqueryNode(subquery, ''))
            return exists_node
    
    elif condition_type == 'expression_based':
        #Expression-based joins (non-equivalent operators)
        #Select Operator
        operators = ['<', '>', '<=', '>=', '!=']
        op = random.choice(operators)
        
        left_col = None
        right_col = None
        
        #Try to find compatible column pairs
        max_attempts = 10
        attempts = 0
        
        while attempts < max_attempts:
            left_col_candidate = main_table.get_random_column()
            
            if is_subquery_join:
                #Subquery connections: select columns from column alias mappings for subqueries
                valid_aliases = list(join_table.column_alias_map.keys())
                selected_alias = random.choice(valid_aliases)
                col_name, data_type, category = join_table.column_alias_map[selected_alias]
                right_col_candidate = Column(selected_alias, join_table.alias, data_type, False, join_table.alias)
            else:
                #General Table Connection
                right_col_candidate = join_table.get_random_column()

            left_category = get_safe_comparison_category(left_col_candidate)
            right_category = get_safe_comparison_category(right_col_candidate)
            if left_category not in ORDERABLE_CATEGORIES or right_category not in ORDERABLE_CATEGORIES:
                attempts += 1
                continue

            if is_type_compatible(left_col_candidate.data_type, right_col_candidate.data_type):
                left_col = ColumnReferenceNode(left_col_candidate, main_alias)
                right_col = ColumnReferenceNode(right_col_candidate, join_alias)
                break
            
            attempts += 1
        
        #If no compatible column pairs are found, look for the first compatible column pair in both tables
        if left_col is None or right_col is None:
            if is_subquery_join:
                #Subquery Connection
                for col1 in main_table.columns:
                    for alias, (col_name, data_type, category) in join_table.column_alias_map.items():
                        left_category = get_safe_comparison_category(col1)
                        right_category = normalize_category(category, data_type)
                        if str(data_type).lower() in ['any', 'unknown']:
                            continue
                        if left_category not in ORDERABLE_CATEGORIES or right_category not in ORDERABLE_CATEGORIES:
                            continue
                        if is_type_compatible(col1.data_type, data_type):
                            left_col = ColumnReferenceNode(col1, main_alias)
                            right_col_candidate = Column(alias, join_table.alias, data_type, False, join_table.alias)
                            right_col = ColumnReferenceNode(right_col_candidate, join_alias)
                            break
                    if left_col and right_col:
                        break
            else:
                #General Table Connection
                for col1 in main_table.columns:
                    for col2 in join_table.columns:
                        left_category = get_safe_comparison_category(col1)
                        right_category = get_safe_comparison_category(col2)
                        if left_category not in ORDERABLE_CATEGORIES or right_category not in ORDERABLE_CATEGORIES:
                            continue
                        if is_type_compatible(col1.data_type, col2.data_type):
                            left_col = ColumnReferenceNode(col1, main_alias)
                            right_col = ColumnReferenceNode(col2, join_alias)
                            break
                    if left_col and right_col:
                        break
            
            #Use the first column of the table as a last resort, but try type conversion
            if left_col is None or right_col is None:
                left_category = get_safe_comparison_category(main_table.columns[0])
                if left_category not in ORDERABLE_CATEGORIES:
                    condition_type = 'simple_eq'
                left_col = ColumnReferenceNode(main_table.columns[0], main_alias)
                if is_subquery_join:
                    #Subquery Connection
                    valid_aliases = list(join_table.column_alias_map.keys())
                    selected_alias = random.choice(valid_aliases)
                    col_name, data_type, category = join_table.column_alias_map[selected_alias]
                    right_col_candidate = Column(selected_alias, join_table.alias, data_type, False, join_table.alias)
                    right_col = ColumnReferenceNode(right_col_candidate, join_alias)
                else:
                    #For numeric types, use numeric literals instead of column references
                    if main_table.columns[0].category == 'numeric' and join_table.columns[0].category != 'numeric':
                        right_col = create_compatible_literal(main_table.columns[0].data_type)
                    else:
                        right_col = ColumnReferenceNode(join_table.columns[0], join_alias)
        
        if left_col is None or right_col is None or condition_type == 'simple_eq':
            pass
        else:
            condition = ComparisonNode(op)
            condition.add_child(left_col)
            condition.add_child(right_col)
            return condition
          
    #Default fallback to Simple Equal Connection - Make sure type matches
    left_col = None
    right_col = None
    
    #Try to find compatible column pairs
    max_attempts = 10
    attempts = 0
    
    while attempts < max_attempts:
        left_col_candidate = main_table.get_random_column()
        right_col_candidate = join_table.get_random_column()
        
        if is_type_compatible(left_col_candidate.data_type, right_col_candidate.data_type):
            left_col = ColumnReferenceNode(left_col_candidate, main_alias)
            right_col = ColumnReferenceNode(right_col_candidate, join_alias)
            break
        
        attempts += 1
    
    #If no compatible column pairs are found, look for the first compatible column pair in both tables
    if left_col is None or right_col is None:
        for col1 in main_table.columns:
            for col2 in join_table.columns:
                if is_type_compatible(col1.data_type, col2.data_type):
                    left_col = ColumnReferenceNode(col1, main_alias)
                    right_col = ColumnReferenceNode(col2, join_alias)
                    break
            if left_col and right_col:
                break
        
        #Use the first column of the table as a last resort, but try type conversion
        if left_col is None or right_col is None:
            left_col = ColumnReferenceNode(main_table.columns[0], main_alias)
            #For numeric types, use numeric literals instead of column references
            if main_table.columns[0].category == 'numeric' and join_table.columns[0].category != 'numeric':
                right_col = create_compatible_literal(main_table.columns[0].data_type)
            else:
                right_col = ColumnReferenceNode(join_table.columns[0], join_alias)
    
    condition = ComparisonNode("=")
    condition.add_child(left_col)
    condition.add_child(right_col)
    
    #Connection condition created
    
    return condition
