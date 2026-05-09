# intent/intent_handler.py
# Java: package com.lcallai.intent;
from abc import ABC, abstractmethod

from intent.intent_result import IntentResult


class IntentHandler(ABC):
    """
    public interface IntentHandler {
        ChatAnswer handle(String rawText, IntentResult result, ChatSession session);
    }
    """

    @abstractmethod
    def handle(self, raw_text: str, result: IntentResult, session) -> object:
        """
        handle(String rawText, IntentResult result, ChatSession session)
        returns ChatAnswer(Python equivalent of ChatAnswer)
        """
        pass
