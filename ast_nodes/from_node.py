"""Implements FROM/JOIN AST nodes and table alias mapping utilities."""

#FromNode class definition - from clause node
import random
from typing import List, Union, Dict, Set, Optional, Tuple
from .ast_node import ASTNode
from data_structures.node_type import NodeType
from data_structures.table import Table
from data_structures.db_dialect import get_current_dialect
from .subquery_node import SubqueryNode
from .comparison_node import ComparisonNode
from .column_reference_node import ColumnReferenceNode


class FromNode(ASTNode):
    """FROMClause Node，Handling table references and connections"""

    def __init__(self):
        super().__init__(NodeType.FROM)
        #Keep original list for backwards compatibility
        self.table_references: List[Union[Table, SubqueryNode]] = []
        self.aliases: List[str] = []
        self.joins: List[Dict] = []  #Connection information: {type, table, alias, condition}
        
        #Add dictionary for more reliable tables - alias mapping management
        self.alias_to_table: Dict[str, Union[Table, SubqueryNode]] = {}
        self.table_to_alias: Dict[int, str] = {}  #Use id as the key to avoid object comparison problems

    def add_table(self, table: Union[Table, SubqueryNode], alias: str) -> None:
        """Add table or subquery reference，Update all mapping structures at the same time"""
        self.table_references.append(table)
        self.aliases.append(alias)
        
        #Update new dictionary mapping
        self.alias_to_table[alias] = table
        self.table_to_alias[id(table)] = alias

    def add_join(self, join_type: str, table: Union[Table, SubqueryNode], alias: str, condition: ASTNode) -> None:
        """Add Connection，Update all mapping structures at the same time"""
        self.joins.append({
            'type': join_type,
            'table': table,
            'alias': alias,
            'condition': condition
        })
        self.table_references.append(table)
        self.aliases.append(alias)
        self.add_child(condition)
        
        #Update new dictionary mapping
        self.alias_to_table[alias] = table
        self.table_to_alias[id(table)] = alias

    def get_table_for_alias(self, alias: str) -> Optional[Union[Table, SubqueryNode]]:
        """Get a table or subquery by alias，Prefer dictionary mapping"""
        #Get priority from new dictionary mappings
        if alias in self.alias_to_table:
            return self.alias_to_table[alias]
        
        #Keep the original logic as a fallback
        try:
            index = self.aliases.index(alias)
            return self.table_references[index]
        except ValueError:
            return None

    def get_alias_for_table(self, table_or_name: Union[Table, SubqueryNode, str]) -> Optional[str]:
        """Get an alias from a table object or table name，Supports more input types and prefers dictionary mapping"""
        #If the input is a table object, use the new dictionary mapping first
        if isinstance(table_or_name, (Table, SubqueryNode)):
            table_id = id(table_or_name)
            if table_id in self.table_to_alias:
                return self.table_to_alias[table_id]
        
        #If the input is a string (table name or subquery alias)
        elif isinstance(table_or_name, str):
            #Traversal Dictionary Mapping Lookup Match
            for alias, table in self.alias_to_table.items():
                if isinstance(table, Table) and table.name == table_or_name:
                    return alias
                elif isinstance(table, SubqueryNode) and table.alias == table_or_name:
                    return alias
        
        #Keep the original logic as a fallback
        table_name = table_or_name if isinstance(table_or_name, str) else None
        if table_name:
            for i, ref in enumerate(self.table_references):
                if isinstance(ref, Table) and ref.name == table_name:
                    return self.aliases[i]
                elif isinstance(ref, SubqueryNode) and ref.alias == table_name:
                    return self.aliases[i]
        
        return None

    def get_all_aliases(self) -> Set[str]:
        """Get all table aliases"""
        return set(self.aliases)

    def get_table_alias_map(self) -> Dict[str, str]:
        """Get table name to alias mapping，Implementation with new dictionary mapping"""
        mapping = {}
        
        #Prioritize building results with new dictionary maps
        for alias, table in self.alias_to_table.items():
            if isinstance(table, Table):
                mapping[table.name] = alias
            elif isinstance(table, SubqueryNode):
                mapping[table.alias] = alias
        
        #If there is no data in the new mapping, use the old logic as a fallback
        if not mapping:
            for i, ref in enumerate(self.table_references):
                if isinstance(ref, Table):
                    mapping[ref.name] = self.aliases[i]
                elif isinstance(ref, SubqueryNode):
                    mapping[ref.alias] = self.aliases[i]
        
        return mapping

    def to_sql(self) -> str:
        if not self.table_references:
            return ""

        #Main Table
        parts = []
        first_table = self.table_references[0]
        first_alias = self.aliases[0]

        if isinstance(first_table, Table):
            table_sql = f"{first_table.name} AS {first_alias}"
            #Add index hint
            table_sql_with_hint = self._add_index_hint(table_sql, first_table)
            parts.append(table_sql_with_hint)
        else:
            parts.append(first_table.to_sql())

        #connecting part
        for join in self.joins:
            join_type = join['type'].upper()
            table = join['table']
            alias = join['alias']
            condition = join.get('condition')
            
            #Support for using clauses
            use_using = False
            if random.random() < 0.2 and isinstance(condition, ComparisonNode) and condition.operator == '=':
                #Check if it can be converted to using clause
                if len(condition.children) == 2 and all(isinstance(child, ColumnReferenceNode) for child in condition.children):
                    left_col = condition.children[0]
                    right_col = condition.children[1]
                    #Use the using clause only if the column names are the same and belong to different tables
                    if hasattr(left_col, 'column') and hasattr(right_col, 'column') and \
                       left_col.column.name == right_col.column.name and \
                       left_col.table_alias != right_col.table_alias:
                        use_using = True
                        using_col = left_col.column.name
            
            if isinstance(table, Table):
                table_sql = f"{table.name} AS {alias}"
                #Add index hint
                table_sql = self._add_index_hint(table_sql, table)
            else:
                table_sql = table.to_sql()
            
            if use_using:
                #Using the using clause
                parts.append(f"{join_type} JOIN {table_sql} USING ({using_col})")
            elif condition:
                #Standard ON condition
                condition_sql = condition.to_sql()
                
                #Check if the current dialect supports subqueries in the join condition
                dialect = get_current_dialect()
                if hasattr(dialect, 'supports_subqueries_in_join') and not dialect.supports_subqueries_in_join():
                    #Avoid generating ON conditions with subqueries if the dialect does not support subqueries in join
                    #Simple Check: Use a simple condition if the condition SQL contains a select statement (possibly a subquery)
                    if 'SELECT' in condition_sql.upper() or '(' in condition_sql and ')' in condition_sql:
                        #Use a simple condition alternative, such as 1 = 1 or table's primary key = primary key
                        #Here we use 1 = 1 as an alternative
                        parts.append(f"{join_type} JOIN {table_sql} ON 1=1")
                    else:
                        parts.append(f"{join_type} JOIN {table_sql} ON {condition_sql}")
                else:
                    #Dialect supports subqueries in join, normal generation
                    parts.append(f"{join_type} JOIN {table_sql} ON {condition_sql}")
            else:
                #No conditions (e.g. cross join)
                parts.append(f"{join_type} JOIN {table_sql}")

        return " ".join(parts)
        
    def add_outer_join(self, table: Union[Table, SubqueryNode], alias: str, condition: ASTNode) -> None:
        """Add external connection（LEFT/RIGHT/FULL）"""
        outer_join_type = random.choice(['LEFT OUTER', 'RIGHT OUTER', 'FULL OUTER'])
        self.add_join(outer_join_type, table, alias, condition)
        
    def add_cross_join(self, table: Union[Table, SubqueryNode], alias: str) -> None:
        """Add cross-connect"""
        self.joins.append({
            'type': 'CROSS',
            'table': table,
            'alias': alias,
            'condition': None
        })
        self.table_references.append(table)
        self.aliases.append(alias)

    def validate_table_references(self) -> Tuple[bool, List[str]]:
        """Verify that the table reference is valid"""
        errors = []
        #Here you can add table reference validation logic
        return (len(errors) == 0, errors)

    def _add_index_hint(self, table_sql: str, table: Table) -> str:
        """Add index hint to table
        
        Args:
            table_sql: SQL representation of the table
            table: Table Objects
            
        Returns:
            SQL after adding index hints
        """
        #No more indexing tips as needed
        return table_sql
    
    def repair_table_references(self) -> None:
        """Fix invalid table reference"""
        #Here you can add table reference repair logic
        pass

    def get_defined_aliases(self) -> Set[str]:
        """Get all defined aliases"""
        aliases = set(self.aliases)
        #Collect aliases from subqueries
        for ref in self.table_references:
            if isinstance(ref, SubqueryNode):
                aliases.update(ref.get_defined_aliases())
        return aliases