"""
skill_internet_repair.py
─────────────────────────────────────────────────────────────
Broadband repair skill module.

Flow:
  Scene 1 (address found):   confirm address → fault desc → contact phone → appointment time → summary confirm → create order
  Scene 2 (address missing): collect account → confirm account → query address → dictate address → confirm address → same as scene 1

State machine is code-driven; LLM only extracts two fields: affirm / value.
"""

import logging
import re
import time
from typing import Optional

from skill.skill_base import SkillModule, SkillStatus, register_skill

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Session storage keys
# ══════════════════════════════════════════════════════════════
_DRAFT_KEY  = "_repair_draft"    # confirmed fields: {address, fault_desc, contact_phone, contact_time}
_STAGE_KEY  = "_repair_stage"    # current stage string
_TEMP_KEY   = "_repair_temp"     # pending value awaiting confirmation (not written to draft yet)
_CALLER_KEY = "_repair_caller"   # caller phone number, shared across stages
_INVALID_COUNT_KEY = "_repair_invalid_count"   # 连续无效value计数，防止语气词导致无限循环
_INVALID_MAX = 3                                # 连续3次无效输入，强制放弃当前流程
# ══════════════════════════════════════════════════════════════
# Flow configuration — toggle each collection step on/off
# ══════════════════════════════════════════════════════════════
_FLOW_CONFIG = {
    "collect_fault":  True,   # fault description
    "collect_phone":  True,   # contact phone number
    "collect_time":   False,  # appointment time (currently disabled)
}

# ══════════════════════════════════════════════════════════════
# Stage constants
# ══════════════════════════════════════════════════════════════
S_ADDR_CONFIRM    = "addr_confirm"
S_ACCOUNT_INPUT = "account_input"
S_ACCOUNT_CONFIRM = "account_confirm"
S_ADDRESS_INPUT   = "address_input"
S_ADDRESS_CONFIRM = "address_confirm"
S_FAULT_INPUT     = "fault_input"
S_FAULT_CONFIRM   = "fault_confirm"
S_PHONE_ASK       = "phone_ask"
S_PHONE_INPUT     = "phone_input"
S_PHONE_CONFIRM   = "phone_confirm"
S_TIME_INPUT      = "time_input"
S_TIME_CONFIRM    = "time_confirm"
S_SUMMARY_CONFIRM = "summary_confirm"

_VALUE_INPUT_STAGES = {S_ACCOUNT_INPUT, S_ADDRESS_INPUT, S_PHONE_INPUT, S_TIME_INPUT}

_FILLER_WORDS = {"啊", "呃", "嗯", "哦", "什么", "什么啊", "啥", "唔", "诶", "呀", "欸"}



# 每个 stage 对应字段的长度规则：
#   min_len      —— 至少要有这么长（不满足则判定无效）
#   exact_len    —— 必须正好等于这个长度（配合 digits_only 提取数字后再判断，用于手机号这类定长字段）
#   digits_only  —— 判断长度前先剔除非数字字符（应对"138-0013-8000"这种带分隔符的口语表达）
_VALUE_LENGTH_RULES = {
    S_ACCOUNT_INPUT: {"min_digits": 4},                         # 宽带账号/绑定手机号，至少要含4位数字（不看整体字符数，避免误伤"无限"这类正常但非账号的测试词）
    S_ADDRESS_INPUT: {"min_len": 4},                             # 地址是自然语言描述，用整体长度判断合理
    S_PHONE_INPUT:   {"exact_len": 11, "digits_only": True},     # 国内手机号固定11位数字
    S_TIME_INPUT:    {"min_len": 2},                             # 最短合理表达如"明天"
}

def _is_meaningless_value(value: Optional[str], stage: Optional[str] = None) -> bool:
    """粗筛：过滤纯语气词/单字符输入，并按字段做校验（不做严格格式校验，避免误伤口语化表达）"""
    if not value:
        return True
    stripped = value.strip()
    if stripped in _FILLER_WORDS or len(stripped) <= 1:
        return True

    rule = _VALUE_LENGTH_RULES.get(stage)
    if not rule:
        return False

    if "min_digits" in rule:
        digits = re.sub(r"\D", "", stripped)
        return len(digits) < rule["min_digits"]

    check_str = re.sub(r"\D", "", stripped) if rule.get("digits_only") else stripped
    if "exact_len" in rule:
        return len(check_str) != rule["exact_len"]
    if "min_len" in rule:
        return len(check_str) < rule["min_len"]
    return False

