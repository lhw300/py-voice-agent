import logging
from typing import Dict
from intent.intent_result import Intent, IntentResult

logger = logging.getLogger(__name__)


class IntentDispatcher:

    def __init__(self):
        self._handlers: Dict[Intent, object] = {}

    def register(self, intent: Intent, handler) -> "IntentDispatcher":
        """注册Handler，支持链式调用"""
        self._handlers[intent] = handler
        return self

    def dispatch(self, raw_text: str, result: IntentResult, session) -> object:
        """根据意图派发到对应Handler"""
        handler = self._handlers.get(result.intent)

        if handler is None:
            logger.error(f" 未注册的intent: {result.intent}，降级为QUERY")
            handler = self._handlers.get(Intent.QUERY)

        if handler is None:
            from models import EivrResponse
            return EivrResponse(code=-1, answer="系统配置错误：未找到任何可用的意图处理器")

        return handler.handle(raw_text, result, session)

    def is_registered(self, intent: Intent) -> bool:
        return intent in self._handlers
