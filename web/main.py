# backend/main.py
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import psycopg2
from psycopg2.extras import RealDictCursor
import ai_config as AiConfig
from search.embedding_client import EmbeddingClient
from search.search_service import getRelevantKnowledge

app = FastAPI(title="RAG Knowledge Manager API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

AiConfig.init("e:/ai")
embed_client = EmbeddingClient("e:/ai/bge-large-zh-v1.5")
TABLE = AiConfig.getStringConfig("db.postgres.table.online", "enterprise_knowledge_1024")

# ── DB connection ─────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host=AiConfig.getStringConfig("db.postgres.host", "localhost"),
        port=AiConfig.getIntConfig("db.postgres.port", 5432),
        dbname=AiConfig.getStringConfig("db.postgres.dbname", "postgres"),
        user=AiConfig.getStringConfig("db.postgres.user", "postgres"),
        password=AiConfig.getStringConfig("db.postgres.password", ""),
    )

# ── Pydantic models ───────────────────────────────────────────────────────────
class KnowledgeItem(BaseModel):
    category: str
    summary: str
    content: str

class KnowledgeItemUpdate(BaseModel):
    category: Optional[str]
    summary: Optional[str]
    content: Optional[str]

# ── Stats ─────────────────────────────────────────────────────────────────────
@app.get("/api/stats")
def get_stats():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT
                    COUNT(*)                                          AS total,
                    COUNT(*) FILTER (WHERE embedding IS NOT NULL)    AS indexed,
                    COUNT(*) FILTER (WHERE embedding IS NULL)        AS pending,
                    COUNT(*) FILTER (WHERE is_active = false)        AS failed
                FROM {TABLE}
            """)
            return cur.fetchone()

# ── List knowledge items ──────────────────────────────────────────────────────
@app.get("/api/knowledge")
def list_knowledge(
    category: Optional[str] = None,
    status: Optional[str] = None,   # indexed | pending | failed
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    conditions = ["1=1"]
    params = []

    if category:
        conditions.append("category = %s")
        params.append(category)

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
            cur.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE {where}", params)
            total = cur.fetchone()["count"]

            cur.execute(f"""
                SELECT id, category, summary, content,
                       CASE WHEN is_active = false THEN 'failed'
                            WHEN embedding IS NOT NULL THEN 'indexed'
                            ELSE 'pending' END AS status,
                       updated_at
                FROM {TABLE}
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT %s OFFSET %s
            """, params + [page_size, offset])

            items = cur.fetchall()
            return {"total": total, "page": page, "page_size": page_size, "items": items}

# ── Categories ────────────────────────────────────────────────────────────────
@app.get("/api/categories")
def list_categories():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT DISTINCT category, COUNT(*) as count FROM {TABLE} GROUP BY category ORDER BY category")
            rows = cur.fetchall()
            return [{"category": r[0], "count": r[1]} for r in rows]

# ── Create ────────────────────────────────────────────────────────────────────
@app.post("/api/knowledge", status_code=201)
def create_knowledge(item: KnowledgeItem):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                INSERT INTO {TABLE} (category, summary, content, is_active, updated_at)
                VALUES (%s, %s, %s, true, NOW())
                RETURNING id, category, summary, content, updated_at
            """, (item.category, item.summary, item.content))
            conn.commit()
            return cur.fetchone()

# ── Update ────────────────────────────────────────────────────────────────────
@app.put("/api/knowledge/{item_id}")
def update_knowledge(item_id: int, item: KnowledgeItemUpdate):
    fields, params = [], []
    if item.category is not None:
        fields.append("category = %s"); params.append(item.category)
    if item.summary is not None:
        fields.append("summary = %s"); params.append(item.summary)
    if item.content is not None:
        fields.append("content = %s"); params.append(item.content)
        # content changed → clear embedding, needs re-vectorization
        fields.append("embedding = NULL")

    fields.append("updated_at = NOW()")
    params.append(item_id)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                UPDATE {TABLE} SET {', '.join(fields)}
                WHERE id = %s RETURNING id
            """, params)
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(404, "Item not found")
            return {"ok": True}

# ── Delete ────────────────────────────────────────────────────────────────────
@app.delete("/api/knowledge/{item_id}")
def delete_knowledge(item_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE} WHERE id = %s", (item_id,))
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(404, "Item not found")
            return {"ok": True}

@app.delete("/api/knowledge")
def delete_many(ids: List[int]):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE} WHERE id = ANY(%s)", (ids,))
            conn.commit()
            return {"deleted": cur.rowcount}

# ── Vectorize ─────────────────────────────────────────────────────────────────
@app.post("/api/knowledge/vectorize")
def vectorize(ids: List[int]):
    results = {"success": 0, "failed": 0, "errors": []}
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT id, summary, content FROM {TABLE} WHERE id = ANY(%s)", (ids,))
            items = cur.fetchall()

        for item in items:
            try:
                text = item["summary"] + " " + item["content"]
                vec = embed_client.embed(text)
                vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                with conn.cursor() as c:
                    c.execute(f"""
                        UPDATE {TABLE}
                        SET embedding = %s::vector, is_active = true, updated_at = NOW()
                        WHERE id = %s
                    """, (vec_str, item["id"]))
                conn.commit()
                results["success"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))

    return results

# ── Search test ───────────────────────────────────────────────────────────────
@app.get("/api/search")
def search(q: str, category: Optional[str] = None, limit: int = 5):
    results = getRelevantKnowledge(TABLE, q, embed_client, category_filter=category, limit=limit)
    return [{"category": r.category, "summary": r.summary, "content": r.content, "distance": round(r.distance, 4)} for r in results]

# ── Bulk import ───────────────────────────────────────────────────────────────
@app.post("/api/knowledge/import")
def bulk_import(items: List[KnowledgeItem]):
    inserted = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for item in items:
                cur.execute(f"""
                    INSERT INTO {TABLE} (category, summary, content, is_active, updated_at)
                    VALUES (%s, %s, %s, true, NOW())
                """, (item.category, item.summary, item.content))
                inserted += 1
        conn.commit()
    return {"inserted": inserted}
