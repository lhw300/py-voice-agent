# db/mongo_service.py  —— 对话历史持久化
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import pymongo
from pymongo import MongoClient
import ai_config as AiConfig

logger = logging.getLogger(__name__)

_client: Optional[MongoClient] = None
_col    = None


def init() -> None:
    global _client, _col
    if _col is not None:
        return

    host   = AiConfig.getStringConfig("db.mongo.host",     "localhost")
    port   = AiConfig.getIntConfig   ("db.mongo.port",     27017)
    user   = AiConfig.getStringConfig("db.mongo.user",     "")
    pwd    = AiConfig.getStringConfig("db.mongo.password", "lcall")
    dbname = AiConfig.getStringConfig("db.mongo.dbname",   "lcallai")

    if user:
        uri = f"mongodb://{user}:{pwd}@{host}:{port}/{dbname}?authSource=admin"
    else:
        uri = f"mongodb://{host}:{port}/"

    _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db      = _client[dbname]
    _col    = db["call_histories"]

    _col.create_index([("sn", pymongo.ASCENDING)], unique=True)
    _col.create_index([("phone", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)])
    _col.create_index([("status", pymongo.ASCENDING), ("updated_at", pymongo.DESCENDING)])
    _col.create_index([("ch", pymongo.ASCENDING)])
    _col.create_index([("created_at", pymongo.DESCENDING)])

    logger.info(f"✅ MongoDB connected: {host}:{port}/{dbname}")


# ─────────────────────────────────────────────
#  写入
# ─────────────────────────────────────────────

def upsert_call(sn: str, phone: str, vo_id: str, ch: str,
                call_date: str, start_time: str) -> None:
    now = datetime.now(timezone.utc)
    _col.update_one(
        {"sn": sn},
        {
            "$setOnInsert": {
                "sn":         sn,
                "phone":      phone,
                "vo_id":      vo_id,
                "ch":         ch,
                "call_date":  call_date,
                "start_time": start_time,
                "status":     "active",
                "created_at": now,
            },
            "$set": {"updated_at": now}
        },
        upsert=True
    )


def save_turn(sn: str, crid: str, user_text: str,
              answer: str, intent: str = None,
              category: str = None, hit_source: str = None,
              elapsed_ms: int = 0) -> None:
    now  = datetime.now(timezone.utc)
    turn = {
        "crid":       crid,
        "user":       user_text,
        "assistant":  answer,
        "intent":     intent,
        "category":   category,
        "hit_source": hit_source,
        "elapsed_ms": elapsed_ms,
        "ts":         now,
    }
    update = {
        "$push": {"turns": turn},
        "$set":  {"updated_at": now},
    }
    if intent == "COMMAND" and answer and "transfer" in answer.lower():
        update["$set"]["status"] = "transferred"

    _col.update_one({"sn": sn}, update)


# ─────────────────────────────────────────────
#  查询辅助
# ─────────────────────────────────────────────

def _idle_minutes() -> int:
    return AiConfig.getIntConfig("db.chathistory.session.timeout.minutes", 3)


def _resolve_status(doc: dict) -> str:
    status = doc.get("status", "active")
    if status == "active":
        updated_at = doc.get("updated_at")
        if updated_at:
            idle = datetime.now(timezone.utc) - updated_at.replace(tzinfo=timezone.utc)
            if idle > timedelta(minutes=_idle_minutes()):
                return "ended"
    return status


def _duration_ms(doc: dict) -> int:
    turns = doc.get("turns", [])
    if not turns:
        return 0
    created_at = doc.get("created_at")
    last_ts    = turns[-1].get("ts")
    if not created_at or not last_ts:
        return 0
    diff = last_ts.replace(tzinfo=timezone.utc) - created_at.replace(tzinfo=timezone.utc)
    return max(0, int(diff.total_seconds() * 1000))


