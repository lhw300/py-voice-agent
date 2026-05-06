from enum import Enum
from dataclasses import dataclass
from typing import Optional


class Intent(Enum):
    QUERY    = "QUERY"     # 寻求答案，触发RAG检索
    COMMAND  = "COMMAND"   # 系统指令，触发action_code执行
    INFORM   = "INFORM"    # 陈述背景信息，存入上下文
    FEEDBACK = "FEEDBACK"  # 情感评价
    ACK      = "ACK"       # 确认/接收
    GREETING = "GREETING"  # 问候或告别
    CHITCHAT = "CHITCHAT"  # 闲聊


class Sentiment(Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL  = "NEUTRAL"


@dataclass
class IntentResult:
    intent:        Intent
    refined_query: Optional[str]  = None   # QUERY时：补全后的疑问句
    sub_intent:    Optional[str]  = None   # ACK子类型：affirm/negate/ack
    sentiment:     Sentiment      = Sentiment.NEUTRAL
    action_code:   Optional[str]  = None   # COMMAND时：动作码
    category:      Optional[str]  = None   # 用户身份

    def is_question(self) -> bool:
        return self.intent == Intent.QUERY

    def __str__(self):
        return (f"IntentResult(intent={self.intent.value}, "
                f"refined_query={self.refined_query}, "
                f"category={self.category}, "
                f"action_code={self.action_code})")
