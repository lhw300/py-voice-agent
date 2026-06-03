# models.py
# Java: com.lcallai.ChatAnswer
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel
import ai_config as AiConfig


class Action(str, Enum):
    """
    public enum Action {
        NONE, TRANSFER, REPLAY, VOL_UP, VOL_DOWN, HANGUP
    }
    """
    NONE     = "NONE"
    TRANSFER = "TRANSFER"
    REPLAY   = "REPLAY"
    VOL_UP   = "VOL_UP"
    VOL_DOWN = "VOL_DOWN"
    HANGUP   = "HANGUP"


# Java: public static final int CODE_OK             =  0;
# Java: public static final int CODE_ERROR          = -1;
# Java: public static final int CODE_NO_KNOWLEDGE   = -100;
# Java: public static final int CODE_LOW_SIMILARITY = -101;
CODE_OK             =  0
CODE_ERROR          = -1
CODE_NO_KNOWLEDGE   = -100
CODE_LOW_SIMILARITY = -101


class ChatRequest(BaseModel):
    """
    Mirrors Java EivrRequest (IVR call payload)
    """
    sn:         str
    crid:       str
    ch:         str
    call_date:  str
    start_time: str
    phone:      str
    vo_id:      str
    text:       str


class ChatAnswer(BaseModel):
    """
    public class ChatAnswer {
        public int    code;
        public String answer;
        public Action action        = Action.NONE;
        public IntentResult intentResult = null;
    }
    """
    code:          int            = CODE_OK
    answer:        Optional[str]  = None
    action:        Action         = Action.NONE
    intent:        Optional[str]  = None   # intent enum name, e.g. "QUERY"
    sub_intent:    Optional[str]  = None   # e.g. "affirm"
    refined_query: Optional[str]  = None   # rewritten query shown to client
    category:      Optional[str]  = None   # knowledge category matched
    sentiment:     Optional[str]  = None   # POSITIVE / NEGATIVE / NEUTRAL

    # =========================================================================
    # Instance methods — Java: shouldTerminate / needsTts / isNegativeFeedback
    # =========================================================================

    def should_terminate(self) -> bool:
        # Java: public boolean shouldTerminate()
        return self.action in (Action.TRANSFER, Action.HANGUP)

    def needs_tts(self) -> bool:
        # Java: public boolean needsTts()
        return self.action != Action.REPLAY

    def is_negative_feedback(self) -> bool:
        # Java: public boolean isNegativeFeedback()
        return self.sentiment == "NEGATIVE"

    def fill_from_intent(self, intent_result: Any) -> "ChatAnswer":
        """
        Populate intent fields from an IntentResult object.
        Java: constructor ChatAnswer(code, answer, intentResult, action)
        """
        if intent_result is None:
            return self
        self.intent        = intent_result.intent.name  if intent_result.intent        else None
        self.sub_intent    = intent_result.sub_intent
        self.refined_query = intent_result.refined_query
        self.category      = intent_result.category
        self.sentiment     = intent_result.sentiment.name if intent_result.sentiment    else None
        return self

    # =========================================================================
    # Static factory methods — Java: ofAnswer / ofAction / ofError / ofNoKnowledge
    # =========================================================================

    @staticmethod
    def of_answer(answer: str, intent_result: Any = None) -> "ChatAnswer":
        # Java: public static ChatAnswer ofAnswer(IntentResult ir, String answerText)
        ca = ChatAnswer(code=CODE_OK, answer=answer, action=Action.NONE)
        return ca.fill_from_intent(intent_result)

    @staticmethod
    def of_action(action: Action, answer: str, intent_result: Any = None) -> "ChatAnswer":
        # Java: public static ChatAnswer ofAction(IntentResult ir, Action action, String tipsText)
        ca = ChatAnswer(code=CODE_OK, answer=answer, action=action)
        return ca.fill_from_intent(intent_result)

    @staticmethod
    def of_error(code: int, fallback_text: str) -> "ChatAnswer":
        # Java: public static ChatAnswer ofError(int code, String fallbackText)
        return ChatAnswer(code=code, answer=fallback_text)

    @staticmethod
    def of_no_knowledge() -> "ChatAnswer":
        # Java: public static ChatAnswer ofNoKnowledge()
        return ChatAnswer.of_error(
            CODE_NO_KNOWLEDGE,
            AiConfig.getStringConfig(
                "response.fallback.no_knowledge",
                "I'm sorry, I don't have information on that at the moment. "
                "If you'd like to speak with a human agent, just say 'transfer to agent'."
            )
        )

    @staticmethod
    def of_system_error(e: Exception) -> "ChatAnswer":
        # Java: ca.code=-1; ca.answer="机器人系统故障: " + e.getMessage()
        return ChatAnswer.of_error(CODE_ERROR, "System error, please try again.")


# backward-compat aliases — remove once all files are updated
EivrRequest  = ChatRequest
EivrResponse = ChatAnswer