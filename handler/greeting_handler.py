# handler/greeting_handler.py
# Java: package com.lcallai.handler;
import logging
import random
import re

from intent.intent_handler import IntentHandler
from intent.intent_result import IntentResult
from models import ChatAnswer
import ai_config as AiConfig
logger = logging.getLogger(__name__)

# Java: private static final String[] POOL = { ... };


class GreetingHandler(IntentHandler):

    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        # farewell = AiConfig.getStringConfig("response.greeting.farewell", "Goodbye!")
        # farewell_pattern = AiConfig.getStringConfig(
        #     "greeting.farewell.pattern", r"bye|goodbye|see you|take care|hang up"
        # )
        # if re.search(farewell_pattern, raw_text, re.IGNORECASE):
        #     return ChatAnswer(code=0, answer=farewell)

        pool_str = AiConfig.getStringConfig("response.greeting.pool", "Hello! How can I help you?")
        pool = [s.strip() for s in pool_str.split("|") if s.strip()]
        return ChatAnswer(code=200, answer=random.choice(pool))
