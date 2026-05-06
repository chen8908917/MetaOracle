"""Sample schema/function factories used to bootstrap generation state."""

from typing import List

from data_structures.column import Column
from data_structures.function import Function
from data_structures.table import Table
from data_structures.db_dialect import get_current_dialect


def create_sample_tables() -> List[Table]:
    """Create sample table definitions."""
    t1 = Table(
        name="t1",
        columns=[
            Column("c1", "INT", "numeric", False, "t1"),
            Column("c2", "VARCHAR(255)", "string", False, "t1"),
            Column("c3", "VARCHAR(255)", "string", False, "t1"),
            Column("c4", "INT", "numeric", False, "t1"),
            Column("c5", "DATE", "datetime", False, "t1"),
            Column("c6", "VARCHAR(10)", "string", False, "t1"),
        ],
        primary_key="c1",
        foreign_keys=[],
    )

    t2 = Table(
        name="t2",
        columns=[
            Column("c1", "INT", "numeric", False, "t2"),
            Column("c2", "INT", "numeric", False, "t2"),
            Column("c3", "DECIMAL(10,2)", "numeric", False, "t2"),
            Column("c4", "VARCHAR(50)", "string", False, "t2"),
            Column("c5", "DATE", "datetime", False, "t2"),
            Column("c6", "MEDIUMTEXT", "string", False, "t2"),
            Column("c7", "LONGTEXT", "string", False, "t2"),
            Column("c8", "MEDIUMBLOB", "binary", False, "t2"),
            Column("c9", "LONGBLOB", "binary", False, "t2"),
            Column("c10", "ENUM('value1','value2','value3')", "string", False, "t2"),
            Column("c11", "SET('a','b','c','d')", "string", False, "t2"),
            Column("c12", "BIT(8)", "binary", False, "t2"),
            Column("c13", "DATETIME", "datetime", False, "t2"),
            Column("c14", "FLOAT(8,2)", "numeric", False, "t2"),
            Column("c15", "DOUBLE(12,4)", "numeric", False, "t2"),
            Column("c16", "JSON", "json", False, "t2"),
        ],
        primary_key="c1",
        foreign_keys=[{"column": "c2", "ref_table": "t1", "ref_column": "c1"}],
    )

    t3 = Table(
        name="t3",
        columns=[
            Column("c1", "INT", "numeric", False, "t3"),
            Column("c2", "INT", "numeric", False, "t3"),
            Column("c3", "INT", "numeric", False, "t3"),
            Column("c4", "YEAR", "numeric", False, "t3"),
            Column("c5", "DATETIME", "datetime", False, "t3"),
            Column("c6", "TINYINT", "numeric", False, "t3"),
            Column("c7", "SMALLINT", "numeric", False, "t3"),
            Column("c8", "MEDIUMINT", "numeric", False, "t3"),
            Column("c9", "BIGINT", "numeric", False, "t3"),
            Column("c10", "LONGTEXT", "string", False, "t3"),
            Column(
                "c11",
                "VARBINARY(255)",
                "binary",
                False,
                "t3",
            ),
            Column("c12", "TINYTEXT", "string", False, "t3"),
            Column("c13", "TINYBLOB", "binary", False, "t3"),
            Column("c14", "SET('x','y','z')", "string", False, "t3"),
            Column("c15", "TINYINT(1)", "numeric", False, "t3"),
        ],
        primary_key="c1",
        foreign_keys=[
            {"column": "c2", "ref_table": "t1", "ref_column": "c1"},
            {"column": "c3", "ref_table": "t2", "ref_column": "c1"},
        ],
    )

    return [t1, t2, t3]


