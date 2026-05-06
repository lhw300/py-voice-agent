import logging
from intent.intent_result import IntentResult, Intent

logger = logging.getLogger(__name__)


class IntentClassifier:

    def classify(self, text: str) -> IntentResult:
        # 暂时全返回GREETING，先跑通流程
        # 后续接入LLM做真正的意图分类
        logger.debug(f"text={text}")
        return IntentResult(intent=Intent.GREETING)
