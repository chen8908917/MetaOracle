import os
import pymysql
import psycopg2
from data_structures.db_dialect import get_current_dialect
import os

class SeedQueryGenerator:
    def __init__(self, file_path='generated_sql/queries.sql', db_config=None):
        self.file_path = file_path
        #
        self.db_config = db_config or {}
        #

    def query_iterator(self):
                
        try:
            #
            abs_path = os.path.abspath(self.file_path)

            with open(abs_path, 'r', encoding='utf-8') as f:
                #
                for line in f:
                    #
                    sql = line.strip()
                    #
                    if sql:
                        yield sql
        except Exception as e:
            print(f"Failed to read SQL file: {e}")

    def get_queries_count(self):
                
        count = 0
        for _ in self.query_iterator():
            count += 1
        return count

    def connect_db(self):
                
        try:
            #
            dialect = get_current_dialect()
            dialect_name = dialect.name.upper()
            
            #
            
            #
            if dialect_name in ["MYSQL", "MARIADB", "TIDB", "OCEANBASE","PERCONA", "POLARDB"]:
                # MySQL??????????????????????
                if dialect_name == "MYSQL":
                    defaults = {
                        'host': '127.0.0.1',
                        'user': 'root',
                        'password': '123456',
                        'database': 'test',
                        'port': 13306
                    }
                elif dialect_name == "MARIADB":
                    defaults = {
                        'host': '127.0.0.1',
                        'user': 'root',
                        'password': '123456',
                        'database': 'test',
                        'port': 9901
                    }
                elif dialect_name == "TIDB":
                    defaults = {
                        'host': '127.0.0.1',
                        'user': 'root',
                        'password': '123456',
                        'database': 'test',
                        'port': 4000
                    }
                elif dialect_name == "OCEANBASE":
                    defaults = {
                        'host': '127.0.0.1',
                        'user': 'root',
                        'password': '',
                        'database': 'test',
                        'port': 2881
                    }
                elif dialect_name == "PERCONA":
                    defaults = {
                        'host': '127.0.0.1',
                        'user': 'root',
                        'password': '123456',
                        'database': 'test',
                        'port': 23306
                    }
                elif dialect_name == "POLARDB":
                    defaults = {
                        'host': '127.0.0.1',
                        'user': 'polardbx_root',
                        'password': '123456',
                        'database': 'test',
                        'port': 8527
                    }
                else:
                    defaults = {}

                for key, value in defaults.items():
                    if self.db_config.get(key) in [None, ""]:
                        self.db_config[key] = value

                # ??MySQL/MariaDB/TiDB/OceanBase??
                connection_params = {
                    'host': self.db_config['host'],
                    'user': self.db_config['user'],
                    'password': self.db_config['password'],
                    'database': self.db_config['database'],
                    'port': self.db_config['port'],
                    'charset': 'utf8mb4'
                }
                
                #
                
                conn = pymysql.connect(**connection_params)
            elif dialect_name == "POSTGRESQL":
                #
                if not self.db_config.get('host'):
                    self.db_config['host'] = '127.0.0.1'
                if not self.db_config.get('user'):
                    self.db_config['user'] = 'postgres'
                if self.db_config.get('password') is None:
                    self.db_config['password'] = 'postgres'
                if not self.db_config.get('database'):
                    self.db_config['database'] = 'test'
                # Avoid carrying MySQL default port into Postgres connections
                if not self.db_config.get('port') or self.db_config.get('port') == 13306:
                    self.db_config['port'] = 5432
                
                conn = psycopg2.connect(
                    host=self.db_config['host'],
                    user=self.db_config['user'],
                    password=self.db_config['password'],
                    dbname=self.db_config['database'],
                    port=self.db_config['port']
                )
            else:
                raise ValueError(f"不支持的数据库方言: {dialect_name}")
            
            #
            return conn
        except Exception as e:
            self._last_connection_error = str(e)
            return None

    def execute_query_with_connection(self, query, conn, dialect_name=None):
                
        if not query or query.strip() == '':
            print("Empty query skipped.")
            return None
        if conn is None:
            return None
        if not dialect_name:
            dialect = get_current_dialect()
            dialect_name = dialect.name.upper()
        try:
            with conn.cursor() as cursor:
                if dialect_name == "POSTGRESQL":
                    import re
                    pattern = r"TO_CHAR\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)"
                    def add_type_cast(match):
                        date_str = match.group(1)
                        format_str = match.group(2)
                        return f"TO_CHAR('{date_str}'::DATE, '{format_str}')"
                    query = re.sub(pattern, add_type_cast, query)
                elif dialect_name == "MYSQL":
                    import re
                    from data_structures.db_dialect import MySQLDialect
                    mysql_dialect = MySQLDialect()
                    function_pattern = r"\b([A-Z][A-Z_]+)\s*\("
                    def apply_function_mapping(match):
                        function_name = match.group(1)
                        mapped_name = mysql_dialect.get_function_name(function_name)
                        return f"{mapped_name}("
                    query = re.sub(function_pattern, apply_function_mapping, query)

                cursor.execute(query)
                processed_query = query.strip().upper()
                while processed_query.startswith('('):
                    processed_query = processed_query[1:].strip()
                is_select_query = processed_query.startswith('SELECT') or processed_query.startswith('WITH')
                if is_select_query:
                    result = cursor.fetchall()
                    column_names = [desc[0] for desc in cursor.description] if cursor.description else []
                    return (result, column_names)
                else:
                    conn.commit()
                    return cursor.rowcount
        except Exception as e:
            raise

    def execute_query(self, query):
                
        conn = self.connect_db()
        if conn is None:
            return None
        try:
            return self.execute_query_with_connection(query, conn)
        except Exception:
            return None
        finally:
            if conn:
                conn.close()

    def execute_queries(self):
                
        for query in self.query_iterator():
            self.execute_query(query)

    def get_seedQuery(self, batch_size=500):
                
        #
        dialect = get_current_dialect()
        dialect_name = dialect.name.upper()
        
        #
        seed_file_path = os.path.join(os.path.dirname(self.file_path) or ".", "seedQuery.sql")
        with open(seed_file_path, "w", encoding="utf-8") as f:
            if dialect_name != "POSTGRESQL":
                target_db = self.db_config.get("database") or "test"
                f.write(f"USE {target_db};\n")
                f.write(dialect.get_session_settings_sql())
                if not dialect.get_session_settings_sql().endswith("\n"):
                    f.write("\n")
            elif dialect_name == "POSTGRESQL":
                f.write("-- PostgreSQL does not use USE statements; the database is selected by connection parameters.\n")
            else:
                f.write(f"-- Current dialect: {dialect_name}\n")

        #
        total_queries = self.get_queries_count()
        print(f"Found {total_queries} SQL queries.")

        #
        success_count = 0
        
        #
        batch = []
        batch_count = 0
        
        #
        for i, sql in enumerate(self.query_iterator(), 1):
            if i % 1000 == 0:
                print(f"Processed {i}/{total_queries} queries.")
            #
            result = self.execute_query(sql)
            
            #
            if result is not None:
                #
                if isinstance(result, int):
                    #
                    pass
                else:
                    #
                    batch.append(sql)
                    batch.append("\n")
                    success_count += 1
                    pass
            else:
                #print(sql)
                pass
            
            #
            if len(batch) >= batch_size * 2:  #
                with open(seed_file_path, "a", encoding="utf-8") as f:
                    for seed in batch:
                        f.write(seed)
                batch = []  #
                batch_count += 1
        
        #
        if batch:
            with open(seed_file_path, "a", encoding="utf-8") as f:
                for seed in batch:
                    f.write(seed)
        
        print(f"\nSeed query generation completed. Valid SELECT queries: {success_count}")
        print(f"Seed queries saved to: {seed_file_path}")


    
       
