"""Defines the Column model used by generators and mutators."""

#Column Class Definition - Stores table column information
from dataclasses import dataclass

@dataclass
class Column:
    """Table Column Information"""
    name: str
    data_type: str
    category: str  # numeric, string, datetime, boolean
    is_nullable: bool
    table_name: str  #Name of the table to which it belongs