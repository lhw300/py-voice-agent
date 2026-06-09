# search/search_service.py
# Java: package com.lcallai;
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import psycopg2
from psycopg2 import pool

import  ai_config as AiConfig

logger = logging.getLogger(__name__)

# Java: private static HikariDataSource dataSource;
_pool: Optional[pool.ThreadedConnectionPool] = None

# Java: private static boolean isInitialized = false;
_initialized: bool = False


@dataclass
class KnowledgeItem:
    """
    public static class KnowledgeItem {
        public String category;
        public String summary;
        public String content;
        public double distance;
    }
    """
    category: str
    summary:  str
    content:  str
    distance: float


"""
public static synchronized void init(String aiType) {
    if (isInitialized) return;
    HikariConfig config = new HikariConfig();
    config.setJdbcUrl(AiConfig.getStringConfig("db.postgres.url", ...));
    config.setUsername(AiConfig.getStringConfig("db.postgres.user", ...));
    config.setPassword(AiConfig.getStringConfig("db.postgres.password", ...));
    config.setMaximumPoolSize(AiConfig.getIntConfig("db.postgres.pool.max", 10));
    dataSource = new HikariDataSource(config);
    isInitialized = true;
}
"""
def init() -> None:
    global _pool, _initialized
    if _initialized:
        return

    # Java: AiConfig.getStringConfig("db.postgres.url", "jdbc:postgresql://localhost:5432/postgres")
    url      = AiConfig.getStringConfig("db.postgres.url",      "jdbc:postgresql://127.0.0.1:5432/postgres")
    user     = AiConfig.getStringConfig("db.postgres.user",     "postgres")
    password = AiConfig.getStringConfig("db.postgres.password", "call")
    max_conn = AiConfig.getIntConfig("db.postgres.pool.max",    10)

    # Convert Java jdbc URL to psycopg2 DSN
    # jdbc:postgresql://host:port/dbname → host:port/dbname
    dsn = url.replace("jdbc:postgresql://", "")
    host_port, dbname = dsn.split("/", 1)
    host, port = (host_port.split(":") + ["5432"])[:2]

    _pool = pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=max_conn,
        host=host,
        port=int(port),
        dbname=dbname,
        user=user,
        password=password,
    )
    _initialized = True
    logger.debug("✅ 已按需初始化 Postgres 连接池")


"""
public static List<KnowledgeItem> getRelevantKnowledge(
        String tableName, String query, EmbeddingClient embedClient) throws Exception {

    init(storage_type);

    // Step 1: 向量化
    long startEmbed = System.currentTimeMillis();
    double[] vector = embedClient.embed(query);
    logger.debug("Step 1: Embedding took: " + (System.currentTimeMillis() - startEmbed) + " ms");

    // Step 2: 检索
    long startSearch = System.currentTimeMillis();
    List<KnowledgeItem> results = searchTopKnowledge(tableName, vector, 15);
    logger.debug("Step 2: Search took: " + (System.currentTimeMillis() - startSearch) + " ms");

    return results;
}
"""
def getRelevantKnowledge(
    table_name: str,
    query: str,
    embed_client,
    category_filter: Optional[str] = None,
    limit: int = 15,
        vector: Optional[List[float]] = None,
) -> List[KnowledgeItem]:
    init()

    # Java: Step 1 — 向量化
    start_embed = time.time()
    if vector is None:
        start_embed = time.time()
        vector = embed_client.embed(query)
        logger.debug("Step 1: new Embedding took: " + str(int((time.time() - start_embed) * 1000)) + " ms")
    else:
        logger.debug("Step 1: existing Embedding took: " + str(int((time.time() - start_embed) * 1000)) + " ms")

    # Java: Step 2 — pgvector 检索
    start_search = time.time()

    results = _searchTopKnowledge(table_name, vector, category_filter, limit)
    logger.debug("Step 2: Search took: " + str(int((time.time() - start_search) * 1000)) + " ms")

    return results


"""
private static List<KnowledgeItem> searchTopKnowledge(
        String tableName, double[] vector, int limit) throws Exception {

    String sql = "SELECT category, summary, content, (embedding <=> ?::vector) as distance " +
                 "FROM " + tableName + " " +
                 "WHERE is_active = true " +
                 "ORDER BY distance ASC LIMIT ?";
    ...
    while (rs.next()) {
        results.add(new KnowledgeItem(
            rs.getString("category"),
            rs.getString("summary"),
            rs.getString("content"),
            rs.getDouble("distance")
        ));
    }
}

Python adds optional category_filter for vector + field filter combination.
"""
def _searchTopKnowledge(
    table_name: str,
    vector: List[float],
    category_filter: Optional[str],
    limit: int,
) -> List[KnowledgeItem]:
    results = []

    # Build vector string: [v1,v2,...] — same format as Java StringBuilder
    # 例如，PostgreSQL 认识的向量长这样：
    # '[0.1, 0.2, 0.3, 0.4]'::vector
    #
    # 但是，你在 Python 中持有的原始数据（vector 变量）是一个普通的 Python 列表对象：
    # [0.1, 0.2, 0.3, 0.4] （这是一个内存中的对象，而不是字符串）。

    vec_str = "[" + ",".join(str(v) for v in vector) + "]"

    use_category = (
            AiConfig.getStringConfig("query.category.required", "false").lower() == "true"
            and bool(category_filter)
    )
    if not use_category:
        category_filter = None

    # Java: WHERE is_active = true
    # Python: optionally add category filter (field filter not in Java version)
    if category_filter:
        sql = (
            "SELECT category, summary, content, "
            "(embedding <=> %s::vector) as distance "
            "FROM " + table_name + " "
            "WHERE is_active = true AND category = %s "
            "ORDER BY distance ASC LIMIT %s"
        )
        params = (vec_str, category_filter, limit)
    else:
        sql = (
            "SELECT category, summary, content, "
            "(embedding <=> %s::vector) as distance "
            "FROM " + table_name + " "
            "WHERE is_active = true "
            "ORDER BY distance ASC LIMIT %s"
        )
        params = (vec_str, limit)
    logger.debug(" sql="+sql)
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            for row in rows:
                results.append(KnowledgeItem(
                    category=row[0],
                    summary=row[1],
                    content=row[2],
                    distance=float(row[3]),
                ))
    finally:
        _pool.putconn(conn)

    return results


