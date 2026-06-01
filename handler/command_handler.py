# handler/command_handler.py
import logging
import ai_config as AiConfig
from intent.intent_handler import IntentHandler
from intent.intent_result import IntentResult
from models import Action, ChatAnswer

logger = logging.getLogger(__name__)


class CommandHandler(IntentHandler):

    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        code = result.action_code

        if not code or not code.strip() or code.lower() == "null":
            logger.error("[CommandHandler] action_code is empty, raw input: " + raw_text)
            fallback = AiConfig.getStringConfig(
                "response.command.unknown",
                "I can transfer you to a human agent or replay the last message. Please describe your issue."
            )
            return ChatAnswer(code=0, answer=fallback)

        logger.debug("[CommandHandler] executing action: " + code)

        if code == "ACTION_REPLAY":
            last_answer = session.getLastAnswer()
            if not last_answer or not last_answer.strip():
                no_replay = AiConfig.getStringConfig(
                    "response.command.no_replay",
                    "There is nothing to replay yet."
                )
                return ChatAnswer(code=0, answer=no_replay)
            return ChatAnswer.of_action(Action.REPLAY, last_answer)

        if code == "ACTION_TRANSFER":
            transfer_text = AiConfig.getStringConfig(
                "response.command.transfer",
                "Transferring you to a human agent, please hold."
            )
            return ChatAnswer.of_action(Action.TRANSFER, transfer_text)

        if code == "ACTION_VOL_UP":
            vol_up_text = AiConfig.getStringConfig("response.command.vol_up", "OK, turning up the volume.")
            return ChatAnswer.of_action(Action.VOL_UP, vol_up_text)

        if code == "ACTION_VOL_DOWN":
            vol_down_text = AiConfig.getStringConfig("response.command.vol_down", "OK, turning down the volume.")
            return ChatAnswer.of_action(Action.VOL_DOWN, vol_down_text)

        if code == "ACTION_HANGUP":
            hangup_text = AiConfig.getStringConfig("response.command.hangup", "Goodbye!")
            return ChatAnswer.of_action(Action.HANGUP, hangup_text)

        logger.error("[CommandHandler] unknown action code: " + code)
        unsupported = AiConfig.getStringConfig(
            "response.command.unsupported",
            "Sorry, this command is not supported."
        )
        return ChatAnswer(code=-1, answer=unsupported)