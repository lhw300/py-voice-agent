# models.py
# Java: com.lcallai.ChatAnswer
from enum import Enum
from typing import Optional
from pydantic import BaseModel


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
        public int code;
        public String answer;
        public Action action = Action.NONE;
    }
    """
    code:   int           = CODE_OK
    answer: Optional[str] = None
    action: Action        = Action.NONE

    def should_terminate(self) -> bool:
        # Java: public boolean shouldTerminate() { return action == TRANSFER || action == HANGUP; }
        return self.action in (Action.TRANSFER, Action.HANGUP)

    def needs_tts(self) -> bool:
        # Java: public boolean needsTts() { return action != Action.REPLAY; }
        return self.action != Action.REPLAY

    @staticmethod
    def of_action(action: Action, answer: str) -> "ChatAnswer":
        # Java: public static ChatAnswer ofAction(IntentResult ir, Action action, String tipsText)
        return ChatAnswer(code=CODE_OK, answer=answer, action=action)

    @staticmethod
    def of_no_knowledge() -> "ChatAnswer":
        # Java: public static ChatAnswer ofNoKnowledge()
        return ChatAnswer(
            code=CODE_NO_KNOWLEDGE,
            answer="抱歉，我在知识库中未找到相关信息，您可以换一种方式描述，或转人工为您服务。"
        )


# backward-compat aliases — remove once all files are updated
EivrRequest  = ChatRequest
ChatAnswer= ChatAnswer