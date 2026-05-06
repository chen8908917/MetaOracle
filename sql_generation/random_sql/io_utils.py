"""File IO helpers for writing generated SQL and index artifacts."""

import os
from datetime import datetime
from typing import List

from data_structures.db_dialect import get_current_dialect

def generate_index_sqls(tables, dialect):
    """Generate index SQL statement for table，Includes enhanced joint indexing capabilities，and add the index information to the Table object
    
    Parameter
    - tables: List Tables
    - dialect: Database dialect
    
    Back
    - Index SQL Statement List
    """
    import random
    import re
    index_sqls = []
    
    def is_text_blob_type(data_type):
        """Check if the data type is text or blob"""
        data_type_lower = data_type.lower()
        #Base text/blob type
        if data_type_lower in ['text', 'longtext', 'mediumtext', 'blob', 'longblob', 'mediumblob']:
            return True
        #Check for 'text' or 'blob' keywords (processing variants)
        if 'text' in data_type_lower or 'blob' in data_type_lower:
            return True
        return False
    
    def get_varchar_length(data_type):
        """Extract length from varchar type definition"""
        match = re.search(r'varchar\((\d+)\)', data_type.lower())
        if match:
            return int(match.group(1))
        return 255  #Default Length
    
    def get_column_with_key_length(col_name, data_type):
        """Add the appropriate key length for columns of type text/blob and long varchar，Avoid exceeding the 255-byte limit"""
        data_type_lower = data_type.lower()
        
        #Processing text/blob types
        if is_text_blob_type(data_type):
            #Add a key length for the text type, use a smaller value to avoid exceeding the limit
            return f"{col_name}(50)"
        #Processing long varchar type
        elif 'varchar' in data_type_lower:
            length = get_varchar_length(data_type)
            #Add key length limit for varchar columns longer than 100
            if length > 100:
                #Using a smaller key length, consider the UTF8mb4 character set (up to 4 bytes per character)
                #Ensure the key length does not exceed the 255-byte limit
                key_length = min(63, length)  #63 * 4 = 252 bytes, stay within limits
                return f"{col_name}({key_length})"
        return col_name
    
    #Generate indexes for each table
    for table in tables:
        #Initialize index list
        if table.indexes is None:
            table.indexes = []
            
        #First create a unique index for the primary key
        if table.primary_key:
            #Get the information of the primary key column, check if it is text/blob type
            pk_col = next((col for col in table.columns if col.name == table.primary_key), None)
            pk_col_with_length = table.primary_key
            if pk_col and is_text_blob_type(pk_col.data_type):
                #The primary key should not be of type text/blob, but for robustness we deal with this case
                pk_col_with_length = f"{table.primary_key}(100)"
                
            index_name = f"idx_{table.name}_pk"
            pk_index_sql = dialect.get_create_index_sql(
                table_name=table.name,
                index_name=index_name,
                columns=[pk_col_with_length],
                is_unique=True
            )
            index_sqls.append(pk_index_sql)
            #Add to index information of table objects
            table.add_index(index_name, [table.primary_key], is_primary=True)
        
        #Now we divide all non-primary key columns into two categories:
        #1. direct index column - not text/blob type
        #2. Columns that require key length - text type (blob still excluded)
        direct_index_columns = []
        text_index_columns = []
        
        for col in table.columns:
            if col.name == table.primary_key:
                continue
                
            if is_text_blob_type(col.data_type):
                #Only text types (excluding blob types) are allowed to create indexes
                if 'text' in col.data_type.lower() and 'blob' not in col.data_type.lower():
                    text_index_columns.append(col)
            else:
                direct_index_columns.append(col)
        
        #Merge all available index columns
        all_index_columns = direct_index_columns + text_index_columns
        
        #Handle only if there are non-primary key columns suitable for indexing
        if all_index_columns:
            #Generate 1-2 single-column indexes for each table
            num_single_indexes = random.randint(1, min(2, len(all_index_columns)))
            
            #Select columns to create single-column indexes
            columns_to_index = random.sample(all_index_columns, num_single_indexes)
            
            #Create a general index for the selected columns
            for col in columns_to_index:
                index_name = f"idx_{table.name}_{col.name}"
                #Get column names with key length (if needed)
                col_with_length = get_column_with_key_length(col.name, col.data_type)
                index_sql = dialect.get_create_index_sql(
                    table_name=table.name,
                    index_name=index_name,
                    columns=[col_with_length],
                    is_unique=False
                )
                index_sqls.append(index_sql)
                #Added to the index information of the table object (stores the original column name, does not contain the key length)
                table.add_index(index_name, [col.name])
            
            #Enhanced joint index generation logic
            if len(all_index_columns) >= 2:
                #Ensure that the probability of generating at least one federated index increases to 80%
                if random.random() < 0.8:
                    #Select 2-3 columns to create a joint index
                    num_cols = random.randint(2, min(3, len(all_index_columns)))
                    composite_cols = random.sample(all_index_columns, num_cols)
                    
                    #Get list of column names with key length
                    col_names_with_length = [get_column_with_key_length(col.name, col.data_type) for col in composite_cols]
                    #Store original column names for indexing information
                    original_col_names = [col.name for col in composite_cols]
                    
                    index_name = f"idx_{table.name}_{'_'.join(original_col_names)}"
                    index_sql = dialect.get_create_index_sql(
                        table_name=table.name,
                        index_name=index_name,
                        columns=col_names_with_length,
                        is_unique=False
                    )
                    index_sqls.append(index_sql)
                    #Add to index information of table object (store original column name)
                    table.add_index(index_name, original_col_names)
                
                #If there are enough columns, a second different joint index may be generated
                if len(all_index_columns) >= 4 and random.random() < 0.5:
                    #Ensure different column combinations are selected
                    remaining_cols = [col for col in all_index_columns if col not in columns_to_index[:2]]
                    if len(remaining_cols) >= 2:
                        num_cols = random.randint(2, min(3, len(remaining_cols)))
                        composite_cols = random.sample(remaining_cols, num_cols)
                        
                        #Get list of column names with key length
                        col_names_with_length = [get_column_with_key_length(col.name, col.data_type) for col in composite_cols]
                        #Store original column names for indexing information
                        original_col_names = [col.name for col in composite_cols]
                        
                        index_name = f"idx_{table.name}_{'_'.join(original_col_names)}"
                        index_sql = dialect.get_create_index_sql(
                            table_name=table.name,
                            index_name=index_name,
                            columns=col_names_with_length,
                            is_unique=False
                        )
                        index_sqls.append(index_sql)
                        #Add to index information of table object (store original column name)
                        table.add_index(index_name, original_col_names)
                
                #Generate a union index that may contain a primary key (only if the table has a primary key)
                if table.primary_key and len(all_index_columns) >= 1 and random.random() < 0.3:
                    #Select 1-2 non-primary key columns to combine with the primary key
                    num_cols = random.randint(1, min(2, len(all_index_columns)))
                    composite_cols = random.sample(all_index_columns, num_cols)
                    
                    #Gets the primary key column name with key length (if needed)
                    pk_col = next((col for col in table.columns if col.name == table.primary_key), None)
                    pk_with_length = table.primary_key
                    if pk_col and is_text_blob_type(pk_col.data_type):
                        pk_with_length = f"{table.primary_key}(100)"
                    
                    #Get a list of non-primary key column names with key length
                    non_pk_cols_with_length = [get_column_with_key_length(col.name, col.data_type) for col in composite_cols]
                    #Portfolio Columns (Primary key is usually placed first)
                    col_names_with_length = [pk_with_length] + non_pk_cols_with_length
                    #Store original column names for indexing information
                    original_col_names = [table.primary_key] + [col.name for col in composite_cols]
                    
                    index_name = f"idx_{table.name}_pk_{'_'.join([col.name for col in composite_cols])}"
                    index_sql = dialect.get_create_index_sql(
                        table_name=table.name,
                        index_name=index_name,
                        columns=col_names_with_length,
                        is_unique=True  #The index containing the primary key is naturally unique
                    )
                    index_sqls.append(index_sql)
                    #Add to index information of table object (store original column name)
                    table.add_index(index_name, original_col_names)
    
    return index_sqls