# 只有在确认类 stage 才显示待确认内容，收集类 stage 不显示
_CONFIRM_STAGES = {
    S_ACCOUNT_CONFIRM, S_ADDRESS_CONFIRM, S_FAULT_CONFIRM,
    S_PHONE_CONFIRM, S_TIME_CONFIRM, S_ADDR_CONFIRM, S_SUMMARY_CONFIRM
}

# ══════════════════════════════════════════════════════════════
# Session read/write helpers
# ══════════════════════════════════════════════════════════════
def _get_stage(session) -> Optional[str]:
    return getattr(session, _STAGE_KEY, None)

def _set_stage(session, stage: str):
    setattr(session, _STAGE_KEY, stage)
    logger.debug("[repair] stage → %s", stage)

def _set_stage2(session, stage: str):
    current = getattr(session, _STAGE_KEY, None)
    setattr(session, _STAGE_KEY, stage)
    logger.debug("[repair] stage → %s", stage)
    if current != stage:
        session.history.clear()
        logger.debug("[repair] history cleared on stage change %s → %s", current, stage)


def _get_draft(session) -> dict:
    return getattr(session, _DRAFT_KEY, None) or {}

def _set_draft(session, draft: dict):
    setattr(session, _DRAFT_KEY, draft)

def _get_temp(session) -> Optional[str]:
    return getattr(session, _TEMP_KEY, None)

def _set_temp(session, val: str):
    setattr(session, _TEMP_KEY, val)

def _get_caller(session) -> str:
    return getattr(session, _CALLER_KEY, "") or ""

def _clear_all(session):
    """Clear all repair-related state from the session."""
    for key in (_DRAFT_KEY, _STAGE_KEY, _TEMP_KEY, _CALLER_KEY):
        setattr(session, key, None)

def _inc_invalid_count(session) -> int:
    count = getattr(session, _INVALID_COUNT_KEY, 0) + 1
    setattr(session, _INVALID_COUNT_KEY, count)
    return count

def _clear_invalid_count(session) -> None:
    setattr(session, _INVALID_COUNT_KEY, 0)
# ══════════════════════════════════════════════════════════════
# Return value helpers
# ══════════════════════════════════════════════════════════════
def _need(msg: str) -> dict:
    return {"status": SkillStatus.NEED_INFO, "msg": msg}

def _pending(msg: str) -> dict:
    return {"status": SkillStatus.PENDING_CONFIRM, "msg": msg}

def _done(msg: str) -> dict:
    return {"status": SkillStatus.DONE, "msg": msg}

def _error(msg: str) -> dict:
    return {"status": SkillStatus.ERROR, "msg": msg}


# ══════════════════════════════════════════════════════════════
# Mock DB queries — replace with real implementations
# ══════════════════════════════════════════════════════════════
async def _query_address_by_phone(phone: str) -> Optional[str]:
    """Look up registered address by caller phone. Returns None if not found."""
    mock = {"13800009999": "广东省广州市天河区天河路100号"}
    return mock.get(phone)

async def _query_address_by_account(account: str) -> Optional[str]:
    """Look up address by broadband account or bound phone. Returns None if not found."""
    mock = {"8888": "广东省广州市越秀区中山路88号"}
    return mock.get(account)

async def _create_order(draft: dict) -> str:
    """Create a repair order and return the order ID."""
    order_id = f"{int(time.time())}"
    logger.info("[repair] order created: %s | %s", order_id, draft)
    return order_id


# ══════════════════════════════════════════════════════════════
# Summary confirmation text — built dynamically from _FLOW_CONFIG
# ══════════════════════════════════════════════════════════════
def _format_summary(draft: dict) -> str:
    lines = ["请确认报修信息：", f"  地址：{draft.get('address', '-')}"]
    if _FLOW_CONFIG["collect_fault"]:
        lines.append(f"  故障描述：{draft.get('fault_desc', '-')}")
    if _FLOW_CONFIG["collect_phone"]:
        lines.append(f"  联系电话：{draft.get('contact_phone', '-')}")
    if _FLOW_CONFIG["collect_time"]:
        lines.append(f"  预约时间：{draft.get('contact_time', '-')}")
    lines.append("确认提交吗？")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# Stage handlers
