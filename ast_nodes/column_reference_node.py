"""Implements column reference AST nodes with alias-aware resolution helpers."""

#ColumnReferenceNode Class Definition - Column Reference Node
from typing import Set, Optional
import random
from .ast_node import ASTNode
from data_structures.node_type import NodeType
from data_structures.column import Column
from data_structures.table import Table

class ColumnReferenceNode(ASTNode):
    """Column Reference Node"""

    def __init__(self, column: Column, table_alias: str):
        super().__init__(NodeType.COLUMN_REFERENCE)
        self.column = column
        self.table_alias = table_alias
        self.metadata = {
            'column_name': column.name,
            'table_name': column.table_name,
            'table_alias': table_alias,
            'data_type': column.data_type,
            'category': column.category,
            'is_aggregate': False  #Column references are not aggregates
        }

    def to_sql(self) -> str:
        return f"{self.table_alias}.{self.column.name}"

    def collect_table_aliases(self) -> Set[str]:
        """Returns the table alias used by this column reference"""
        return {self.table_alias}

    def collect_column_aliases(self) -> Set[str]:
        """Returns the column name used by this column reference（Probably an alias）"""
        return {self.column.name}

    def is_valid(self, from_node: 'FromNode') -> bool:
        """Check if the column reference is valid"""
        table_ref = from_node.get_table_for_alias(self.table_alias)
        if not table_ref:
            return False  #Invalid table alias

        if isinstance(table_ref, Table):
            #Check if the table contains this column
            return table_ref.has_column(self.column.name)
        else:
            #Import locally within the method to avoid loop imports
            from .subquery_node import SubqueryNode
            if isinstance(table_ref, SubqueryNode):
                #Check if the subquery contains the column alias
                return table_ref.has_column_alias(self.column.name)
        return False

    def find_replacement(self, from_node: 'FromNode') -> Optional['ColumnReferenceNode']:
        """Look for valid alternate column references，Support for subquery column aliases"""
        table_ref = from_node.get_table_for_alias(self.table_alias)
        if not table_ref:
            #Invalid table alias, try to find a valid table alias replacement
            valid_aliases = list(from_node.get_all_aliases())
            if not valid_aliases:
                return None
            new_alias = random.choice(valid_aliases)
            table_ref = from_node.get_table_for_alias(new_alias)
            if not table_ref:
                return None
            self.table_alias = new_alias

        if isinstance(table_ref, Table):
            #Find Similar Columns From Table
            similar_cols = table_ref.get_similar_columns(self.column.name)
            if similar_cols:
                return ColumnReferenceNode(random.choice(similar_cols), self.table_alias)
            return ColumnReferenceNode(table_ref.get_random_column(), self.table_alias)

        else:
            #Import locally within the method to avoid loop imports
            from .subquery_node import SubqueryNode
            if isinstance(table_ref, SubqueryNode):
                #Fix: Only use aliases that are actually defined in subqueries
                if table_ref.column_alias_map:
                    #Get all available column aliases
                    valid_aliases = list(table_ref.column_alias_map.keys())
                    if valid_aliases:
                        alias = random.choice(valid_aliases)
                        col_name, data_type, category = table_ref.column_alias_map[alias]
                        virtual_col = Column(
                            name=alias,
                            data_type=data_type,
                            category=category,
                            is_nullable=False,
                            table_name=table_ref.alias
                        )
                        return ColumnReferenceNode(virtual_col, self.table_alias)

                #Use default column if there is no alias or the alias is invalid
                virtual_col = Column(
                    name="id",
                    data_type="INT",
                    category="numeric",
                    is_nullable=False,
                    table_name=table_ref.alias
                )
                return ColumnReferenceNode(virtual_col, self.table_alias)

        return None