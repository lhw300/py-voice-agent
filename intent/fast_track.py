# intent/fast_track.py
#
# Fast-track rule engine — short-circuits LLM for high-frequency simple inputs.
# Fires BEFORE IntentClassifier.classify() to reduce latency from ~1.5s to <1ms.
#
# Design principles:
#   - Only match inputs where the intent is unambiguous regardless of context
#   - Patterns must be EXACT or near-exact — no fuzzy guessing
#   - When in doubt, return None and let LLM decide
#   - All patterns are stripped and lowercased before matching

import re
from typing import Optional

from intent.intent_result import Intent, IntentResult, Sentiment

# ---------------------------------------------------------------------------
# Rule tables — (pattern, IntentResult factory)
# Order matters: more specific patterns first
# ---------------------------------------------------------------------------

# COMMAND — only trigger when the utterance is SOLELY a command with no business content
_COMMAND_RULES = [
    # ACTION_REPLAY
#  ^ — 从字符串开头匹配
# (什么|啊|...) — 括号里是候选词，| 是"或"，匹配其中任意一个
# 嗯\? — \? 是转义，匹配字面问号字符（不转义的 ? 在正则里是"前面的字符出现0或1次"）
# [？?。！!]* — 方括号是字符集，匹配括号内任意一个字符，* 是0次或多次 — 即允许末尾带任意标点
# $ — 到字符串结尾
# 整句意思：整个字符串只能是这些词之一，后面可以跟标点，没有其他内容。

    (re.compile(r"^(什么|啊|嗯\?|再说一遍|再说一次|重新说|没听清|听不清|你说什么|刚才说什么|能再说一遍吗?)[？?。！!]*$"),
     lambda: IntentResult(intent=Intent.COMMAND, action_code="ACTION_REPLAY", refined_query="")),

    # ACTION_HANGUP
    (re.compile(r"^(再见|拜拜|拜了|不聊了|挂了|结束通话|goodbye|bye)[,，。！!～~]*$"),
     lambda: IntentResult(intent=Intent.COMMAND, action_code="ACTION_HANGUP", refined_query="")),

    # ACTION_TRANSFER
    (re.compile(r"^(转人工|找真人|转客服|帮我转|要投诉)[,，。！!]*$"),
     lambda: IntentResult(intent=Intent.COMMAND, action_code="ACTION_TRANSFER", refined_query="")),

    # ACTION_VOL_UP
    (re.compile(r"^(大声点|声音大点|音量调大|大声一点)[,，。！!]*$"),
     lambda: IntentResult(intent=Intent.COMMAND, action_code="ACTION_VOL_UP", refined_query="")),

    # ACTION_VOL_DOWN
    (re.compile(r"^(小声点|声音小点|音量调小|小声一点)[,，。！!]*$"),
     lambda: IntentResult(intent=Intent.COMMAND, action_code="ACTION_VOL_DOWN", refined_query="")),
]

# GREETING — pure greeting with no business content
_GREETING_RULES = [
    (re.compile(r"^(你好|您好|hello|hi|哈喽|嗨|喂)[,，。！!～~]*$", re.IGNORECASE),
     lambda t: IntentResult(intent=Intent.GREETING, refined_query=t)),
]

# ACK — pure acknowledgement with no business content
_ACK_AFFIRM = re.compile(r"^(是的|对的|没错|是|对|确认|好的|嗯|知道了|行|行吧|收到)[,，。！!]*$")
_ACK_NEGATE = re.compile(r"^(不用了|不是|不对|不好|不需要|取消)[,，。！!,，]*$")
_ACK_PLAIN  = re.compile(r"^(好的|嗯|ok|好|知道了)[,，。！!]*$", re.IGNORECASE)

_ACK_RULES = [
    (_ACK_AFFIRM, lambda t: IntentResult(intent=Intent.ACK, sub_intent="affirm",  refined_query=t)),
    (_ACK_NEGATE, lambda t: IntentResult(intent=Intent.ACK, sub_intent="negate",  refined_query=t)),
    (_ACK_PLAIN,  lambda t: IntentResult(intent=Intent.ACK, sub_intent="ack",     refined_query=t)),
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fast_track(user_text: str) -> Optional[IntentResult]:
    """
    Attempt to classify user_text using regex rules only.
    Returns IntentResult if a rule fires, None otherwise (caller must use LLM).

    Mirrors Java concept:
        private IntentResult fastTrack(String userText) {
            // regex shortcut
            return null; // fall through to LLM
        }
    """
    if not user_text or not user_text.strip():
        return None

    text = user_text.strip()

    # COMMAND rules (no context needed — purely lexical)
    # 等价写法
    # for item in _COMMAND_RULES:
    #     pattern = item[0]   # 正则对象
    # factory = item[1]   # lambda 函数
    for pattern, factory in _COMMAND_RULES:
        if pattern.match(text):
            return factory()

    # GREETING rules
    for pattern, factory in _GREETING_RULES:
        if pattern.match(text):
            return factory(text)

    # ACK rules
    for pattern, factory in _ACK_RULES:
        if pattern.match(text):
            return factory(text)

    # No rule matched — let LLM handle it
    return None
