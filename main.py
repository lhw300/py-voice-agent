# main.py  —— 统一启动入口
# 启动方式不变: ./venv/bin/python main.py

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import ai_config as AiConfig

# ── Config dir：必须先确定，不能走 ai.conf fallback（它是定位 ai.conf 的输入）──
CONFIG_DIR     = os.environ.get("AI_CONFIG_DIR",  "/home/call/py-voice-agent")


# ── 新增：提前 init AiConfig，使下面的 LOG_DIR 等参数能读到 ai.conf ──────────
# AiConfig.reload() 是幂等的，session_manager.init() 之后还会再 init 一次，
# 不会有冲突，只是多读一次文件，可忽略不计。
AiConfig.init(CONFIG_DIR)


# ── Logging（改动点：三级 fallback）────────────────────────────────────────
LOG_DIR = os.environ.get(
    "LOG_DIR",
    AiConfig.getStringConfig("log.dir", "/home/call/py-voice-agent/logs")
)
LOG_MAX_BYTES = int(os.environ.get(
    "LOG_MAX_BYTES",
    AiConfig.getStringConfig("log.max_bytes", str(10 * 1024 * 1024))
))
LOG_BACKUP_COUNT = int(os.environ.get(
    "LOG_BACKUP_COUNT",
    AiConfig.getStringConfig("log.backup_count", "5")
))

os.makedirs(LOG_DIR, exist_ok=True)

_formatter = logging.Formatter(
    "%(levelname)s: %(asctime)s %(name)s:%(lineno)s %(message)s"
)
logging.getLogger("pymongo").setLevel(logging.WARNING)

_console_handler = logging.StreamHandler(stream=sys.stdout)
_console_handler.setFormatter(_formatter)

_file_handler = RotatingFileHandler(
    filename=os.path.join(LOG_DIR, "a.log"),
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8",
)
_file_handler.setFormatter(_formatter)

logging.basicConfig(level=logging.DEBUG, handlers=[_console_handler, _file_handler], force=True)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

import session.session_manager as session_manager
from search.embedding_client import EmbeddingClient
import search.mongo_service as mongo_service
import main_ai
import web.main_web as web_router
import web.auth_router as auth_router


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    session_manager.init(config_dir=CONFIG_DIR)
    session_manager.warm_up()

    from session.session_manager import ACTIVE_EMBED
    embed_client = ACTIVE_EMBED
    table        = AiConfig.getStringConfig("db.postgres.table.online", "enterprise_knowledge_1024")
    web_router.init(embed_client, table)
    mongo_service.init()
    logger.info(f"✅ Ready — port 7626  config={CONFIG_DIR}  table={table}")
    yield
    logger.info("🛑 Shutting down ...")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="LCallAI Voice Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(web_router.router)  # /api/...
app.include_router(main_ai.router)     # /ai_send  /filling  /filling_ai
app.include_router(auth_router.router)

@app.get("/health")
def health():
    return {"status": "ok", "config_file": AiConfig.configFile}

app.mount("/aiweb", StaticFiles(directory="web/dist", html=True), name="static")
if __name__ == "__main__":
    reload = os.environ.get("APP_RELOAD", "false").lower() == "true"
    uvicorn.run("main:app", host="0.0.0.0", port=7626, reload=False)