"""
public static void shutdown() {
    if (dataSource != null) dataSource.close();
    logger.debug("🌙 资源已关闭");
}
"""
def shutdown() -> None:
    global _pool, _initialized
    if _pool:
        _pool.closeall()
        _pool = None
    _initialized = False
    logger.debug("🌙 资源已关闭")

def _create_embed_client(base_dir: str):
    run_type = AiConfig.getStringConfig("system.run.type", "hybrid-qwen").lower()

    if run_type == "qwen":
        from openai import OpenAI
        from search.embedding_client import CloudEmbeddingClient
        qwen_key = AiConfig.getStringConfig("api.key.qwen", "")
        client = OpenAI(
            api_key=qwen_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        return CloudEmbeddingClient(client, model="text-embedding-v3")

    elif run_type == "openai":
        from openai import OpenAI
        from search.embedding_client import CloudEmbeddingClient
        openai_key = AiConfig.getStringConfig("api.key.openai", "")
        client = OpenAI(api_key=openai_key)
        return CloudEmbeddingClient(client, model="text-embedding-3-small")  # 1536维

    else:
        from search.embedding_client import EmbeddingClient
        embed_name = AiConfig.getStringConfig("djl.model.embed.name",
                                              "text2vec-base-chinese-paraphrase-pt")
        model_path = str(Path(base_dir) / embed_name)
        return EmbeddingClient(model_path)

# ── Test entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    logging.basicConfig(
        format="%(levelname)s: %(asctime)s %(name)s:%(lineno)s %(message)s",
        level=logging.DEBUG, stream=sys.stdout, force=True
    )

    config_path = sys.argv[1] if len(sys.argv) > 1 else "e:/ai"

    import ai_config as AiConfig
    AiConfig.init(config_path)

    from search.embedding_client import EmbeddingClient
    embed_name = AiConfig.getStringConfig("djl.model.embed.name", "text2vec-base-chinese-paraphrase-pt")
    embed_path = config_path.replace("\\", "/") + "/" + embed_name
    embed_client = EmbeddingClient(embed_path)

    table_name = AiConfig.getStringConfig("db.postgres.table.online", "enterprise_knowledge_768")

    # ── Test cases ────────────────────────────────────────────────────────────
    tests = [
        ("老师初始密码是多少",    "老师"),
        ("学生忘记密码怎么办",    "学生"),
        ("怎么参加省市级培训",    None),
        ("Win10能安装吗",         "老师"),
    ]

    # for query, category in tests:
    #     logger.debug("=" * 50)
    #     logger.debug("query=" + query + "  category=" + str(category))
    #     items = getRelevantKnowledge(table_name, query, embed_client,
    #                                  category_filter=category, limit=5)
    #     if not items:
    #         logger.debug("❌ 无结果")
    #     for i, item in enumerate(items):
    #         logger.debug(
    #             f"  [{i+1}] dist={KnowledgeItem.__dataclass_fields__ and item.distance:.3f}"
    #             f"  category={item.category}  summary={item.summary}"
    #         )



    # ── Two-stage retrieval 测试（直接调用 ChatSession._performTwoStageRetrievalAsync）──
    logger.debug("\n" + "=" * 50)
    logger.debug("🔁 开始测试 _performTwoStageRetrievalAsync")

    from search.rerank_client import RerankClient
    from session.model_router import ModelRouter
    from session.chat_session import ChatSession

    rerank_name = AiConfig.getStringConfig("djl.model.rerank.name", "bge-reranker-v2-m3")
    rerank_path = config_path.replace("\\", "/") + "/" + rerank_name
    rerank_client = RerankClient(rerank_path)

    router = ModelRouter(
        rewriter_client=None,
        rerank_client=rerank_client,
        final_llm_client=None,
    )

    session = ChatSession("test_two_stage")
    session.router          = router
    session.embeddingClient = embed_client
    session.tableName       = table_name
    session.setSInfo("[2stage]")

    two_stage_tests = [
        #("老师初始密码是多少", "老师"),
         #("学生忘记密码怎么办", "学生"),
          ("怎么参加省市级培训", None),
        # ("Win10能安装吗",      "老师"),
    ]

    for query, category in two_stage_tests:
        logger.debug("=" * 50)
        logger.debug("query=" + query + "  category=" + str(category))
        session.currentCategory = category
        results = session._performTwoStageRetrievalAsyncBatch(query)
        if not results:
            logger.debug("❌ 无结果")
        for i, item in enumerate(results):
            logger.debug(f"  [{i+1}] dist={item['distance']:.3f}"
                         + "  category=" + str(item['category'])
                         + "  summary=" + str(item['summary']))

    ChatSession.shutdownExecutor()
    shutdown()
    logger.debug("✅ 测试完成")