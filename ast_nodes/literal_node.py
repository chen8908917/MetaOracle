"""Implements literal value AST nodes and dialect-safe formatting helpers."""

#LiteralNode Class Definition - Literals Node
from typing import Set, Any
from .ast_node import ASTNode
from data_structures.node_type import NodeType
from data_structures.db_dialect import get_dialect_config

class LiteralNode(ASTNode):
    """Literals Node（Handling single quotation mark escapes）"""

    def __init__(self, value: Any, data_type: str):
        super().__init__(NodeType.LITERAL)
        self.value = value
        self.data_type = data_type
        self.category = data_type
        self.metadata = {
            'value': value,
            'data_type': data_type,
            'is_aggregate': False  #Literals are not aggregates
        }

    def to_sql(self) -> str:
        #Get current dialect configuration
        dialect = get_dialect_config()
        
        #Uniform use of dialect-specific literal representations to ensure that type information is preserved
        return dialect.get_literal_representation(self.value, self.data_type)

    def collect_column_aliases(self) -> Set[str]:
        """Literals do not refer to column aliases"""
        return set()
    
    def collect_table_aliases(self) -> Set[str]:
        """Literals do not refer to table aliases"""
        return set()