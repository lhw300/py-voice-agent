# search/cache_service.py
#
# K1 / K2 cache service
#
# K1 — exact match (Redis, no TTL, LRU 1000)
#   key  : cache:k1:{MD5(convert(question))}
#   value: ChatAnswer JSON (full fields including intentResult)
#
# K2 — semantic match (Redis Hash, no TTL, LRU 500)
#   key  : cache:k2:vec:{uuid}
#   fields: vector(bytes), answer, action, intent, sentiment,
#           sub_intent, action_code, refined_query, category, question
#   index: cache:k2:_index  ZSet (score=timestamp for LRU eviction)
#
# Public API:
#   init()                            — call once on startup
#   k1_get(question)  -> dict | None  — exact lookup
#   k1_put(question, chat_answer)     — write to K1 after RAG
#   k2_get(norm, vector) -> dict|None — semantic lookup (caller provides vector)
#   k2_put(norm, vector, chat_answer) — write to K2 after RAG
#   convert(text) -> str              — normalize question text
#
# ai.conf keys:
#   redis.host=localhost
#   redis.port=6379
#   redis.db=0
#   redis.password=
#   redis.convert.file=config/redis_convert_health.txt
#   k1.lru.max=1000
#   k2.lru.max=500
#   k2.similarity.threshold=0.90
# ---------------------------------------------------------------------------

import hashlib
import json
import logging
import math
import os
import re
import time
import uuid
from typing import Optional

import redis

import ai_config as AiConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis key constants
# ---------------------------------------------------------------------------
_PREFIX_K1    = "cache:k1:"
_PREFIX_K2    = "cache:k2:vec:"
_K1_INDEX     = "cache:k1:_index"
_K2_INDEX     = "cache:k2:_index"

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------
_convert_rules:  list[tuple[re.Pattern, str]] = []
_convert_loaded: bool = False
_redis_client:   Optional[redis.Redis] = None
_initialized:    bool = False


# ===========================================================================
# init()
# ===========================================================================

_redis_available: bool = False
_config_dir: str = "e:/ai"
_cache_ttl_seconds: int = 0  # 0 = no TTL
def init(config_dir: str = "e:/ai") -> None:
    """
    Call once on application startup.
    Establishes Redis connection and loads convert rules.
    If Redis is unavailable, cache is silently disabled — RAG continues normally.
    Idempotent.
    """
    global _initialized, _redis_available,_config_dir,_cache_ttl_seconds
    if _initialized:
        return
    _config_dir = config_dir
    logger.debug("[cache] init start ...")

    days = AiConfig.getIntConfig("cache.ttl.days", 0)
    _cache_ttl_seconds = days * 86400
    logger.debug(f"[cache] TTL={'no expiry' if _cache_ttl_seconds == 0 else str(days) + ' days'}")

    _load_convert_rules()
    try:
        r = _get_redis()
        r.ping()
        _redis_available = True
        logger.debug("[cache] Redis ping OK")
    except Exception as e:
        _redis_available = False
        logger.warning(f"[cache] Redis unavailable, cache disabled: {e}")
    _initialized = True
    logger.debug("[cache] init complete")


# ===========================================================================
# convert()
# ===========================================================================

