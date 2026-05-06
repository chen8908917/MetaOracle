"""Generates DDL/DML statements (CREATE/INSERT) for sampled schemas."""

import random
import re
import string
from datetime import datetime, timedelta
from typing import List, Optional

from data_structures.db_dialect import get_current_dialect
from sql_generation.random_sql.geometry import create_geometry_wkt
from data_structures.table import Table

def generate_create_table_sql(table: Table) -> str:
    """Generate table-building SQL statements"""
    #Get the current database dialect
    dialect = get_current_dialect()
    
    parts = [f"CREATE TABLE {table.name} ("]

    #column definition
    column_defs = []
    for col in table.columns:
        is_primary_key = col.name == table.primary_key
        #Generate column definitions using dialect methods
        column_def = dialect.get_column_definition(
            col.name, 
            col.data_type, 
            col.is_nullable, 
            is_primary_key
        )
        column_defs.append(f"    {column_def}")

    #Add a primary key constraint if there is no serial primary key syntax using dialect
    if not any("SERIAL" in def_ for def_ in column_defs) and table.primary_key:
        primary_key_def = dialect.get_primary_key_constraint(table.primary_key)
        column_defs.append(f"    {primary_key_def}")

    #Foreign key - add only when dialect is supported
    if hasattr(dialect, 'supports_foreign_keys') and dialect.supports_foreign_keys():
        for fk in table.foreign_keys:
            column_defs.append(f"    FOREIGN KEY ({fk['column']}) REFERENCES {fk['ref_table']}({fk['ref_column']}) ")

    parts.append(",\n".join(column_defs))
    parts.append(");")

    return "\n".join(parts)

