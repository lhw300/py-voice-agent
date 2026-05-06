import logging
from typing import Dict
from session.chat_session import ChatSession
from intent.intent_classifier import IntentClassifier
from intent.intent_dispatcher import IntentDispatcher
from intent.intent_result import Intent
from handler.greeting_handler import GreetingHandler
from handler.query_handler import QueryHandler
from handler.filling_handler import FillingHandler
logger = logging.getLogger(__name__)

sessions: Dict[str, ChatSession] = {}
_classifier = None
_dispatcher = None


def init():
    global _classifier, _dispatcher

    _classifier = IntentClassifier()

    _dispatcher = (IntentDispatcher()
        .register(Intent.GREETING, GreetingHandler())
        .register(Intent.QUERY,    QueryHandler())   # ← 新增
        .register(Intent.INFORM,   FillingHandler())  # ← filling走INFORM意图
    )




    logger.info("SessionManager initialized")


def get_session(session_id: str) -> ChatSession:
    if session_id not in sessions:
        session = ChatSession(session_id)
        session.set_intent_pipeline(_classifier, _dispatcher)
        sessions[session_id] = session
        logger.debug(f" create new session sn={session_id}")
    return sessions[session_id]
