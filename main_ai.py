# main_ai.py  —— voice agent 对话路由（原 main.py 改名）
# 不再独立启动，由 main.py 统一 include

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
import logging
import time
from models import ChatRequest, ChatAnswer
import session.session_manager as session_manager
from handler.filling_handler    import FillingHandler
from handler.filling_handler_ai import FillingHandlerAI
from intent.intent_result import IntentResult, Intent
import search.mongo_service as mongo_service
logger = logging.getLogger(__name__)

router = APIRouter()

_filling_handler    = FillingHandler()
_filling_handler_ai = FillingHandlerAI()
def _sanitize_text(text: str) -> str:
    """去除无法编码为 UTF-8 的孤立代理项字符（lone surrogates），
    常见于 ASR 识别结果中混入被截断的 emoji/特殊符号。"""
    if not text:
        return text
    return text.encode("utf-8", errors="ignore").decode("utf-8")


import time
import asyncio


@router.post("/ai_send")
async def ai_send(req: ChatRequest) -> ChatAnswer:

    t0 = time.time()
    req.text = _sanitize_text(req.text)

    try:
        t_mongo1 = time.time()
        await run_in_threadpool(
            mongo_service.upsert_call,
            sn         = req.sn,
            phone      = req.phone      or "",
            vo_id      = req.vo_id      or "ai_send",
            ch         = req.ch         or "",
            call_date  = req.call_date  or "",
            start_time = req.start_time or "",
        )
        upsert_elapsed = int((time.time()-t_mongo1)*1000)
        logger.debug(f"[sn={req.sn}] upsert_call elapsed: {upsert_elapsed}ms")
    except Exception as e:
        upsert_elapsed = -1
        logger.error(f"upsert_call error: {e}", exc_info=True)

    session = session_manager.get_session(req.sn)
    session.setCRID(req.crid)
    session._caller_phone = req.phone or "9"

    t_ask_start = time.time()
    answer = await session.ask_skill(req.text)
    if answer is None:
        answer = await run_in_threadpool(session.ask, req.text)
    ask_layer_elapsed = int((time.time() - t_ask_start) * 1000)

    elapsed = int((time.time() - t0) * 1000)

    # ── 补上 main_ai 层面的总耗时,方便定位没被下层统计到的开销 ──
    if answer.cost is None:
        answer.cost = {}
    answer.cost["upsert_call"]      = upsert_elapsed
    answer.cost["ask_layer_total"]  = ask_layer_elapsed   # ask_skill+ask 加起来的真实耗时(含ask_skill内部除chat_with_tools外的逻辑)
    answer.cost["server_total"]     = elapsed

    logger.debug(f"[sn={req.sn}] [main_ai] upsert={upsert_elapsed}ms  ask_layer={ask_layer_elapsed}ms  server_total={elapsed}ms")

    intent    = str(session.currentIntentResult.intent.name) if session.currentIntentResult else None
    category  = session.currentCategory
    hit_source = answer.hit_source if hasattr(answer, "hit_source") else None

    asyncio.create_task(
        _save_turn_async(
            sn=req.sn, crid=req.crid or "", user_text=req.text,
            answer=answer.answer or "", intent=intent, category=category,
            hit_source=hit_source, elapsed_ms=elapsed,
        )
    )

    return answer

async def _save_turn_async(**kwargs):
    """后台异步写 Mongo，失败不影响主流程，只记日志"""
    t0 = time.time()
    try:
        await run_in_threadpool(mongo_service.save_turn, **kwargs)
        logger.debug(f"[sn={kwargs.get('sn')}] save_turn elapsed: {int((time.time()-t0)*1000)}ms (async)")
    except Exception as e:
        logger.error(f"save_turn error: {e}", exc_info=True)

@router.post("/filling")
async def filling(req: ChatRequest) -> ChatAnswer:
    session = session_manager.get_session(req.sn)
    result  = IntentResult(intent=Intent.INFORM)
    req.text = _sanitize_text(req.text)
    resp    = await run_in_threadpool(_filling_handler.handle, req.text, result, session)
    logger.debug("eivrResponse=" + str(resp))
    return resp


@router.post("/filling_ai")
async def filling_ai(req: ChatRequest) -> ChatAnswer:
    session = session_manager.get_session(req.sn)
    req.text = _sanitize_text(req.text)
    result  = IntentResult(intent=Intent.INFORM)
    resp    = await run_in_threadpool(_filling_handler_ai.handle, req.text, result, session)
    logger.debug("eivrResponse=" + str(resp))
    return resp
