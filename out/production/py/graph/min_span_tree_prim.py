from typing import List

def _get_min_weight_vertex(num_vertices: int, min_weights: List[float], visited: List[bool]) -> int:
    """
    步骤 1 封装：在所有尚未入树的顶点中，寻找一个距离当前生成树最近的顶点。

    Args:
        num_vertices (int): 图中顶点的总总数 (Number of vertices)。
        min_weights (List[float]): 记录每个顶点到当前生成树的最短边权重数组 (Key weights)。
        visited (List[bool]): 访问标记数组，True 表示该顶点已加入最小生成树。

    Returns:
        int: 选出的最近顶点索引 (Index)；如果图不连通或所有点已入树，则返回 -1。
    """
    u = -1
    min_val = float('inf')
    for v in range(num_vertices):
        if not visited[v] and min_weights[v] < min_val:
            min_val = min_weights[v]
            u = v
    return u


def _update_neighbors(u: int, num_vertices: int, graph: List[List[int]],
                      visited: List[bool], min_weights: List[float], parent: List[int]) -> None:
    """
    步骤 3 封装：遍历刚刚入树的顶点 u 的所有邻居，动态更新它们到生成树的最短距离。

    Args:
        u (int): 当前新加入生成树的顶点索引。
        num_vertices (int): 图中顶点的总总数。
        graph (List[List[int]]): 邻接矩阵 (Adjacency Matrix)，存储图的边权值，0 表示不直接相连。
        visited (List[bool]): 访问标记数组，用于过滤已经入树的邻居。
        min_weights (List[float]): 待更新的最短距离数组。如果发现更短的边，将在此处更新。
        parent (List[int]): 父节点数组 (Parent array)，用于记录最小生成树的路径结构。
    """
    for v in range(num_vertices):
        # 条件：u-v 之间有边 (权重不为 0)、邻居 v 未入树、且通过 u 连接的边权比之前记录的更小
        if graph[u][v] != 0 and not visited[v] and graph[u][v] < min_weights[v]:
            min_weights[v] = graph[u][v]  # 更新邻居到树的最短边权
            parent[v] = u                 # 记录邻居 v 的父节点为 u


def prim_mst(graph: List[List[int]]) -> None:
    """
    Prim 算法主函数：通过邻接矩阵求解并打印最小生成树 (Minimum Spanning Tree)。

    Args:
        graph (List[List[int]]): 输入的图，用邻接矩阵表示（正整数代表边权，0 代表无边）。
    """
    num_vertices = len(graph)

    # 状态数据结构初始化
    visited = [False] * num_vertices
    min_weights = [float('inf')] * num_vertices
    parent = [-1] * num_vertices  # 起始节点的父节点为 -1
    print("num_vertices=",num_vertices)
    print("parent=",parent)
    # 贪心算法起点：选取 0 号顶点作为最初的生成树根节点
    min_weights[0] = 0
    print("初始状态 min_weights:", min_weights)
    # 外层核心状态机循环：每次选择一个顶点入树，总共执行 V 次
    for _ in range(num_vertices):

        # 1. 找点 (Find min vertex)
        u = _get_min_weight_vertex(num_vertices, min_weights, visited)
        if u == -1:
            break  # 如果剩下的点都不可达，说明图不连通，提前结束
        print("  _get_min_weight_vertex: u=", u)
        # 2. 标记入树 (Mark as visited)
        visited[u] = True

        # 3. 更新邻居 (Update neighbors)
        _update_neighbors(u, num_vertices, graph, visited, min_weights, parent)
        print("更新后的 min_weights:", min_weights)
    # 计算完毕，输出结果
    _print_mst(num_vertices, parent, graph)


def _print_mst(num_vertices: int, parent: List[int], graph: List[List[int]]) -> None:
    """
    辅助打印输出函数：格式化输出最小生成树的每一条边和总权重。

    Args:
        num_vertices (int): 图中顶点的总总数。
        parent (List[int]): 最终生成的父节点映射数组。
        graph (List[List[int]]): 原始图的邻接矩阵，用于提取边的实际权重。
    """
    print("Edge \tWeight")
    total_weight = 0
    for i in range(1, num_vertices):
        if parent[i] != -1:
            weight = graph[i][parent[i]]
            print(f"{parent[i]} - {i} \t{weight}")
            total_weight += weight
    print(f"Total MST Weight: {total_weight}")


# --- 测试运行 ---
if __name__ == "__main__":
    # 测试用的无向图邻接矩阵
    my_graph = [
    [0, 1, 4],  # 顶点 0 与 0, 1, 2 的连通情况
    [1, 0, 2],  # 顶点 1 与 0, 1, 2 的连通情况
    [4, 2, 0]   # 顶点 2 与 0, 1, 2 的连通情况
]
    prim_mst(my_graph)