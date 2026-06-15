from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Any
import psycopg2
from psycopg2.extras import RealDictCursor
import re
import os
import ai_config as AiConfig
from search.embedding_client import EmbeddingClient
from search.search_service import getRelevantKnowledge

app = FastAPI(title="RAG Knowledge Manager API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_DIR = os.environ.get("AI_CONFIG_DIR", "/home/call/py-voice-agent")
LLM_CONFIG_DIR = os.environ.get("LLM_CONFIG_DIR", "/home/call/py-voice-agent")
AiConfig.init(CONFIG_DIR)
embed_client = EmbeddingClient(os.path.join(LLM_CONFIG_DIR, "bge-large-zh-v1.5"))
TABLE = AiConfig.getStringConfig("db.postgres.table.online", "enterprise_knowledge_1024")
CONFIG_FILE = os.path.join(CONFIG_DIR, "ai.conf")

# ── DB ────────────────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host=AiConfig.getStringConfig("db.postgres.host", "localhost"),
        port=AiConfig.getIntConfig("db.postgres.port", 5432),
        dbname=AiConfig.getStringConfig("db.postgres.dbname", "postgres"),
        user=AiConfig.getStringConfig("db.postgres.user", "postgres"),
        password=AiConfig.getStringConfig("db.postgres.password", ""),
    )

# ── Config helpers ────────────────────────────────────────────────────────────
def parse_conf(text: str) -> dict[str, Any]:
    result = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        kv = re.split(r"\s+#", stripped, maxsplit=1)[0]
        if "=" in kv:
            k, _, v = kv.partition("=")
            result[k.strip()] = v.strip()
    return result

def write_conf(original: str, updates: dict[str, str]) -> str:
    lines = original.splitlines()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            out.append(line)
            continue
        kv = re.split(r"\s+#", stripped, maxsplit=1)[0]
        if "=" in kv:
            k, _, _ = kv.partition("=")
            key = k.strip()
            if key in updates:
                comment_match = re.search(r"\s+(#.*)$", line)
                comment = f"  {comment_match.group(1)}" if comment_match else ""
                out.append(f"{key}={updates[key]}{comment}")
                continue
        out.append(line)
    return "\n".join(out)

def load_config() -> dict[str, str]:
    if not os.path.exists(CONFIG_FILE):
        raise HTTPException(status_code=404, detail=f"配置文件未找到: {CONFIG_FILE}")
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return parse_conf(f.read())

def load_raw() -> str:
    if not os.path.exists(CONFIG_FILE):
        raise HTTPException(status_code=404, detail=f"配置文件未找到: {CONFIG_FILE}")
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return f.read()

# ── Pydantic models ───────────────────────────────────────────────────────────
class KnowledgeItem(BaseModel):
    category: str
    summary: str
    content: str

class KnowledgeItemUpdate(BaseModel):
    category: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None

class ConfigUpdate(BaseModel):
    updates: dict[str, str]

class SingleUpdate(BaseModel):
    key: str
    value: str

# ═══════════════════════════════════════════════════
#  知识库 API
# ═══════════════════════════════════════════════════

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

@app.get("/api/knowledge")
def list_knowledge(
        category: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
):
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
            return {"total": total, "page": page, "page_size": page_size, "items": cur.fetchall()}

@app.get("/api/categories")
def list_categories():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT DISTINCT category, COUNT(*) as count FROM {TABLE} GROUP BY category ORDER BY category")
            rows = cur.fetchall()
            return [{"category": r[0], "count": r[1]} for r in rows]

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

@app.put("/api/knowledge/{item_id}")
def update_knowledge(item_id: str, item: KnowledgeItemUpdate):
    fields, params = [], []
    if item.category is not None:
        fields.append("category = %s"); params.append(item.category)
    if item.summary is not None:
        fields.append("summary = %s"); params.append(item.summary)
    if item.content is not None:
        fields.append("content = %s"); params.append(item.content)
        fields.append("embedding = NULL")
    fields.append("updated_at = NOW()")
    params.append(item_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {TABLE} SET {', '.join(fields)} WHERE id = %s", params)
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(404, "Item not found")
            return {"ok": True}

@app.delete("/api/knowledge/{item_id}")
def delete_knowledge(item_id: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE} WHERE id = %s", (item_id,))
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(404, "Item not found")
            return {"ok": True}

@app.delete("/api/knowledge")
def delete_many(ids: List[str]):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE} WHERE id = ANY(%s)", (ids,))
            conn.commit()
            return {"deleted": cur.rowcount}

@app.post("/api/knowledge/vectorize")
def vectorize(ids: List[str]):
    results = {"success": 0, "failed": 0, "errors": []}
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT id, summary, content FROM {TABLE} WHERE id = ANY(%s)", (ids,))
            items = cur.fetchall()
        for item in items:
            try:
                vec = embed_client.embed(item["summary"] + " " + item["content"])
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

@app.get("/api/search")
def search(q: str, category: Optional[str] = None, limit: int = 5):
    results = getRelevantKnowledge(TABLE, q, embed_client, category_filter=category, limit=limit)
    return [{"category": r.category, "summary": r.summary, "content": r.content, "distance": round(r.distance, 4)} for r in results]

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

# ═══════════════════════════════════════════════════
#  配置管理 API
# ═══════════════════════════════════════════════════

@app.get("/api/config")
def get_all_config():
    return {"data": load_config(), "file": CONFIG_FILE}

@app.get("/api/config/raw")
def get_raw_config():
    return {"content": load_raw()}

@app.put("/api/config")
def update_config(body: ConfigUpdate):
    raw = load_raw()
    new_raw = write_conf(raw, body.updates)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(new_raw)
    return {"ok": True, "updated": list(body.updates.keys())}

@app.patch("/api/config/item")
def update_single(body: SingleUpdate):
    raw = load_raw()
    new_raw = write_conf(raw, {body.key: body.value})
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(new_raw)
    return {"ok": True, "key": body.key, "value": body.value}

@app.get("/api/config/section/{prefix}")
def get_section(prefix: str):
    all_conf = load_config()
    return {"prefix": prefix, "data": {k: v for k, v in all_conf.items() if k.startswith(prefix)}}

@app.post("/api/config/reload")
def reload_config():
    return {"ok": True, "data": load_config()}

@app.get("/health")
def health():
    return {"status": "ok", "config_file": CONFIG_FILE}

# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)