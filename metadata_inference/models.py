from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class InferredColumnType:
    """Type metadata inferred for one SELECT output column."""

    data_type: str
    type_family: str
    source: str = "unknown"


@dataclass(frozen=True)
class InferredColumnNullability:
    """Nullability inferred for one SELECT output column."""

    is_nullable: bool
    source: str = "unknown"


@dataclass(frozen=True)
class InferredMetadata:
    """Metadata currently inferred from one DQL statement."""

    column_names: List[str] = field(default_factory=list)
    column_count: int = 0
    column_types: List[InferredColumnType] = field(default_factory=list)
    column_nullability: List[InferredColumnNullability] = field(default_factory=list)
    error: Optional[str] = None
