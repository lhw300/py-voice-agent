# intent/intent_result.py
# Java: package com.lcallai.intent;
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Intent(Enum):
    """
    public enum Intent {
        QUERY, COMMAND, INFORM, FEEDBACK, ACK, GREETING, CHITCHAT
    }
    """
    QUERY    = "QUERY"
    COMMAND  = "COMMAND"
    INFORM   = "INFORM"
    FEEDBACK = "FEEDBACK"
    ACK      = "ACK"
    GREETING = "GREETING"
    CHITCHAT = "CHITCHAT"


class Sentiment(Enum):
    """
    public enum Sentiment { POSITIVE, NEGATIVE, NEUTRAL }
    """
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL  = "NEUTRAL"


@dataclass
class IntentResult:
    """
    public class IntentResult {
        public final Intent    intent;
        public final String    subIntent;
        public final Sentiment sentiment;
        public final String    refinedQuery;
        public final String    actionCode;
        public final String    category;
    }
    """
    intent:        Intent
    refined_query: Optional[str]       = None        # Java: refinedQuery
    sub_intent:    Optional[str]       = None        # Java: subIntent
    sentiment:     Sentiment           = Sentiment.NEUTRAL
    action_code:   Optional[str]       = None        # Java: actionCode
    category:      Optional[str]       = None

    def is_question(self) -> bool:
        # Java: public boolean isQuestion() { return intent == Intent.QUERY; }
        return self.intent == Intent.QUERY

    def __str__(self) -> str:
        # Java: public String toString() { return "IntentResult{intent=..." }
        return (
            "IntentResult{"
            "intent=" + self.intent.value +
            ", subIntent='" + str(self.sub_intent) + "'"
            ", sentiment=" + self.sentiment.value +
            ", refinedQuery='" + str(self.refined_query) + "'"
            ", actionCode='" + str(self.action_code) + "'"
            ", category='" + str(self.category) + "'"
            "}"
        )
