# handler/inform_handler.py
# Java: package com.lcallai.handler;
import logging
import random

from intent.intent_handler import IntentHandler
from intent.intent_result import IntentResult
from models import ChatAnswer

logger = logging.getLogger(__name__)

# Java: private static final String[] RESPONSES = { ... };
RESPONSES = [
    "好的，我已经记下了。请问还有什么我可以帮您的吗？",
    "明白了，感谢您告诉我。请问有什么需要进一步了解的吗？",
    "好的，我知道了。您还有其他问题吗？",
    "嗯，我记住了。请问接下来有什么需要帮您处理的？",
    "收到，谢谢您的说明。请问还有什么我能帮到您的？",
]


class InformHandler(IntentHandler):
    """
    public ChatAnswer handle(String rawText, IntentResult result, ChatSession session) {
        logger.debug("[InformHandler] 已记录用户背景信息: " + rawText);
        if (result.category != null && !result.category.isBlank()) {
            session.setCurrentCategory(result.category);
        }
        String pending = session.getPendingQuery();
        if (pending != null) {
            session.clearPendingQuery();
            return session.askByQueryMode(pending, false);
        }
        String reply = RESPONSES[new Random().nextInt(RESPONSES.length)];
        return new ChatAnswer(0, reply, result);
    }
    """
    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        logger.debug("[InformHandler] 已记录用户背景信息: " + raw_text)

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
            return session.askByQueryMode(pending, False)

        # Java: String reply = RESPONSES[new Random().nextInt(RESPONSES.length)];
        reply = random.choice(RESPONSES)
        return ChatAnswer(code=0, answer=reply)
