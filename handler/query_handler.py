# handler/query_handler.py
# Java: package com.lcallai.handler;
import logging

from intent.intent_handler import IntentHandler
from intent.intent_result import IntentResult
from models import ChatAnswer

logger = logging.getLogger(__name__)


class QueryHandler(IntentHandler):
    """
    public ChatAnswer handle(String rawText, IntentResult result, ChatSession session) {
        logger.debug("[QueryHandler] refinedQuery=" + result.refinedQuery);
        if (!"simple".equalsIgnoreCase(session.getQueryMode())) {
            if (session.getCurrentCategory() == null) {
                return new ChatAnswer(0, "请问您是老师、学生还是管理员呢？", result);
            }
        }
        return session.askByQueryMode(result.refinedQuery, false);
    }
    """
    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        logger.debug("[QueryHandler] refinedQuery=" + str(result.refined_query))

        # Java: if (!"simple".equalsIgnoreCase(session.getQueryMode()))
        if not "simple".lower() == (session.getQueryMode() or "").lower():
            # Java: if (session.getCurrentCategory() == null)
            if session.getCurrentCategory() is None:
                return ChatAnswer(code=0, answer="请问您是老师、学生还是管理员呢？")

        # Java: return session.askByQueryMode(result.refinedQuery, false);
        return session.askByQueryMode(result.refined_query, False)