# ══════════════════════════════════════════════════════════════
async def _stage_init(session, caller_phone: str) -> dict:
    """Entry point: look up address to decide scene 1 or scene 2."""
    setattr(session, _CALLER_KEY, caller_phone)
    _set_draft(session, {})

    address = await _query_address_by_phone(caller_phone)
    logger.debug("_stage_init _query_address_by_phone %s", address)
    if address:
        _set_temp(session, address)
        _set_stage(session, S_ADDR_CONFIRM)
        return _pending(f"您的报修地址是：{address}，确认吗？")
    else:
        _set_stage(session, S_ACCOUNT_INPUT)
        return _need("未查询到您的地址信息，请提供宽带账号或绑定手机号码。")


async def _stage_addr_confirm(session, affirm, value) -> dict:
    """Scene 1: confirm the address found in the system."""
    if affirm is True:
        draft = _get_draft(session)
        draft["address"] = _get_temp(session)
        _set_draft(session, draft)
        _set_temp(session, None)

        # advance to next enabled step
        if _FLOW_CONFIG["collect_fault"]:
            _set_stage(session, S_FAULT_INPUT)
            return _need("好的，请简要描述您的故障情况。")
        elif _FLOW_CONFIG["collect_phone"]:
            caller = _get_caller(session)
            _set_stage(session, S_PHONE_ASK)
            return _need(f"好的，联系电话是否使用来电号码 {caller}？")
        else:
            _set_stage(session, S_SUMMARY_CONFIRM)
            return _pending(_format_summary(draft))
    elif affirm is False:
        # user denies address → switch to scene 2 (repair for someone else)
        _set_temp(session, None)
        _set_stage(session, S_ACCOUNT_INPUT)

        return _need("好的，请提供宽带账号或绑定手机号码。")
    else:
        temp = _get_temp(session)
        return _pending(f"您的报修地址是：{temp}，请确认是否正确？")


async def _stage_account_input(session, affirm, value) -> dict:
    """Scene 2: collect broadband account or bound phone number."""
    # affirm=True 且带 value：上一轮 LLM 没调工具，这一轮合并处理
    if affirm is True and value:
        _set_temp(session, value)
        _set_stage(session, S_ACCOUNT_CONFIRM)
        return await _stage_account_confirm(session, affirm=True, value=value)
    if not value:
        return _need("请提供宽带账号或绑定手机号码。")
    _set_temp(session, value)
    _set_stage(session, S_ACCOUNT_CONFIRM)
    return _pending(f"您提供的账号是：{value}，确认吗？")


async def _stage_account_confirm(session, affirm, value) -> dict:
    """Confirm account then query address."""
    if affirm is False:
        _set_temp(session, None)
        _set_stage(session, S_ACCOUNT_INPUT)
        return _need("好的，请重新提供宽带账号或绑定手机号码。")
    if affirm is True:
        account = _get_temp(session)
        _set_temp(session, None)
        address = await _query_address_by_account(account)
        if address:
            # address found — do not reveal it, ask user to dictate instead
            _set_stage(session, S_ADDRESS_INPUT)
            return _need("好的，请口述您的报修地址。")
        else:
            _set_stage(session, S_ACCOUNT_INPUT)

            return _need("抱歉，未能查到该账号的信息，请重新提供宽带账号或绑定手机号码。")
    # no clear response — repeat confirmation
    account = _get_temp(session)
    return _pending(f"您提供的账号是：{account}，请确认是否正确？")


async def _stage_address_input(session, affirm, value) -> dict:
    """Ask user to dictate the repair address."""
    if affirm is True and value:
        _set_temp(session, value)
        _set_stage(session, S_ADDRESS_CONFIRM)
        return await _stage_address_confirm(session, affirm=True, value=value)
    if not value:
        return _need("请口述您的报修地址。")
    _set_temp(session, value)
    _set_stage(session, S_ADDRESS_CONFIRM)
    return _pending(f"您的地址是：{value}，确认吗？")


