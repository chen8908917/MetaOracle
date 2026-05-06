"""Implements logical (AND/OR/NOT) AST nodes and composition utilities."""

#LogicalNode Class Definition - Logical Expression Node
from typing import Set, Tuple, List
from .ast_node import ASTNode
from data_structures.node_type import NodeType

class LogicalNode(ASTNode):
    """Logical Expression Node"""

    def __init__(self, operator: str):
        super().__init__(NodeType.LOGICAL)
        self.operator = operator
        self.metadata = {
            'operator': operator,
            'is_aggregate': False  #Logical expressions are not aggregates
        }

    def to_sql(self) -> str:
        if self.operator == 'NOT':
            if self.children:
                return f"NOT ({self.children[0].to_sql()})"
            return "NOT"

        if not self.children:
            return ""
        elif len(self.children) == 1:
            return self.children[0].to_sql()
        elif len(self.children) == 2:
            left = self.children[0].to_sql()
            right = self.children[1].to_sql()
            return f"({left} {self.operator} {right})"
        else:
            #Handling Multiple Child Node Situations
            sql_parts = [child.to_sql() for child in self.children if child.to_sql()]
            if not sql_parts:
                return ""
            #Concatenate all subexpressions with the same operator
            return f"({f' {self.operator} '.join(sql_parts)})"

    def collect_column_aliases(self) -> Set[str]:
        """Collect column aliases referenced in logical expressions"""
        aliases = set()
        for child in self.children:
            aliases.update(child.collect_column_aliases())
        return aliases

    def validate_columns(self, from_node: 'FromNode') -> Tuple[bool, List[str]]:
        """Verify that the column reference in the logical expression is valid"""
        errors = []
        for child in self.children:
            if hasattr(child, 'validate_columns'):
                valid, child_errors = child.validate_columns(from_node)
                if not valid:
                    errors.extend(child_errors)
        return (len(errors) == 0, errors)

    def repair_columns(self, from_node: 'FromNode') -> None:
        """Fix invalid column references in logical expressions"""
        for child in self.children:
            if hasattr(child, 'repair_columns'):
                child.repair_columns(from_node)