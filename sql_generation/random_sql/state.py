from typing import List, Optional

from data_structures.table import Table


SUBQUERY_DEPTH = 2
TABLES: Optional[List[Table]] = None


def get_tables() -> List[Table]:
    return TABLES if TABLES is not None else []


def set_tables(tables_list: List[Table]) -> None:
    global TABLES
    TABLES = tables_list


def set_subquery_depth(depth: int) -> None:
    global SUBQUERY_DEPTH
    SUBQUERY_DEPTH = depth


def get_subquery_depth() -> int:
    return SUBQUERY_DEPTH
