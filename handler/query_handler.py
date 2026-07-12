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
    import logging
import ai_config as AiConfig
from intent.intent_handler import IntentHandler
from intent.intent_result import IntentResult
from models import ChatAnswer

logger = logging.getLogger(__name__)

class QueryHandler(IntentHandler):

    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        logger.debug("[QueryHandler] refinedQuery=" + str(result.refined_query))
        # ★ 新增：优先处理"续接被搁置的问题" ★
        pending = session.getPendingQuery()
        if pending is not None:
            if result.category and result.category.strip():
                session.setCurrentCategory(result.category)
            if session.getCurrentCategory() is not None:
                logger.debug("[QueryHandler] 续接被搁置的问题: " + pending)
                session.clearPendingQuery()
                return session.askByQueryMode(pending, False, allow_cache_write=False)
            # 身份还没确认，继续走下面的常规追问逻辑

        category_required = AiConfig.getBooleanConfig("query.category.required", False)

        if category_required and session.getCurrentCategory() is None:
            ask_text = AiConfig.getStringConfig(
                "response.query.ask_category",
                "May I ask, are you a teacher, student, or administrator?"
            )
            return ChatAnswer(code=0, answer=ask_text)

        return session.askByQueryMode(result.refined_query, False)

