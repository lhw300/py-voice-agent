# handler/filling_handler.py
import logging
from intent.intent_handler import IntentHandler
from handler.slot_validator import validate_slot
from intent.intent_result import IntentResult
from models import ChatAnswer

logger = logging.getLogger(__name__)

SLOTS = [
    ("name",    "请问您的姓名？"),
    ("phone",   "请问您的联系电话？"),
    ("address", "请问您的装机地址？"),
]

NEED_CONFIRM = {"phone", "address"}

RE_ASK = {
    "phone":   "好的，请重新告诉我您的联系电话？",
    "address": "好的，请重新告诉我您的装机地址？",
}

# 明确的否定短语，优先级最高
NO_PHRASES  = ["不对", "不是", "不好", "错了", "重新"]
# 单字否定，最后才匹配
NO_SINGLE   = ["不", "否", "no"]

YES_PHRASES = ["没错", "对的", "是的", "好的", "确认", "正确"]
YES_SINGLE  = ["对", "是", "嗯", "好", "yes"]

def is_no(text):
    t = text.strip()
    return any(w in t for w in NO_PHRASES) or any(t == w for w in NO_SINGLE)

def is_yes(text):
    if is_no(text): return False
    t = text.strip()
    return any(w in t for w in YES_PHRASES) or any(w in t for w in YES_SINGLE)

def confirm_text(key, value):
    if key == "phone":
        spaced = "-".join(list(value))
        return f"您的电话是{spaced}，对吗？"
    if key == "address":
        return f"您的地址是{value}，对吗？"

def _build_complete_response(session) -> ChatAnswer:  # ← 类外面
    name    = session.slots["name"]
    phone   = session.slots["phone"]
    address = session.slots["address"]
    session.slots        = None
    session.pending_slot = None
    session.confirming   = None
    return ChatAnswer(code=0, answer=f"好的{name}，您的报修已登记。联系电话{phone}，地址{address}，我们会尽快安排工程师上门处理。")


class FillingHandler(IntentHandler):

    def handle(self, raw_text: str, result: IntentResult, session) -> ChatAnswer:
        logger.debug(f"raw_text={raw_text}")

        # 初始化槽位（第一次进入）
        if not hasattr(session, "slots") or session.slots is None:
            session.slots        = {key: None for key, _ in SLOTS}
            session.pending_slot = "name"
            session.confirming   = False
            return ChatAnswer(code=0, answer="您好，请问您的姓名？")

        # ── 正在等待用户确认 ──────────────────────────────────────
        logger.debug(f"session.confirming={session.confirming}")
        if session.confirming:
            key = session.pending_slot

            if is_yes(raw_text):
                session.confirming   = False
                session.pending_slot = None
                for k, question in SLOTS:          # ← 缩进在if is_yes里面
                    if session.slots[k] is None:
                        session.pending_slot = k
                        return ChatAnswer(code=0, answer=question)
                return _build_complete_response(session)

            elif is_no(raw_text):
                session.slots[key] = None
                session.confirming = False
                return ChatAnswer(code=0, answer=RE_ASK[key])

            else:
                return ChatAnswer(code=0, answer=f'请回答"对"或"不对"，{confirm_text(key, session.slots[key])}')

        # ── 把用户刚说的话填入待填槽位 ────────────────────────────
        logger.debug(f"session.pending_slot={session.pending_slot}")
        if session.pending_slot is not None:
            key = session.pending_slot

            ok, error_msg = validate_slot(key, raw_text)
            if not ok:
                return ChatAnswer(code=0, answer=error_msg)

            session.slots[key] = raw_text
            logger.debug(f"填入槽位 {key}={raw_text}")

            if key in NEED_CONFIRM:
                session.confirming = True
                return ChatAnswer(code=0, answer=confirm_text(key, raw_text))

            session.pending_slot = None

        # ── 找下一个未填的槽位 ────────────────────────────────────
        for key, question in SLOTS:
            if session.slots[key] is None:
                session.pending_slot = key
                logger.debug(f"set session.pending_slot={key} answer={question}")
                return ChatAnswer(code=0, answer=question)

        # ── 所有槽位已填满，完成报修 ──────────────────────────────
        return _build_complete_response(session)