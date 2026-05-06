from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Sequence

import pymysql
from pymysql.constants import FIELD_TYPE

from data_structures.db_dialect import set_dialect
from metadata_inference.inferer import MetadataInferer
from metadata_inference.models import InferredMetadata
from pipeline.invalid_result_logger import log_invalid_result
from sql_generation.random_sql.samples import create_sample_tables


@dataclass
class CheckMismatch:
    detector_name: str
    expected: Any
    actual: Any
    details: Any = None
    local_log_label: str | None = None
    local_log_message: str | None = None


@dataclass
class ActualQueryResult:
    column_names: List[str]
    column_types: List[str]
    column_nullability: List[bool]
    rows: List[Any]


CheckFn = Callable[[InferredMetadata, ActualQueryResult], List[CheckMismatch]]


_NUMERIC_CODES = {
    FIELD_TYPE.DECIMAL,
    FIELD_TYPE.NEWDECIMAL,
    FIELD_TYPE.TINY,
    FIELD_TYPE.SHORT,
    FIELD_TYPE.LONG,
    FIELD_TYPE.FLOAT,
    FIELD_TYPE.DOUBLE,
    FIELD_TYPE.LONGLONG,
    FIELD_TYPE.INT24,
}
_STRING_CODES = {
    FIELD_TYPE.VAR_STRING,
    FIELD_TYPE.VARCHAR,
    FIELD_TYPE.STRING,
}
_DATETIME_CODES = {
    FIELD_TYPE.DATE,
    FIELD_TYPE.TIME,
    FIELD_TYPE.DATETIME,
    FIELD_TYPE.TIMESTAMP,
    getattr(FIELD_TYPE, "YEAR", 13),
}
_BINARY_CODES = {
    FIELD_TYPE.BLOB,
    FIELD_TYPE.TINY_BLOB,
    FIELD_TYPE.MEDIUM_BLOB,
    FIELD_TYPE.LONG_BLOB,
    FIELD_TYPE.BIT,
}
_JSON_CODES = {FIELD_TYPE.JSON}


def _split_queries(query_file_path: str) -> List[str]:
    with open(query_file_path, "r", encoding="utf-8") as f:
        content = f.read()

    parts = [part.strip() for part in re.split(r"\n\s*\n+", content) if part.strip()]
    queries: List[str] = []
    for part in parts:
        upper = part.upper()
        if upper.startswith("SET GLOBAL ") or upper.startswith("USE "):
            continue
        queries.append(part)
    return queries


def _summarize_rows(rows: Sequence[Any], preview_limit: int = 5) -> Dict[str, Any]:
    return {
        "row_count": len(rows),
        "rows_preview": [
            list(row) if isinstance(row, tuple) else row
            for row in list(rows)[:preview_limit]
        ],
    }


def _family_from_type_code(type_code: int, charsetnr=None) -> str:
    if type_code in _NUMERIC_CODES:
        return "numeric"
    if charsetnr == 63 and type_code in (_STRING_CODES | _BINARY_CODES):
        return "binary"
    if type_code in _STRING_CODES:
        return "string"
    if type_code in _DATETIME_CODES:
        return "datetime"
    if type_code in _BINARY_CODES:
        if type_code != FIELD_TYPE.BIT and charsetnr not in (None, 63):
            return "string"
        return "binary"
    if type_code in _JSON_CODES:
        return "json"
    return "unknown"


def _classify_exec_error(msg: str) -> str:
    low = msg.lower()
    if "out of range" in low or "overflow" in low or "data truncation" in low:
        return "numeric_overflow"
    if "incorrect datetime value" in low or "incorrect date value" in low or ("incorrect" in low and "datetime" in low):
        return "invalid_date"
    if "json" in low:
        return "json_error"
    if "character set 'binary'" in low or "cannot convert string" in low:
        return "binary_charset_error"
    if "sort aborted" in low or "sort_buffer_size" in low or "out of sort memory" in low:
        return "sort_memory"
    if "not unique table/alias" in low:
        return "duplicate_alias"
    if "you have an error in your sql syntax" in low:
        return "syntax_error"
    return msg


