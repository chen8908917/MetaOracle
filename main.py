from pipeline.models import RunSettings
from pipeline.runner import run


if __name__ == '__main__':

    # =====================
    # Runtime configuration
    # =====================
    run_settings = RunSettings(
        dialect_str='mysql',
        run_hours=12,
        use_database_tables=False,
        enable_result_checks=True,
        db_config={
            "host": "127.0.0.1",
            "port": 13306,
            "database": "test",
            "user": "root",
            "password": "123456",
            "dialect": "MYSQL",
        },
    )

    run(run_settings)
