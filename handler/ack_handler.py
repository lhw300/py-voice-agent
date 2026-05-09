# handler/ack_handler.py
# Java: package com.lcallai.handler;
from intent.intent_handler import IntentHandler
from intent.intent_result import IntentResult
from models import ChatAnswer


class AckHandler(IntentHandler):
    """
    public ChatAnswer handle(String rawText, IntentResult result, ChatSession session) {
        String sub = result.subIntent;
        if ("affirm".equalsIgnoreCase(sub)) {
            return new ChatAnswer(0, "好的，已确认。请问还有什么可以帮您？", result);
        }
        if ("negate".equalsIgnoreCase(sub)) {
            return new ChatAnswer(0, "好的，没问题。如有需要随时告诉我。", result);
        }
        return new ChatAnswer(0, "好的！请问有什么可以帮您？", result);
    }
    """
    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        sub = result.sub_intent  # Java: result.subIntent

        # Java: if ("affirm".equalsIgnoreCase(sub))
        if sub and sub.lower() == "affirm":
            return ChatAnswer(code=0, answer="好的，已确认。请问还有什么可以帮您？")

        # Java: if ("negate".equalsIgnoreCase(sub))
        if sub and sub.lower() == "negate":
            return ChatAnswer(code=0, answer="好的，没问题。如有需要随时告诉我。")

        # Java: return new ChatAnswer(0, "好的！请问有什么可以帮您？", result);
        return ChatAnswer(code=0, answer="好的！请问有什么可以帮您？")
