"""Column selection tracking utilities for random SQL generation."""

import random
from typing import Any, Dict, List, Optional

from data_structures.column import Column

from .type_utils import get_full_column_identifier


class ColumnUsageTracker:
    """Track usage of columns in SQL queries"""

    def __init__(self):
        self.used_columns = set()
        self.select_columns = set()
        self.filter_columns = set()
        self.available_columns = {}
        self.table_references = {}

    def initialize_from_from_node(self, from_node):
        """Initialize available column information according to the from clause"""
        self.available_columns = {}
        self.table_references = {}

        if hasattr(from_node, "table_references") and hasattr(from_node, "aliases"):
            for table_ref, alias in zip(from_node.table_references, from_node.aliases):
                self.table_references[alias] = table_ref
                if hasattr(table_ref, "columns"):
                    columns_obj = table_ref.columns
                    columns_list = columns_obj() if callable(columns_obj) else columns_obj
                    self.available_columns[alias] = columns_list
                elif hasattr(table_ref, "column_alias_map"):
                    subquery_columns = []
                    for col_alias, (col_name, data_type, category) in table_ref.column_alias_map.items():
                        subquery_columns.append(Column(col_alias, data_type, category, False, alias))
                    self.available_columns[alias] = subquery_columns

    def get_all_available_columns(self) -> Dict[str, List[Any]]:
        all_available_columns = {}
        for table_alias, columns in self.available_columns.items():
            available = [col for col in columns if not self.is_column_used(table_alias, col.name)]
            all_available_columns[table_alias] = available
        return all_available_columns

    def has_table(self, table_alias: str) -> bool:
        return table_alias in self.table_references

    def has_column(self, table_alias: str, column_name: str) -> bool:
        if table_alias not in self.available_columns:
            return False
        return any(col.name == column_name for col in self.available_columns[table_alias])

    def get_table_by_alias(self, table_alias: str) -> Any:
        return self.table_references.get(table_alias)

    def mark_column_as_used(self, table_alias: str, column_name: str) -> None:
        column_id = get_full_column_identifier(table_alias, column_name)
        self.used_columns.add(column_id)

    def mark_column_as_select(self, table_alias: str, column_name: str) -> None:
        column_id = get_full_column_identifier(table_alias, column_name)
        self.used_columns.add(column_id)
        self.select_columns.add(column_id)

    def mark_column_as_filter(self, table_alias: str, column_name: str) -> None:
        column_id = get_full_column_identifier(table_alias, column_name)
        self.used_columns.add(column_id)
        self.filter_columns.add(column_id)

    def mark_column_used(self, column_identifier: str) -> None:
        self.used_columns.add(column_identifier)

    def is_column_used(self, *args) -> bool:
        if len(args) == 1:
            column_id = args[0]
            return column_id in self.used_columns
        if len(args) == 2:
            table_alias, column_name = args
            column_id = get_full_column_identifier(table_alias, column_name)
            return column_id in self.used_columns
        return False

    def is_column_in_select(self, *args) -> bool:
        if len(args) == 1:
            column_id = args[0]
            return column_id in self.select_columns
        if len(args) == 2:
            table_alias, column_name = args
            column_id = get_full_column_identifier(table_alias, column_name)
            return column_id in self.select_columns
        return False

    def is_column_in_filter(self, *args) -> bool:
        if len(args) == 1:
            column_id = args[0]
            return column_id in self.filter_columns
        if len(args) == 2:
            table_alias, column_name = args
            column_id = get_full_column_identifier(table_alias, column_name)
            return column_id in self.filter_columns
        return False

    def is_column_available_for_filter(self, *args) -> bool:
        if len(args) == 1:
            column_id = args[0]
            return column_id not in self.select_columns and column_id not in self.filter_columns
        if len(args) == 2:
            table_alias, column_name = args
            column_id = get_full_column_identifier(table_alias, column_name)
            return column_id not in self.select_columns and column_id not in self.filter_columns
        return False

    def get_available_columns(self, table: Any, table_alias: str) -> List[Any]:
        if table_alias in self.available_columns:
            return [
                col
                for col in self.available_columns[table_alias]
                if not self.is_column_used(table_alias, col.name)
            ]

        available_columns = []
        if hasattr(table, "columns"):
            for col in table.columns:
                if not self.is_column_used(table_alias, col.name):
                    available_columns.append(col)
        elif hasattr(table, "column_alias_map"):
            for alias, (col_name, data_type, category) in table.column_alias_map.items():
                if not self.is_column_used(table_alias, alias):
                    available_columns.append(Column(alias, data_type, category, False, table_alias))
        return available_columns

    def get_columns_available_for_filter(self, table: Any, table_alias: str) -> List[Any]:
        available_columns = []
        if hasattr(table, "columns"):
            for col in table.columns:
                if self.is_column_available_for_filter(table_alias, col.name):
                    available_columns.append(col)
        elif hasattr(table, "column_alias_map"):
            for alias, (col_name, data_type, category) in table.column_alias_map.items():
                if self.is_column_available_for_filter(table_alias, alias):
                    available_columns.append(Column(alias, data_type, category, False, table_alias))
        return available_columns

    def select_unique_column(self, table: Any, table_alias: str) -> Optional[Any]:
        available_columns = self.get_available_columns(table, table_alias)
        if available_columns:
            return random.choice(available_columns)
        return None

    def select_column_for_select(self, table: Any, table_alias: str) -> Optional[Any]:
        available_columns = self.get_available_columns(table, table_alias)
        if available_columns:
            return random.choice(available_columns)
        if hasattr(table, "columns") and table.columns:
            return random.choice(table.columns)
        if hasattr(table, "column_alias_map"):
            valid_aliases = list(table.column_alias_map.keys())
            if valid_aliases:
                alias = random.choice(valid_aliases)
                col_name, data_type, category = table.column_alias_map[alias]
                return Column(alias, data_type, category, False, table_alias)
        return None

    def select_column_for_filter(self, table: Any, table_alias: str) -> Optional[Any]:
        available_columns = self.get_columns_available_for_filter(table, table_alias)
        if available_columns:
            return random.choice(available_columns)
        return None


