from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Optional


def _normalize_dialect(dialect: Optional[str]) -> str:
    value = (dialect or "UNKNOWN").strip().upper()
    return value or "UNKNOWN"


def _normalize_detector_name(detector_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (detector_name or "").strip())
    return cleaned or "unknown_detector"


def build_invalid_result_log_path(
    dialect: Optional[str],
    detector_name: str,
    root_dir: str = "invalid_result",
) -> str:
    normalized_dialect = _normalize_dialect(dialect)
    normalized_detector = _normalize_detector_name(detector_name)
    return os.path.join(root_dir, normalized_dialect, f"{normalized_detector}.log")


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def log_invalid_result(
    *,
    dialect: Optional[str],
    detector_name: str,
    round_label: Optional[str],
    sql: str,
    execu_result: Any,
    expected: Any,
    actual: Any,
    details: Optional[Any] = None,
    root_dir: str = "invalid_result",
) -> str:
    log_path = build_invalid_result_log_path(
        dialect=dialect,
        detector_name=detector_name,
        root_dir=root_dir,
    )
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    normalized_detector = _normalize_detector_name(detector_name)
    expected_key = f"expected_{normalized_detector}"
    actual_key = f"actual_{normalized_detector}"

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"timestamp={datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"round={round_label or 'UNKNOWN'}\n")
        f.write(f"sql={sql}\n")
        f.write(f"excu_result={_format_value(execu_result)}\n")
        f.write(f"{expected_key}={_format_value(expected)}\n")
        f.write(f"{actual_key}={_format_value(actual)}\n")
        if details is not None:
            f.write(f"details={_format_value(details)}\n")
        f.write("-" * 80 + "\n")
    return log_path
