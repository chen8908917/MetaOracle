"""Implements UNION/INTERSECT/EXCEPT AST nodes and combined query handling."""

#SetOperationNode Class Definition - Collection Operations Node
from typing import List, Set
from .ast_node import ASTNode
from data_structures.node_type import NodeType

class SetOperationNode(ASTNode):
    """Collections Operations Node（UNION/UNION ALL/INTERSECT/EXCEPT）"""

    def __init__(self, operation_type: str):
        super().__init__(NodeType.SET_OPERATION)
        self.operation_type = operation_type  # 'UNION', 'UNION ALL', 'INTERSECT', 'EXCEPT'
        self.queries: List['SelectNode'] = []  #Participate in select queries for collection operations

    def add_query(self, select_node: 'SelectNode') -> None:
        """Add a select query that participates in a collection operation"""
        self.queries.append(select_node)
        self.add_child(select_node)

    def to_sql(self) -> str:
        """Convert to SQL String"""
        if not self.queries or len(self.queries) < 2:
            return ""  #At least two queries are required
        
        #Get the current database dialect
        from data_structures.db_dialect import get_current_dialect
        current_dialect = get_current_dialect()
        #print(f"#{current_dialect.__class__.__name__}")
        is_polardb = current_dialect.__class__.__name__ == 'PolarDBDialect'
        #Check if it is a Percona dialect
        is_percona = 'percona' in current_dialect.name.lower() or (hasattr(current_dialect, '__class__') and 'percona' in current_dialect.__class__.__name__.lower())
        
        #Ensure every query is a valid SQL statement
        query_sqls = []
        for query in self.queries:
            sql = query.to_sql()
            #Remove extra spaces or line breaks that may cause issues
            sql = sql.strip()
            #Ensure each query is not an empty string
            if sql:
                #Checks if the query contains an order BY or limit clause, enclosed in parentheses if any
                #For PolarDB, the left query (first query) is not wrapped in parentheses
                if not is_polardb:
                    if ('ORDER BY' in sql.upper() or 'LIMIT' in sql.upper()) and not is_polardb:
                        #Make sure the query is not enclosed in parentheses
                        if not (sql.startswith('(') and sql.endswith(')')):
                            sql = f"({sql})"
                query_sqls.append(sql)
        
        #Returns an empty string if there is no valid query
        if len(query_sqls) < 2:
            return ""
        
        #Special handling for Percona dialects: intersect and except operators are not supported in Percona 5.7
        if is_percona:
            if self.operation_type in ['INTERSECT', 'EXCEPT']:
                #Convert intersect and except to Union all in Percona
                #Note: This is not a semantic equivalence conversion, but can avoid grammatical errors
                #More sophisticated conversion strategies may be required in real-world applications
                return " UNION ALL ".join(query_sqls).strip()
            elif self.operation_type == "UNION":
                #Percona supports Union but we use Union all uniformly to avoid potential issues
                return " UNION ALL ".join(query_sqls).strip()
            else:
                #For Union all, leave as is
                return " UNION ALL ".join(query_sqls).strip()
        else:
            #Normal handling of non-Percona dialects
            if self.operation_type == "UNION ALL":
                #Make sure that there is only one space before and after the operator, and that there are no extra spaces or line breaks
                return " UNION ALL ".join(query_sqls).strip()
            else:
                #Process additional operators
                return f" {self.operation_type} ".join(query_sqls).strip()

    def contains_window_function(self) -> bool:
        """Check to include window functions"""
        for query in self.queries:
            if query.contains_window_function():
                return True
        return False

    def contains_aggregate_function(self) -> bool:
        """Check for the inclusion of aggregate functions"""
        for query in self.queries:
            if query.contains_aggregate_function():
                return True
        return False

    def get_referenced_columns(self) -> Set[str]:
        """Get all referenced columns"""
        columns = set()
        for query in self.queries:
            columns.update(query.get_referenced_columns())
        return columns