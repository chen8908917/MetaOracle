"""Defines dependency records used for node ordering and constraints."""

# Dependency - 
from dataclasses import dataclass

@dataclass
class Dependency:
    """"""
    source_node_id: str
    target_node_id: str
    reason: str  # 