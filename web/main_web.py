# web/main.py  —— knowledge 管理 + config 管理路由
# 不再独立启动，由 main.py 统一 include

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
import psycopg2
from psycopg2.extras import RealDictCursor
import ai_config as AiConfig
from search.embedding_client import EmbeddingClient
from search.search_service import getRelevantKnowledge
from search.ingestion_service import _readFromTxt_from_str, _upsertToDatabase, _cleanContent
router = APIRouter(prefix="/api")

# 由 main.py lifespan 注入
_embed_client: Optional[EmbeddingClient] = None
_table: Optional[str] = None


def init(embed_client: EmbeddingClient, table: str):
    global _embed_client, _table
    _embed_client = embed_client
    _table        = table


# ── DB ────────────────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host     = AiConfig.getStringConfig("db.postgres.host",     "localhost"),
        port     = AiConfig.getIntConfig   ("db.postgres.port",     5432),
        dbname   = AiConfig.getStringConfig("db.postgres.dbname",   "postgres"),
        user     = AiConfig.getStringConfig("db.postgres.user",     "postgres"),
        password = AiConfig.getStringConfig("db.postgres.password", ""),
    )


# ── Pydantic models ───────────────────────────────────────────────────────────
class KnowledgeItem(BaseModel):
    category: str
    summary:  str
    content:  str

class KnowledgeItemUpdate(BaseModel):
    category: Optional[str] = None
    summary:  Optional[str] = None
    content:  Optional[str] = None

class ConfigUpdate(BaseModel):
    updates: Dict[str, str]

class SingleUpdate(BaseModel):
    key:   str
    value: str


# ═══════════════════════════════════════════════════
#  知识库 API
# ═══════════════════════════════════════════════════

@router.get("/stats")
def get_stats():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT
                    COUNT(*)                                          AS total,
                    COUNT(*) FILTER (WHERE embedding IS NOT NULL)    AS indexed,
                    COUNT(*) FILTER (WHERE embedding IS NULL)        AS pending,
                    COUNT(*) FILTER (WHERE is_active = false)        AS failed
                FROM {_table}
            """)
            return cur.fetchone()


@router.get("/knowledge")
def list_knowledge(
        category:  Optional[str] = None,
        status:    Optional[str] = None,
        search:    Optional[str] = None,
        page:      int = 1,
        page_size: int = 20,
):
    conditions = ["1=1"]
    params     = []

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

    where  = " AND ".join(conditions)
    offset = (page - 1) * page_size

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT COUNT(*) FROM {_table} WHERE {where}", params)
            total = cur.fetchone()["count"]
            cur.execute(f"""
                SELECT id, category, summary, content,
                       CASE WHEN is_active = false THEN 'failed'
                            WHEN embedding IS NOT NULL THEN 'indexed'
                            ELSE 'pending' END AS status,
                       updated_at
                FROM {_table}
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT %s OFFSET %s
            """, params + [page_size, offset])
            return {"total": total, "page": page, "page_size": page_size, "items": cur.fetchall()}


@router.get("/categories")
def list_categories():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT DISTINCT category, COUNT(*) as count FROM {_table} GROUP BY category ORDER BY category")
            rows = cur.fetchall()
            return [{"category": r[0], "count": r[1]} for r in rows]


@router.post("/knowledge", status_code=201)
def create_knowledge(item: KnowledgeItem):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                INSERT INTO {_table} (category, summary, content, is_active, updated_at)
                VALUES (%s, %s, %s, true, NOW())
                RETURNING id, category, summary, content, updated_at
            """, (item.category, item.summary, item.content))
            conn.commit()
            return cur.fetchone()


