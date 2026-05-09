# handler/greeting_handler.py
# Java: package com.lcallai.handler;
import logging
import random
import re

from intent.intent_handler import IntentHandler
from intent.intent_result import IntentResult
from models import ChatAnswer

logger = logging.getLogger(__name__)

# Java: private static final String[] POOL = { ... };
POOL = [
    "您好！我是粤教翔云3.0助手。我可以帮您找回密码或指导安装。请问您是老师还是学生？",
    "哈喽！找初始密码吗？试试 A202101b 吧！其他问题请直接提问。",
    "见到您真高兴！安装3.0请确保电脑是 Win7 或以上。您遇到什么安装报错了吗？",
    "嗨！我是您的数字教材管家。虽然我不能替您备课，但我能秒回业务难题。想聊点什么？",
    "您好，粤教翔云3.0专家为您服务。请问您是老师、学生还是管理员？",
]


class GreetingHandler(IntentHandler):
    """
    public ChatAnswer handle(String userInput, IntentResult intentRes, ChatSession session) {
        if (userInput.matches(".*(再见|拜拜|下次聊|退出了|不聊了).*")) {
            return new ChatAnswer(0, "好的，祝您工作顺利，", intentRes);
        }
        String text = POOL[new Random().nextInt(POOL.length)];
        return new ChatAnswer(200, text, intentRes);
    }
    """
    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        # Java: if (userInput.matches(".*(再见|拜拜|下次聊|退出了|不聊了).*"))
        if re.search(r"再见|拜拜|下次聊|退出了|不聊了", raw_text):
            return ChatAnswer(code=0, answer="好的，祝您工作顺利，")

        # Java: String text = POOL[new Random().nextInt(POOL.length)];
        text = random.choice(POOL)
        return ChatAnswer(code=200, answer=text)
