from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
import ai_config as AiConfig
import os

from search import knowledge_service as ks

LLM_CONFIG_DIR = os.environ.get("LLM_CONFIG_DIR", "/home/call/py-voice-agent")
router = APIRouter()


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
    updates: Dict[str, str]


class SingleUpdate(BaseModel):
    key: str
    value: str


# ═══════════════════════════════════════════════════
#  知识库 API
# ═══════════════════════════════════════════════════

@router.get("/api/stats")
def get_stats():
    return ks.get_stats()


@router.get("/api/knowledge")
def list_knowledge(
        category: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
):
    return ks.list_knowledge(category, status, search, page, page_size)


@router.get("/api/categories")
def list_categories():
    return ks.list_categories()


@router.post("/api/knowledge", status_code=201)
def create_knowledge(item: KnowledgeItem):
    return ks.create_knowledge(item.category, item.summary, item.content)


@router.put("/api/knowledge/{item_id}")
def update_knowledge(item_id: str, item: KnowledgeItemUpdate):
    ok = ks.update_knowledge(item_id, item.category, item.summary, item.content)
    if not ok:
        raise HTTPException(404, "Item not found")
    return {"ok": True}


@router.delete("/api/knowledge/{item_id}")
def delete_knowledge(item_id: str):
    ok = ks.delete_knowledge(item_id)
    if not ok:
        raise HTTPException(404, "Item not found")
    return {"ok": True}


@router.delete("/api/knowledge")
def delete_many(ids: List[str]):
    return {"deleted": ks.delete_many(ids)}


@router.post("/api/knowledge/vectorize")
def vectorize(ids: List[str]):
    return ks.vectorize_ids(ids)


@router.get("/api/search")
def search(q: str, category: Optional[str] = None, limit: int = 5):
    return ks.search_knowledge(q, category, limit)


@router.post("/api/knowledge/import")
def bulk_import(items: List[KnowledgeItem]):
    inserted = ks.bulk_import([i.dict() for i in items])
    return {"inserted": inserted}


# ═══════════════════════════════════════════════════
#  配置管理 API
# ═══════════════════════════════════════════════════

@router.get("/api/config")
def get_all_config():
    return {"data": AiConfig.get_all(), "file": AiConfig.configFile}


@router.get("/api/config/raw")
def get_raw_config():
    return {"content": AiConfig.get_raw()}


@router.put("/api/config")
def update_config(body: ConfigUpdate):
    AiConfig.save(body.updates)
    return {"ok": True, "updated": list(body.updates.keys())}


@router.patch("/api/config/item")
def update_single(body: SingleUpdate):
    AiConfig.save({body.key: body.value})
    return {"ok": True, "key": body.key, "value": body.value}


@router.get("/api/config/section/{prefix}")
def get_section(prefix: str):
    all_conf = AiConfig.get_all()
    return {"prefix": prefix, "data": {k: v for k, v in all_conf.items() if k.startswith(prefix)}}


@router.post("/api/config/reload")
def reload_config():
    AiConfig.reload()
    return {"ok": True, "data": AiConfig.get_all()}


@router.get("/health")
def health():
    return {"status": "ok", "config_file": AiConfig.configFile}