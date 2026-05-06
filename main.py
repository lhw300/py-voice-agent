import logging
import uvicorn
from fastapi import FastAPI
from models import EivrRequest, EivrResponse
import session.session_manager as session_manager
from handler.filling_handler import FillingHandler
from handler.filling_handler_ai import FillingHandlerAI
import os

import sys
logging.basicConfig(
    format='%(levelname)s: %(asctime)s %(name)s:%(lineno)s %(message)s',
    level=logging.DEBUG,
    stream=sys.stdout   ,
    force=True
)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
os.environ["DASHSCOPE_API_KEY"] = "你的key"
app = FastAPI()


@app.on_event("startup")
def startup():
    session_manager.init()


@app.post("/ai_send")
async def ai_send(req: EivrRequest) -> EivrResponse:
    session = session_manager.get_session(req.sn)
    return session.ask(req.text)

filling_handler = FillingHandler()
@app.post("/filling")
async def filling(req: EivrRequest) -> EivrResponse:
    session = session_manager.get_session(req.sn)
    from intent.intent_result import IntentResult, Intent
    result = IntentResult(intent=Intent.INFORM)
    eivrResponse= filling_handler.handle(req.text, result, session)
    logger.debug(f"eivrResponse={eivrResponse}")
    return eivrResponse

filling_handler_ai = FillingHandlerAI()

@app.post("/filling_ai")
async def filling_ai(req: EivrRequest) -> EivrResponse:
    session = session_manager.get_session(req.sn)
    from intent.intent_result import IntentResult, Intent
    result = IntentResult(intent=Intent.INFORM)
    eivrResponse= filling_handler_ai.handle(req.text, result, session)
    logger.debug(f"eivrResponse={eivrResponse}")
    return eivrResponse


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=False)
