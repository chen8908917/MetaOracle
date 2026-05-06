from typing import Iterable, Optional

from data_structures.table import Table

from .column_names import infer_column_names


def infer_column_count(
    sql: str,
    tables: Optional[Iterable[Table]] = None,
    dialect: Optional[str] = None,
) -> int:
    """Infer SELECT result column count."""

    return len(infer_column_names(sql, tables=tables, dialect=dialect))

