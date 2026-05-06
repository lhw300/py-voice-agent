import logging
import random
from handler.base_handler import BaseHandler
from intent.intent_result import IntentResult
from models import EivrResponse

logger = logging.getLogger(__name__)

POOL = [
    "您好！我是宽带客服助手，可以帮您报修或查询业务。请问您遇到什么问题？",
    "哈喽！请问您遇到什么宽带问题？我来帮您处理。",
    "您好，宽带客服为您服务。请问有什么可以帮您？",
    "嗨！我是您的宽带服务助手。请问您需要报修还是查询？",
    "您好，请问有什么可以帮您？"
]

FAREWELL_KEYWORDS = ["再见", "拜拜", "下次聊", "退出了", "不聊了"]


class GreetingHandler(BaseHandler):

    def handle(self, raw_text: str, result: IntentResult, session) -> EivrResponse:
        logger.debug(f"[GreetingHandler] raw_text={raw_text}")

        # 告别语
        if any(kw in raw_text for kw in FAREWELL_KEYWORDS):
            return EivrResponse(code=0, answer="好的，祝您生活愉快，再见！")

        # 随机从候选池选一条
        answer = random.choice(POOL)
        return EivrResponse(code=200, answer=answer)
