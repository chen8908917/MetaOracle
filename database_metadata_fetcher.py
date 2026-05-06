"""Fetch table/column/index metadata and map it into internal Table objects."""

from __future__ import annotations

from typing import Dict, List, Optional

try:
    import pymysql
except Exception:  # pragma: no cover - handled at runtime
    pymysql = None

from data_structures.column import Column
from data_structures.table import Table


class DatabaseMetadataFetcher:
    """Load schema metadata from INFORMATION_SCHEMA for supported MySQL-like DBs."""

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        dialect: str = "MYSQL",
    ) -> None:
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.dialect = (dialect or "MYSQL").upper()
        self._conn = None

    def connect(self) -> bool:
        """Open a metadata connection. Returns True on success."""
        if self._conn is not None:
            return True
        if pymysql is None:
            print("pymysql is not available; cannot connect to the database.")
            return False
        try:
            self._conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True,
            )
            return True
        except Exception as exc:
            print(f"Failed to connect to database: {exc}")
            self._conn = None
            return False

    def disconnect(self) -> None:
        """Close the current metadata connection if open."""
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def get_all_tables_info(self) -> List[Table]:
        """Build `Table` models with columns, PK/FK relations, and index info."""
        if self._conn is None:
            if not self.connect():
                return []

        table_names = self._fetch_table_names()
        columns_by_table = self._fetch_columns()
        primary_keys = self._fetch_primary_keys()
        foreign_keys = self._fetch_foreign_keys()
        indexes = self._fetch_indexes()

        tables: List[Table] = []
        for table_name in table_names:
            columns = columns_by_table.get(table_name, [])
            primary_key_cols = primary_keys.get(table_name, [])
            primary_key = primary_key_cols[0] if primary_key_cols else ""
            table = Table(
                name=table_name,
                columns=columns,
                primary_key=primary_key,
                foreign_keys=foreign_keys.get(table_name, []),
                indexes=[],
            )
            for index in indexes.get(table_name, []):
                table.add_index(
                    index_name=index["name"],
                    columns=index["columns"],
                    is_primary=index.get("is_primary", False),
                )
            tables.append(table)
        return tables

    def _fetchall(self, sql: str, params: tuple) -> List[Dict]:
        """Execute a metadata query and return rows as dicts."""
        if self._conn is None:
            return []
        with self._conn.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())

    def _fetch_table_names(self) -> List[str]:
        """List all base table names in the current database."""
        sql = """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """
        rows = self._fetchall(sql, (self.database,))
        return [row["TABLE_NAME"] for row in rows]

    def _fetch_columns(self) -> Dict[str, List[Column]]:
        """Load columns and infer each column category used by SQL generation."""
        sql = """
            SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """
        rows = self._fetchall(sql, (self.database,))
        columns_by_table: Dict[str, List[Column]] = {}
        for row in rows:
            table_name = row["TABLE_NAME"]
            data_type = row.get("DATA_TYPE") or ""
            column_type = row.get("COLUMN_TYPE") or data_type
            category = self._infer_category(data_type, column_type)
            is_nullable = str(row.get("IS_NULLABLE", "")).upper() == "YES"
            column = Column(
                name=row["COLUMN_NAME"],
                data_type=column_type,
                category=category,
                is_nullable=is_nullable,
                table_name=table_name,
            )
            columns_by_table.setdefault(table_name, []).append(column)
        return columns_by_table

    def _fetch_primary_keys(self) -> Dict[str, List[str]]:
        """Load primary key columns per table (ordered for composite PKs)."""
        sql = """
            SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s AND CONSTRAINT_NAME = 'PRIMARY'
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """
        rows = self._fetchall(sql, (self.database,))
        primary_keys: Dict[str, List[str]] = {}
        for row in rows:
            primary_keys.setdefault(row["TABLE_NAME"], []).append(row["COLUMN_NAME"])
        return primary_keys

    def _fetch_foreign_keys(self) -> Dict[str, List[Dict[str, str]]]:
        """Load foreign key relationships keyed by source table name."""
        sql = """
            SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s AND REFERENCED_TABLE_NAME IS NOT NULL
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """
        rows = self._fetchall(sql, (self.database,))
        foreign_keys: Dict[str, List[Dict[str, str]]] = {}
        for row in rows:
            foreign_keys.setdefault(row["TABLE_NAME"], []).append(
                {
                    "column": row["COLUMN_NAME"],
                    "ref_table": row["REFERENCED_TABLE_NAME"],
                    "ref_column": row["REFERENCED_COLUMN_NAME"],
                }
            )
        return foreign_keys

    def _fetch_indexes(self) -> Dict[str, List[Dict[str, object]]]:
        """Load index definitions and merge multi-column index entries."""
        sql = """
            SELECT TABLE_NAME, INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX, NON_UNIQUE
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
        """
        rows = self._fetchall(sql, (self.database,))
        indexes_by_table: Dict[str, Dict[str, Dict[str, object]]] = {}
        for row in rows:
            table_name = row["TABLE_NAME"]
            index_name = row["INDEX_NAME"]
            entry = indexes_by_table.setdefault(table_name, {}).setdefault(
                index_name,
                {
                    "name": index_name,
                    "columns": [],
                    "is_primary": str(index_name).upper() == "PRIMARY",
                },
            )
            entry["columns"].append(row["COLUMN_NAME"])
        return {
            table_name: list(indexes.values())
            for table_name, indexes in indexes_by_table.items()
        }

    def _infer_category(self, data_type: str, column_type: str) -> str:
        """Map SQL data types to project categories used by expression builders."""
        base = str(data_type or "").strip().lower()
        column_type_lower = str(column_type or "").strip().lower()

        numeric_types = {
            "int",
            "integer",
            "bigint",
            "smallint",
            "tinyint",
            "mediumint",
            "float",
            "double",
            "decimal",
            "numeric",
            "real",
            "year",
        }
        datetime_types = {"date", "datetime", "timestamp", "time"}
        json_types = {"json"}
        binary_types = {
            "binary",
            "varbinary",
            "blob",
            "longblob",
            "mediumblob",
            "tinyblob",
            "geometry",
            "point",
            "linestring",
            "polygon",
            "multipoint",
            "multilinestring",
            "multipolygon",
            "geometrycollection",
            "bit",
        }
        boolean_types = {"boolean", "bool"}

        if base in numeric_types:
            if base == "tinyint" and column_type_lower.startswith("tinyint(1"):
                return "boolean"
            return "numeric"
        if base in datetime_types:
            return "datetime"
        if base in json_types:
            return "json"
        if base in binary_types:
            return "binary"
        if base in boolean_types:
            return "boolean"
        return "string"