async def _stage_address_confirm(session, affirm, value) -> dict:
    """Confirm the dictated address."""
    if affirm is True:
        draft = _get_draft(session)
        draft["address"] = _get_temp(session)
        _set_draft(session, draft)
        _set_temp(session, None)

        # advance to next enabled step
        if _FLOW_CONFIG["collect_fault"]:
            _set_stage(session, S_FAULT_INPUT)
            return _need("好的，请简要描述您的故障情况。")
        elif _FLOW_CONFIG["collect_phone"]:
            caller = _get_caller(session)
            _set_stage(session, S_PHONE_ASK)
            return _need(f"好的，联系电话是否使用来电号码 {caller}？")
        else:
            _set_stage(session, S_SUMMARY_CONFIRM)
            return _pending(_format_summary(draft))
    elif affirm is False:
        _set_temp(session, None)
        _set_stage(session, S_ADDRESS_INPUT)

        return _need("好的，请重新口述您的报修地址。")
    else:
        temp = _get_temp(session)
        return _pending(f"您的地址是：{temp}，请确认是否正确？")


async def _stage_fault_input(session, affirm, value) -> dict:

    """Collect fault description — no pass-through, fault text is ambiguous."""

    if not value:
        return _need("请简要描述您的故障情况。")
    _set_temp(session, value)
    _set_stage(session, S_FAULT_CONFIRM)
    return _pending(f"您的故障描述是：{value}，确认吗？")


async def _stage_fault_confirm(session, affirm, value) -> dict:
    """Confirm fault description."""
    if affirm is True:
        # ignore spurious value — LLM may pass unrelated content (e.g. phone number)
        # always read fault_desc from _TEMP_KEY which was set in fault_input
        draft = _get_draft(session)
        draft["fault_desc"] = _get_temp(session)
        _set_draft(session, draft)
        _set_temp(session, None)
        caller = _get_caller(session)
        # advance to next enabled step
        if _FLOW_CONFIG["collect_phone"]:
            _set_stage(session, S_PHONE_ASK)
            return _need(f"好的，联系电话是否使用来电号码 {caller}？")
        else:
            _set_stage(session, S_SUMMARY_CONFIRM)
            return _pending(_format_summary(draft))
    elif affirm is False:
        _set_temp(session, None)
        _set_stage(session, S_FAULT_INPUT)

        return _need("好的，请重新描述您的故障情况。")
    else:
        temp = _get_temp(session)
        return _pending(f"您的故障描述是：{temp}，请确认是否正确？")


async def _stage_phone_ask(session, affirm, value) -> dict:
    if affirm is True:
        caller = _get_caller(session)
        draft = _get_draft(session)
        draft["contact_phone"] = caller
        _set_draft(session, draft)
        if _FLOW_CONFIG["collect_time"]:
            _set_stage(session, S_TIME_INPUT)
            return _need("好的，请说出预约上门时间。")
        else:
            _set_stage(session, S_SUMMARY_CONFIRM)
            return _pending(_format_summary(draft))
    elif affirm is False:
        _set_stage(session, S_PHONE_INPUT)
        return _need("请提供您的联系电话。")
    elif value:                          # ← 新增：用户直接给了号码
        _set_stage(session, S_PHONE_INPUT)
        return await _stage_phone_input(session, affirm=None, value=value)
    else:
        caller = _get_caller(session)
        return _need(f"联系电话是否使用来电号码 {caller}？")


async def _stage_phone_input(session, affirm, value) -> dict:
    """Collect an alternative contact phone number."""
    if affirm is True and value:
        _set_temp(session, value)
        _set_stage(session, S_PHONE_CONFIRM)
        return await _stage_phone_confirm(session, affirm=True, value=value)

    if not value:
        return _need("请提供您的联系电话。")
    _set_temp(session, value)
    _set_stage(session, S_PHONE_CONFIRM)
    return _pending(f"您的联系电话是：{value}，确认吗？")


async def _stage_phone_confirm(session, affirm, value) -> dict:
    """Confirm the contact phone number."""
    if affirm is True:
        draft = _get_draft(session)
        draft["contact_phone"] = _get_temp(session)
        _set_draft(session, draft)
        _set_temp(session, None)
        # advance to next enabled step
        if _FLOW_CONFIG["collect_time"]:
            _set_stage(session, S_TIME_INPUT)
            return _need("好的，请说出预约上门时间。")
        else:
            _set_stage(session, S_SUMMARY_CONFIRM)
            return _pending(_format_summary(draft))
    elif affirm is False:
        _set_temp(session, None)
        _set_stage(session, S_PHONE_INPUT)

        return _need("好的，请重新提供您的联系电话。")
    else:
        temp = _get_temp(session)
        return _pending(f"您的联系电话是：{temp}，请确认是否正确？")