def convert(text: str) -> str:
    """
    Normalize a question for consistent cache key generation:
      1. Strip and lowercase
      2. Apply substitution rules from redis_convert_health.txt
      3. Remove punctuation
      4. Collapse whitespace
    """
    if not text:
        return ""
    _load_convert_rules()
    t = text.strip().lower()
    for pattern, replacement in _convert_rules:
        repl = (" " + replacement + " ") if replacement else " "
        t = pattern.sub(repl, t)
    t = re.sub(r"[，。！？、；：""''（）《》【】,.!?;:\"'()\[\]{}<>~`@#$%^&*_+=|\\/-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # (Fallback)
    return t if t else text.strip()



# ===========================================================================
# K1 — exact match
# ===========================================================================

def k1_get(question: str) -> Optional[dict]:
    """
    Exact-match cache lookup.
    Call before embed/RAG. Returns full ChatAnswer dict on hit, None on miss.
    On hit: refreshes ZSet score (LRU semantics).
    """
    if not _redis_available:
        return None   # 或 return（put函数）
    norm = convert(question)
    if not norm:
        return None
    h   = _make_hash(norm)
    key = _PREFIX_K1 + h
    r   = _get_redis()
    try:
        val = r.get(key)
        if val:
            logger.debug(f"[K1] hit  hash={h}  q={norm[:50]}")
            r.zadd(_K1_INDEX, {h: time.time()})
            return json.loads(val)
    except Exception as e:
        logger.warning(f"[K1] get error: {e}")
    return None


def k1_put(question: str, chat_answer, permanent: bool = False) -> None:
    if not _redis_available:
        return
    norm = convert(question)
    if not norm:
        return
    h   = _make_hash(norm)
    key = _PREFIX_K1 + h
    r   = _get_redis()
    cap = AiConfig.getIntConfig("k1.lru.max", 1000)
    try:
        d = _to_dict(chat_answer)
        d["question"] = norm          # ← 注入问题文本
        payload = json.dumps(d, ensure_ascii=False)
        pipe = r.pipeline()
        if permanent or _cache_ttl_seconds == 0:
            pipe.set(key, payload)
        else:
            pipe.set(key, payload, ex=_cache_ttl_seconds)
        pipe.zadd(_K1_INDEX, {h: time.time()})
        pipe.execute()
        _evict(r, _K1_INDEX, _PREFIX_K1, cap)
        logger.debug(f"[K1] put{'(permanent)' if permanent else ''}  hash={h}  q={norm[:50]}")
    except Exception as e:
        logger.warning(f"[K1] put error: {e}")
# ===========================================================================
# K2 — semantic match
# ===========================================================================

def k2_get(norm: str, vector: list[float]) -> Optional[dict]:
    """
    Semantic cache lookup using cosine similarity.
    Caller must provide the already-computed embedding vector.

    Usage in RAG pipeline:
        norm   = convert(question)
        vector = embed_client.embed(norm)        # ~300ms, done once
        hit    = k2_get(norm, vector)
        if hit:
            return hit                           # skip rerank + LLM

    Returns full ChatAnswer dict on hit, None on miss.
    """
    if not _redis_available:
        return None   # 或 return（put函数）

    if not norm or not vector:
        return None

    threshold = AiConfig.getDoubleConfig("k2.similarity.threshold", 0.95)
    r         = _get_redis()

    try:
        keys = r.zrange(_K2_INDEX, 0, -1)
        if not keys:
            return None

        best_score = -1.0
        best_val   = None
        best_key   = None

        for entry_id in keys:
            raw = r.hgetall(_PREFIX_K2 + entry_id)
            if not raw or "vector" not in raw:
                continue
            # >>>>>>>>>> 增加的代码开始 >>>>>>>>>>
            # 1. 兼容处理：确保从 Redis 拿出来的问题能正常解析为字符串（防止乱码）
            raw_q = raw.get("question", b"")
            stored_q = raw_q.decode("utf-8") if isinstance(raw_q, bytes) else str(raw_q)
            # <<<<<<<<<< 增加的代码结束 <<<<<<<<<<
            stored_vec = _bytes_to_vector(raw["vector"].encode("latin-1"))
            score      = _cosine(vector, stored_vec)
            # >>>>>>>>>> 增加的代码开始 >>>>>>>>>>
            # 2. 打印当前对比的向量值和对应的问题
            print("\n" + "-" * 50)
            print(f"[K2 对比中] 相似度分数 (Score): {score:.4f}")

            #print(f"🔹 当前查询的向量 (Norm Vec - 前5维): {vector[:5]} ... (总长度: {len(vector)})")
            print(f"🔸 数据库的问题 (Stored Q): {stored_q}")
            #print(f"🔸 数据库的向量 (Stored Vec - 前5维): {stored_vec[:5]} ... (总长度: {len(stored_vec)})")
            print("-" * 50)
            # <<<<<<<<<< 增加的代码结束 <<<<<<<<<<

            if score > best_score:
                best_score = score
                best_val   = raw
                best_key   = entry_id

        if best_score >= threshold and best_val:
            logger.debug(f"[K2] hit  score={best_score:.4f}  q={norm[:50]}")
            r.zadd(_K2_INDEX, {best_key: time.time()})
            return _k2_raw_to_answer(best_val)

    except Exception as e:
        logger.warning(f"[K2] get error: {e}")

    return None


def k2_put(norm: str, vector: list[float], chat_answer, permanent: bool = False) -> None:
    """
    Write a ChatAnswer + its embedding vector to K2 after RAG pipeline.
    Evicts oldest entry when LRU cap is exceeded.
    """
    if not _redis_available:
        return None   # 或 return（put函数）

    if not norm or not vector:
        return

    r      = _get_redis()
    cap    = AiConfig.getIntConfig("k2.lru.max", 500)
    eid    = uuid.uuid4().hex
    k2_key = _PREFIX_K2 + eid
    # 改之后
    def _s(v) -> str:
        return "" if v is None else str(v)
    try:
        ans    = _to_dict(chat_answer)
        ir     = ans.get("intent_result") or {}
        fields = {
            "vector"       : _vector_to_bytes(vector).decode("latin-1"),
            "question"     : norm or "",
            "answer"       : ans.get("answer") or "",
            "action"       : ans.get("action") or "NONE",
            "code"         : str(ans.get("code", 0)),
            "intent"       : ir.get("intent") or "",
            "sentiment"    : ir.get("sentiment") or "",
            "sub_intent"   : ir.get("sub_intent") or "",
            "action_code"  : ir.get("action_code") or "",
            "refined_query": ir.get("refined_query") or "",
            "category"     : ir.get("category") or "",
        }
        pipe = r.pipeline()
        pipe.hset(k2_key, mapping=fields)

        if not permanent and _cache_ttl_seconds > 0:
            pipe.expire(k2_key, _cache_ttl_seconds)

        pipe.zadd(_K2_INDEX, {eid: time.time()})
        pipe.execute()
        _evict(r, _K2_INDEX, _PREFIX_K2, cap)
        logger.debug(f"[K2] put   id={eid}  q={norm[:50]}")
    except Exception as e:
        logger.warning(f"[K2] put error: {e}")


# ===========================================================================
# Internal helpers
# ===========================================================================

def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        host = AiConfig.getStringConfig("redis.host", "localhost")
        port = AiConfig.getIntConfig("redis.port", 6379)
        db   = AiConfig.getIntConfig("redis.db", 0)
        pwd  = AiConfig.getStringConfig("redis.password", "")
        _redis_client = redis.Redis(
            host=host, port=port, db=db,
            password=pwd if pwd else None,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        logger.debug(f"[cache] Redis connected → {host}:{port} db={db}")
    return _redis_client


def _make_hash(normalized: str) -> str:
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]


def _load_convert_rules() -> None:
    """Load normalization rules from redis_convert_health.txt. Runs once."""
    global _convert_rules, _convert_loaded
    if _convert_loaded:
        return
    base_dir  = _config_dir
    rel_path  = AiConfig.getStringConfig("redis.convert.file", "config/redis_convert_health.txt")
    file_path = os.path.join(base_dir, rel_path).replace("\\", "/")
    rules: list[tuple[re.Pattern, str]] = []
    if not os.path.exists(file_path):
        logger.warning(f"[cache] convert file not found: {file_path}")
        _convert_loaded = True
        _convert_rules  = rules
        return
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "->" not in line:
                    continue
                left, right = line.split("->", 1)
                src = left.strip().lower()
                dst = right.strip().lower()
                if not src:
                    continue
                pattern = re.compile(r"(?<!\w)" + re.escape(src) + r"(?!\w)")
                rules.append((pattern, dst))
        logger.debug(f"[cache] loaded {len(rules)} convert rules")
    except Exception as e:
        logger.warning(f"[cache] failed to load convert rules: {e}")
    _convert_loaded = True
    _convert_rules  = rules


def _evict(r: redis.Redis, index_key: str, prefix: str, cap: int) -> None:
    """Evict oldest entries from ZSet index when count exceeds cap."""
    count = r.zcard(index_key)
    if count <= cap:
        return
    evict_n = count - cap
    oldest  = r.zrange(index_key, 0, evict_n - 1)
    if oldest:
        pipe = r.pipeline()
        for eid in oldest:
            pipe.delete(prefix + eid)
        pipe.zrem(index_key, *oldest)
        pipe.execute()
        logger.debug(f"[cache] evicted {len(oldest)} from {index_key}")


def _serialize_answer(chat_answer) -> str:
    """Serialize ChatAnswer (instance or dict) to JSON string."""
    return json.dumps(_to_dict(chat_answer), ensure_ascii=False)


def _to_dict(chat_answer) -> dict:
    """Convert ChatAnswer instance or dict to plain dict."""
    if isinstance(chat_answer, dict):
        return chat_answer
    # Pydantic model
    if hasattr(chat_answer, "model_dump"):
        d = chat_answer.model_dump()
    elif hasattr(chat_answer, "dict"):
        d = chat_answer.dict()
    else:
        d = chat_answer.__dict__.copy()
    # serialize enums to string
    for k, v in d.items():
        if hasattr(v, "value"):
            d[k] = v.value
    # serialize nested IntentResult
    ir = d.get("intent_result")
    if ir and not isinstance(ir, dict):
        if hasattr(ir, "model_dump"):
            ir_d = ir.model_dump()
        elif hasattr(ir, "__dict__"):
            ir_d = ir.__dict__.copy()
        else:
            ir_d = {}
        for k, v in ir_d.items():
            if hasattr(v, "value"):
                ir_d[k] = v.value
        d["intent_result"] = ir_d
    return d


def _k2_raw_to_answer(raw: dict) -> dict:
    """Reconstruct a ChatAnswer dict from K2 Redis Hash fields."""
    def _or_none(v: str):
        return None if v == "" else v
    return {
        "code"  : int(raw.get("code", 0)),
        "answer": raw.get("answer", ""),
        "action": raw.get("action", "NONE"),
        "intent_result": {
            "intent"       : raw.get("intent", ""),
            "sentiment"    : raw.get("sentiment", ""),
            "sub_intent"   : _or_none(raw.get("sub_intent", "")),
            "action_code"  : _or_none(raw.get("action_code", "")),
            "refined_query": _or_none(raw.get("refined_query", "")),
            "category"     : _or_none(raw.get("category", "")),
        }
    }

def warmup(config_dir: str) -> None:
    import session.session_manager as sm

    faq_path = os.path.join(config_dir,
                            AiConfig.getStringConfig("redis.faq.file", "config/redis_faq_health.txt"))

    if not os.path.exists(faq_path):
        logger.warning(f"[cache] warmup faq file not found: {faq_path}")
        return

    try:
        _get_redis().flushdb()
        logger.debug("[cache] Redis flushed before warmup")
    except Exception as e:
        logger.warning(f"[cache] flush failed: {e}")

    # parse FAQ entries
    entries = []
    current_q, current_a = [], ""
    with open(faq_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("Q:"):
                current_q = [v.strip() for v in line[2:].strip().split("|") if v.strip()]
            elif line.startswith("A:"):
                current_a = line[2:].strip()
                if current_q and current_a:
                    entries.append((current_q, current_a))
                current_q, current_a = [], ""

    total_q = sum(len(e[0]) for e in entries)
    logger.debug(f"[cache] warmup start: {len(entries)} entries, {total_q} questions")

    success = 0
    for questions, faq_answer in entries:
        answer_dict = {
            "code"         : 0,
            "answer"       : faq_answer,
            "action"       : "NONE",
            "hit_source"   : "k1",
            "intent_result": {}
        }

        # K1 — write each Q variant, skip duplicates
        seen_hashes = set()
        for q in questions:
            norm = convert(q)
            h    = _make_hash(norm)
            if h in seen_hashes:
                logger.debug(f"[warmup] skip duplicate  hash={h}  q={q[:40]}")
                continue
            seen_hashes.add(h)
            k1_put(norm, answer_dict, permanent=True)
            success += 1

        # K2 — one representative vector per entry
        rep_q  = next((q for q in questions if "?" in q), questions[0])
        norm   = convert(rep_q)
        try:
            vector = sm.ACTIVE_EMBED.embed(norm)
            k2_put(norm, vector, answer_dict, permanent=True)
        except Exception as e:
            logger.warning(f"[cache] warmup k2 embed failed: {rep_q[:40]} — {e}")

    logger.debug(f"[cache] warmup complete: {success} K1 written, {len(entries)} K2 written")
def _vector_to_bytes(vector: list[float]) -> bytes:
    """Encode float list as raw bytes (4 bytes per float, little-endian)."""
    import struct
    return struct.pack(f"<{len(vector)}f", *vector)


def _bytes_to_vector(data: bytes) -> list[float]:
    """Decode bytes back to float list."""
    import struct
    n = len(data) // 4
    return list(struct.unpack(f"<{n}f", data))


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot  = sum(x * y for x, y in zip(a, b))
    na   = math.sqrt(sum(x * x for x in a))
    nb   = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ===========================================================================
# Self-test: python search/cache_service.py
# ===========================================================================
if __name__ == "__main__2":
    import random
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    AiConfig.configMap = {
        "base.dir":                "e:/ai",
        "redis.host":              "localhost",
        "redis.port":              "6379",
        "redis.db":                "0",
        "redis.convert.file":      "config/redis_convert_health.txt",
        "k1.lru.max":              "1000",
        "k2.lru.max":              "500",
        "k2.similarity.threshold": "0.90",
    }

    init()

    # ------------------------------------------------------------------
    # Test cases — pre-built ChatAnswer dicts covering all intent types
    # ------------------------------------------------------------------
    test_cases = [
        # QUERY — clinic hours
        {
            "question": "What are your clinic hours?",
            "answer": {
                "code": 0,
                "answer": "We are open Monday to Friday 8 AM to 6 PM, Saturday 9 AM to 1 PM.",
                "action": "NONE",
                "intent_result": {
                    "intent": "QUERY", "sentiment": "NEUTRAL",
                    "sub_intent": None, "action_code": None,
                    "refined_query": "clinic hours", "category": "hours",
                }
            }
        },
        # QUERY — prescription refill
        {
            "question": "Can I get a prescription refill by phone?",
            "answer": {
                "code": 0,
                "answer": "Yes, call us during office hours with your medication details.",
                "action": "NONE",
                "intent_result": {
                    "intent": "QUERY", "sentiment": "NEUTRAL",
                    "sub_intent": None, "action_code": None,
                    "refined_query": "prescription refill phone", "category": "prescription",
                }
            }
        },
        # COMMAND — transfer
        {
            "question": "Transfer me to an agent",
            "answer": {
                "code": 0,
                "answer": "Transferring you to a human agent, please hold.",
                "action": "TRANSFER",
                "intent_result": {
                    "intent": "COMMAND", "sentiment": "NEUTRAL",
                    "sub_intent": None, "action_code": "ACTION_TRANSFER",
                    "refined_query": "", "category": None,
                }
            }
        },
        # GREETING
        {
            "question": "Hello",
            "answer": {
                "code": 0,
                "answer": "Hello! How can I help you today?",
                "action": "NONE",
                "intent_result": {
                    "intent": "GREETING", "sentiment": "POSITIVE",
                    "sub_intent": None, "action_code": None,
                    "refined_query": "", "category": None,
                }
            }
        },
        # FEEDBACK — negative
        {
            "question": "Your service is terrible",
            "answer": {
                "code": 0,
                "answer": "I'm sorry to hear that. Let me transfer you to a senior staff member.",
                "action": "TRANSFER",
                "intent_result": {
                    "intent": "FEEDBACK", "sentiment": "NEGATIVE",
                    "sub_intent": None, "action_code": "ACTION_TRANSFER",
                    "refined_query": "", "category": None,
                }
            }
        },
        # CHITCHAT
        {
            "question": "Tell me a joke",
            "answer": {
                "code": 0,
                "answer": "I'm better at answering clinic questions, but I'll try! Why did the doctor carry a red pen? In case they needed to draw blood!",
                "action": "NONE",
                "intent_result": {
                    "intent": "CHITCHAT", "sentiment": "POSITIVE",
                    "sub_intent": None, "action_code": None,
                    "refined_query": "", "category": None,
                }
            }
        },
    ]

    # ------------------------------------------------------------------
    # Pre-load all test cases into K1
    # ------------------------------------------------------------------
    print("\n── pre-loading test cases into K1 ──")
    for tc in test_cases:
        k1_put(tc["question"], tc["answer"])
        print(f"  put: {tc['question']}")

    # ------------------------------------------------------------------
    # K1 exact match tests
    # ------------------------------------------------------------------
    print("\n── K1 exact match tests ──")
    queries = [
        "What are your clinic hours?",           # exact
        "Could you tell me your clinic hours?",  # convert归一 → same hash
        "transfer me to an agent",               # exact lowercase
        "hello",                                 # greeting
        "This question is not in cache.",        # miss
    ]
    for q in queries:
        hit = k1_get(q)
        tag = "HIT " if hit else "MISS"
        print(f"  [{tag}] {q}")
        if hit:
            print(f"         action={hit.get('action')}  intent={hit.get('intent_result', {}).get('intent')}")

    # ------------------------------------------------------------------
    # K2 semantic match tests (fake vectors — dim=8 for test speed)
    # ------------------------------------------------------------------
    print("\n── K2 semantic match tests (fake 8-dim vectors) ──")

    def fake_vec(seed: int, dim: int = 8) -> list[float]:
        random.seed(seed)
        v = [random.gauss(0, 1) for _ in range(dim)]
        norm = math.sqrt(sum(x*x for x in v))
        return [x / norm for x in v]

    # Write 3 entries into K2
    k2_entries = [
        ("clinic hours",      fake_vec(1), test_cases[0]["answer"]),
        ("prescription refill", fake_vec(2), test_cases[1]["answer"]),
        ("transfer agent",    fake_vec(3), test_cases[2]["answer"]),
    ]
    for norm_q, vec, ans in k2_entries:
        k2_put(norm_q, vec, ans)
        print(f"  k2_put: {norm_q}")

    # Query with very similar vector (same seed → cosine=1.0)
    print()
    for norm_q, vec, _ in k2_entries:
        hit = k2_get(norm_q, vec)
        tag = "HIT " if hit else "MISS"
        print(f"  [{tag}] semantic: {norm_q}")
        if hit:
            print(f"         answer={hit.get('answer', '')[:60]}...")

    # Query with dissimilar vector → should miss
    dissimilar = fake_vec(99)
    hit = k2_get("some random query", dissimilar)
    print(f"  [{'HIT ' if hit else 'MISS'}] dissimilar vector (expected MISS)")

if __name__ == "__main__":
    import math
    import random
    import logging

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # ── 配置 ────────────────────────────────────────────────────────────
    AiConfig.configMap = {
        "base.dir":                "e:/ai",
        "redis.host":              "localhost",
        "redis.port":              "6379",
        "redis.db":                "0",
        "redis.convert.file":      "config/redis_convert_health.txt",
        "k1.lru.max":              "1000",
        "k2.lru.max":              "500",
        "k2.similarity.threshold": "0.90",
    }

    init()

    # ── 知识库：粤教翔云 FAQ ────────────────────────────────────────────
    # 每条 entry = (representative_question, norm_key, ChatAnswer)
    faq: list[tuple[str, str, dict]] = [
        (
            "老师的电脑配置是什么",
            "teacher client system requirements",
            {
                "code": 0,
                "answer": "电脑客户端要求Windows 7或以上的操作系统。不支持在任何手机或平板设备（如 iPad）上安装使用。",
                "action": "NONE",
                "intent_result": {
                    "intent": "QUERY", "sentiment": "NEUTRAL",
                    "sub_intent": None, "action_code": None,
                    "refined_query": "teacher client system requirements",
                    "category": "system",
                },
            },
        ),
        (
            "老师的账号是多少",
            "teacher account password",
            {
                "code": 0,
                "answer": "账号为个人身份证号码，初始密码为大写A202101小写b。若忘记密码，可在登录页面点击忘记密码通过手机接收验证码重置。",
                "action": "NONE",
                "intent_result": {
                    "intent": "QUERY", "sentiment": "NEUTRAL",
                    "sub_intent": None, "action_code": None,
                    "refined_query": "teacher account password",
                    "category": "account",
                },
            },
        ),
        (
            "什么是云教案",
            "cloud lesson plan feature",
            {
                "code": 0,
                "answer": "是以教案为单位，将课件、数字教材、碎片资源、小测等组合在一起的数字化备课功能。",
                "action": "NONE",
                "intent_result": {
                    "intent": "QUERY", "sentiment": "NEUTRAL",
                    "sub_intent": None, "action_code": None,
                    "refined_query": "cloud lesson plan feature",
                    "category": "feature",
                },
            },
        ),
        (
            "学生的电脑配置是什么",
            "student client system requirements",
            {
                "code": 0,
                "answer": "电脑客户端支持Windows 7或以上，安卓客户端支持安卓6.0版本或以上，苹果客户端支持iOS 13或以上的系统。",
                "action": "NONE",
                "intent_result": {
                    "intent": "QUERY", "sentiment": "NEUTRAL",
                    "sub_intent": None, "action_code": None,
                    "refined_query": "student client system requirements",
                    "category": "system",
                },
            },
        ),
        (
            "学生的账号是什么",
            "student account password",
            {
                "code": 0,
                "answer": "个人账号是学生的个人身份证号码，初始密码是向大写A202101小写b。",
                "action": "NONE",
                "intent_result": {
                    "intent": "QUERY", "sentiment": "NEUTRAL",
                    "sub_intent": None, "action_code": None,
                    "refined_query": "student account password",
                    "category": "account",
                },
            },
        ),
        (
            "学生忘记密码怎么办",
            "student forgot password reset",
            {
                "code": 0,
                "answer": "若没绑定手机号，需联系本班教师或学校管理员重置密码；若已绑定手机号，可通过登录页面点击忘记密码自助重置。",
                "action": "NONE",
                "intent_result": {
                    "intent": "QUERY", "sentiment": "NEUTRAL",
                    "sub_intent": None, "action_code": None,
                    "refined_query": "student forgot password reset",
                    "category": "account",
                },
            },
        ),
        (
            "管理员账号是多少",
            "admin account password",
            {
                "code": 0,
                "answer": "管理员账号是本校十位数的学校标识码，初始密码统一由所属教育局下发。",
                "action": "NONE",
                "intent_result": {
                    "intent": "QUERY", "sentiment": "NEUTRAL",
                    "sub_intent": None, "action_code": None,
                    "refined_query": "admin account password",
                    "category": "account",
                },
            },
        ),
        (
            "管理员忘记密码怎么办",
            "admin forgot password reset",
            {
                "code": 0,
                "answer": "管理员账号是本校十位数的学校标识码，忘记密码可在登录页面通过手机验证码找回密码。",
                "action": "NONE",
                "intent_result": {
                    "intent": "QUERY", "sentiment": "NEUTRAL",
                    "sub_intent": None, "action_code": None,
                    "refined_query": "admin forgot password reset",
                    "category": "account",
                },
            },
        ),
    ]

    # ── 预加载全部 FAQ 到 K1 ────────────────────────────────────────────
    print("\n── 预加载 FAQ 到 K1 ──")
    for rep_q, _, answer in faq:
        k1_put(rep_q, answer)
        print(f"  put: {rep_q}")

    # ── K1 精确命中测试 ────────────────────────────────────────────────
    print("\n── K1 精确/归一命中测试 ──")
    k1_queries = [
        ("老师的电脑配置是什么",       True,  "原句，应命中"),
        ("教师客户端下载",             True,  "同义词归一后应命中"),
        ("老师端系统Windows要求",      True,  "同义词归一后应命中"),
        ("老师的账号是多少",           True,  "原句，应命中"),
        ("忘记密码怎么修改",           True,  "同义词归一后应命中"),
        ("学生的账号是什么",           True,  "原句，应命中"),
        ("孩子账号是什么",             True,  "同义词归一后应命中"),
        ("学生忘记密码怎么办",         True,  "原句，应命中"),
        ("学生手机没绑定怎么办",       True,  "同义词归一后应命中"),
        ("管理员账号是多少",           True,  "原句，应命中"),
        ("这个问题不在知识库里面",     False, "应 MISS"),
    ]

    pass_k1 = 0
    for q, expect_hit, note in k1_queries:
        hit = k1_get(q)
        got_hit = hit is not None
        ok = got_hit == expect_hit
        tag = "✓" if ok else "✗"
        ht = "HIT " if got_hit else "MISS"
        print(f"  [{tag}][{ht}] {q}  ({note})")
        if got_hit and hit:
            print(f"          action={hit.get('action')}  "
                  f"intent={hit.get('intent_result', {}).get('intent')}")
        if ok:
            pass_k1 += 1

    print(f"\n  K1 结果: {pass_k1}/{len(k1_queries)} 通过")

    # ── K2 语义命中测试（fake 8-dim 向量，仅验证存取逻辑）────────────────
    print("\n── K2 语义命中测试（fake 8-dim 向量）──")

    def fake_vec(seed: int, dim: int = 8) -> list[float]:
        random.seed(seed)
        v = [random.gauss(0, 1) for _ in range(dim)]
        norm = math.sqrt(sum(x * x for x in v))
        return [x / norm for x in v]

    # 把有 norm_key 的 FAQ 条目写入 K2
    k2_entries = [
        (norm_key, fake_vec(i), answer)
        for i, (_, norm_key, answer) in enumerate(faq)
        if norm_key
    ]

    print()
    for norm_q, vec, ans in k2_entries:
        k2_put(norm_q, vec, ans)
        print(f"  k2_put: {norm_q}")

    # 用同一个向量查询（cosine = 1.0，必然命中）
    print()
    pass_k2 = 0
    for norm_q, vec, _ in k2_entries:
        hit = k2_get(norm_q, vec)
        ok = hit is not None
        tag = "✓" if ok else "✗"
        ht = "HIT " if ok else "MISS"
        print(f"  [{tag}][{ht}] {norm_q}")
        if ok:
            pass_k2 += 1
            print(f"          answer={hit.get('answer', '')[:50]}...")

    # 用不相关向量查询 → 应 MISS
    dissimilar = fake_vec(9999)
    hit = k2_get("完全不相关的问题", dissimilar)
    dis_ok = hit is None
    print(f"  [{'✓' if dis_ok else '✗'}][{'MISS' if dis_ok else 'HIT '}] "
          f"不相关向量（预期 MISS）")

    print(f"\n  K2 结果: {pass_k2}/{len(k2_entries)} 语义命中，"
          f"不相关向量: {'正确 MISS' if dis_ok else '错误 HIT'}")

    # ── 汇总 ────────────────────────────────────────────────────────────
    print("\n══════════════════════════════════")
    print(f"  K1: {pass_k1}/{len(k1_queries)}")
    print(f"  K2: {pass_k2}/{len(k2_entries)}  +  dissimilar={'OK' if dis_ok else 'FAIL'}")
    print("══════════════════════════════════")