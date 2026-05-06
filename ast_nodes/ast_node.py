"""Defines the abstract base node used by all custom SQL AST node types."""

#ASTNode Base Class Definition
import string
import random
from typing import List, Dict, Any, Optional, Set
from data_structures.node_type import NodeType

class ASTNode:
    """ASTNode Base Class"""

    def __init__(self, node_type: NodeType):
        self.id = self._generate_id()
        self.node_type = node_type
        self.children: List[ASTNode] = []
        self.parent: Optional[ASTNode] = None
        self.metadata: Dict[str, Any] = {}  #Storage Node Specific Information

    def _generate_id(self) -> str:
        """Generate Unique Node IDs"""
        return 'node_' + ''.join(random.choices(
            string.ascii_lowercase + string.digits, k=8
        ))

    def add_child(self, child: 'ASTNode') -> None:
        """Add Child Node"""
        self.children.append(child)
        child.parent = self

    def get_descendants(self) -> List['ASTNode']:
        """Get all descendant nodes"""
        descendants = []
        for child in self.children:
            descendants.append(child)
            descendants.extend(child.get_descendants())
        return descendants

    def to_sql(self) -> str:
        """Convert to SQL String（Implemented by subclass）"""
        raise NotImplementedError("Subclasses must implement to_sql()")

    def contains_window_function(self) -> bool:
        """Checks if a node or its child nodes contain window functions"""
        if self.node_type == NodeType.FUNCTION_CALL:
            if self.metadata.get('func_type') == 'window':
                return True

        for child in self.children:
            if child.contains_window_function():
                return True

        return False

    def contains_aggregate_function(self) -> bool:
        """Checks if a node or its child nodes contain aggregate functions"""
        if self.node_type == NodeType.FUNCTION_CALL:
            if self.metadata.get('func_type') == 'aggregate':
                return True

        for child in self.children:
            if child.contains_aggregate_function():
                return True

        return False