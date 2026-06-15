# handler/inform_handler.py
# Java: package com.lcallai.handler;
import logging
import random

from intent.intent_handler import IntentHandler
from intent.intent_result import IntentResult
from models import ChatAnswer
import ai_config as AiConfig
logger = logging.getLogger(__name__)

# Java: private static final String[] RESPONSES = { ... };


class InformHandler(IntentHandler):

    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        logger.debug("[InformHandler] recorded user background info: " + raw_text)

        # Java: if (result.category != null && !result.category.isBlank())
        if result.category and result.category.strip():
            # Java: session.setCurrentCategory(result.category);
            session.setCurrentCategory(result.category)

        # Java: String pending = session.getPendingQuery();
        pending = session.getPendingQuery()

        # Java: if (pending != null)
        if pending is not None:
            # Java: session.clearPendingQuery();
            session.clearPendingQuery()
            # Java: return session.askByQueryMode(pending, false);
            return session.askByQueryMode(pending, False, allow_cache_write=False)

        pool_str = AiConfig.getStringConfig("response.inform.ack", "Got it. Anything else I can help with?")
        pool = [s.strip() for s in pool_str.split("|") if s.strip()]
        reply = random.choice(pool)
        return ChatAnswer(code=0, answer=reply)
