import os
import sqlglot
import json
from get_seedQuery import SeedQueryGenerator
from data_structures.db_dialect import get_current_dialect


def _get_sqlglot_dialect_name() -> str:
    dialect = get_current_dialect()
    if dialect and dialect.name.upper() == "POSTGRESQL":
        return "postgres"
    return "mysql"

class Change:
    def __init__(self,file_path="./generated_sql/seedQuery.sql"):
        self.file_path=file_path
        self.seedqueries=self.get_queries()

    def get_queries(self):
        
                """Docstring."""
        queries = []
        try:
            #
            abs_path = os.path.abspath(self.file_path)

            with open(abs_path, 'r', encoding='utf-8') as f:
                #
                for line_num, line in enumerate(f, 1):  #
                    #
                    sql = line.strip()
                    #
                    if sql:
                        queries.append(sql)
            return queries
        except Exception as e:
            print(f"读取SQL文件时出错: {e}")
            return []

    def getAST(self,query):
        try:
            ast = sqlglot.parse_one(query, read=_get_sqlglot_dialect_name())
            print(ast)
            #
            return ast
        except Exception as e:
            print(f"解析查询失败: {e}")
            return None
    def ASTChange(self,query):
        ast=self.getAST(query)
        return ast
       


