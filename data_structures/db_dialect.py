"""Defines dialect abstractions and dialect-specific SQL behavior helpers."""

from abc import ABC, abstractmethod


class DBDialect(ABC):
    """Database Dialect Abstract Base Class"""
    @property
    @abstractmethod
    def name(self):
        """Databse name"""
        pass
    
    @abstractmethod
    def get_create_database_sql(self, db_name: str) -> str:
        """Gets the SQL statement that created the database"""
        pass
    
    @abstractmethod
    def get_use_database_sql(self, db_name: str) -> str:
        """Gets the SQL statement that uses the database"""
        pass
    
    @abstractmethod
    def get_drop_database_sql(self, db_name: str) -> str:
        """Gets the SQL statement to delete the database"""
        pass
    
    @abstractmethod
    def get_column_definition(self, col_name: str, data_type: str, nullable: bool, is_primary_key: bool = False) -> str:
        """Gets the SQL statement of the column definition"""
        pass
    
    @abstractmethod
    def get_primary_key_constraint(self, primary_key: str) -> str:
        """Gets the SQL statement of the primary key constraint"""
        pass
    
    @abstractmethod
    def get_datetime_literal(self, year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> str:
        """Get SQL representation of datetime literal"""
        pass
    
    @abstractmethod
    def get_function_name(self, function_name: str) -> str:
        """Get dialect-specific function names"""
        pass
    
    @abstractmethod
    def get_literal_representation(self, value: str, data_type: str) -> str:
        """Get a dialect-specific representation of a literal amount"""
        pass
    
    @abstractmethod
    def get_create_index_sql(self, table_name: str, index_name: str, columns: list, is_unique: bool = False) -> str:
        """Gets the SQL statement that creates the MySQL index"""
        pass
    
    @abstractmethod
    def get_session_settings_sql(self) -> str:
        """Get SQL statements for MySQL session settings"""
        pass


class MySQLDialect(DBDialect):
    """MySQLDatabase dialect implementation"""
    @property
    def name(self):
        return "MYSQL"
    
    def get_create_database_sql(self, db_name: str) -> str:
        return f"CREATE DATABASE IF NOT EXISTS {db_name};"
    
    def get_use_database_sql(self, db_name: str) -> str:
        return f"USE {db_name};"
    
    def get_drop_database_sql(self, db_name: str) -> str:
        return f"DROP DATABASE IF EXISTS {db_name};"
    
    def get_column_definition(self, col_name: str, data_type: str, nullable: bool, is_primary_key: bool = False) -> str:
        nullable_str = "NULL" if nullable else "NOT NULL"
        if is_primary_key and "INT" in data_type:
            return f"{col_name} {data_type} {nullable_str} AUTO_INCREMENT"
        return f"{col_name} {data_type} {nullable_str}"
    
    def get_primary_key_constraint(self, primary_key: str) -> str:
        return f"PRIMARY KEY ({primary_key})"
    
    def get_datetime_literal(self, year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> str:
        #Check if only the date part is required (all time parameters are default 0)
        if hour == 0 and minute == 0 and second == 0:
            return f"'{year:04d}-{month:02d}-{day:02d}'"
        else:
            return f"'{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}'"
    
    def get_function_name(self, function_name: str) -> str:
        #MySQL Function Name Mapping
        function_mapping = {
            "TO_CHAR": "DATE_FORMAT",
            "VARIANCE_POP": "VAR_POP",
            "VARIANCE_SAMP": "VAR_SAMP"
        }
        return function_mapping.get(function_name, function_name)
    
    def get_literal_representation(self, value: str, data_type: str) -> str:
        #Ensure data_type is a string and not None
        if data_type is None:
            data_type = 'UNKNOWN'
        
        #Special Handling null Values
        if value is None:
            return 'NULL'
        
        #Make sure value is a string
        value_str = str(value)
        
        #Special processing datetime type, make sure to always add quotation marks
        if data_type.upper() in ['DATE', 'DATETIME', 'TIMESTAMP']:
            #Check if the value is already surrounded by single or double quotes
            if (value_str.startswith("'") and value_str.endswith("'") or 
                value_str.startswith('"') and value_str.endswith('"')):
                #If there are already quotes, return the original value directly (no extra escape)
                return value_str
            #Filter non-ASCII characters to ensure only valid UTF-8 characters are included
            safe_value = ''.join(char for char in value_str if ord(char) < 128)
            #Escape single quotes and add quotes
            escaped_value = safe_value.replace("'", "''")
            return f"'{escaped_value}'"
        elif data_type.upper() in ['VARCHAR', 'VARCHAR(255)', 'STRING']:
            #Make sure value is a string
            #Check if the value is already surrounded by single or double quotes
            if (value_str.startswith("'") and value_str.endswith("'") or 
                value_str.startswith('"') and value_str.endswith('"')):
                #If there are already quotes, return the original value directly (no extra escape)
                return value_str
            #Filter non-ASCII characters to ensure only valid UTF-8 characters are included
            #Use ascii encoding, ignore non-ASCII characters
            safe_value = ''.join(char for char in value_str if ord(char) < 128)
            #Escape single quotes and add quotes
            escaped_value = safe_value.replace("'", "''")
            return f"'{escaped_value}'"
        elif data_type.upper() in ['BOOLEAN', 'BOOL']:
            #MySQL uses the true/false string to represent a Boolean value
            return f"'{str(value).lower()}'"
        elif data_type.upper() == 'JSON':
            #Make sure the JSON value is in the correct quote format
            value_str = str(value)
            safe_value = ''.join(char for char in value_str if ord(char) < 128)
            escaped_value = safe_value.replace("'", "''")
            return f"'{escaped_value}'"
        elif data_type.upper() in ['BLOB', 'TINYBLOB', 'MEDIUMBLOB', 'LONGBLOB']:
            #Special handling of binary types to ensure utf8mb4 requirements are met
            #Check if the value is already in hexadecimal format (X '...')
            if value_str.startswith("X'") and value_str.endswith("'"):
                #Extract hexadecimal part
                hex_part = value_str[2:-1]
                #Ensure hexadecimal data length is even (full bytes)
                if len(hex_part) % 2 != 0:
                    hex_part = '0' + hex_part
                #Validate hex characters
                if all(c in '0123456789ABCDEFabcdef' for c in hex_part):
                    #For utf8mb4, you need to ensure that the binary data is a valid UTF-8 encoding sequence
                    #Because we can't directly verify the validity of UTF-8 for binary data in a string representation
                    #We chose to explicitly convert it to utf8mb4 using MySQL's convert function
                    return f"CONVERT({value_str} USING utf8mb4)"
            #Returns an empty binary value if it is not in standard format
            return "X''"
        #For other data types, make sure the string returned is a valid UTF-8
        value_str = str(value)
        #Checks if the value is of string type
        if isinstance(value, str):
            #Filter non-ASCII characters to ensure only valid UTF-8 characters are included
            safe_value = ''.join(char for char in value_str if ord(char) < 128)
            return safe_value
        return value_str
    
    def get_create_index_sql(self, table_name: str, index_name: str, columns: list, is_unique: bool = False) -> str:
        """Gets the SQL statement that creates the MySQL index"""
        unique_clause = "UNIQUE" if is_unique else ""
        columns_str = ", ".join(columns)
        return f"CREATE {unique_clause} INDEX {index_name} ON {table_name} ({columns_str});"
    
    def get_session_settings_sql(self) -> str:
        """Get SQL statements for MySQL session settings"""
        return "SET GLOBAL sort_buffer_size = 64 * 1024 * 1024;\nSET GLOBAL read_rnd_buffer_size = 8 * 1024 * 1024;"


class PostgreSQLDialect(DBDialect):
    """PostgreSQLDatabase dialect implementation"""
    @property
    def name(self):
        return "POSTGRESQL"
    
    def get_create_database_sql(self, db_name: str) -> str:
        #PostgreSQL does not support IF not exists clauses
        return f"CREATE DATABASE {db_name};"
    
    def get_use_database_sql(self, db_name: str) -> str:
        #There is no use statement in PostgreSQL, the connection database is specified by the connection parameter
        return ""
    
    def get_drop_database_sql(self, db_name: str) -> str:
        #PostgreSQL needs to disconnect all connections before deleting the database
        terminate_sql = f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}';"
        drop_sql = f"DROP DATABASE IF EXISTS {db_name};"
        return f"{terminate_sql}\n{drop_sql}"
    
    def get_column_definition(self, col_name: str, data_type: str, nullable: bool, is_primary_key: bool = False) -> str:
        nullable_str = "NULL" if nullable else "NOT NULL"
        if is_primary_key and "INT" in data_type:
            #PostgreSQL uses serial or generated always AS identity
            return f"{col_name} SERIAL PRIMARY KEY"
        #PostgreSQL uses timestamp instead of datetime
        if data_type == "DATETIME":
            data_type = "TIMESTAMP"
        return f"{col_name} {data_type} {nullable_str}"
    
    def get_primary_key_constraint(self, primary_key: str) -> str:
        #For serial type primary keys, there is no need to add the primary key constraint separately
        return f"PRIMARY KEY ({primary_key})"
    
    def get_datetime_literal(self, year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> str:
        #Check if only the date part is required (all time parameters are default 0)
        if hour == 0 and minute == 0 and second == 0:
            return f"'{year:04d}-{month:02d}-{day:02d}'"
        else:
            #PostgreSQL's datetime format is compatible with MySQL
            return f"'{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}'"
    
    def get_function_name(self, function_name: str) -> str:
        #PostgreSQL function name mapping
        function_mapping = {
            "DATE_FORMAT": "TO_CHAR"
        }
        return function_mapping.get(function_name, function_name)
    
    def get_literal_representation(self, value: str, data_type: str) -> str:
        #Ensure data_type is a string and not None
        if data_type is None:
            data_type = 'UNKNOWN'
        
        #Special Handling null Values
        if value is None:
            return 'NULL'
        
        #Make sure value is a string
        value_str = str(value)
        #Check if the value is already surrounded by single or double quotes
        is_quoted = (value_str.startswith("'") and value_str.endswith("'") or 
                    value_str.startswith('"') and value_str.endswith('"'))
        
        #Add single quotation marks for string, date and timestamp types
        if data_type.upper() in ['VARCHAR', 'VARCHAR(255)', 'TEXT', 'DATE', 'TIMESTAMP', 'STRING', 'DATETIME']:
            if is_quoted:
                #If there are already quotes, return the original value directly (no extra escape)
                return value_str
            #Otherwise escape single quotes and add quotes
            escaped_value = value_str.replace("'", "''")
            #Make sure to return a single quoted string
            return f"'{escaped_value}'"
        elif data_type.upper() in ['BOOLEAN', 'BOOL']:
            #PostgreSQL uses the true/false keyword to represent a boolean value
            return str(value).upper()
        # （），
        return str(value)
    
    def get_create_index_sql(self, table_name: str, index_name: str, columns: list, is_unique: bool = False) -> str:
        """PostgreSQLSQL"""
        unique_clause = "UNIQUE" if is_unique else ""
        columns_str = ", ".join(columns)
        return f"CREATE {unique_clause} INDEX {index_name} ON {table_name} ({columns_str});"

    def get_session_settings_sql(self) -> str:
        """PostgreSQLSQL"""
        return ""


class MariaDBDialect(MySQLDialect):
    """MariaDBDatabase dialect implementation"""
    @property
    def name(self):
        return "MARIADB"
    
    def get_column_definition(self, col_name: str, data_type: str, nullable: bool, is_primary_key: bool = False) -> str:
        #MariaDB treats JSON as an alias for LONGTEXT and requires special handling
        if data_type.upper() == "JSON":
            data_type = "LONGTEXT"
        # GEOMETRY，MariaDB
        return super().get_column_definition(col_name, data_type, nullable, is_primary_key)
    
    def get_function_name(self, function_name: str) -> str:
        # MariaDB
        function_mapping = {
            "TO_CHAR": "DATE_FORMAT",
            "VARIANCE_POP": "VAR_POP",
            "VARIANCE_SAMP": "VAR_SAMP"
            # MySQL，MariaDB
        }
        return function_mapping.get(function_name, function_name)
    
    def get_literal_representation(self, value: str, data_type: str) -> str:
        #Ensure data_type is a string and not None
        if data_type is None:
            data_type = 'UNKNOWN'
        
        # JSON：MariaDBJSON
        if data_type.upper() == "JSON":
            import json
            #Make sure value is a string
            value_str = str(value)
            #Filter non-ASCII characters to ensure only valid UTF-8 characters are included
            safe_value = ''.join(char for char in value_str if ord(char) < 128)
            # 
            escaped_value = safe_value.replace('"', '\\"')
            return f'"{escaped_value}"'
        
        # MariaDBJSONLONGTEXT，LONGTEXT
        if data_type.upper() == "JSON":
            data_type = "LONGTEXT"
        
        # BOOLEAN，MariaDBTINYINT(1)
        if data_type.upper() in ['BOOLEAN', 'BOOL']:
            #Make sure value is a string
            value_str = str(value).lower() if value is not None else 'null'
            if value_str in ['true', 'false']:
                return '1' if value_str == 'true' else '0'
        
        # ，MariaDB
        if data_type.upper() in ['GEOMETRY', 'POINT', 'LINESTRING', 'POLYGON']:
            # MariaDBMySQL，
            return "NULL"
        
        # 
        return super().get_literal_representation(value, data_type)
    
    def supports_native_json(self) -> bool:
        """MariaDBJSON，LONGTEXT"""
        return False
    
    def supports_math_equivalence_transformations(self) -> bool:
        """MariaDB，MIN/MAX"""
        return False


class TiDBDialect(MySQLDialect):
    """TiDBDatabase dialect implementation"""
    @property
    def name(self):
        return "TIDB"
    
    def supports_subqueries_in_join_condition(self) -> bool:
        """TiDBON"""
        return False
        
    def supports_share_lock_mode(self) -> bool:
        """TiDBLOCK IN SHARE MODE，"""
        return False


class OceanBaseDialect(MySQLDialect):
    """OceanBaseDatabase dialect implementation"""
    @property
    def name(self):
        return "OCEANBASE"


class PerconaDialect(MySQLDialect):
    """PerconaDatabase dialect implementation"""
    @property
    def name(self):
        return "PERCONA"


class PolarDBDialect(MySQLDialect):
    """PolarDBDatabase dialect implementation"""
    @property
    def name(self):
        return "POLARDB"
    
    def get_column_definition(self, col_name: str, data_type: str, nullable: bool, is_primary_key: str) -> str:
        # ，
        # 
        nullable_str = "NULL" if nullable else "NOT NULL"
        if is_primary_key and "INT" in data_type:
            return f"{col_name} {data_type} {nullable_str} AUTO_INCREMENT"
        return f"{col_name} {data_type} {nullable_str}"
    
    def get_primary_key_constraint(self, primary_key: str) -> str:
        # 
        return f"PRIMARY KEY ({primary_key})"
    
    def get_function_name(self, function_name: str) -> str:
        # PolarDB-X
        # AVG
        unsupported_functions = {
            "STD": "AVG",
            "STDDEV": "AVG",
            "STDDEV_POP": "AVG",
            "STDDEV_SAMP": "AVG",
            "VARIANCE": "AVG",
            "VARIANCE_POP": "AVG",
            "VARIANCE_SAMP": "AVG",
            "VAR_POP": "AVG",
            "VAR_SAMP": "AVG"
        }
        
        # 
        if function_name in unsupported_functions:
            return unsupported_functions[function_name]
        
        # MySQL
        function_mapping = {
            "TO_CHAR": "DATE_FORMAT"
        }
        return function_mapping.get(function_name, function_name)
    
    def supports_foreign_keys(self) -> bool:
        """PolarDB"""
        return False
    
    def supports_subqueries_in_join(self) -> bool:
        """PolarDBJOIN"""
        return False
    
    def supports_share_lock_mode(self) -> bool:
        """PolarDBLOCK IN SHARE MODE，FOR KEY SHARE"""
        return True
    
    def supports_except_operator(self) -> bool:
        """PolarDB-XEXCEPT"""
        # PolarDB-XMySQL，EXCEPT
        return False
    
    def supports_intersect_operator(self) -> bool:
        """PolarDB-XINTERSECT"""
        # PolarDB-XMySQL，INTERSECT
        return False


class DBDialectFactory:
    """"""
    _dialects = {
        "MYSQL": MySQLDialect,
        "POSTGRESQL": PostgreSQLDialect,
        "MARIADB": MariaDBDialect,
        "TIDB": TiDBDialect,
        "OCEANBASE": OceanBaseDialect,
        "PERCONA": PerconaDialect,
        "POLARDB": PolarDBDialect
    }
    
    _current_dialect = None
    
    @classmethod
    def get_dialect(cls, dialect_name: str) -> DBDialect:
        """"""
        dialect_name = dialect_name.upper()
        if dialect_name not in cls._dialects:
            raise ValueError(f"Unsupported database dialect: {dialect_name}")
        return cls._dialects[dialect_name]()
    
    @classmethod
    def set_current_dialect(cls, dialect_name: str) -> None:
        """"""
        cls._current_dialect = cls.get_dialect(dialect_name)
    
    @classmethod
    def get_current_dialect(cls) -> DBDialect:
        """"""
        if cls._current_dialect is None:
            # MySQL
            cls.set_current_dialect("MYSQL")
        return cls._current_dialect


# MySQL
def get_current_dialect() -> DBDialect:
    """"""
    return DBDialectFactory.get_current_dialect()

def set_current_dialect(dialect_name: str) -> None:
    """"""
    DBDialectFactory.set_current_dialect(dialect_name)

# ，
def set_dialect(dialect_name: str) -> None:
    """（，）"""
    DBDialectFactory.set_current_dialect(dialect_name)

def get_dialect_config() -> DBDialect:
    """（，）"""
    return DBDialectFactory.get_current_dialect()