def get_random_column_with_tracker(
    table: Any,
    table_alias: str,
    column_tracker: Optional[ColumnUsageTracker] = None,
    for_select: bool = False,
) -> Optional[Any]:
    if column_tracker:
        if for_select:
            col = column_tracker.select_column_for_select(table, table_alias)
            if col:
                column_tracker.mark_column_as_select(table_alias, col.name)
                return col
        else:
            col = column_tracker.select_column_for_filter(table, table_alias)
            if col:
                column_tracker.mark_column_as_filter(table_alias, col.name)
                return col
            if hasattr(table, "columns") and table.columns:
                selected_col = random.choice(table.columns)
                column_tracker.mark_column_as_filter(table_alias, selected_col.name)
                return selected_col
            if hasattr(table, "column_alias_map"):
                valid_aliases = list(table.column_alias_map.keys())
                if valid_aliases:
                    alias = random.choice(valid_aliases)
                    col_name, data_type, category = table.column_alias_map[alias]
                    column_tracker.mark_column_as_filter(table_alias, alias)
                    return Column(alias, data_type, category, False, table_alias)
        return None

    if hasattr(table, "get_random_column"):
        return table.get_random_column()
    if hasattr(table, "columns") and table.columns:
        return random.choice(table.columns)
    if hasattr(table, "column_alias_map"):
        valid_aliases = list(table.column_alias_map.keys())
        if valid_aliases:
            alias = random.choice(valid_aliases)
            col_name, data_type, category = table.column_alias_map[alias]
            return Column(alias, data_type, category, False, table_alias)
    return None