def save_sql_to_file(
    sql: str,
    output_dir: str = "generated_sql",
    file_type: str = "all",
    mode: str = "w",
    database_name: str = "test",
) -> str:
    """Save the generated SQL to a file
    
    Parameter
    - sql: SQLstatement?
    - output_dir: Output Directory
    - file_type: Type of document"schema", "query", or "all")
    - mode: Writing Mode"w"Show overrides，"a"Indicates append)
    """
    #Create Output Directory
    os.makedirs(output_dir, exist_ok=True)

    #Generate filename from file type
    if file_type == "schema":
        filename = "schema.sql"
    elif file_type == "query":
        filename = "queries.sql"
    else:
        filename = "seedquery.sql"
    
    filepath = os.path.join(output_dir, filename)

    #Get the current database dialect
    from data_structures.db_dialect import get_current_dialect
    dialect = get_current_dialect()

    #Write to Files
    with open(filepath, mode, encoding="utf-8") as f:
        if mode == "w":  #Write database settings only in overlay mode
            if file_type == "schema":
                #Generate database operation statements using dialect methods
                drop_db_sql = dialect.get_drop_database_sql(database_name)
                create_db_sql = dialect.get_create_database_sql(database_name)
                f.write(drop_db_sql)
                if drop_db_sql and not drop_db_sql.endswith("\n"):
                    f.write("\n")
                f.write(create_db_sql)
                if create_db_sql and not create_db_sql.endswith("\n"):
                    f.write("\n")
            
            #Generate statements using databases using dialect methods
            use_db_sql = dialect.get_use_database_sql(database_name)
            set_session_sql = dialect.get_session_settings_sql()
            if set_session_sql:
                f.write(set_session_sql)
                if not set_session_sql.endswith("\n"):
                    f.write("\n")
            if use_db_sql:
                f.write(use_db_sql)
                if not use_db_sql.endswith("\n"):
                    f.write("\n")
            else:
                #If there is no use statement (such as PostgreSQL), add a comment explaining how to connect
                f.write("-- PostgreSQLThere are no use statements in，Connection database specified by connection parameters\n")
        f.write(sql)

    return filepath


from typing import Optional, Dict
# ------------------------------
#The main function.
# ------------------------------
