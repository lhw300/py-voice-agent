# handler/ack_handler.py
# Java: package com.lcallai.handler;
from intent.intent_handler import IntentHandler
from intent.intent_result import IntentResult
from models import ChatAnswer
import ai_config as AiConfig

class AckHandler(IntentHandler):

    # def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
    #     sub = result.sub_intent  # Java: result.subIntent
    #
    #     # Java: if ("affirm".equalsIgnoreCase(sub))
    #     if sub and sub.lower() == "affirm":
    #         return ChatAnswer(code=0, answer="好的，已确认。请问还有什么可以帮您？")
    #
    #     # Java: if ("negate".equalsIgnoreCase(sub))
    #     if sub and sub.lower() == "negate":
    #         return ChatAnswer(code=0, answer="好的，没问题。如有需要随时告诉我。")
    #
    #     # Java: return new ChatAnswer(0, "好的！请问有什么可以帮您？", result);
    #     return ChatAnswer(code=0, answer="好的！请问有什么可以帮您？")

    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        sub = (result.sub_intent or "").lower()
        if sub == "affirm":
            text = AiConfig.getStringConfig("response.ack.affirm", "Got it. Anything else?")
        elif sub == "negate":
            text = AiConfig.getStringConfig("response.ack.negate", "No problem. Let me know if you need anything.")
        else:
            text = AiConfig.getStringConfig("response.ack.default", "Sure! What can I help you with?")
        return ChatAnswer(code=0, answer=text)
