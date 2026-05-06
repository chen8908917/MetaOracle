"""Implements ORDER BY AST nodes and sort expression formatting."""

#OrderByNode class definition - order BY clause node
from typing import List, Tuple
from .ast_node import ASTNode
from data_structures.node_type import NodeType

class OrderByNode(ASTNode):
    """ORDER BYClause Node"""

    def __init__(self):
        super().__init__(NodeType.ORDER_BY)
        self.expressions: List[Tuple[ASTNode, str]] = []  # (expression, direction)

    def add_expression(self, expr: ASTNode, direction: str = 'ASC') -> None:
        self.expressions.append((expr, direction))
        self.add_child(expr)

    def to_sql(self) -> str:
        if not self.expressions:
            return ""
        parts = []
        for expr, direction in self.expressions:
            parts.append(f"{expr.to_sql()} {direction}")
        return ", ".join(parts)
    #Collect table aliases used in the order BY clause
    def collect_table_aliases(self) -> set:
        aliases = set()
        for expr, _ in self.expressions:
            aliases.update(expr.collect_table_aliases())
        return aliases