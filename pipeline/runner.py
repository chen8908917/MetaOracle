import gc
import os
import time
from pathlib import Path

import pymysql

from generate_random_sql import Generate
from data_structures.db_dialect import set_dialect

from .logger import log_message
from .models import RunSettings
from .result_checker import run_result_checks


def _round_db_config(run_settings: RunSettings, database_name: str) -> dict:
    db_config = dict(run_settings.db_config or {})
    db_config["database"] = database_name
    return db_config


def _execute_mysql_schema(schema_file_path: str, db_config: dict) -> list[str]:
    statements = []
    with open(schema_file_path, "r", encoding="utf-8") as schema_file:
        for part in schema_file.read().split(";"):
            statement = part.strip()
            if statement:
                statements.append(statement)

    connection_params = {
        "host": db_config.get("host", "127.0.0.1"),
        "port": int(db_config.get("port", 13306)),
        "user": db_config.get("user", "root"),
        "password": db_config.get("password", "123456"),
        "charset": "utf8mb4",
    }
    conn = pymysql.connect(**connection_params)
    skipped = []
    try:
        with conn.cursor() as cursor:
            for statement in statements:
                try:
                    cursor.execute(statement)
                except Exception as exc:
                    statement_upper = statement.lstrip().upper()
                    statement_normalized = " ".join(statement_upper.split())
                    if statement_normalized.startswith("CREATE INDEX") or statement_normalized.startswith("CREATE UNIQUE INDEX"):
                        skipped.append(f"Skipped index statement: {exc}")
                        continue
                    if statement_normalized.startswith("SET GLOBAL"):
                        skipped.append(f"Skipped global setting: {exc}")
                        continue
                    raise
        conn.commit()
        return skipped
    finally:
        conn.close()


def _execute_round_schema(round_dir: str, db_config: dict, log_file_path: str) -> None:
    schema_file_path = os.path.join(round_dir, "schema.sql")
    if not os.path.exists(schema_file_path):
        log_message(f"Schema file not found, skip schema execution: {schema_file_path}", log_file_path)
        return

    dialect = str(db_config.get("dialect") or "").upper()
    if dialect in ("", "MYSQL", "MARIADB", "TIDB", "OCEANBASE", "PERCONA", "POLARDB"):
        skipped = _execute_mysql_schema(schema_file_path, db_config)
        log_message(f"Schema executed: {schema_file_path}", log_file_path)
        for message in skipped[:10]:
            log_message(message, log_file_path)
        if len(skipped) > 10:
            log_message(f"Skipped {len(skipped) - 10} additional non-critical schema statements.", log_file_path)
        return

    raise ValueError(f"Schema execution is not implemented for dialect: {dialect}")


def _run_internal_generation(
    run_settings: RunSettings,
    log_file_path: str,
    round_dir: str,
    database_name: str,
    round_db_config: dict,
) -> str:
    log_message("Start generating SQL...", log_file_path)
    generate_start = time.time()
    if run_settings.use_database_tables and not run_settings.db_config:
        raise ValueError(
            "use_database_tables=True requires db_config in RunSettings."
        )

    Path(round_dir).mkdir(parents=True, exist_ok=True)
    Generate(
        subquery_depth=2,
        total_insert_statements=40,
        num_queries=1000,
        query_type="default",
        use_database_tables=run_settings.use_database_tables,
        db_config=round_db_config,
        output_dir=round_dir,
        database_name=database_name,
    )
    generate_end = time.time()
    log_message(
        f"SQL generation completed in {generate_end - generate_start:.2f}s.",
        log_file_path,
    )

    log_message(f"Start executing schema into database: {database_name}", log_file_path)
    schema_start = time.time()
    _execute_round_schema(round_dir, round_db_config, log_file_path)
    schema_end = time.time()
    log_message(
        f"Schema execution completed in {schema_end - schema_start:.2f}s.",
        log_file_path,
    )

    query_file_path = os.path.join(round_dir, "queries.sql")
    log_message(f"DQL preprocessing disabled; using raw query file: {query_file_path}", log_file_path)
    return query_file_path


def run(run_settings: RunSettings) -> None:
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_filename = f"execution_log_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    log_file_path = os.path.join(log_dir, log_filename)

    start_time = time.time()
    log_message(
        f"Program started at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}",
        log_file_path,
    )

    try:
        set_dialect(run_settings.dialect_str)
        log_message(f"Dialect set to: {run_settings.dialect_str}", log_file_path)
        total_seconds = run_settings.run_hours * 3600
        cycle_count = 0
        cycle_start_time = time.time()

        log_message(
            f"Begin loop execution for up to {run_settings.run_hours} hour(s).",
            log_file_path,
        )

        while time.time() - cycle_start_time < total_seconds:
            cycle_count += 1
            log_message(f"\n===== Cycle {cycle_count} start =====", log_file_path)
            round_dir = os.path.join("generated_sql", f"round{cycle_count}")
            database_name = f"database{cycle_count}"
            round_db_config = _round_db_config(run_settings, database_name)

            try:
                query_file_path = _run_internal_generation(
                    run_settings,
                    log_file_path,
                    round_dir,
                    database_name,
                    round_db_config,
                )

                log_message(f"Skip DQL preprocessing for raw query file: {query_file_path}", log_file_path)

                if run_settings.enable_result_checks:
                    log_message("Start result checks...", log_file_path)
                    check_summary = run_result_checks(
                        round_dir=round_dir,
                        database_name=database_name,
                        db_config=round_db_config,
                        dialect=run_settings.dialect_str,
                        detector_names=None,
                    )
                    log_message(
                        "Result checks done: "
                        f"checks={check_summary.get('nullability_checks', 0)} "
                        f"violations={check_summary.get('nullability_violations', 0)} "
                        f"exec_fail={check_summary['exec_fail']}",
                        log_file_path,
                    )

                elapsed = time.time() - cycle_start_time
                remaining = max(total_seconds - elapsed, 0.0)
                log_message(
                    f"Cycle {cycle_count} done. elapsed={elapsed:.2f}s remaining={remaining:.2f}s",
                    log_file_path,
                )
            except Exception as exc:
                log_message(f"Cycle {cycle_count} failed: {exc}", log_file_path)
                continue
            finally:
                gc.collect()
                log_message("Garbage collection completed.")

        end_time = time.time()
        total_time = end_time - start_time
        log_message("\n===== Run Summary =====", log_file_path)
        log_message(
            f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}",
            log_file_path,
        )
        log_message(
            f"Ended at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}",
            log_file_path,
        )
        log_message(f"Total elapsed: {total_time:.2f}s", log_file_path)
        log_message(f"Completed cycles: {cycle_count}", log_file_path)
        log_message(f"Log file saved to: {os.path.abspath(log_file_path)}", log_file_path)
    except Exception as exc:
        error_time = time.time()
        log_message(f"\nProgram failed: {exc}", log_file_path)
        log_message(
            f"Failure time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(error_time))}",
            log_file_path,
        )
        log_message(f"Elapsed before failure: {error_time - start_time:.2f}s", log_file_path)
        log_message(f"Log file saved to: {os.path.abspath(log_file_path)}", log_file_path)
        raise
