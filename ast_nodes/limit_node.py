"""Implements LIMIT/OFFSET AST nodes and SQL serialization."""

from typing import Set
from .ast_node import ASTNode
from data_structures.node_type import NodeType

class LimitNode(ASTNode):
    """LIMITClause Node"""

    def __init__(self, value: int):
        super().__init__(NodeType.LIMIT)
        self.value = value
        self.metadata = {'value': value}

    def to_sql(self) -> str:
        return str(self.value)
    
    def collect_table_aliases(self) -> Set[str]:
        """Collect all table aliases referenced in the node"""
        aliases = set()
        #Recursively collect table alias references for all child nodes
        for child in self.children:
            aliases.update(child.collect_table_aliases())
        return aliases