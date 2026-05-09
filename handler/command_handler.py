# handler/command_handler.py
# Java: package com.lcallai.handler;
import logging

from intent.intent_handler import IntentHandler
from intent.intent_result import IntentResult
from models import Action, ChatAnswer

logger = logging.getLogger(__name__)


class CommandHandler(IntentHandler):
    """
    public ChatAnswer handle(String rawText, IntentResult result, ChatSession session) {
        String code = result.actionCode;
        if (code == null || code.isBlank() || "null".equalsIgnoreCase(code)) {
            logger.error("[CommandHandler] action_code 为空，原始输入: " + rawText);
            return new ChatAnswer(0, "收到您的指令，但我目前只能帮您转人工 或者重复说上一次 或您可以直接描述您遇到的问题。");
        }
        logger.debug("[CommandHandler] 执行动作: " + code);
        switch (code) {
            case "ACTION_REPLAY":
                String lastAnswer = session.getLastAnswer();
                if (lastAnswer == null || lastAnswer.isBlank())
                    return new ChatAnswer(ChatAnswer.CODE_OK, "暂时没有可重播的内容。", result);
                return ChatAnswer.ofAction(result, ChatAnswer.Action.REPLAY, lastAnswer);
            case "ACTION_TRANSFER":
                return ChatAnswer.ofAction(result, ChatAnswer.Action.TRANSFER, "正在为您转接人工客服，请稍候。");
            case "ACTION_VOL_UP":
                return ChatAnswer.ofAction(result, ChatAnswer.Action.VOL_UP, "好的，大声点");
            case "ACTION_VOL_DOWN":
                return ChatAnswer.ofAction(result, ChatAnswer.Action.VOL_DOWN, "好的，小声点");
            case "ACTION_HANGUP":
                return ChatAnswer.ofAction(result, ChatAnswer.Action.HANGUP, "好的，再见！");
            default:
                logger.error("[CommandHandler] 未知动作码: " + code);
                return new ChatAnswer(-1, "暂不支持该指令", result);
        }
    }
    """
    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        code = result.action_code  # Java: result.actionCode

        # Java: if (code == null || code.isBlank() || "null".equalsIgnoreCase(code))
        if not code or not code.strip() or code.lower() == "null":
            logger.error("[CommandHandler] action_code 为空，原始输入: " + raw_text)
            return ChatAnswer(code=0, answer="收到您的指令，但我目前只能帮您转人工 或者重复说上一次 或您可以直接描述您遇到的问题。")

        logger.debug("[CommandHandler] 执行动作: " + code)

        # Java: switch (code) { case "ACTION_REPLAY": ... }
        if code == "ACTION_REPLAY":
            lastAnswer = session.getLastAnswer()
            # Java: if (lastAnswer == null || lastAnswer.isBlank())
            if not lastAnswer or not lastAnswer.strip():
                return ChatAnswer(code=0, answer="暂时没有可重播的内容。")
            # Java: return ChatAnswer.ofAction(result, ChatAnswer.Action.REPLAY, lastAnswer);
            return ChatAnswer.of_action(Action.REPLAY, lastAnswer)

        if code == "ACTION_TRANSFER":
            # Java: return ChatAnswer.ofAction(result, ChatAnswer.Action.TRANSFER, "正在为您转接人工客服，请稍候。");
            return ChatAnswer.of_action(Action.TRANSFER, "正在为您转接人工客服，请稍候。")

        if code == "ACTION_VOL_UP":
            return ChatAnswer.of_action(Action.VOL_UP, "好的，大声点")

        if code == "ACTION_VOL_DOWN":
            return ChatAnswer.of_action(Action.VOL_DOWN, "好的，小声点")

        if code == "ACTION_HANGUP":
            return ChatAnswer.of_action(Action.HANGUP, "好的，再见！")

        # Java: default: logger.error("[CommandHandler] 未知动作码: " + code);
        logger.error("[CommandHandler] 未知动作码: " + code)
        return ChatAnswer(code=-1, answer="暂不支持该指令")
