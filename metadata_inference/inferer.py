from typing import Iterable, Optional

from data_structures.table import Table

from .column_count import infer_column_count
from .column_names import infer_column_names
from .column_types import infer_column_types
from .models import InferredMetadata
from .nullability import infer_column_nullability


class MetadataInferer:
    """Facade for DQL result metadata inference."""

    def __init__(
        self,
        tables: Optional[Iterable[Table]] = None,
        dialect: Optional[str] = None,
        non_empty_tables: Optional[Iterable[str]] = None,
        assume_tables_non_empty: bool = True,
    ):
        self.tables = list(tables or [])
        self.dialect = dialect
        self.non_empty_tables = list(non_empty_tables or [])
        self.assume_tables_non_empty = assume_tables_non_empty

    def infer(self, sql: str) -> InferredMetadata:
        try:
            names = infer_column_names(sql, tables=self.tables, dialect=self.dialect)
            types = infer_column_types(sql, tables=self.tables, dialect=self.dialect)
            return InferredMetadata(
                column_names=names,
                column_count=infer_column_count(sql, tables=self.tables, dialect=self.dialect),
                column_types=types,
                column_nullability=infer_column_nullability(
                    sql,
                    tables=self.tables,
                    dialect=self.dialect,
                    non_empty_tables=self.non_empty_tables,
                    assume_tables_non_empty=self.assume_tables_non_empty,
                ),
            )
        except Exception as exc:
            return InferredMetadata(error=str(exc))
