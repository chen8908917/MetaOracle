"""Data-type normalization and compatibility helper utilities."""

import random
from typing import List

from data_structures.column import Column
from data_structures.db_dialect import get_current_dialect


def get_full_column_identifier(table_alias: str, column_name: str) -> str:
    """Generate full column identifiers"""
    return f"{table_alias}.{column_name}"


def map_return_type_to_category(return_type: str) -> str:
    """Map function return types to categories used by the generator."""
    if not return_type:
        return "numeric"
    return_type_str = str(return_type).strip()
    lower = return_type_str.lower()
    if lower in ["numeric", "string", "datetime", "binary", "json", "boolean"]:
        return lower

    upper = return_type_str.upper()
    numeric_types = {
        "INT",
        "INTEGER",
        "BIGINT",
        "SMALLINT",
        "TINYINT",
        "FLOAT",
        "DOUBLE",
        "DECIMAL",
        "NUMERIC",
        "REAL",
    }
    string_types = {
        "VARCHAR",
        "CHAR",
        "TEXT",
        "LONGTEXT",
        "MEDIUMTEXT",
        "TINYTEXT",
        "STRING",
    }
    datetime_types = {"DATE", "DATETIME", "TIMESTAMP", "TIME"}
    json_types = {"JSON"}
    binary_types = {
        "BINARY",
        "VARBINARY",
        "BLOB",
        "LONGBLOB",
        "MEDIUMBLOB",
        "TINYBLOB",
        "GEOMETRY",
        "POINT",
        "LINESTRING",
        "POLYGON",
        "MULTIPOINT",
        "MULTILINESTRING",
        "MULTIPOLYGON",
        "GEOMETRYCOLLECTION",
    }
    boolean_types = {"BOOLEAN", "BOOL"}

    if upper in numeric_types:
        return "numeric"
    if upper in string_types:
        return "string"
    if upper in datetime_types:
        return "datetime"
    if upper in json_types:
        return "json"
    if upper in binary_types:
        return "binary"
    if upper in boolean_types:
        return "boolean"
    if upper == "ANY":
        return "numeric"
    return "numeric"


def map_param_type_to_category(param_type: str) -> str:
    """Map function param types to categories used by the generator."""
    if not param_type:
        return "any"
    if str(param_type).strip().lower() == "any":
        return "any"
    return map_return_type_to_category(param_type)


ORDERABLE_CATEGORIES = {"numeric", "datetime"}


def get_comparison_operators(category: str, include_like: bool = False) -> List[str]:
    """Return valid comparison operators for the given category."""
    base_ops = ["=", "<>", "!="]
    if category in ORDERABLE_CATEGORIES:
        return base_ops + ["<", ">", "<=", ">="]
    if category == "string":
        return base_ops + (["LIKE", "NOT LIKE"] if include_like else [])
    return base_ops


def normalize_category(category: str, data_type: str) -> str:
    """Normalize a column category using its category/data_type strings."""
    known_categories = {"numeric", "string", "datetime", "json", "binary", "boolean"}
    if category:
        category_str = str(category).strip().lower()
        if category_str in known_categories:
            return category_str
        if category_str in ["any", "unknown"]:
            return "string"
        return map_return_type_to_category(category_str)
    data_type_str = str(data_type).strip().lower()
    if data_type_str in ["any", "unknown"]:
        return "string"
    return map_return_type_to_category(data_type)


def adjust_expected_type_for_min_max(func_name: str, param_idx: int, expected_type: str) -> str:
    """Constrain MIN/MAX to orderable categories to avoid invalid arguments."""
    if func_name in ["MIN", "MAX"] and param_idx == 0:
        return random.choice(["numeric", "datetime"])
    return expected_type


def adjust_expected_type_for_conditionals(func_name: str, param_idx: int, expected_type: str) -> str:
    """Restrict conditional functions to avoid unsupported types in some dialects."""
    if expected_type != "any":
        return expected_type
    dialect_name = get_current_dialect().name.upper()
    if dialect_name == "MARIADB" and func_name in ["IF", "IFNULL", "NULLIF"]:
        return "numeric"
    return expected_type


def get_cast_types() -> List[str]:
    """Return valid CAST/CONVERT target types for the current dialect."""
    data_types = ["SIGNED", "DATE", "DATETIME", "DOUBLE", "FLOAT", "CHAR"]
    dialect_name = get_current_dialect().name.upper()
    if dialect_name == "POLARDB":
        data_types = [t for t in data_types if t != "DOUBLE"]
    return data_types


def get_safe_comparison_category(col: Column) -> str:
    """Return a conservative category for comparison operators."""
    category = normalize_category(col.category, col.data_type)
    data_type = str(getattr(col, "data_type", "")).lower()
    data_type_category = map_return_type_to_category(col.data_type)
    known_categories = {"numeric", "string", "datetime", "json", "binary", "boolean"}
    if data_type_category in known_categories and data_type_category != category:
        category = data_type_category
    if data_type in ["any", "unknown"]:
        return "string"
    return category