@router.put("/knowledge/{item_id}")
def update_knowledge(item_id: str, item: KnowledgeItemUpdate):
    fields, params = [], []
    if item.category is not None:
        fields.append("category = %s"); params.append(item.category)
    if item.summary is not None:
        fields.append("summary = %s");  params.append(item.summary)
    if item.content is not None:
        fields.append("content = %s");  params.append(item.content)
        fields.append("embedding = NULL")
    fields.append("updated_at = NOW()")
    params.append(item_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {_table} SET {', '.join(fields)} WHERE id = %s", params)
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(404, "Item not found")
            return {"ok": True}


@router.delete("/knowledge/{item_id}")
def delete_knowledge(item_id: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {_table} WHERE id = %s", (item_id,))
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(404, "Item not found")
            return {"ok": True}


@router.delete("/knowledge")
def delete_many(ids: List[str]):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {_table} WHERE id = ANY(%s)", (ids,))
            conn.commit()
            return {"deleted": cur.rowcount}


@router.post("/knowledge/vectorize")
def vectorize(ids: List[str]):
    results = {"success": 0, "failed": 0, "errors": []}
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT id, summary, content FROM {_table} WHERE id = ANY(%s)", (ids,))
            items = cur.fetchall()
        for item in items:
            try:
                vec     = _embed_client.embed(item["summary"] + " " + item["content"])
                vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                with conn.cursor() as c:
                    c.execute(f"""
                        UPDATE {_table}
                        SET embedding = %s::vector, is_active = true, updated_at = NOW()
                        WHERE id = %s
                    """, (vec_str, item["id"]))
                conn.commit()
                results["success"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))
    return results


@router.get("/search")
def search(q: str, category: Optional[str] = None, limit: int = 5):
    results = getRelevantKnowledge(_table, q, _embed_client, category_filter=category, limit=limit)
    return [{"category": r.category, "summary": r.summary, "content": r.content,
             "distance": round(r.distance, 4)} for r in results]


@router.post("/knowledge/import")
def bulk_import(items: List[KnowledgeItem]):
    inserted = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for item in items:
                cur.execute(f"""
                    INSERT INTO {_table} (category, summary, content, is_active, updated_at)
                    VALUES (%s, %s, %s, true, NOW())
                """, (item.category, item.summary, item.content))
                inserted += 1
        conn.commit()
    return {"inserted": inserted}


# ═══════════════════════════════════════════════════
#  配置管理 API — 全部委托给 AiConfig
# ═══════════════════════════════════════════════════

@router.get("/config")
def get_all_config():
    return {"data": AiConfig.get_all(), "file": AiConfig.configFile}


@router.get("/config/raw")
def get_raw_config():
    return {"content": AiConfig.get_raw()}


@router.put("/config")
def update_config(body: ConfigUpdate):
    AiConfig.save(body.updates)
    return {"ok": True, "updated": list(body.updates.keys())}


@router.patch("/config/item")
def update_single(body: SingleUpdate):
    AiConfig.save({body.key: body.value})
    return {"ok": True, "key": body.key, "value": body.value}


@router.post("/config/reload")
def reload_config():
    AiConfig.reload()
    return {"ok": True, "data": AiConfig.get_all()}



# ═══════════════════════════════════════════════════
#  对话历史 API
# ═══════════════════════════════════════════════════
import search.mongo_service as mongo_service


@router.get("/conversations")
def list_conversations(
        keyword:    Optional[str] = None,
        sn:        Optional[str] = None,
        phone:     Optional[str] = None,

        status:    Optional[str] = None,
        ch:        Optional[str] = None,
        date_from: Optional[str] = None,
        date_to:   Optional[str] = None,
        page:      int = 1,
        page_size: int = 20,
):
    return mongo_service.list_calls(keyword=keyword,sn=sn,
        phone=phone, status=status, ch=ch,
        date_from=date_from, date_to=date_to,
        page=page, page_size=page_size,
    )


@router.get("/conversations/{sn}")
def get_conversation(sn: str):
    doc = mongo_service.get_call(sn)
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    # turns 转成前端 message 格式
    messages = []
    for t in doc.get("turns", []):
        messages.append({"role": "user", "text": t.get("user", ""),  "ts": str(t.get("ts", ""))})
        messages.append({"role": "bot",  "text": t.get("assistant", ""), "ts": str(t.get("ts", ""))})
    doc["messages"] = messages
    return doc

from fastapi import UploadFile, File
from search.ingestion_service import _readFromTxt, _upsertToDatabase, _cleanContent
import io, time as _time

@router.post("/knowledge/import/txt")
async def import_txt(file: UploadFile = File(...)):
    text    = (await file.read()).decode("utf-8")
    entries = _readFromTxt_from_str(text)
    db_url  = AiConfig.getStringConfig("db.postgres.url",      "")
    db_user = AiConfig.getStringConfig("db.postgres.user",     "postgres")
    db_pass = AiConfig.getStringConfig("db.postgres.password", "")
    success = 0
    for entry in entries:
        try:
            content = _cleanContent(entry.content)
            semantic_text = f"Category: [{entry.category}]. Summary: {entry.summary}. Content: {content}"
            vec = _embed_client.embed(semantic_text)
            _upsertToDatabase(_table, entry, vec, db_url, db_user, db_pass)
            success += 1
        except Exception as e:
            logger.error(f"import_txt entry {entry.id} failed: {e}")
    return {"inserted": success, "total": len(entries)}

# 追加到 web/main.py 末尾

# ═══════════════════════════════════════════════════
#  缓存管理 API
# ═══════════════════════════════════════════════════
# ═══════════════════════════════════════════════════
#  缓存管理 API  （追加到 web/main.py 末尾）
# ═══════════════════════════════════════════════════
# ═══════════════════════════════════════════════════
#  缓存管理 API  （追加到 web/main.py 末尾）
# ═══════════════════════════════════════════════════
from search.cache_service import (
    k1_put, k2_put,
    _get_redis, _K1_INDEX, _K2_INDEX,
    _PREFIX_K1, _PREFIX_K2, convert,
)
import json

def _ensure_str(val) -> str:
    if isinstance(val, bytes): return val.decode("utf-8")
    return str(val) if val is not None else ""


@router.get("/cache/list")
def cache_list(
        cache_type: str = "k1",   # k1 or k2
        page:       int = 1,
        page_size:  int = 20,
):
    r      = _get_redis()
    offset = (page - 1) * page_size
    items  = []

    if cache_type == "k1":
        # zrevrange = 按 score（插入时间）倒序
        total_keys = r.zcard(_K1_INDEX)
        keys = r.zrevrange(_K1_INDEX, offset, offset + page_size - 1)
        for h_bytes in keys:
            h   = _ensure_str(h_bytes)
            val = r.get(_PREFIX_K1 + h)
            if not val: continue
            d   = json.loads(_ensure_str(val))
            ttl = r.ttl(_PREFIX_K1 + h)
            items.append({
                "id":         h,
                "question":   d.get("question", ""),
                "answer":     d.get("answer",   ""),
                "hit_source": d.get("hit_source", ""),
                "ttl":        ttl,
                "permanent":  ttl == -1,
            })
    else:
        total_keys = r.zcard(_K2_INDEX)
        keys = r.zrevrange(_K2_INDEX, offset, offset + page_size - 1)
        for eid_bytes in keys:
            eid = _ensure_str(eid_bytes)
            raw = r.hgetall(_PREFIX_K2 + eid)
            if not raw: continue
            question = _ensure_str(raw.get(b"question", raw.get("question", "")))
            answer   = _ensure_str(raw.get(b"answer",   raw.get("answer",   "")))
            ttl = r.ttl(_PREFIX_K2 + eid)
            items.append({
                "id":       eid,
                "question": question,
                "answer":   answer,
                "ttl":      ttl,
                "permanent":ttl == -1,
            })

    return {
        "total":     total_keys,
        "page":      page,
        "page_size": page_size,
        "items":     items,
    }


class CacheAddRequest(BaseModel):
    question:  str
    answer:    str
    permanent: bool = True


@router.post("/cache/add")
def cache_add(body: CacheAddRequest):
    norm = convert(body.question)
    if not norm:
        raise HTTPException(400, "Question is empty after normalization")

    answer_dict = {
        "code":          0,
        "answer":        body.answer,
        "action":        "NONE",
        "hit_source":    "k1",
        "intent_result": {}
    }

    k1_put(norm, answer_dict, permanent=body.permanent)

    k2_written = False
    try:
        vector = _embed_client.embed(norm)
        k2_put(norm, vector, answer_dict, permanent=body.permanent)
        k2_written = True
    except Exception as e:
        logger.warning(f"cache_add k2 embed failed: {e}")

    return {
        "ok":         True,
        "norm":       norm,
        "k1_written": True,
        "k2_written": k2_written,
        "permanent":  body.permanent,
    }


@router.delete("/cache/k1/{item_id}")
def cache_delete_k1(item_id: str):
    r = _get_redis()
    r.zrem(_K1_INDEX, item_id)
    r.delete(_PREFIX_K1 + item_id)
    return {"ok": True}


@router.delete("/cache/k2/{item_id}")
def cache_delete_k2(item_id: str):
    r = _get_redis()
    r.zrem(_K2_INDEX, item_id)
    r.delete(_PREFIX_K2 + item_id)
    return {"ok": True}
