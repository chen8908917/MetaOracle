from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class RunSettings:
    dialect_str: str
    run_hours: int
    use_database_tables: bool = False
    db_config: Optional[Dict[str, Any]] = None
    enable_result_checks: bool = False