def generate_insert_sql(table: Table, num_rows: int = 5, existing_primary_keys: dict = None, primary_key_values: list = None) -> str:
    """Generate Insert SQL Statement（One insert per line）

    Args:
        table: Table Objects
        num_rows: Number of rows generated
        existing_primary_keys: Primary Key-Value Dictionary for Other Tables，Used for foreign key references
    """
    if not table.columns:
        return ""

    #Get the current database dialect
    dialect = get_current_dialect()
    
    #Column Name
    columns = [col.name for col in table.columns]

    #If no primary key value is provided, a unique value is generated for the non-self-increasing primary key
    if primary_key_values is None:
        primary_key_values = set()
        for _ in range(num_rows):
            while True:
                val = random.randint(1, 10000)
                if val not in primary_key_values:
                    primary_key_values.add(val)
                    break
        primary_key_values = list(primary_key_values)

    #Generate a single-line insert statement
    insert_sqls = []
    for i in range(num_rows):
        row_values = []
        for col in table.columns:
            normalized_type = col.data_type.upper()
            if col.name == table.primary_key:
                #Use pre-generated unique primary key value
                row_values.append(str(primary_key_values[i]))
            elif any(fk for fk in table.foreign_keys if fk["column"] == col.name):
                #Handles the foreign key, referencing the primary key value that already exists
                fk = next(fk for fk in table.foreign_keys if fk["column"] == col.name)
                ref_table = fk["ref_table"]
                if existing_primary_keys and ref_table in existing_primary_keys and existing_primary_keys[ref_table]:
                    #Randomly select one from the primary key values of the reference table
                    ref_pk_values = existing_primary_keys[ref_table]
                    if ref_pk_values:
                        selected_pk = random.choice(ref_pk_values)
                        row_values.append(str(selected_pk))
                    else:
                        #If the primary key value list of the reference table is empty, use a random value
                        row_values.append(str(random.randint(1, 100)))
                else:
                    #If there is no primary key value referencing the table, use a random value (this can lead to foreign key constraint errors in practice)
                    row_values.append(str(random.randint(1, 100)))
            #Generate logic based on specific data types
            elif (
                normalized_type.startswith("INT")
                or normalized_type.startswith("TINYINT")
                or normalized_type.startswith("SMALLINT")
                or normalized_type.startswith("MEDIUMINT")
                or normalized_type.startswith("BIGINT")
            ):
                if table.name == "orders" and col.name == "amount":
                    #the amount column of the orders table uses an integer
                    row_values.append(str(random.randint(10, 1000)))
                else:
                    row_values.append(str(random.randint(0, 100)))
            elif col.data_type.startswith("DECIMAL") or col.data_type.startswith("NUMERIC"):
                row_values.append(f"{random.uniform(10, 1000):.2f}")
            elif col.data_type.startswith("FLOAT") or col.data_type.startswith("DOUBLE"):
                row_values.append(f"{random.uniform(0.0, 100.0):.2f}")
            elif col.data_type.startswith("VARCHAR") or col.data_type in ["CHAR", "TEXT", "LONGTEXT", "MEDIUMTEXT", "TINYTEXT"]:
                #Special handling of the status column of the orders table
                if table.name == "orders" and col.name == "status":
                    #Randomly select from three states
                    status_values = ["finished", "finishing", "to_finish"]
                    row_values.append(f"'{random.choice(status_values)}'")
                #Do special processing on the email column of the users table to generate a 10-digit integer @ qq.com format
                elif table.name == "users" and col.name == "email":
                    #Generate 10-bit random integer
                    ten_digit_number = random.randint(1000000000, 9999999999)
                    row_values.append(f"'{ten_digit_number}@qq.com'")
                #Do special treatment on the sex column of the users table, the value is girl or boy
                elif table.name == "users" and col.name == "sex":
                    #Randomly selected from both genders
                    sex_values = ["girl", "boy"]
                    row_values.append(f"'{random.choice(sex_values)}'")
                else:
                    #Generate random strings using pure ASCII characters to avoid UTF-8 encoding issues
                    import string
                    
                    #Determine string length based on data type
                    if col.data_type.startswith("VARCHAR"):
                        #Attempt to extract length from varchar definition
                        match = re.search(r"VARCHAR\((\d+)\)", col.data_type)
                        if match:
                            max_length = int(match.group(1))
                            #Generate random strings up to the maximum length
                            string_length = random.randint(1, min(max_length, 255))  #Prevent excessive length
                        else:
                            #Default varchar length
                            string_length = random.randint(5, 20)
                    elif col.data_type.startswith("CHAR"):
                        #Try to extract length from char definition
                        match = re.search(r"CHAR\((\d+)\)", col.data_type)
                        if match:
                            #Char types use fixed lengths
                            string_length = int(match.group(1))
                        else:
                            #Default char Length
                            string_length = 10
                    elif col.data_type == "TINYTEXT":
                        #TINYTEXT max length is 255
                        string_length = random.randint(1, 200)
                    elif col.data_type == "TEXT":
                        #Max text length is 65535
                        string_length = random.randint(1, 500)
                    elif col.data_type == "MEDIUMTEXT":
                        #MEDIUMTEXT maximum length is 16777215
                        string_length = random.randint(1, 1000)
                    elif col.data_type == "LONGTEXT":
                        #LONGTEXT maximum length is 4294967295
                        string_length = random.randint(1, 2000)
                    else:
                        #Default Length
                        string_length = random.randint(5, 20)
                    
                    #Generate a random string of the specified length, ensuring that the sample_prefix counts towards the total length
                    prefix = 'sample_'
                    #Subtract the prefix length from the total length to ensure that the total length meets the requirements
                    random_part_length = max(1, string_length - len(prefix))  #Make sure there is at least 1 random character
                    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=random_part_length))
                    row_values.append(f"'{prefix}{random_str}'")
            elif normalized_type.startswith("VARBINARY") or normalized_type.startswith("BINARY"):
                byte_length = random.randint(1, 32)
                hex_data = "".join(random.choices("0123456789ABCDEF", k=byte_length * 2))
                row_values.append(f"X'{hex_data}'")
            elif col.data_type == "DATE":
                #Generate Random Date Values
                days = random.randint(0, 365)
                date_val = datetime.now() - timedelta(days=days)
                datetime_literal = dialect.get_datetime_literal(
                    date_val.year, date_val.month, date_val.day
                )
                row_values.append(datetime_literal)
            elif col.data_type == "TIME":
                #Generate random time values
                hours = random.randint(0, 23)
                minutes = random.randint(0, 59)
                seconds = random.randint(0, 59)
                datetime_literal = dialect.get_datetime_literal(
                    2023, 1, 1, hours, minutes, seconds
                )
                row_values.append(datetime_literal)
            elif col.data_type in ["DATETIME", "TIMESTAMP"]:
                #Generate Random Date Time Values
                days = random.randint(0, 365)
                hours = random.randint(0, 23)
                minutes = random.randint(0, 59)
                seconds = random.randint(0, 59)
                date_val = datetime.now() - timedelta(days=days)
                datetime_literal = dialect.get_datetime_literal(
                    date_val.year, date_val.month, date_val.day, 
                    hours, minutes, seconds
                )
                row_values.append(datetime_literal)
            elif col.data_type == "BOOLEAN" or col.data_type == "BOOL":
                #Generate Boolean representation from dialect
                is_true = random.choice([True, False])
                if dialect.name == "POSTGRESQL":
                    #PostgreSQL uses the true/false keyword
                    row_values.append("TRUE" if is_true else "FALSE")
                else:
                    #MySQL uses 1/0 or true/false strings
                    row_values.append(str(is_true).lower())

            elif col.data_type.startswith("SET"):
                #Set Type: Randomly select one or more from the allowed values
                #Parse Optional Values in set Definition
                set_values = re.findall(r"'([^']+)',?", col.data_type)
                if set_values:
                    #Randomly select elements between 1 and the number of all values
                    num_selected = random.randint(1, len(set_values))
                    selected_values = random.sample(set_values, num_selected)
                    row_values.append("'" + ",".join(selected_values) + "'")
                else:
                    row_values.append("''")
            elif col.data_type.startswith("ENUM"):
                #Enum Type: Randomly select one from the enum values
                enum_values = re.findall(r"'([^']+)',?", col.data_type)
                if enum_values:
                    row_values.append("'" + random.choice(enum_values) + "'")
                else:
                    row_values.append("NULL")
            elif col.data_type.startswith("BIT"):
                #Bit Type: Generate Random Bit Value
                #Number of resolution bits
                bit_count = re.search(r"BIT\((\d+)\)", col.data_type)
                if bit_count:
                    bit_count = int(bit_count.group(1))
                    #Generate a random binary number with the specified number of digits
                    max_value = 2 ** bit_count - 1
                    row_values.append("b'" + bin(random.randint(0, max_value))[2:].zfill(bit_count) + "'")
                else:
                    row_values.append("b'0'")
            elif col.data_type in ["YEAR"]:
                #Year Type: Generate a random year between 2000-2023
                row_values.append(str(random.randint(2000, 2023)))
            elif col.data_type in ["GEOMETRY", "POINT", "LINESTRING", "POLYGON"]:
                if get_current_dialect().name == "TIDB":
                    row_values.append("NULL")
                    continue
                #Geometry type: generates simple geometric data
                if col.data_type == "POINT":
                    #Generate simple point coordinates
                    lat = round(random.uniform(-90, 90), 6)
                    lng = round(random.uniform(-180, 180), 6)
                    row_values.append(f"ST_GeomFromText('POINT({lat} {lng})')")
                elif col.data_type == "LINESTRING":
                    #Generate Simple Lines
                    points = []
                    for _ in range(2):
                        lat = round(random.uniform(-90, 90), 6)
                        lng = round(random.uniform(-180, 180), 6)
                        points.append(f"{lat} {lng}")
                    row_values.append(f"ST_GeomFromText('LINESTRING({','.join(points)})')")
                elif col.data_type == "POLYGON":
                    #Generate simple polygons
                    points = []
                    for _ in range(4):
                        lat = round(random.uniform(-90, 90), 6)
                        lng = round(random.uniform(-180, 180), 6)
                        points.append(f"{lat} {lng}")
                    #Closed Polygonal
                    points.append(points[0])
                    row_values.append(f"ST_GeomFromText('POLYGON(({','.join(points)}))')")
                else:
                    #Generic geometry type, defaults to point
                    lat = round(random.uniform(-90, 90), 6)
                    lng = round(random.uniform(-180, 180), 6)
                    row_values.append(f"ST_GeomFromText('POINT({lat} {lng})')")
            elif col.data_type == "JSON" or col.data_type.startswith("JSON"):
                #JSON type: generating random JSON data
                import json
                
                #Randomly select JSON structure type
                json_types = ["simple_object", "nested_object", "array", "mixed"]
                json_type = random.choice(json_types)
                
                if json_type == "simple_object":
                    #Simple JSON Object
                    json_data = {
                        "k1": random.randint(1, 1000),
                        "k2": f"sample_{random.randint(1, 100)}",
                        "k3": random.uniform(10, 1000),
                        "k4": random.choice([True, False])
                    }
                elif json_type == "nested_object":
                    #Nested JSON objects
                    json_data = {
                        "k1": {
                            "k2": random.randint(1, 1000),
                            "k3": f"user_{random.randint(1, 100)}",
                            "k4": {
                                "k5": random.randint(18, 65),
                                "k6": f"user{random.randint(1, 100)}@example.com",
                                "k7": {
                                    "k8": f"city_{random.randint(1, 100)}",
                                    "k9": "Sample Country"
                                }
                            }
                        },
                        "k10": datetime.now().isoformat()
                    }
                elif json_type == "array":
                    #JSON Array
                    array_length = random.randint(1, 10)
                    json_data = [{
                        "k1": i,
                        "k2": f"item_{i}",
                        "k3": random.uniform(1, 100)
                    } for i in range(array_length)]
                else:
                    #Mixed type JSON
                    json_data = {
                        "k1": random.randint(1, 1000),
                        "k2": f"mixed_{random.randint(1, 100)}",
                        "k3": [f"tag_{random.randint(1, 100)}" for _ in range(random.randint(1, 5))],
                        "k4": {
                            "k5": random.choice(["A", "B", "C"]),
                            "k6": [random.randint(1, 100) for _ in range(random.randint(1, 5))],
                            "k7": {
                                "k8": f"user_{random.randint(1, 100)}",
                                "k9": datetime.now().isoformat()
                            }
                        },
                        "k10": random.choice([True, False])
                    }
                
                #Convert JSON data to strings and add to results
                json_str = json.dumps(json_data, ensure_ascii=False)
                row_values.append(f"'{json_str}'")
            elif col.data_type in ["BLOB", "TINYBLOB", "MEDIUMBLOB", "LONGBLOB","BIT(8)"]:
                #Blob type: Generate binary data that meets the requirements of utf8mb4 (in hexadecimal)
                #utf8mb4 encoding rules:
                #1 byte: 0xxxxxxx
                #2 bytes: 110xxxxx 10xxxxxx
                #3 bytes: 1110xxxx 10xxxxxx 10xxxxxx
                #4 bytes: 11110xxx 10xxxxxx 10xxxxxx 10xxxxxx
                #To ensure compatibility, we generate a valid UTF-8 sequence of 1-3 bytes
                utf8_bytes = bytearray()
                total_bytes = random.randint(1, 50)  #Strictly limit the total number of bytes to 510 to ensure aggregate function requirements are met
                current_size = 0
                
                while current_size < total_bytes:
                    #Randomly select to generate 1-3 bytes of UTF-8 characters (covers most commonly used characters)
                    #Ensure that the total bytes limit is not exceeded
                    remaining_bytes = total_bytes - current_size
                    if remaining_bytes >= 3:
                        byte_length = random.choice([1, 2, 3])
                    elif remaining_bytes >= 2:
                        byte_length = random.choice([1, 2])
                    else:
                        byte_length = 1
                    
                    if byte_length == 1:
                        #1 byte character (ASCII): 0xxxxxxx
                        utf8_bytes.append(random.randint(0x00, 0x7F))
                        current_size += 1
                    elif byte_length == 2:
                        #2 byte characters: 110xxxxx 10xxxxxx
                        utf8_bytes.append(random.randint(0xC0, 0xDF))  # 110xxxxx
                        utf8_bytes.append(random.randint(0x80, 0xBF))  # 10xxxxxx
                        current_size += 2
                    elif byte_length == 3:
                        #3-byte characters: 1110xxxx 10xxxxxx 10xxxxxx
                        utf8_bytes.append(random.randint(0xE0, 0xEF))  # 1110xxxx
                        utf8_bytes.append(random.randint(0x80, 0xBF))  # 10xxxxxx
                        utf8_bytes.append(random.randint(0x80, 0xBF))  # 10xxxxxx
                        current_size += 3
                
                #Convert to hexadecimal string
                hex_data = utf8_bytes.hex().upper()
                row_values.append(f"X'{hex_data}'")
            else:
                #Defaults to null
                row_values.append("NULL")

        #Construct a single-line insert statement
        values_str = ", ".join(row_values)
        insert_sql = f"INSERT INTO {table.name} ({', '.join(columns)}) VALUES ({values_str});"
        insert_sqls.append(insert_sql)

    #Concatenate all insert statements
    return "\n".join(insert_sqls)
