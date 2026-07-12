# search/knowledge_service.py
#
# 知识库单条/批量 CRUD + 向量化，供 web/main_web.py 调用
# 职责边界：这里管"知识库当前状态的增删改查"
#          批量从文件导入的核心逻辑在 ingestion_service.py（本文件复用它的 build_semantic_text）
#
import logging
import uuid
from typing import Optional, List

import psycopg2
from psycopg2.extras import RealDictCursor

import ai_config as AiConfig
from search.ingestion_service import build_semantic_text

logger = logging.getLogger(__name__)


def get_conn():
    return psycopg2.connect(
        host=AiConfig.getStringConfig("db.postgres.host", "localhost"),
        port=AiConfig.getIntConfig("db.postgres.port", 5432),
        dbname=AiConfig.getStringConfig("db.postgres.dbname", "postgres"),
        user=AiConfig.getStringConfig("db.postgres.user", "postgres"),
        password=AiConfig.getStringConfig("db.postgres.password", ""),
    )


def get_stats(table: str) -> dict:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT
                    COUNT(*)                                          AS total,
                    COUNT(*) FILTER (WHERE embedding IS NOT NULL)    AS indexed,
                    COUNT(*) FILTER (WHERE embedding IS NULL)        AS pending,
                    COUNT(*) FILTER (WHERE is_active = false)        AS failed
                FROM {table}
            """)
            return cur.fetchone()


def list_knowledge(table: str, category=None, status=None, search=None, page=1, page_size=20) -> dict:
    conditions = ["1=1"]
    params = []
    if category:
        conditions.append("category = %s"); params.append(category)
    if status == "indexed":
        conditions.append("embedding IS NOT NULL AND is_active = true")
    elif status == "pending":
        conditions.append("embedding IS NULL AND is_active = true")
    elif status == "failed":
        conditions.append("is_active = false")
    if search:
        conditions.append("(summary ILIKE %s OR content ILIKE %s OR category ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    offset = (page - 1) * page_size

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params)
            total = cur.fetchone()["count"]
            cur.execute(f"""
                SELECT id, category, summary, content,
                       CASE WHEN is_active = false THEN 'failed'
                            WHEN embedding IS NOT NULL THEN 'indexed'
                            ELSE 'pending' END AS status,
                       updated_at
                FROM {table}
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT %s OFFSET %s
            """, params + [page_size, offset])
            return {"total": total, "page": page, "page_size": page_size, "items": cur.fetchall()}


def list_categories(table: str) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT DISTINCT category, COUNT(*) as count FROM {table} GROUP BY category ORDER BY category")
            rows = cur.fetchall()
            return [{"category": r[0], "count": r[1]} for r in rows]


def create_knowledge(table: str, category: str, summary: str, content: str) -> dict:
    new_id = uuid.uuid4().hex[:16]   # 与现有数据的 id 格式（16位十六进制）保持一致
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                INSERT INTO {table} (id, category, summary, content, is_active, updated_at)
                VALUES (%s, %s, %s, %s, true, NOW())
                RETURNING id, category, summary, content, updated_at
            """, (new_id, category, summary, content))
            conn.commit()
            return cur.fetchone()


def update_knowledge(table: str, item_id: str, category=None, summary=None, content=None) -> bool:
    fields, params = [], []
    if category is not None:
        fields.append("category = %s"); params.append(category)
    if summary is not None:
        fields.append("summary = %s"); params.append(summary)
    if content is not None:
        fields.append("content = %s"); params.append(content)
        fields.append("embedding = NULL")  # content变了，清空旧向量
    fields.append("updated_at = NOW()")
    params.append(item_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {table} SET {', '.join(fields)} WHERE id = %s", params)
            conn.commit()
            return cur.rowcount > 0


def delete_knowledge(table: str, item_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {table} WHERE id = %s", (item_id,))
            conn.commit()
            return cur.rowcount > 0


def delete_many(table: str, ids: List[str]) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {table} WHERE id = ANY(%s)", (ids,))
            conn.commit()
            return cur.rowcount


def vectorize_ids(table: str, ids: List[str], embed_client) -> dict:
    results = {"success": 0, "failed": 0, "errors": []}
    embed_desc = embed_client.describe() if hasattr(embed_client, "describe") else embed_client.modeType()
    logger.info(f"[vectorize_ids] table={table}  embed_client={embed_desc}  请求 {len(ids)} 个id")

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT id, category, summary, content FROM {table} WHERE id = ANY(%s)",
                (ids,)
            )
            items = cur.fetchall()

        logger.info(f"[vectorize_ids] 请求 {len(ids)} 个id，实际取到 {len(items)} 条")

        for item in items:
            try:
                # 与 ingestion_service.run() 批量导入用同一个函数拼接文本，
                # 确保网页单条向量化和命令行批量导入生成的向量在同一个语义空间
                semantic_text = build_semantic_text(item["category"], item["summary"], item["content"])
                vector  = embed_client.embed(semantic_text)
                vec_str = "[" + ",".join(str(v) for v in vector) + "]"
                with conn.cursor() as c:
                    c.execute(f"""
                        UPDATE {table}
                        SET embedding = %s::vector, is_active = true, updated_at = NOW()
                        WHERE id = %s
                    """, (vec_str, item["id"]))
                conn.commit()
                results["success"] += 1
                logger.debug(f"[vectorize_ids] id={item['id']} 成功")
            except Exception as e:
                logger.error(f"[vectorize_ids] id={item['id']} summary={item.get('summary','')[:30]!r} 失败: {e}")
                results["failed"] += 1
                results["errors"].append(str(e))

    logger.info(f"[vectorize_ids] 完成：成功 {results['success']} 条，失败 {results['failed']} 条")
    return results


def bulk_import(table: str, items: List[dict]) -> int:
    inserted = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for item in items:
                new_id = uuid.uuid4().hex[:16]
                cur.execute(f"""
                    INSERT INTO {table} (id, category, summary, content, is_active, updated_at)
                    VALUES (%s, %s, %s, %s, true, NOW())
                """, (new_id, item["category"], item["summary"], item["content"]))
                inserted += 1
        conn.commit()
    return inserted