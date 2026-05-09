# main.py
import logging
import os
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool

from models import ChatRequest, ChatAnswer
import session.session_manager as session_manager
from handler.filling_handler    import FillingHandler
from handler.filling_handler_ai import FillingHandlerAI
from intent.intent_result import IntentResult, Intent

logging.basicConfig(
    format="%(levelname)s: %(asctime)s %(name)s:%(lineno)s %(message)s",
    level=logging.DEBUG,
    stream=sys.stdout,
    force=True,
)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Config directory — matches Java: SessionManager.init(baseDir)
CONFIG_DIR = os.environ.get("AI_CONFIG_DIR", "e:/ai")

app = FastAPI()


@app.on_event("startup")
def startup():
    # Java: SessionManager.init(configPath);
    session_manager.init(config_dir=CONFIG_DIR)


# ---------------------------------------------------------------------------
# /ai_send — mirrors Java ChatManager.ask() → SessionManager.getSession() → session.ask()
# run_in_threadpool: releases the async event loop during blocking LLM calls,
# allowing concurrent requests from different sn's to be handled simultaneously.
# ---------------------------------------------------------------------------
@app.post("/ai_send")
async def ai_send(req: ChatRequest) -> ChatAnswer:
    # Java: ChatSession session = SessionManager.getSession(sn);
    session = session_manager.get_session(req.sn)
    session.setCRID(req.crid)
    # Java: session.askString(text)
    return await run_in_threadpool(session.ask, req.text)


# ---------------------------------------------------------------------------
# /filling — rule-based slot filling
# ---------------------------------------------------------------------------
_filling_handler = FillingHandler()

@app.post("/filling")
async def filling(req: ChatRequest) -> ChatAnswer:
    session = session_manager.get_session(req.sn)
    result  = IntentResult(intent=Intent.INFORM)
    resp    = await run_in_threadpool(_filling_handler.handle, req.text, result, session)
    logger.debug("eivrResponse=" + str(resp))
    return resp


# ---------------------------------------------------------------------------
# /filling_ai — AI-driven slot filling
# ---------------------------------------------------------------------------
_filling_handler_ai = FillingHandlerAI()

@app.post("/filling_ai")
async def filling_ai(req: ChatRequest) -> ChatAnswer:
    session = session_manager.get_session(req.sn)
    result  = IntentResult(intent=Intent.INFORM)
    resp    = await run_in_threadpool(_filling_handler_ai.handle, req.text, result, session)
    logger.debug("eivrResponse=" + str(resp))
    return resp


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=False)