async def _stage_time_input(session, affirm, value) -> dict:
    """Collect appointment time."""
    if affirm is True and value:
        _set_temp(session, value)
        _set_stage(session, S_TIME_CONFIRM)
        return await _stage_time_confirm(session, affirm=True, value=value)

    if not value:
        return _need("请说出预约上门时间，例如明天上午、后天下午两点等。")
    _set_temp(session, value)
    _set_stage(session, S_TIME_CONFIRM)
    return _pending(f"预约时间是：{value}，确认吗？")


async def _stage_time_confirm(session, affirm, value) -> dict:
    """Confirm appointment time."""
    if affirm is True:
        draft = _get_draft(session)
        draft["contact_time"] = _get_temp(session)
        _set_draft(session, draft)
        _set_temp(session, None)
        _set_stage(session, S_SUMMARY_CONFIRM)
        return _pending(_format_summary(draft))
    elif affirm is False:
        _set_temp(session, None)
        _set_stage(session, S_TIME_INPUT)

        return _need("好的，请重新说出预约上门时间。")
    else:
        temp = _get_temp(session)
        return _pending(f"预约时间是：{temp}，请确认是否正确？")


async def _stage_summary_confirm(session, affirm, value) -> dict:
    """Final summary confirmation — submit order on approval."""
    if affirm is True:
        draft = _get_draft(session)
        order_id = await _create_order(draft)
        _clear_all(session)
        return _done(f"报修工单已提交，工单号：{order_id}，我们将尽快安排上门处理，感谢您的耐心等待。")
    elif affirm is False:
        draft = _get_draft(session)
        # if user specified which field to change, jump directly
        if value:
            v = value
            if any(k in v for k in ["地址", "address"]):
                _set_stage(session, S_ADDRESS_INPUT)
                return _need("好的，请重新口述您的报修地址。")
            if _FLOW_CONFIG["collect_fault"] and any(k in v for k in ["故障", "fault"]):
                _set_stage(session, S_FAULT_INPUT)
                return _need("好的，请重新描述您的故障情况。")
            if _FLOW_CONFIG["collect_phone"] and any(k in v for k in ["电话", "phone", "号码"]):
                caller = _get_caller(session)
                _set_stage(session, S_PHONE_ASK)
                return _need(f"好的，联系电话是否使用来电号码 {caller}？")
            if _FLOW_CONFIG["collect_time"] and any(k in v for k in ["时间", "预约", "time"]):
                _set_stage(session, S_TIME_INPUT)
                return _need("好的，请重新说出预约上门时间。")
        # user did not specify — list only the enabled fields
        options = [f"  1. 地址：{draft.get('address', '-')}"]
        idx = 2
        if _FLOW_CONFIG["collect_fault"]:
            options.append(f"  {idx}. 故障描述：{draft.get('fault_desc', '-')}")
            idx += 1
        if _FLOW_CONFIG["collect_phone"]:
            options.append(f"  {idx}. 联系电话：{draft.get('contact_phone', '-')}")
            idx += 1
        if _FLOW_CONFIG["collect_time"]:
            options.append(f"  {idx}. 预约时间：{draft.get('contact_time', '-')}")
        return _need("好的，请问您需要修改哪项信息？\n" + "\n".join(options))
    else:
        # no clear response — repeat summary
        draft = _get_draft(session)
        return _pending(_format_summary(draft))


