# intent/intent_dispatcher.py
# Java: package com.lcallai.intent;
import logging
from typing import Dict

from intent.intent_result import Intent, IntentResult

logger = logging.getLogger(__name__)


class IntentDispatcher:
    """
    public class IntentDispatcher {
        private final Map<IntentResult.Intent, IntentHandler> handlers =
                new EnumMap<>(IntentResult.Intent.class);
    }
    """

    def __init__(self):
        # Java: private final Map<IntentResult.Intent, IntentHandler> handlers = new EnumMap<>(...);
        self._handlers: Dict[Intent, object] = {}

    """
    public IntentDispatcher register(IntentResult.Intent intent, IntentHandler handler) {
        handlers.put(intent, handler);
        return this;
    }
    """
    def register(self, intent: Intent, handler) -> "IntentDispatcher":
        self._handlers[intent] = handler
        return self

    """
    public ChatAnswer dispatch(String rawText, IntentResult result, ChatSession session) {
        IntentHandler handler = handlers.get(result.intent);
        if (handler == null) {
            logger.error("[IntentDispatcher] 未注册的 intent: " + result.intent + "，降级为 QUERY");
            handler = handlers.get(IntentResult.Intent.QUERY);
        }
        if (handler == null) {
            return new ChatAnswer(-1, "系统配置错误：未找到任何可用的意图处理器");
        }
        return handler.handle(rawText, result, session);
    }
    """
    def dispatch(self, raw_text: str, result: IntentResult, session) -> object:
        handler = self._handlers.get(result.intent)

        if handler is None:
            logger.error("[IntentDispatcher] 未注册的 intent: " + str(result.intent) + "，降级为 QUERY")
            handler = self._handlers.get(Intent.QUERY)

        if handler is None:
            from models import ChatAnswer
            return ChatAnswer(code=-1, answer="系统配置错误：未找到任何可用的意图处理器")

        return handler.handle(raw_text, result, session)

    """
    public boolean isRegistered(IntentResult.Intent intent) {
        return handlers.containsKey(intent);
    }
    """
    def is_registered(self, intent: Intent) -> bool:
        return intent in self._handlers
