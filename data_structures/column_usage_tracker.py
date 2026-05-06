"""Tracks column usage to reduce invalid or repetitive column choices."""

import random
from typing import Optional, Any
from .column import Column

class ColumnUsageTracker:
    """Track usage of columns in SQL queries"""
    
    def __init__(self):
        #Store all used column identifiers
        self.used_columns = set()
        #Column identifiers stored for use in select clauses
        self.select_columns = set()
        #Column identifier stored for use in the filter clause (where/having/on)
        self.filter_columns = set()
        #Store all available columns (table alias - > column list)
        self.available_columns = {}
        #Store all table reference information (table alias - > table object)
        self.table_references = {}
        
    def initialize_from_from_node(self, from_node):
        """Initialize available column information based on a table or subquery in the from clause
        
        Args:
            from_node: FromNodeRomantic Interest，Contains table reference and connection information
        """
        print(f"[ColumnTracker] fromFROMClause Initialize Available Column Information")
        
        #Clear existing information
        self.available_columns = {}
        self.table_references = {}
        
        #Get all table references
        if hasattr(from_node, 'table_references') and hasattr(from_node, 'aliases'):
            #Traverse all table references and aliases
            for table_ref, alias in zip(from_node.table_references, from_node.aliases):
                self.table_references[alias] = table_ref
    
    def select_column_for_select(self, table, table_alias):
        """Select columns for select clause（Allow Duplicates）"""
        if hasattr(table, 'columns') and table.columns:
            return random.choice(table.columns)
        return None
    
    def select_column_for_filter(self, table, table_alias):
        """Select columns for filter clause（Not in select and filter）"""
        if hasattr(table, 'columns') and table.columns:
            #Prefer columns that are not used anywhere
            unused_columns = [col for col in table.columns if f"{table_alias}.{col.name}" not in self.used_columns]
            if unused_columns:
                return random.choice(unused_columns)
            #If there are no unused columns, select only the columns used in select
            select_only_columns = [col for col in table.columns if f"{table_alias}.{col.name}" in self.select_columns and f"{table_alias}.{col.name}" not in self.filter_columns]
            if select_only_columns:
                return random.choice(select_only_columns)
        return None
    
    def mark_column_as_select(self, table_alias, column_name):
        """The marker column is used in the select clause"""
        col_id = f"{table_alias}.{column_name}"
        self.used_columns.add(col_id)
        self.select_columns.add(col_id)
    
    def mark_column_as_filter(self, table_alias, column_name):
        """The marker column is used in the filter clause"""
        col_id = f"{table_alias}.{column_name}"
        self.used_columns.add(col_id)
        self.filter_columns.add(col_id)

#Modify the get_random_column method to support column usage trackers
def get_random_column_with_tracker(table: Any, table_alias: str, column_tracker: ColumnUsageTracker = None, for_select: bool = False) -> Optional[Any]:
    """Use tracker to select columns based on columns
    table: Table Objects
    table_alias: Table Alias
    column_tracker: Column Tracker Instance
    for_select: Whether to select columns for the select clause
    """
    print(f"[ColumnTracker] Recallget_random_column_with_tracker - Form: {table_alias}, for_select: {for_select}")
    
    if column_tracker:
        print(f"[ColumnTracker] Use column tracker to select columns")
        
        if for_select:
            #Select columns for select clause (allow duplicates)
            col = column_tracker.select_column_for_select(table, table_alias)
            if col:
                print(f"[ColumnTracker] Successfully selected columns forselectClause: {table_alias}.{col.name}")
                column_tracker.mark_column_as_select(table_alias, col.name)
                return col
        else:
            #Select columns for filter clause (not in select and filter)
            col = column_tracker.select_column_for_filter(table, table_alias)
            if col:
                print(f"[ColumnTracker] Successfully selected columns forfilterClause: {table_alias}.{col.name}")
                column_tracker.mark_column_as_filter(table_alias, col.name)
                return col
            
            #If no columns are available for filter, use fallback scheme (select any column)
            print(f"[ColumnTracker] Alarms: Not available forfilterColumns of，Use fallback scheme")
            
            if hasattr(table, 'columns') and table.columns:
                selected_col = random.choice(table.columns)
                column_tracker.mark_column_as_filter(table_alias, selected_col.name)
                return selected_col
            elif hasattr(table, 'column_alias_map'):
                valid_aliases = list(table.column_alias_map.keys())
                if valid_aliases:
                    alias = random.choice(valid_aliases)
                    col_name, data_type, category = table.column_alias_map[alias]
                    column_tracker.mark_column_as_filter(table_alias, alias)
                    return Column(alias, data_type, category, False, table_alias)
        
        return None
    
    #If there is no tracker, use the original logic
    if hasattr(table, 'get_random_column'):
        return table.get_random_column()
    elif hasattr(table, 'columns') and table.columns:
        return random.choice(table.columns)
    elif hasattr(table, 'column_alias_map'):
        valid_aliases = list(table.column_alias_map.keys())
        if valid_aliases:
            alias = random.choice(valid_aliases)
            col_name, data_type, category = table.column_alias_map[alias]
            return Column(alias, data_type, category, False, table_alias)
    
    return None