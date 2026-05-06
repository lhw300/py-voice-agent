import logging
from intent.intent_result import IntentResult
from models import EivrResponse

logger = logging.getLogger(__name__)


class ChatSession:

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.current_category = None
        self.intent_classifier = None
        self.intent_dispatcher = None

    def set_intent_pipeline(self, classifier, dispatcher):
        self.intent_classifier = classifier
        self.intent_dispatcher = dispatcher

    def ask(self, text: str) -> EivrResponse:
        if not text or not text.strip():
            return EivrResponse(code=-1, answer="输入为空")

        result: IntentResult = self.intent_classifier.classify(text)
        logger.debug(f"sn={self.session_id} intent={result.intent} refined={result.refined_query}")

        return self.intent_dispatcher.dispatch(text, result, self)
    
    def ask_by_rag(self, query: str) -> EivrResponse:
        # TODO: 后续接入pgvector检索
        logger.debug(f"ask_by_rag query={query}")
        return EivrResponse(code=0, answer="RAG暂未实现，query=" + query)