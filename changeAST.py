import os
import sqlglot
from generateAST import Change
from data_structures.db_dialect import get_current_dialect


def _get_sqlglot_dialect_name() -> str:
    """Map current dialect to sqlglot dialect name."""
    dialect = get_current_dialect()
    if dialect and dialect.name.upper() == "POSTGRESQL":
        return "postgres"
    return "mysql"



class PreSolve:
    def __init__(self, file_path="./generated_sql/seedQuery.sql", extension=False, db_config=None):
        self.change = Change()
        self.file_path = file_path
        # extension is kept for backward-compatible callers. The mutation framework has been removed.
        self.extension = extension
        self.db_config = db_config
        #
        dialect = get_current_dialect()
        self.db_type = dialect.name if dialect else 'UNKNOWN'
        #

    def seed_query_iterator(self):
                """Docstring."""
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
            print(f"读取种子查询文件时出错: {e}")

    def preprocess_sql(self, query: str) -> str:
        """Parse and preprocess one DQL statement, returning normalized SQL."""
        ast = self.change.ASTChange(query)
        if ast is None:
            raise ValueError("SQL解析失败")
        preprocessed_ast = self.detailsolve(ast)
        return preprocessed_ast.sql(
            dialect=_get_sqlglot_dialect_name(),
            normalize=False,
            normalize_functions=False,
        )

    def presolve(self, batch_size=100, max_queries=None):
                """Docstring."""
        #
        processed_count = 0
        batch_count = 0
        
        #
        for query in self.seed_query_iterator():
            #
            if max_queries is not None and processed_count >= max_queries:
                break
            print(query)
            try:
                #
                processed_count += 1
                if processed_count % 50 == 0:
                    print(f"已处理 {processed_count} 个种子查询")
                
                preprocessed_sql = self.preprocess_sql(query)
                print(f"=====原始SQL:{query}======")
                print(f"=====预处理后SQL:{preprocessed_sql}======")

                #
                if processed_count % batch_size == 0:
                    batch_count += 1
                    print(f"已完成第 {batch_count} 批处理，释放部分内存...")
                    #
                    del preprocessed_sql
                    #
                    if 'change_ast' in locals():
                        del change_ast
                    if 'mutable_nodes' in locals():
                        del mutable_nodes
                    
            except Exception as e:
                print(f"处理查询时出错: {str(e)}")
                #
                continue
        
        print(f"\n预处理完成！总共处理了 {processed_count} 个种子查询")
            
    def _is_aggregate_function(self, node):
                """Docstring."""regate_functions = [
            'Avg', 'Count', 'Max', 'Min', 'Sum',
            'GroupConcat',
            'Std', 'Stddev', 'StddevPop', 'StddevSamp',
            'Variance', 'VariancePop', 'VarPop', 'VarSamp', 'StdDevPop', 'StdDevSamp',
            'BitAnd', 'BitOr', 'BitXor','Exp',
            
        ]

        #
        if hasattr(node, '__class__'):
            class_name = node.__class__.__name__
            
            #
            if class_name in aggregate_functions:
                return True
            
            #
            if class_name == 'Anonymous':
                #
                if hasattr(node, 'name') and node.name is not None:
                    func_name = node.name.upper()
                    if func_name in [
                        'STD', 'STDDEV', 'VAR', 'VARIANCE', 'BIT_AND', 'BIT_OR', 'BIT_XOR',
                        'AVG', 'COUNT', 'MAX', 'MIN', 'SUM', 'GROUP_CONCAT','EXP',
                    ]:
                        return True
                elif hasattr(node, 'this') and isinstance(node.this, str):
                    #
                    func_name = node.this.upper()
                    if func_name in [
                        'STD', 'STDDEV', 'VAR', 'VARIANCE', 'BIT_AND', 'BIT_OR', 'BIT_XOR',
                        'AVG', 'COUNT', 'MAX', 'MIN', 'SUM', 'GROUP_CONCAT','EXP',
                    ]:
                        return True
        
        return False
    
    def detailsolve(self, ast):
                """Docstring."""
        print(f"=== 原始AST ===")
        print(ast.__class__.__name__)
        print(ast)
        try:
            #
            select_nodes = []
            for node in ast.walk():
                if isinstance(node, sqlglot.expressions.Select):
                    select_nodes.append(node)
            
            print(f"找到 {len(select_nodes)} 个SELECT节点")
            
            #
            for i, select_node in enumerate(select_nodes):
                print(f"处理SELECT节点 {i+1}/{len(select_nodes)}")
                self._process_select_node(select_node)
        except Exception as e:
            print(f"预处理AST时出错: {str(e)}")
        
        return ast
      

    def _process_select_node(self, ast):
                """Docstring."""nt(f"=== 处理SELECT节点 ===")
        print(ast)
        
        #
        for i, expr in enumerate(ast.expressions):
            #
            if isinstance(expr, sqlglot.expressions.Alias) and isinstance(expr.this, sqlglot.expressions.Window):
                print(f"检测到窗口函数: {expr}")
                #
                new_expr = sqlglot.expressions.Alias(
                    this=sqlglot.expressions.Literal(this=1, is_string=False),
                    alias=expr.alias
                )
                ast.expressions[i].replace(new_expr)
                print(f"已替换为: {new_expr}")
            #
            elif isinstance(expr, sqlglot.expressions.Alias) and self._is_aggregate_function(expr.this):
                print(f"检测到聚合函数: {expr}")
                agg_func = expr.this
                print(agg_func.args)
                print(agg_func.__class__.__name__)
                
                #
                args = []
                if agg_func.__class__.__name__ == 'GroupConcat':
                    args.append(agg_func.this.this)
                    print(args)
                elif agg_func.__class__.__name__ != 'Anonymous' and hasattr(agg_func, 'args') and 'this' in agg_func.args:
                    args = agg_func.args['this'] if isinstance(agg_func.args['this'], list) else [agg_func.args['this']]
                elif agg_func.__class__.__name__ =='Anonymous':
                    args = agg_func.expressions
                #
                has_distinct = False
                
                #
                if hasattr(agg_func, 'this') and hasattr(agg_func.this, '__class__') and agg_func.this.__class__.__name__ == 'Distinct':
                    has_distinct = True
                    print(f"聚合函数包含DISTINCT关键字")
                    #
                    if hasattr(agg_func.this, 'expressions') and agg_func.this.expressions:
                        args = agg_func.this.expressions
                
                #
                if args:
                    #
                    new_expr = sqlglot.expressions.Alias(
                        this=args[0],
                        alias=expr.alias
                    )
                    ast.expressions[i].replace(new_expr)
                    print(f"已将聚合函数替换为其参数: {new_expr}")
                else:
                    print("聚合函数没有参数，跳过替换")
            elif isinstance(expr, sqlglot.expressions.Alias) and isinstance(expr.this, sqlglot.expressions.Subquery):
                new_expr = sqlglot.expressions.Alias(
                    this=sqlglot.expressions.Literal(this=1, is_string=False),
                    alias=expr.alias
                )
                ast.expressions[i].replace(new_expr)
                print(f"已将子查询替换为整数值1: {new_expr}")

        #
        #
        if hasattr(ast, 'args') and 'limit' in ast.args and ast.args['limit']:
            limit_clause = ast.args['limit']
            print(f"检测到LIMIT子句: {limit_clause}")
            #
            del ast.args['limit']
            print("已移除LIMIT子句")  
        
        #
        if hasattr(ast, 'args') and 'joins' in ast.args:
           
            joins_clause = ast.args['joins']
            print(f"检测到JOIN子句: {joins_clause}")
            if joins_clause:
                #
                #
                for clause in joins_clause:
                    if 'side' in clause.args:
                        print(clause.args['side'])
                        clause.args['side'] = None
                        #
                        clause.args['kind'] = 'INNER'
                    if 'kind' in clause.args:
                        clause.args['kind'] = 'INNER'
        
        #
        if hasattr(ast, 'args') and 'group' in ast.args:
            group_clause = ast.args['group']
            if group_clause:
                print(f"检测到GROUP BY子句: {group_clause}")
                #
                del ast.args['group']
                print("已移除GROUP BY子句")  
        #
        if hasattr(ast, 'args') and 'having' in ast.args and ast.args['having']:
            having_clause = ast.args['having']
            print(f"检测到HAVING子句: {having_clause}")
            
            #
            for value in having_clause.walk():
                    if isinstance(value, sqlglot.expressions.Expression) and self._is_aggregate_function(value):
                        #
                        agg_func = value

                        print(agg_func.args)
                        print(agg_func.__class__.__name__)
                        
                        #
                        args = []
                        if agg_func.__class__.__name__ == 'GroupConcat':
                            args.append(agg_func.this.this)
                            print(args)
                        elif agg_func.__class__.__name__ != 'Anonymous' and hasattr(agg_func, 'args') and 'this' in agg_func.args:
                            args = agg_func.args['this'] if isinstance(agg_func.args['this'], list) else [agg_func.args['this']]
                        elif agg_func.__class__.__name__ =='Anonymous':
                            args = agg_func.expressions
                        #
                        has_distinct = False
                        
                        #
                        if hasattr(agg_func, 'this') and hasattr(agg_func.this, '__class__') and agg_func.this.__class__.__name__ == 'Distinct':
                            has_distinct = True
                            print(f"聚合函数包含DISTINCT关键字")
                            #
                            if hasattr(agg_func.this, 'expressions') and agg_func.this.expressions:
                                args = agg_func.this.expressions
                        
                        #
                        if args:
                            #
                            new_expr = args[0]
                            agg_func.replace(new_expr)
                            print(f"已将聚合函数替换为其参数: {new_expr}")
                        else:
                            print("聚合函数没有参数，跳过替换")
        if hasattr(ast, 'args') and 'where' in ast.args and ast.args['where']:
            where_clause = ast.args['where']
            print(f"检测到WHERE子句: {where_clause}")
            
            #
            #
            for node in list(where_clause.walk()):
                if self._is_aggregate_function(node):
                    print(f"在WHERE子句中检测到聚合函数: {node}")
                    
                    #
                    replacement = None
                    if hasattr(node, 'args') and 'this' in node.args:
                        args = node.args['this']
                        replacement = args[0] if isinstance(args, list) and args else args
                    elif hasattr(node, 'this') and node.this:
                        #
                        if hasattr(node.this, '__class__') and node.this.__class__.__name__ == 'Distinct':
                            if hasattr(node.this, 'expressions') and node.this.expressions:
                                replacement = node.this.expressions[0] if node.this.expressions else None
                        else:
                            replacement = node.this
                    
                    #
                    if replacement:
                        print(f"将聚合函数替换为其参数: {replacement}")
                        #
                        parent = None
                        parent_key = None
                        #
                        for potential_parent in list(where_clause.walk()):
                            if hasattr(potential_parent, 'args'):
                                for key, value in potential_parent.args.items():
                                    if value is node:
                                        parent = potential_parent
                                        parent_key = key
                                        break
                                    elif isinstance(value, list):
                                        for i, item in enumerate(value):
                                            if item is node:
                                                parent = potential_parent
                                                parent_key = (key, i)
                                                break
                                if parent:
                                    break
                        
                        #
                        if parent and parent_key:
                            if isinstance(parent_key, tuple):
                                #
                                parent.args[parent_key[0]][parent_key[1]] = replacement
                            else:
                                #
                                parent.args[parent_key] = replacement
                            print(f"已成功替换聚合函数节点")
                    
        #
        #
        #
        is_scalar_query = False
        if hasattr(ast, 'expressions') and len(ast.expressions) == 1:
            #
            has_group_by = hasattr(ast, 'args') and 'group' in ast.args and ast.args['group']
            
            #
            has_complex_join = False
            if hasattr(ast, 'args') and 'from' in ast.args and ast.args['from']:
                from_clause = ast.args['from']
                if hasattr(from_clause, 'expressions'):
                    for expr in from_clause.expressions:
                        if isinstance(expr, sqlglot.expressions.Join):
                            has_complex_join = True
                            break
            
            #
            if not has_group_by and not has_complex_join:
                is_scalar_query = True
        
        if is_scalar_query:
            print(f"检测到标量查询: {ast}")
            order_by_expr = None
            #
            select_expr = ast.expressions[0]
            if isinstance(select_expr, sqlglot.expressions.Alias) and isinstance(select_expr.this, sqlglot.expressions.Column):
                order_by_expr = select_expr.this
            elif isinstance(select_expr, sqlglot.expressions.Column):
                order_by_expr = select_expr
            
            #
            if hasattr(ast, 'args'):
                if order_by_expr:
                    #
                    order_by = sqlglot.expressions.Order(expressions=[order_by_expr])
                    ast.args['order'] = order_by
                    print(f"已添加ORDER BY子句: {order_by_expr}")
                
                #
                limit = sqlglot.expressions.Limit(
                    expression=sqlglot.expressions.Literal.number(1)
                )
                ast.args['limit'] = limit
                print("已添加LIMIT 1子句")
        print(f"修改后的AST: {ast}")

        
        
        
        
    
    