def create_sample_functions() -> List[Function]:
    """Create a list of sample functions，Based on MySQL 8.4Aggregate Function Specification"""
    #Get the current database dialect
    from data_structures.db_dialect import DBDialectFactory
    current_dialect = DBDialectFactory.get_current_dialect()
    
    #Set the maximum number of parameters for the lag and lead functions according to the dialect
    lag_max_params = 3
    lead_max_params = 3
    if current_dialect.name == "MARIADB":
        lag_max_params = 2
        lead_max_params = 2
    
    functions = [
        #Aggregate functions - based on official MySQL 8.4 documentation
        #Basic Aggregation Functions
        Function("COUNT", 1, 1, ["any"], "INT", "aggregate"),
        Function("COUNT_DISTINCT", 1, 1, ["any"], "INT", "aggregate"),
        #Sum return type: return decimal for exact value parameter, return double for approximate value parameter
        Function("SUM", 1, 1, ["numeric"], "numeric", "aggregate"),
        Function("SUM_DISTINCT", 1, 1, ["numeric"], "numeric", "aggregate"),
        #AVG return type: return decimal for exact value parameter, return double for approximate value parameter
        Function("AVG", 1, 1, ["numeric"], "numeric", "aggregate"),
        #Max/min accepts various types of parameters
        Function("MAX", 1, 1, ["any"], "any", "aggregate"),
        Function("MIN", 1, 1, ["any"], "any", "aggregate"),
        
        #Bit-operation aggregate function - supports binary strings and numeric types
        Function("BIT_AND", 1, 1, ["numeric"], "numeric", "aggregate"),
        Function("BIT_OR", 1, 1, ["numeric"], "numeric", "aggregate"),
        Function("BIT_XOR", 1, 1, ["numeric"], "numeric", "aggregate"),
        
        #String aggregation function - group_concat supports multiple parameters and various types
        Function("GROUP_CONCAT", 1, None, ["any"], "string", "aggregate"),
        
        #Statistical Analysis Aggregation Function - Logarithmic Value Parameter Returns double Value
        Function("STD", 1, 1, ["numeric"], "DOUBLE", "aggregate"),
        Function("STDDEV", 1, 1, ["numeric"], "DOUBLE", "aggregate"),
        Function("STDDEV_POP", 1, 1, ["numeric"], "DOUBLE", "aggregate"),
        Function("STDDEV_SAMP", 1, 1, ["numeric"], "DOUBLE", "aggregate"),
        Function("VARIANCE", 1, 1, ["numeric"], "DOUBLE", "aggregate"),
        #Function("VAR_POP", 1, 1, ["numeric"], "DOUBLE", "aggregate"),
        Function("VAR_SAMP", 1, 1, ["numeric"], "DOUBLE", "aggregate"),
        
        #Window Functions
        #Function("FIRST_VALUE", 1, 1, ["any"], "any", "window"),
        #Function("LAST_VALUE", 1, 1, ["any"], "any", "window"),

        #Scalar function
        #String function
        Function("CONCAT", 2, None, ["string", "string"], "string", "scalar"),
        Function("CONCAT_WS", 2, None, ["string", "string"], "string", "scalar"),
        Function("SUBSTRING", 2, 3, ["string", "numeric"], "string", "scalar"),
        Function("SUBSTRING_INDEX", 3, 3, ["string", "string", "numeric"], "string", "scalar"),
        Function("LEFT", 2, 2, ["string", "numeric"], "string", "scalar"),
        Function("RIGHT", 2, 2, ["string", "numeric"], "string", "scalar"),
        Function("TRIM", 1, 3, ["string"], "string", "scalar"),
        Function("LTRIM", 1, 1, ["string"], "string", "scalar"),
        Function("RTRIM", 1, 1, ["string"], "string", "scalar"),
        Function("LOWER", 1, 1, ["string"], "string", "scalar"),
        Function("UPPER", 1, 1, ["string"], "string", "scalar"),
        Function("LENGTH", 1, 1, ["string"], "INT", "scalar"),
        Function("CHAR_LENGTH", 1, 1, ["string"], "INT", "scalar"),
        Function("REPLACE", 3, 3, ["string", "string", "string"], "string", "scalar"),
        Function("REPEAT", 2, 2, ["string", "numeric"], "string", "scalar"),
        Function("REVERSE", 1, 1, ["string"], "string", "scalar"),
        #Function("SPLIT_STR", 3, 3, ["string", "string", "numeric"], "string", "scalar"),
        
        #Math function
        Function("ABS", 1, 1, ["numeric"], "numeric", "scalar"),
        Function("ROUND", 1, 2, ["numeric"], "numeric", "scalar"),
        Function("CEIL", 1, 1, ["numeric"], "numeric", "scalar"),
        Function("CEILING", 1, 1, ["numeric"], "numeric", "scalar"),
        Function("FLOOR", 1, 1, ["numeric"], "numeric", "scalar"),
        Function("DEGREES", 1, 1, ["numeric"], "numeric", "scalar"),
        Function("MOD", 2, 2, ["numeric", "numeric"], "numeric", "scalar"),
        Function("DIV", 2, 2, ["numeric", "numeric"], "INT", "scalar"),
        Function("POWER", 2, 2, ["numeric", "numeric"], "DOUBLE", "scalar"),
        Function("SQRT", 1, 1, ["numeric"], "DOUBLE", "scalar"),
        Function("LOG", 1, 2, ["numeric"], "DOUBLE", "scalar"),
        Function("LOG10", 1, 1, ["numeric"], "DOUBLE", "scalar"),
        Function("LN", 1, 1, ["numeric"], "DOUBLE", "scalar"),
        Function("EXP", 1, 1, ["numeric"], "DOUBLE", "scalar"),
        Function("PI", 0, 0, [], "DOUBLE", "scalar"),
        
        # 
        Function("SIN", 1, 1, ["numeric"], "numeric", "scalar"),
        Function("COS", 1, 1, ["numeric"], "numeric", "scalar"),
        Function("TAN", 1, 1, ["numeric"], "numeric", "scalar"),
        Function("ASIN", 1, 1, ["numeric"], "numeric", "scalar"),
        Function("ACOS", 1, 1, ["numeric"], "numeric", "scalar"),
        Function("ATAN", 1, 2, ["numeric"], "numeric", "scalar"),
        Function("ATAN2", 2, 2, ["numeric", "numeric"], "numeric", "scalar"),
        
        #Time date function (keep deterministic function only)
        Function("YEAR", 1, 1, ["datetime"], "INT", "scalar"),
        Function("MONTH", 1, 1, ["datetime"], "INT", "scalar"),
        Function("DAY", 1, 1, ["datetime"], "INT", "scalar"),
        Function("DAYNAME", 1, 1, ["datetime"], "string", "scalar"),
        Function("DAYOFMONTH", 1, 1, ["datetime"], "INT", "scalar"),
        Function("DAYOFWEEK", 1, 1, ["datetime"], "INT", "scalar"),
        Function("DAYOFYEAR", 1, 1, ["datetime"], "INT", "scalar"),
        Function("HOUR", 1, 1, ["datetime"], "INT", "scalar"),
        Function("MINUTE", 1, 1, ["datetime"], "INT", "scalar"),
        Function("SECOND", 1, 1, ["datetime"], "INT", "scalar"),
        Function("DATE", 1, 1, ["datetime"], "date", "scalar"),
        Function("TIME", 1, 1, ["datetime"], "time", "scalar"),
        #Function("DATETIME", 1, 1, ["numeric"], "datetime", "scalar"),
        Function("DATE_ADD", 3, 3, ["datetime", "string", "numeric"], "datetime", "scalar"),
        Function("DATE_SUB", 3, 3, ["datetime", "string", "numeric"], "datetime", "scalar"),
        Function("ADDDATE", 2, 3, ["datetime", "numeric"], "datetime", "scalar"),
        Function("SUBDATE", 2, 3, ["datetime", "numeric"], "datetime", "scalar"),
        Function("DATEDIFF", 2, 2, ["date", "date"], "INT", "scalar"),
        Function("TIMEDIFF", 2, 2, ["datetime", "datetime"], "time", "scalar"),
        Function("TIMESTAMPDIFF", 3, 3, ["string", "datetime", "datetime"], "INT", "scalar"),
        Function("DATE_FORMAT", 2, 2, ["datetime", "string"], "string", "scalar", format_string_required=True),
        Function("STR_TO_DATE", 2, 2, ["string", "string"], "datetime", "scalar", format_string_required=True),
        
        #Type conversion function
        Function("CAST", 2, 2, ["any", "string"], "any", "scalar"),
        Function("CONVERT", 2, 2, ["any", "string"], "any", "scalar"),
        
        #Conditional Functions
        Function("IF", 3, 3, ["any", "any", "any"], "any", "scalar"),
        Function("IFNULL", 2, 2, ["any", "any"], "string", "scalar"),
        Function("NULLIF", 2, 2, ["any", "any"], "string", "scalar"),
        
        #JSON function
        Function("JSON_ARRAY", 0, None, [], "json", "scalar"),
        Function("JSON_OBJECT", 2, 2, ["string", "any"], "json", "scalar"),
        Function("JSON_EXTRACT", 2, None, ["json", "string"], "json", "scalar"),
        Function("JSON_VALUE", 2, 2, ["json", "string"], "any", "scalar"),
        Function("JSON_SET", 3, None, ["json", "string", "any"], "json", "scalar"),
        Function("JSON_INSERT", 3, None, ["json", "string", "any"], "json", "scalar"),
        Function("JSON_REPLACE", 3, None, ["json", "string", "any"], "json", "scalar"),
        Function("JSON_REMOVE", 2, None, ["json", "string"], "json", "scalar"),
        
        #System functions (only deterministic functions are retained)
        Function("DATABASE", 0, 0, [], "string", "scalar"),
        Function("SCHEMA", 0, 0, [], "string", "scalar"),
        Function("VERSION", 0, 0, [], "string", "scalar"),
        
        #Other scalar functions
        Function("MD5", 1, 1, ["string"], "string", "scalar"),
        Function("SHA1", 1, 1, ["string"], "string", "scalar"),
        Function("SHA2", 2, 2, ["string", "numeric"], "string", "scalar"),
        
        #Window Functions
        Function("ROW_NUMBER", 0, 0, [], "INT", "window"),
        Function("RANK", 0, 0, [], "INT", "window"),
        Function("DENSE_RANK", 0, 0, [], "INT", "window"),
        Function("NTILE", 1, 1, ["numeric"], "INT", "window"),
        Function("CUME_DIST", 0, 0, [], "DOUBLE", "window"),
        Function("PERCENT_RANK", 0, 0, [], "DOUBLE", "window"),
        Function("LAG", 1, lag_max_params, ["any"], "any", "window"),
        Function("LEAD", 1, lead_max_params, ["any", "numeric", "any"], "any", "window"),
        Function("NTH_VALUE", 2, 2, ["any", "numeric"], "any", "window"),
        Function("FIRST_VALUE", 1, 1, ["any"], "any", "window"),
        Function("LAST_VALUE", 1, 1, ["any"], "any", "window"),
        
    ]
    unsupported_functions_by_dialect = {
        "POLARDB": {"JSON_VALUE"},
        "TIDB": {"JSON_VALUE"},
    }
    dialect_name = current_dialect.name.upper()
    functions = [
        f for f in functions
        if not (f.name.upper().startswith("ST_") or f.name.upper() == "POINT")
    ]
    unsupported_functions = unsupported_functions_by_dialect.get(dialect_name, set())
    if unsupported_functions:
        functions = [f for f in functions if f.name not in unsupported_functions]
    return functions