def _check_column_count(metadata: InferredMetadata, actual: ActualQueryResult) -> List[CheckMismatch]:
    expected = metadata.column_count
    observed = len(actual.column_names)
    if expected == observed:
        return []
    return [
        CheckMismatch(
            detector_name="column_count",
            expected=expected,
            actual=observed,
            local_log_label="COLUMN_COUNT_MISMATCH",
            local_log_message=f"expected={expected} actual={observed}",
        )
    ]


def _check_column_names(metadata: InferredMetadata, actual: ActualQueryResult) -> List[CheckMismatch]:
    expected = metadata.column_names
    observed = actual.column_names
    if expected == observed:
        return []
    return [
        CheckMismatch(
            detector_name="column_names",
            expected=expected,
            actual=observed,
            local_log_label="COLUMN_NAME_MISMATCH",
            local_log_message=f"expected={expected} actual={observed}",
        )
    ]


def _check_column_types(metadata: InferredMetadata, actual: ActualQueryResult) -> List[CheckMismatch]:
    expected = [item.type_family for item in metadata.column_types]
    observed = actual.column_types
    if expected == observed:
        return []
    return [
        CheckMismatch(
            detector_name="column_types",
            expected=expected,
            actual=observed,
            details={
                "inferred_names": metadata.column_names,
                "actual_names": actual.column_names,
                "inferred_nullability": [item.is_nullable for item in metadata.column_nullability],
                "actual_nullability": actual.column_nullability,
            },
            local_log_label="COLUMN_TYPE_MISMATCH",
            local_log_message=f"expected={expected} actual={observed}",
        )
    ]


def _check_column_nullability(metadata: InferredMetadata, actual: ActualQueryResult) -> List[CheckMismatch]:
    inferred = metadata.column_nullability or []
    rows = actual.rows
    if not rows or not inferred:
        return []

    for row_index, row in enumerate(rows, start=1):
        for col_index, value in enumerate(row, start=1):
            if col_index <= len(inferred) and not inferred[col_index - 1].is_nullable and value is None:
                expected = [item.is_nullable for item in inferred]
                actual = {
                    "observed_null_at_non_nullable": True,
                    "row_index": row_index,
                    "column_index": col_index,
                    "row_value": list(row) if isinstance(row, tuple) else row,
                }
                return [
                    CheckMismatch(
                        detector_name="column_nullability",
                        expected=expected,
                        actual=actual,
                        local_log_label="NULLABILITY_VIOLATION",
                        local_log_message=(
                            f"row={row_index} col={col_index}\n"
                            f"nullability={expected}\n"
                            f"row={row}"
                        ),
                    )
                ]
    return []


_BUILTIN_CHECKS: Dict[str, CheckFn] = {
    "column_count": _check_column_count,
    "column_names": _check_column_names,
    "column_types": _check_column_types,
    "column_nullability": _check_column_nullability,
}