def _fmt(doc: dict) -> dict:
    turns  = doc.get("turns", [])
    dur_ms = _duration_ms(doc)
    return {
        "_id":        doc.get("sn"),
        "caller":     doc.get("phone"),
        "channel":    _ch_to_channel(doc.get("ch", "1")),
        "status":     _resolve_status(doc),
        "turn_count": len(turns),
        "start_at":   doc.get("created_at"),
        "duration_s": dur_ms // 1000,
        "sn":         doc.get("sn"),
        "vo_id":      doc.get("vo_id"),
        "ch":         doc.get("ch"),
        "call_date":  doc.get("call_date"),
        "start_time": doc.get("start_time"),
        "updated_at": doc.get("updated_at"),
    }



# ─────────────────────────────────────────────
#  查询
# ─────────────────────────────────────────────

def list_calls(
        sn:        Optional[str] = None,
        phone:     Optional[str] = None,
        keyword:   Optional[str] = None,
        status:    Optional[str] = None,
        ch:        Optional[str] = None,
        date_from: Optional[str] = None,
        date_to:   Optional[str] = None,
        page:      int = 1,
        page_size: int = 20,
) -> dict:
    query: dict = {}
    if phone:
        query["phone"] = {"$regex": phone, "$options": "i"}
    if ch:
        query["ch"] = ch
    if sn:
            query["sn"] = {"$regex": sn, "$options": "i"}
    if date_from or date_to:
        date_filter = {}
        if date_from: date_filter["$gte"] = date_from
        if date_to:   date_filter["$lte"] = date_to
        query["call_date"] = date_filter
    else:
        # 默认最近7天
        from datetime import date, timedelta
        date_filter = {"$gte": (date.today() - timedelta(days=7)).isoformat()}
        query["call_date"] = date_filter
    if keyword:
        query["turns"] = {"$elemMatch": {
            "$or": [
                {"user":      {"$regex": keyword, "$options": "i"}},
                {"assistant": {"$regex": keyword, "$options": "i"}},
            ]
        }}

    if status == "transferred":
        query["status"] = "transferred"

    total  = _col.count_documents(query)
    offset = (page - 1) * page_size
    docs = list(_col.find(query)
                .sort("created_at", pymongo.DESCENDING)
                .skip(offset).limit(page_size))

    rows = [_fmt(d) for d in docs]

    if status == "active":
        rows = [r for r in rows if r["status"] == "active"]
    elif status == "ended":
        rows = [r for r in rows if r["status"] == "ended"]

    return {"total": total, "page": page, "page_size": page_size, "data": rows}


def get_call(sn: str) -> Optional[dict]:
    doc = _col.find_one({"sn": sn})
    if not doc:
        return None
    result          = _fmt(doc)
    result["turns"] = doc.get("turns", [])
    return result

def _ch_to_channel(ch: str) -> str:
    return "phone" if ch == "1" else "web"

def search_by_phone(phone: str, limit: int = 20) -> list:
    docs = list(_col.find({"phone": {"$regex": phone, "$options": "i"}}, {"turns": 0})
                .sort("created_at", pymongo.DESCENDING).limit(limit))
    return [_fmt(d) for d in docs]


def get_stats() -> dict:
    from datetime import date
    today       = date.today().isoformat()
    total       = _col.count_documents({})
    transferred = _col.count_documents({"status": "transferred"})
    today_cnt   = _col.count_documents({"call_date": today})
    return {
        "total":       total,
        "transferred": transferred,
        "today":       today_cnt,
    }


def delete_call(sn: str) -> bool:
    result = _col.delete_one({"sn": sn})
    return result.deleted_count == 1


def delete_many(sns: list) -> int:
    result = _col.delete_many({"sn": {"$in": sns}})
    return result.deleted_count


# ─────────────────────────────────────────────
#  Test
# ─────────────────────────────────────────────