# ══════════════════════════════════════════════════════════════
# Unified handle entry point
# ══════════════════════════════════════════════════════════════
async def handle(session, tool_name: str = None, phone: str = "", affirm=None, value: str = None, **kwargs) -> dict:
    stage = _get_stage(session)
    logger.debug("[repair] handle stage=%s affirm=%s value=%s", stage, affirm, value)

    if stage is None:
        return await _stage_init(session, phone)
    # 通用粗筛：语气词/单字符/长度不达标的 value 在收集类 stage 视为"未提供"，
    # 复用各 stage 函数已有的 `if not value:` 分支重新引导，不需要逐个函数改
    # 通用粗筛：语气词/单字符/长度不达标的 value 在收集类 stage 视为"未提供"
    if stage in _VALUE_INPUT_STAGES and _is_meaningless_value(value, stage):
        logger.debug("[repair] value=%r 在 stage=%s 被判定为无效内容，视为未提供", value, stage)
        value = None
        invalid_count = _inc_invalid_count(session)
        if invalid_count >= _INVALID_MAX:
            logger.info("[repair] 连续 %d 次无效输入，强制放弃报修流程", invalid_count)
            _clear_all(session)
            return {
                "status": SkillStatus.CANCELLED,
                "msg": "抱歉，未能获取到有效信息，本次报修流程已结束，如有其他问题欢迎继续咨询。",
            }
    elif value:
        _clear_invalid_count(session)   # 这轮提供了有效内容，计数清零，避免"这次有效下次又从0算起"的误伤

    dispatch = {
        S_ADDR_CONFIRM:    _stage_addr_confirm,
        S_ACCOUNT_INPUT: _stage_account_input,
        S_ACCOUNT_CONFIRM: _stage_account_confirm,
        S_ADDRESS_INPUT:   _stage_address_input,
        S_ADDRESS_CONFIRM: _stage_address_confirm,
        S_FAULT_INPUT:     _stage_fault_input,
        S_FAULT_CONFIRM:   _stage_fault_confirm,
        S_PHONE_ASK:       _stage_phone_ask,
        S_PHONE_INPUT:     _stage_phone_input,
        S_PHONE_CONFIRM:   _stage_phone_confirm,
        S_TIME_INPUT:      _stage_time_input,
        S_TIME_CONFIRM:    _stage_time_confirm,
        S_SUMMARY_CONFIRM: _stage_summary_confirm,
    }

    fn = dispatch.get(stage)
    logger.debug("[repair] dispatch.get stage: %s fn=%s", stage,fn)
    if fn is None:
        logger.error("[repair] unknown stage: %s", stage)
        return _error(f"内部错误：未知步骤 {stage}")

    return await fn(session, affirm=affirm, value=value)


# ══════════════════════════════════════════════════════════════
# Locked prompt
# ══════════════════════════════════════════════════════════════
_STAGE_HINTS = {
    S_ADDR_CONFIRM:    "等待客户确认系统查到的地址（是/否）",
    #S_ACCOUNT_INPUT:    "等待客户提供宽带账号或绑定手机号码",
    S_ACCOUNT_INPUT: "等待客户提供宽带账号或绑定手机号码",
    S_ACCOUNT_CONFIRM: "等待客户确认账号（是/否）",
    #S_ADDRESS_INPUT:   "等待客户口述报修地址",
    S_ADDRESS_INPUT: "等待客户口述报修地址，客户说的任何地址描述都直接调工具传入",
    S_ADDRESS_CONFIRM: "等待客户确认口述地址（是/否）",
    S_FAULT_INPUT:     "等待客户描述故障情况",
    S_FAULT_CONFIRM:   "等待客户确认故障描述（是/否）",
    S_PHONE_ASK:       "等待客户确认是否使用来电号码作为联系电话（是/否）",
    S_PHONE_INPUT:     "等待客户提供联系电话 ",
    S_PHONE_CONFIRM:   "等待客户确认联系电话（是/否）",
    S_TIME_INPUT:      "等待客户说出预约上门时间",
    S_TIME_CONFIRM:    "等待客户确认预约时间（是/否）",
    S_SUMMARY_CONFIRM: "等待客户确认所有报修信息并提交（是/否），或指定修改某项",

}

_FORCE_RULE_STAGES = {
    S_ACCOUNT_INPUT:   "客户本轮任何输入都视为账号，禁止自然语言回复，必须调工具",
    S_ADDRESS_INPUT:   "客户本轮任何输入都视为地址，禁止自然语言回复，必须调工具",
    S_FAULT_INPUT:     "客户本轮任何输入都视为故障描述，禁止自然语言回复，必须调工具",
    S_PHONE_INPUT:     "客户本轮任何输入都视为联系电话，禁止自然语言回复，必须调工具",
    S_TIME_INPUT:      "客户本轮任何输入都视为预约时间，禁止自然语言回复，必须调工具",
    S_ADDR_CONFIRM:    "禁止自然语言回复，必须调工具",
    S_ACCOUNT_CONFIRM: "禁止自然语言回复，必须调工具",
    S_ADDRESS_CONFIRM: "禁止自然语言回复，必须调工具",
    S_FAULT_CONFIRM:   "禁止自然语言回复，必须调工具",
    S_PHONE_ASK:       "禁止自然语言回复，必须调工具",
    S_PHONE_CONFIRM:   "禁止自然语言回复，必须调工具",
    S_TIME_CONFIRM:    "禁止自然语言回复，必须调工具",

    S_SUMMARY_CONFIRM: "禁止自然语言回复，必须调工具；客户说出字段名（地址/故障/电话号码联系电话）表示要修改该项，调用 internet_repair_collect(affirm=false, value=客户说的内容)",
}


