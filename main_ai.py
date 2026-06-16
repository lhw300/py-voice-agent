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

@router.post("/ai_send")
async def ai_send(req: ChatRequest) -> ChatAnswer:

    t0 = time.time()
    try:
    # 第一次 sn 进来 → upsert 通话记录
        mongo_service.upsert_call(
            sn         = req.sn,
            phone      = req.phone      or "",
            vo_id      = req.vo_id      or "ai_send",
            ch         = req.ch         or "",
            call_date  = req.call_date  or "",
            start_time = req.start_time or "",
        )
    except Exception as e:
        logger.error(f"upsert_call error: {e}", exc_info=True)
    session = session_manager.get_session(req.sn)
    session.setCRID(req.crid)
    answer: ChatAnswer = await run_in_threadpool(session.ask, req.text)

    elapsed = int((time.time() - t0) * 1000)

    # 每轮追加 turn
    intent    = str(session.currentIntentResult.intent.name) if session.currentIntentResult else None
    category  = session.currentCategory
    hit_source = answer.hit_source if hasattr(answer, "hit_source") else None

    mongo_service.save_turn(
        sn         = req.sn,
        crid       = req.crid or "",
        user_text  = req.text,
        answer     = answer.answer or "",
        intent     = intent,
        category   = category,
        hit_source = hit_source,
        elapsed_ms = elapsed,
    )

    return answer

@router.post("/filling")
async def filling(req: ChatRequest) -> ChatAnswer:
    session = session_manager.get_session(req.sn)
    result  = IntentResult(intent=Intent.INFORM)
    resp    = await run_in_threadpool(_filling_handler.handle, req.text, result, session)
    logger.debug("eivrResponse=" + str(resp))
    return resp


@router.post("/filling_ai")
async def filling_ai(req: ChatRequest) -> ChatAnswer:
    session = session_manager.get_session(req.sn)
    result  = IntentResult(intent=Intent.INFORM)
    resp    = await run_in_threadpool(_filling_handler_ai.handle, req.text, result, session)
    logger.debug("eivrResponse=" + str(resp))
    return resp
