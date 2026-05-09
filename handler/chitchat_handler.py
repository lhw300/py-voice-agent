# handler/chitchat_handler.py
# Java: package com.lcallai.handler;
import logging
from typing import Optional

from intent.intent_handler import IntentHandler
from intent.intent_result import IntentResult
from models import ChatAnswer

logger = logging.getLogger(__name__)


class ChitchatHandler(IntentHandler):
    """
    public class ChitchatHandler implements IntentHandler {
        private final String chitchatPrompt;

        public ChitchatHandler(String chitchatPrompt) {
            this.chitchatPrompt = chitchatPrompt;
        }
    }
    """

    def __init__(self, chitchat_prompt: Optional[str] = None):
        # Java: this.chitchatPrompt = chitchatPrompt;
        self.chitchatPrompt = chitchat_prompt

    """
    public ChatAnswer handle(String rawText, IntentResult result, ChatSession session) {
        logger.debug("[ChitchatHandler] 切换至纯净对话模式，跳过所有知识库检索");
        try {
            String optimizedQuery = result.refinedQuery != null ? result.refinedQuery : rawText;
            String ans = session.executeChitchat(chitchatPrompt, optimizedQuery);
            return new ChatAnswer(0, ans, result);
        } catch (Exception e) {
            logger.error("", e);
            return new ChatAnswer(-1, "闲聊系统暂时休息了: ", result);
        }
    }
    """
    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        logger.debug("[ChitchatHandler] 切换至纯净对话模式，跳过所有知识库检索")
        try:
            # Java: String optimizedQuery = result.refinedQuery != null ? result.refinedQuery : rawText;
            optimizedQuery = result.refined_query if result.refined_query else raw_text

            # Java: String ans = session.executeChitchat(chitchatPrompt, optimizedQuery);
            ans = session.executeChitchat(self.chitchatPrompt, optimizedQuery)

            return ChatAnswer(code=0, answer=ans)
        except Exception as e:
            logger.error(str(e))
            return ChatAnswer(code=-1, answer="闲聊系统暂时休息了: ")
