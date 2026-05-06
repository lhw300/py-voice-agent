# handler/query_handler.py
import logging
from handler.base_handler import BaseHandler
from intent.intent_result import IntentResult
from models import EivrResponse

logger = logging.getLogger(__name__)


class QueryHandler(BaseHandler):

    def handle(self, raw_text: str, result: IntentResult, session) -> EivrResponse:
        logger.debug(f"refined_query={result.refined_query}")

        # 身份未知，先反问
        if session.current_category is None:
            return EivrResponse(code=0, answer="请问您是宽带用户还是企业客户？")

        # TODO: 接入RAG检索
        return session.ask_by_rag(result.refined_query)