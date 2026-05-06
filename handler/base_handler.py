from abc import ABC, abstractmethod
from intent.intent_result import IntentResult


class BaseHandler(ABC):

    @abstractmethod
    def handle(self, raw_text: str, result: IntentResult, session) -> object:
        pass