def _test(config_path: str) -> None:
    import time as _time

    AiConfig.init(config_path)
    init()

    # 清理旧测试数据
    _col.delete_many({"sn": {"$in": ["SN001", "SN002", "SN003"]}})
    print("🧹 清理旧测试数据")

    # ── 写入 ──
    print("\n=== 写入测试数据 ===")
    upsert_call("SN001", "13800001000", "ai_send", "1", "2026-06-15", "10:00:00")
    upsert_call("SN002", "13800001007", "ai_send", "2", "2026-06-15", "11:00:00")
    upsert_call("SN003", "13800001014", "ai_send", "1", "2026-06-14", "13:00:00")
    print("  3 条通话记录写入完成")

    save_turn("SN001", "c1", "想查余额",   "您的余额是500元",   intent="QUERY",   category="账户", hit_source="k1",  elapsed_ms=320)
    save_turn("SN001", "c2", "还有优惠吗", "目前有折扣活动",    intent="QUERY",   category="产品", hit_source="rag", elapsed_ms=850)
    save_turn("SN002", "c1", "转人工",     "Transferring you",  intent="COMMAND", category=None,   hit_source=None,  elapsed_ms=100)
    save_turn("SN003", "c1", "营业时间",   "周一到周五9点到5点", intent="QUERY",  category="信息", hit_source="k2",  elapsed_ms=200)
    print("  4 条 turn 写入完成")

    # ── get_call ──
    print("\n=== get_call(SN001) ===")
    doc = get_call("SN001")
    print(f"  status={doc['status']}  turns={doc['turn_count']}  duration_ms={doc['duration_ms']}")
    for t in doc["turns"]:
        print(f"    [{t['crid']}] {t['user']} → {t['assistant'][:20]}  hit={t['hit_source']}")

    print("\n=== get_call(SN002) — 应为 transferred ===")
    doc = get_call("SN002")
    print(f"  status={doc['status']}  ✅" if doc["status"] == "transferred" else f"  ❌ status={doc['status']}")

    # ── active/ended 判断（等超时）──
    timeout = _idle_minutes()
    print(f"\n=== SN001 状态（timeout={timeout}min，刚写入应为 active）===")
    doc = get_call("SN001")
    print(f"  status={doc['status']}  ✅" if doc["status"] == "active" else f"  ❌ status={doc['status']}")

    # ── list_calls ──
    print("\n=== list_calls() 全部 ===")
    result = list_calls(page=1, page_size=10)
    print(f"  total={result['total']}")
    for r in result["data"]:
        print(f"    {r['sn']} {r['phone']} status={r['status']} turns={r['turn_count']} dur={r['duration_ms']}ms")

    print("\n=== list_calls(phone='138') ===")
    result = list_calls(phone="138")
    print(f"  matched={len(result['data'])}  ✅" if len(result["data"]) == 3 else f"  ❌ matched={len(result['data'])}")

    print("\n=== list_calls(status='transferred') ===")
    result = list_calls(status="transferred")
    print(f"  count={len(result['data'])}  ✅" if len(result["data"]) == 1 else f"  ❌ count={len(result['data'])}")

    print("\n=== list_calls(ch='1') ===")
    result = list_calls(ch="1")
    print(f"  count={len(result['data'])}  ✅" if len(result["data"]) == 2 else f"  ❌ count={len(result['data'])}")

    print("\n=== list_calls(date_from='2026-06-15', date_to='2026-06-15') ===")
    result = list_calls(date_from="2026-06-15", date_to="2026-06-15")
    print(f"  count={len(result['data'])}  ✅" if len(result["data"]) == 2 else f"  ❌ count={len(result['data'])}")

    print("\n=== search_by_phone('13800001000') ===")
    rows = search_by_phone("13800001000")
    print(f"  found={len(rows)}  ✅" if len(rows) == 1 else f"  ❌ found={len(rows)}")

    print("\n=== get_stats() ===")
    stats = get_stats()
    print(f"  {stats}")

    print("\n=== delete_call(SN003) ===")
    ok = delete_call("SN003")
    print(f"  deleted={ok}  ✅" if ok else "  ❌ not deleted")
    doc = get_call("SN003")
    print(f"  get_call after delete=None  ✅" if doc is None else f"  ❌ still exists")

    print("\n=== delete_many([SN001, SN002]) ===")
    cnt = delete_many(["SN001", "SN002"])
    print(f"  deleted={cnt}  ✅" if cnt == 2 else f"  ❌ deleted={cnt}")
    result = list_calls(phone="138")
    print(f"  remaining={len(result['data'])}  ✅" if len(result["data"]) == 0 else f"  ❌ remaining={len(result['data'])}")

    print("\n✅ 全部测试完成")


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AI_CONFIG_DIR", "/home/call/py-voice-agent")
    _test(config_path)