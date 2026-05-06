"""Defines function metadata models for expression and mutation strategies."""

# Function - 
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Function:
    """"""
    name: str
    min_params: int
    max_params: int  # None
    param_types: List[str]  # 
    return_type: str  # 
    func_type: str  # scalar, aggregate, window
    format_string_required: bool = False