def build_locked_prompt(session, caller_phone: str) -> str:
    stage = _get_stage(session) or "初始化"
    hint = _STAGE_HINTS.get(stage, stage)
    draft = _get_draft(session)

    collected = ""
    if draft:
        labels = {
            "address": "地址", "fault_desc": "故障描述",
            "contact_phone": "联系电话", "contact_time": "预约时间"
        }
        lines = [f"  - {labels.get(k, k)}：{v}" for k, v in draft.items()]
        collected = "\n已确认字段：\n" + "\n".join(lines)

    temp = _get_temp(session)
    temp_hint = f"\n待确认内容：{temp}" if (temp and stage in _CONFIRM_STAGES) else ""

    extra_rule = f"- 【强制】{_FORCE_RULE_STAGES[stage]}\n" if stage in _FORCE_RULE_STAGES else ""

    return f"""# Role: 智能客服助理（宽带报修模式）

## Context
- 当前来电手机号: {caller_phone}（系统自动注入）
- 当前步骤: {hint}{collected}{temp_hint}

## 规则
- 客户提供了信息（账号/地址/故障描述/电话/时间等）→ 调用 internet_repair_collect(value=客户说的内容)，不管格式是否正确，原样传入
- 客户明确确认（嗯/是/对/没错/确认/提交等）→ 调用 internet_repair_collect(affirm=true)
- 客户明确否认（不对/不是/错了/重新/不低等）→ 调用 internet_repair_collect(affirm=false)
- 客户既提供信息又确认 → 调用 internet_repair_collect(affirm=true, value=内容)
- 客户明确放弃/取消 → 调用 cancel_skill
- 其他无关输入 → 不调工具，根据当前步骤自然语言引导客户
- 禁止讨论快递查询、投诉等其他话题
{extra_rule}
## 输出格式
- 回复必须是纯文本，不得使用 markdown、bullet point、换行、emoji、序号
- 所有内容用自然口语连续表达，适合直接语音播放
"""

# ══════════════════════════════════════════════════════════════
# Tool schemas
# ══════════════════════════════════════════════════════════════
_TOOL_ENTRY = {
    "type": "function",
    "function": {
        "name": "internet_repair_skill",
        "description": "用户提及宽带故障、网络不通、宽带报修、网络故障时调用，发起报修流程。",
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "来电手机号，从系统 Context 自动获取"},
            },
            "required": ["phone"],
        },
    },
}

_TOOL_COLLECT = {
    "type": "function",
    "function": {
        "name": "internet_repair_collect",
        "description": "报修流程中客户提供信息或确认/否认时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "affirm": {
                    "type": "boolean",
                    "description": "客户明确确认为true，明确否认为false，未明确表态时不传此字段",
                },
                "value": {
                    "type": "string",
                    "description": "客户本轮提供的具体内容，如账号、地址、故障描述、电话、时间等",
                },
            },
            "required": [],
        },
    },
}

_TOOL_CANCEL = {
    "type": "function",
    "function": {
        "name": "cancel_skill",
        "description": "用户明确表示放弃、取消当前报修流程时调用，比如说 不修了、算了、取消报修、不用上门了 等等。",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string", "description": "用户放弃的原因，可选"}},
            "required": [],
        },
    },
}


# ══════════════════════════════════════════════════════════════
# Skill registration
# ══════════════════════════════════════════════════════════════
register_skill(SkillModule(
    name="internet_repair",
    tools=[_TOOL_ENTRY],
    trigger_keywords=["宽带坏了", "网络不通", "宽带报修", "网络故障", "宽带故障",
                      "断网", "网络断了", "我要报修", "宽带慢", "网速慢",
                      "宽带太慢", "网速太慢","上网慢", "网络慢","网断了"],
    locked_tools=[_TOOL_COLLECT, _TOOL_CANCEL],
    build_locked_prompt=build_locked_prompt,
    handle=handle,
    tool_names=["internet_repair_skill", "internet_repair_collect"],
    clear=lambda session: _clear_all(session),
    use_history_in_locked=False,
))