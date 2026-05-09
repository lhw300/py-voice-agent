# handler/feedback_handler.py
# Java: package com.lcallai.handler;
import logging
from typing import Dict

from intent.intent_handler import IntentHandler
from intent.intent_result import IntentResult, Sentiment
from models import Action, ChatAnswer

logger = logging.getLogger(__name__)


class FeedbackHandler(IntentHandler):
    """
    public class FeedbackHandler implements IntentHandler {
        private final ConcurrentHashMap<String, Integer> negCountMap = new ConcurrentHashMap<>();
        private final int transferThreshold;

        public FeedbackHandler() { this(4); }
        public FeedbackHandler(int transferThreshold) { this.transferThreshold = transferThreshold; }
    }
    """

    def __init__(self, transfer_threshold: int = 4):
        # Java: private final ConcurrentHashMap<String, Integer> negCountMap = new ConcurrentHashMap<>();
        self._neg_count_map: Dict[str, int] = {}
        # Java: private final int transferThreshold;
        self._transfer_threshold = transfer_threshold

    """
    public ChatAnswer handle(String rawText, IntentResult result, ChatSession session) {
        String sid = session.getSessionId();
        if (result.sentiment == IntentResult.Sentiment.NEGATIVE) {
            int count = negCountMap.merge(sid, 1, Integer::sum);
            if (count >= transferThreshold) {
                negCountMap.remove(sid);
                return ChatAnswer.ofAction(result, ChatAnswer.Action.TRANSFER, "抱歉给您带来极差体验，正在为您转接高级专家。");
            }
            return new ChatAnswer(0, "非常抱歉让您产生困扰，您的反馈已记录，我会努力改进。", result);
        }
        negCountMap.remove(sid);
        if (result.sentiment == IntentResult.Sentiment.POSITIVE) {
            return new ChatAnswer(0, "能帮到您真是太好了！我会继续加油的。", result);
        }
        return new ChatAnswer(0, "收到您的反馈，感谢您的支持。", result);
    }
    """
    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        # Java: String sid = session.getSessionId();
        sid = session.getSessionId()

        # Java: if (result.sentiment == IntentResult.Sentiment.NEGATIVE)
        if result.sentiment == Sentiment.NEGATIVE:
            # Java: int count = negCountMap.merge(sid, 1, Integer::sum);
            count = self._neg_count_map.get(sid, 0) + 1
            self._neg_count_map[sid] = count

            # Java: if (count >= transferThreshold)
            if count >= self._transfer_threshold:
                # Java: negCountMap.remove(sid);
                self._neg_count_map.pop(sid, None)
                # Java: return ChatAnswer.ofAction(result, ChatAnswer.Action.TRANSFER, "抱歉给您带来极差体验...");
                return ChatAnswer.of_action(Action.TRANSFER, "抱歉给您带来极差体验，正在为您转接高级专家。")

            return ChatAnswer(code=0, answer="非常抱歉让您产生困扰，您的反馈已记录，我会努力改进。")

        # Java: negCountMap.remove(sid);
        self._neg_count_map.pop(sid, None)

        # Java: if (result.sentiment == IntentResult.Sentiment.POSITIVE)
        if result.sentiment == Sentiment.POSITIVE:
            return ChatAnswer(code=0, answer="能帮到您真是太好了！我会继续加油的。")

        # Java: return new ChatAnswer(0, "收到您的反馈，感谢您的支持。", result);
        return ChatAnswer(code=0, answer="收到您的反馈，感谢您的支持。")

    def reset_neg_count(self, session_id: str) -> None:
        # Java: public void resetNegCount(String sessionId) { negCountMap.remove(sessionId); }
        self._neg_count_map.pop(session_id, None)