def run_result_checks(
    *,
    round_dir: str,
    database_name: str,
    db_config: dict,
    dialect: str,
    detector_names: Sequence[str] | None = None,
) -> Dict[str, Any]:
    set_dialect(dialect)
    selected_names = list(detector_names or _BUILTIN_CHECKS.keys())
    unknown = [name for name in selected_names if name not in _BUILTIN_CHECKS]
    if unknown:
        raise ValueError(f"Unknown result detector(s): {unknown}")

    query_file_path = os.path.join(round_dir, "queries.sql")
    exec_error_log_path = os.path.join(round_dir, "query_execution_errors.log")
    summary_path = os.path.join(round_dir, "result_check_summary.txt")
    local_log_paths = {
        "column_count": os.path.join(round_dir, "column_count_mismatches.log"),
        "column_names": os.path.join(round_dir, "column_name_mismatches.log"),
        "column_types": os.path.join(round_dir, "column_type_mismatches.log"),
        "column_nullability": os.path.join(round_dir, "nullability_violations.log"),
    }

    queries = _split_queries(query_file_path)
    tables = create_sample_tables()

    conn = pymysql.connect(
        host=db_config.get("host", "127.0.0.1"),
        port=int(db_config.get("port", 13306)),
        user=db_config.get("user", "root"),
        password=db_config.get("password", "123456"),
        database=database_name,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        table_counts: Dict[str, int] = {}
        non_empty_tables: List[str] = []
        with conn.cursor() as cur:
            for table in ["t1", "t2", "t3"]:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                table_counts[table] = count
                if count > 0:
                    non_empty_tables.append(table)

        inferer = MetadataInferer(
            tables=tables,
            dialect=dialect,
            non_empty_tables=non_empty_tables,
            assume_tables_non_empty=True,
        )

        exec_ok = 0
        exec_fail = 0
        infer_ok = 0
        infer_err = 0
        exec_error_types = Counter()
        detector_checks = Counter()
        detector_violations = Counter()

        local_logs = {
            detector_name: open(path, "w", encoding="utf-8")
            for detector_name, path in local_log_paths.items()
            if detector_name in selected_names
        }
        try:
            with open(exec_error_log_path, "w", encoding="utf-8") as elog:
                for index, sql in enumerate(queries, start=1):
                    round_label = f"{os.path.basename(round_dir)}_stmt_{index}"
                    metadata = inferer.infer(sql)
                    if metadata.error:
                        infer_err += 1
                        continue
                    infer_ok += 1

                    try:
                        with conn.cursor() as cur:
                            cur.execute(sql)
                            rows = cur.fetchall()
                            description = cur.description or []
                            fields = getattr(getattr(cur, "_result", None), "fields", None) or []
                            actual_result = ActualQueryResult(
                                column_names=[desc[0] for desc in description],
                                column_types=[
                                    _family_from_type_code(
                                        desc[1],
                                        getattr(fields[index], "charsetnr", None) if index < len(fields) else None,
                                    )
                                    for index, desc in enumerate(description)
                                ],
                                column_nullability=[bool(desc[6]) for desc in description],
                                rows=list(rows),
                            )
                    except Exception as exc:
                        exec_fail += 1
                        exec_error_types[_classify_exec_error(str(exc))] += 1
                        elog.write(f"[{index}] {exc}\nSQL: {sql}\n\n")
                        continue

                    exec_ok += 1
                    execu_result = _summarize_rows(actual_result.rows)

                    for detector_name in selected_names:
                        detector_checks[detector_name] += 1
                        mismatches = _BUILTIN_CHECKS[detector_name](metadata, actual_result)
                        if not mismatches:
                            continue

                        for mismatch in mismatches:
                            detector_violations[mismatch.detector_name] += 1
                            log_invalid_result(
                                dialect=dialect,
                                detector_name=mismatch.detector_name,
                                round_label=round_label,
                                sql=sql,
                                execu_result=execu_result,
                                expected=mismatch.expected,
                                actual=mismatch.actual,
                                details=mismatch.details,
                            )
                            local_log = local_logs.get(mismatch.detector_name)
                            if local_log and mismatch.local_log_label and mismatch.local_log_message:
                                local_log.write(
                                    f"[{index}] {mismatch.local_log_label} {mismatch.local_log_message}\n"
                                    f"SQL: {sql}\n\n"
                                )
        finally:
            for file in local_logs.values():
                file.close()

        summary = {
            "round_dir": round_dir,
            "database": database_name,
            "generated": len(queries),
            "table_counts": table_counts,
            "non_empty_tables": non_empty_tables,
            "exec_ok": exec_ok,
            "exec_fail": exec_fail,
            "exec_error_types": dict(exec_error_types),
            "infer_ok": infer_ok,
            "infer_err": infer_err,
            "detector_checks": dict(detector_checks),
            "detector_violations": dict(detector_violations),
        }

        if "column_nullability" in selected_names:
            summary["nullability_checks"] = detector_checks["column_nullability"]
            summary["nullability_violations"] = detector_violations["column_nullability"]
        if "column_count" in selected_names:
            summary["column_count_checks"] = detector_checks["column_count"]
            summary["column_count_violations"] = detector_violations["column_count"]
        if "column_names" in selected_names:
            summary["column_name_checks"] = detector_checks["column_names"]
            summary["column_name_violations"] = detector_violations["column_names"]
        if "column_types" in selected_names:
            summary["column_type_checks"] = detector_checks["column_types"]
            summary["column_type_violations"] = detector_violations["column_types"]

        with open(summary_path, "w", encoding="utf-8") as f:
            for key, value in summary.items():
                f.write(f"{key}={value}\n")
        return summary
    finally:
        conn.close()
