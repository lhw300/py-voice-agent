# intent/fast_track.py

import re
from typing import Optional

from intent.intent_result import Intent, IntentResult, Sentiment

# ---------------------------------------------------------------------------
# COMMAND rules
# Strategy: Chinese OR English, joined with | inside each pattern group
# ---------------------------------------------------------------------------
_COMMAND_RULES = [
    # ACTION_REPLAY
    (re.compile(
        r"^(什么|啊|嗯\?|再说一遍|再说一次|重新说|没听清|听不清|你说什么|刚才说什么|能再说一遍吗?"
        r"|pardon|sorry\?|what\?|what did you say|say that again|could you repeat that|repeat please)[？?。！!]*$",
        re.IGNORECASE),
     lambda: IntentResult(intent=Intent.COMMAND, action_code="ACTION_REPLAY", refined_query="")),

    # ACTION_HANGUP
    (re.compile(
        r"^(再见|拜拜|拜了|不聊了|挂了|结束通话"
        r"|bye|goodbye|see you|hang up)[,，。！!～~]*$",
        re.IGNORECASE),
     lambda: IntentResult(intent=Intent.COMMAND, action_code="ACTION_HANGUP", refined_query="")),

    # ACTION_TRANSFER
    (re.compile(
        r"^(转人工|找真人|转客服|帮我转|要投诉"
        r"|transfer|speak to (a |an )?(agent|person|human|representative|staff|operator)"
        r"|get me (a |an )?(agent|person|human)|connect me|talk to (a |an )?human)[,，。！!]*$",
        re.IGNORECASE),
     lambda: IntentResult(intent=Intent.COMMAND, action_code="ACTION_TRANSFER", refined_query="")),

    # ACTION_VOL_UP
    (re.compile(
        r"^(大声点|声音大点|音量调大|大声一点"
        r"|louder|speak up|turn (it |the volume )?up|volume up|i can'?t hear you)[,，。！!]*$",
        re.IGNORECASE),
     lambda: IntentResult(intent=Intent.COMMAND, action_code="ACTION_VOL_UP", refined_query="")),

    # ACTION_VOL_DOWN
    (re.compile(
        r"^(小声点|声音小点|音量调小|小声一点"
        r"|quieter|lower|speak (more )?quietly|turn (it |the volume )?down|volume down)[,，。！!]*$",
        re.IGNORECASE),
     lambda: IntentResult(intent=Intent.COMMAND, action_code="ACTION_VOL_DOWN", refined_query="")),
]

# ---------------------------------------------------------------------------
# GREETING rules
# ---------------------------------------------------------------------------
_GREETING_RULES = [
    (re.compile(
        r"^(你好|您好|哈喽|嗨|喂"
        r"|hello|hi|hey|good morning|good afternoon|good evening|howdy)[,，。！!～~]*$",
        re.IGNORECASE),
     lambda t: IntentResult(intent=Intent.GREETING, refined_query=t)),
]

# ---------------------------------------------------------------------------
# ACK rules
# ---------------------------------------------------------------------------
_ACK_AFFIRM = re.compile(
    r"^(是的|对的|没错|是|对|确认|好的|嗯|知道了|行|行吧|收到"
    r"|yes|yeah|yep|correct|right|confirmed|sure|understood|got it|that'?s right)[,，。！!]*$",
    re.IGNORECASE)

_ACK_NEGATE = re.compile(
    r"^(不用了|不是|不对|不好|不需要|取消"
    r"|no|nope|not really|cancel|never mind|no thanks|that'?s not it|not needed)[,，。！!,，]*$",
    re.IGNORECASE)

_ACK_PLAIN = re.compile(
    r"^(好的|嗯|好|知道了"
    r"|ok|okay|all right|fine|i see|noted)[,，。！!]*$",
    re.IGNORECASE)

_ACK_RULES = [
    (_ACK_AFFIRM, lambda t: IntentResult(intent=Intent.ACK, sub_intent="affirm", refined_query=t)),
    (_ACK_NEGATE, lambda t: IntentResult(intent=Intent.ACK, sub_intent="negate", refined_query=t)),
    (_ACK_PLAIN,  lambda t: IntentResult(intent=Intent.ACK, sub_intent="ack",    refined_query=t)),
]

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def fast_track(user_text: str) -> Optional[IntentResult]:
    if not user_text or not user_text.strip():
        return None

    text = user_text.strip()

    for pattern, factory in _COMMAND_RULES:
        if pattern.match(text):
            return factory()

    for pattern, factory in _GREETING_RULES:
        if pattern.match(text):
            return factory(text)

    for pattern, factory in _ACK_RULES:
        if pattern.match(text):
            return factory(text)

    return None