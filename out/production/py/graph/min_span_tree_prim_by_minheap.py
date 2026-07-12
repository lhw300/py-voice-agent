import heapq

def _push_neighbors_to_heap(u, adj_list, visited, min_heap):
    """
    辅助函数 (Helper Function)：
    遍历当前节点 u 的所有邻居，如果邻居尚未入树，就将边推入最小堆。
    """
    print("_push_neighbors_to_heap begin... u=",u)
    # 这里的 adj_list[u] 格式为: [(neighbor_v, weight), ...]
    for v, weight in adj_list[u]:
        print(" check v=",v," visited="+str(visited[v]))
        if not visited[v]:
            # 保持堆的特性：将权值作为元组的第一个元素，heapq 会自动按权值从小到大排序
            # 格式：(权重, 邻居节点, 当前节点作为父节点)
            heapq.heappush(min_heap, (weight, v, u))
            print("heappush weight=",weight," v=",v," parent=",u)

def prim_mst_with_heap(adj_list, num_vertices):
    # 初始化状态
    visited = [False] * num_vertices
    mst_edges = []  # 存储最终生成树的边 (Parent, Child, Weight)
    total_cost = 0

    # 初始化最小堆：(weight, current_node, parent_node)
    # 选取 0 号顶点作为起点，权重为 0，没有父节点（用 -1 表示）
    min_heap = [(0, 0, -1)]

    # 核心循环：只要堆不为空，就继续扩展
    while min_heap:

        # --- 1. 弹出当前距离生成树最近的边 ---
        weight, u, parent = heapq.heappop(min_heap)
        print("heappop weight=",weight," u=",u," parent=",parent," visited[u] ",str(visited[u]))
        # 贪心选择的去重：如果该节点已经被其他更短的边带入树中了，直接跳过
        if visited[u]:
            continue

        # --- 2. 标记入树并记录结果 ---
        visited[u] = True
        print("set true.. visited[u] ",u)
        total_cost += weight
        if parent != -1:
            mst_edges.append((parent, u, weight))

        # --- 3. 封装的更新逻辑：遍历 u 的所有邻居并推入堆 ---
        _push_neighbors_to_heap(u, adj_list, visited, min_heap)

    # 打印最终结果
    _print_mst(mst_edges, total_cost)


def _print_mst(mst_edges, total_cost):
    """辅助打印函数"""
    print("Edge \tWeight")
    for u, v, w in mst_edges:
        print(f"{u} - {v} \t{w}")
    print(f"Total MST Cost: {total_cost}")


# --- 测试数据 (邻接表 Adjacency List) ---
if __name__ == "__main__":
    # 图的顶点数
    num_nodes = 5

    # 极其简短的邻接表表达方式
    my_adj_list = {
        0: [(1, 1), (2, 4)],  # 0 连着 1(权值1) 和 2(权值4)
        1: [(0, 1), (2, 2)],  # 1 连着 0(权值1) 和 2(权值2)
        2: [(0, 4), (1, 2)]   # 2 连着 0(权值4) 和 1(权值2)
    }

    prim_mst_with_heap(my_adj_list, num_nodes)