from typing import Dict, Iterable, List, Optional

from sqlglot import expressions as exp

from data_structures.column import Column
from data_structures.table import Table


class SchemaContext:
    """Resolve table aliases and column metadata for one parsed SELECT."""

    def __init__(self, tables: Optional[Iterable[Table]] = None):
        self.tables: Dict[str, Table] = {
            table.name.lower(): table for table in (tables or [])
        }
        self.alias_to_table: Dict[str, str] = {}

    def bind_select(self, select_expr: exp.Select) -> "SchemaContext":
        from_expr = select_expr.args.get("from_")
        if from_expr is not None:
            self._bind_source(from_expr.this)

        for join_expr in select_expr.args.get("joins") or []:
            self._bind_source(join_expr.this)
        return self

    def _bind_source(self, source: Optional[exp.Expression]) -> None:
        if isinstance(source, exp.Table):
            table_name = source.name
            if not table_name:
                return
            alias = source.alias_or_name or table_name
            self.alias_to_table[alias.lower()] = table_name.lower()
            self.alias_to_table[table_name.lower()] = table_name.lower()
        elif isinstance(source, exp.Subquery):
            alias = source.alias_or_name
            if alias:
                self.alias_to_table[alias.lower()] = alias.lower()

    def visible_tables(self) -> List[Table]:
        seen = set()
        result: List[Table] = []
        for table_name in self.alias_to_table.values():
            if table_name in seen:
                continue
            seen.add(table_name)
            table = self.tables.get(table_name)
            if table:
                result.append(table)
        if result:
            return result
        return list(self.tables.values())

    def resolve_column(self, column_expr: exp.Column) -> Optional[Column]:
        column_name = (column_expr.name or "").lower()
        table_ref = (column_expr.table or "").lower()
        if not column_name:
            return None

        if table_ref:
            table_name = self.alias_to_table.get(table_ref, table_ref)
            table = self.tables.get(table_name)
            return table.get_column(column_name) if table else None

        matches: List[Column] = []
        for table in self.visible_tables():
            col = table.get_column(column_name)
            if col:
                matches.append(col)

        return matches[0] if len(matches) == 1 else None
