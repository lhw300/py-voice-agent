"""
skill_internet_repair.py
─────────────────────────────────────────────────────────────
宽带报修业务模块。

流程：
  场景1（能查到地址）：地址确认 → 故障描述 → 联系电话 → 预约时间 → 汇总确认 → 生成工单
  场景2（查不到地址）：收集账号 → 确认账号 → 查地址 → 口述地址 → 确认地址 → 同场景1后续

状态机由代码驱动，LLM 只负责提取 affirm / value 两个字段。
"""

import logging
import time
from typing import Optional

from skill.skill_base import SkillModule, SkillStatus, register_skill

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Session 存储 key
# ══════════════════════════════════════════════════════════════
_DRAFT_KEY  = "_repair_draft"    # 已确认的字段 {address, fault_desc, contact_phone, contact_time}
_STAGE_KEY  = "_repair_stage"    # 当前步骤字符串
_TEMP_KEY   = "_repair_temp"     # 待确认的临时值（确认前不写入 draft）
_CALLER_KEY = "_repair_caller"   # 保存 caller_phone 供各步使用

# ══════════════════════════════════════════════════════════════
# Stage 常量
# ══════════════════════════════════════════════════════════════
S_ADDR_CONFIRM    = "addr_confirm"
S_COLLECT_ACCOUNT = "collect_account"
S_ACCOUNT_CONFIRM = "account_confirm"
S_INPUT_ADDRESS   = "input_address"
S_ADDRESS_CONFIRM = "address_confirm"
S_FAULT_INPUT     = "fault_input"
S_FAULT_CONFIRM   = "fault_confirm"
S_PHONE_ASK       = "phone_ask"
S_PHONE_INPUT     = "phone_input"
S_PHONE_CONFIRM   = "phone_confirm"
S_TIME_INPUT      = "time_input"
S_TIME_CONFIRM    = "time_confirm"
S_SUMMARY_CONFIRM = "summary_confirm"


# ══════════════════════════════════════════════════════════════
# Session 读写工具函数
# ══════════════════════════════════════════════════════════════
def _get_stage(session) -> Optional[str]:
    return getattr(session, _STAGE_KEY, None)

def _set_stage(session, stage: str):
    setattr(session, _STAGE_KEY, stage)
    logger.debug("[repair] stage → %s", stage)

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
    for key in (_DRAFT_KEY, _STAGE_KEY, _TEMP_KEY, _CALLER_KEY):
        setattr(session, key, None)


# ══════════════════════════════════════════════════════════════
# 返回值工具函数
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
# Mock DB 查询（TODO：替换为真实实现）
# ══════════════════════════════════════════════════════════════
async def _query_address_by_phone(phone: str) -> Optional[str]:
    """用来电号码查标准地址，查不到返回 None"""
    mock = {"13800000000": "广东省广州市天河区天河路100号"}
    return mock.get(phone)

async def _query_address_by_account(account: str) -> Optional[str]:
    """用宽带账号或绑定手机查地址，查不到返回 None"""
    mock = {"8888": "广东省广州市越秀区中山路88号"}
    return mock.get(account)

async def _create_order(draft: dict) -> str:
    """生成工单，返回工单号"""
    order_id = f"WB{int(time.time())}"
    logger.info("[repair] order created: %s | %s", order_id, draft)
    return order_id


# ══════════════════════════════════════════════════════════════
# 汇总确认文本
# ══════════════════════════════════════════════════════════════
def _format_summary(draft: dict) -> str:
    return (
        f"请确认报修信息：\n"
        f"  地址：{draft.get('address', '-')}\n"
        f"  故障描述：{draft.get('fault_desc', '-')}\n"
        f"  联系电话：{draft.get('contact_phone', '-')}\n"
        #f"  预约时间：{draft.get('contact_time', '-')}\n"
        f"确认提交吗？"
    )


# ══════════════════════════════════════════════════════════════
# 各阶段处理函数
# ══════════════════════════════════════════════════════════════
async def _stage_init(session, caller_phone: str) -> dict:
    """入口：查地址，决定走场景1还是场景2"""
    setattr(session, _CALLER_KEY, caller_phone)
    _set_draft(session, {})

    address = await _query_address_by_phone(caller_phone)
    logger.debug("_stage_init _query_address_by_phone %s  ", address)
    if address:
        _set_temp(session, address)
        _set_stage(session, S_ADDR_CONFIRM)
        return _pending(f"您的报修地址是：{address}，确认吗？")
    else:
        _set_stage(session, S_COLLECT_ACCOUNT)
        return _need("未查询到您的地址信息，请提供宽带账号或绑定手机号码。")


async def _stage_addr_confirm(session, affirm, value) -> dict:
    """场景1：确认系统查到的地址"""
    if affirm is True:
        draft = _get_draft(session)
        draft["address"] = _get_temp(session)
        _set_draft(session, draft)
        _set_stage(session, S_FAULT_INPUT)
        return _need("好的，请简要描述您的故障情况。")
    elif affirm is False:
        # 否认地址 → 转场景2，替人报修
        _set_stage(session, S_COLLECT_ACCOUNT)
        return _need("好的，请提供宽带账号或绑定手机号码。")
    else:
        temp = _get_temp(session)
        return _pending(f"您的报修地址是：{temp}，请确认是否正确？")


async def _stage_collect_account(session, affirm, value) -> dict:
    """场景2：收集宽带账号或绑定手机"""
    if not value:
        return _need("请提供宽带账号或绑定手机号码。")
    _set_temp(session, value)
    _set_stage(session, S_ACCOUNT_CONFIRM)
    return _pending(f"您提供的账号是：{value}，确认吗？")


async def _stage_account_confirm(session, affirm, value) -> dict:
    """确认账号后查地址"""
    if affirm is False:
        _set_stage(session, S_COLLECT_ACCOUNT)
        return _need("好的，请重新提供宽带账号或绑定手机号码。")
    if affirm is True:
        account = _get_temp(session)
        address = await _query_address_by_account(account)
        if address:
            # 查到地址，不展示，让客户口述
            _set_stage(session, S_INPUT_ADDRESS)
            return _need("好的，请口述您的报修地址。")
        else:
            _set_stage(session, S_COLLECT_ACCOUNT)
            return _need("抱歉，未能查到该账号的信息，请重新提供宽带账号或绑定手机号码。")
    # 未明确表态
    account = _get_temp(session)
    return _pending(f"您提供的账号是：{account}，请确认是否正确？")


async def _stage_input_address(session, affirm, value) -> dict:
    """口述地址"""
    if not value:
        return _need("请口述您的报修地址。")
    _set_temp(session, value)
    _set_stage(session, S_ADDRESS_CONFIRM)
    return _pending(f"您的地址是：{value}，确认吗？")


async def _stage_address_confirm(session, affirm, value) -> dict:
    """确认口述地址"""
    if affirm is True:
        draft = _get_draft(session)
        draft["address"] = _get_temp(session)
        _set_draft(session, draft)
        _set_stage(session, S_FAULT_INPUT)
        return _need("好的，请简要描述您的故障情况。")
    elif affirm is False:
        _set_stage(session, S_INPUT_ADDRESS)
        return _need("好的，请重新口述您的报修地址。")
    else:
        temp = _get_temp(session)
        return _pending(f"您的地址是：{temp}，请确认是否正确？")


async def _stage_fault_input(session, affirm, value) -> dict:
    """收集故障描述"""
    if not value:
        return _need("请简要描述您的故障情况。")
    _set_temp(session, value)
    _set_stage(session, S_FAULT_CONFIRM)
    return _pending(f"您的故障描述是：{value}，确认吗？")


async def _stage_fault_confirm(session, affirm, value) -> dict:
    """确认故障描述"""
    if affirm is True:
        draft = _get_draft(session)
        draft["fault_desc"] = _get_temp(session)
        _set_draft(session, draft)
        caller = _get_caller(session)
        _set_stage(session, S_PHONE_ASK)
        return _need(f"好的，联系电话是否使用来电号码 {caller}？")
    elif affirm is False:
        _set_stage(session, S_FAULT_INPUT)
        return _need("好的，请重新描述您的故障情况。")
    else:
        temp = _get_temp(session)
        return _pending(f"您的故障描述是：{temp}，请确认是否正确？")


async def _stage_phone_ask(session, affirm, value) -> dict:
    """问是否用来电号码作为联系电话"""
    if affirm is True:
        caller = _get_caller(session)
        draft = _get_draft(session)
        draft["contact_phone"] = caller
        _set_draft(session, draft)
        #_set_stage(session, S_TIME_INPUT)
        #return _need("好的，请说出预约上门时间。")
        _set_stage(session, S_SUMMARY_CONFIRM)
        return _pending(_format_summary(draft))

    elif affirm is False:
        _set_stage(session, S_PHONE_INPUT)
        return _need("请提供您的联系电话。")
    else:
        caller = _get_caller(session)
        return _need(f"联系电话是否使用来电号码 {caller}？")


async def _stage_phone_input(session, affirm, value) -> dict:
    """收集其他联系电话"""
    if not value:
        return _need("请提供您的联系电话。")
    _set_temp(session, value)
    _set_stage(session, S_PHONE_CONFIRM)
    return _pending(f"您的联系电话是：{value}，确认吗？")


async def _stage_phone_confirm(session, affirm, value) -> dict:
    """确认联系电话"""
    if affirm is True:
        draft = _get_draft(session)
        draft["contact_phone"] = _get_temp(session)
        _set_draft(session, draft)
        _set_stage(session, S_TIME_INPUT)
        return _need("好的，请说出预约上门时间。")
    elif affirm is False:
        _set_stage(session, S_PHONE_INPUT)
        return _need("好的，请重新提供您的联系电话。")
    else:
        temp = _get_temp(session)
        return _pending(f"您的联系电话是：{temp}，请确认是否正确？")


async def _stage_time_input(session, affirm, value) -> dict:
    """收集预约时间"""
    if not value:
        return _need("请说出预约上门时间，例如明天上午、后天下午两点等。")
    _set_temp(session, value)
    _set_stage(session, S_TIME_CONFIRM)
    return _pending(f"预约时间是：{value}，确认吗？")


async def _stage_time_confirm(session, affirm, value) -> dict:
    """确认预约时间"""
    if affirm is True:
        draft = _get_draft(session)
        draft["contact_time"] = _get_temp(session)
        _set_draft(session, draft)
        _set_stage(session, S_SUMMARY_CONFIRM)
        return _pending(_format_summary(draft))
    elif affirm is False:
        _set_stage(session, S_TIME_INPUT)
        return _need("好的，请重新说出预约上门时间。")
    else:
        temp = _get_temp(session)
        return _pending(f"预约时间是：{temp}，请确认是否正确？")


async def _stage_summary_confirm(session, affirm, value) -> dict:
    """汇总确认，提交工单"""
    if affirm is True:
        draft = _get_draft(session)
        order_id = await _create_order(draft)
        _clear_all(session)
        return _done(f"报修工单已提交，工单号：{order_id}，我们将尽快安排上门处理，感谢您的耐心等待。")
    elif affirm is False:
        draft = _get_draft(session)
        # 如果 value 里说了要改哪项，直接跳转
        if value:
            v = value
            if any(k in v for k in ["地址", "address"]):
                _set_stage(session, S_INPUT_ADDRESS)
                return _need("好的，请重新口述您的报修地址。")
            if any(k in v for k in ["故障", "fault"]):
                _set_stage(session, S_FAULT_INPUT)
                return _need("好的，请重新描述您的故障情况。")
            if any(k in v for k in ["电话", "phone", "号码"]):
                caller = _get_caller(session)
                _set_stage(session, S_PHONE_ASK)
                return _need(f"好的，联系电话是否使用来电号码 {caller}？")
            if any(k in v for k in ["时间", "预约", "time"]):
                _set_stage(session, S_TIME_INPUT)
                return _need("好的，请重新说出预约上门时间。")
        # 未指定修改哪项，让客户说
        return _need(
            f"好的，请问您需要修改哪项信息？\n"
            f"  1. 地址：{draft.get('address', '-')}\n"
            f"  2. 故障描述：{draft.get('fault_desc', '-')}\n"
            f"  3. 联系电话：{draft.get('contact_phone', '-')}\n"
            f"  4. 预约时间：{draft.get('contact_time', '-')}"
        )
    else:
        draft = _get_draft(session)
        return _pending(_format_summary(draft))


# ══════════════════════════════════════════════════════════════
# 统一 handle 入口
# ══════════════════════════════════════════════════════════════
async def handle(session, tool_name: str = None, phone: str = "", affirm=None, value: str = None, **kwargs) -> dict:
    stage = _get_stage(session)
    logger.debug("[repair] handle stage=%s affirm=%s value=%s", stage, affirm, value)

    if stage is None:
        return await _stage_init(session, phone)

    dispatch = {
        S_ADDR_CONFIRM:    _stage_addr_confirm,
        S_COLLECT_ACCOUNT: _stage_collect_account,
        S_ACCOUNT_CONFIRM: _stage_account_confirm,
        S_INPUT_ADDRESS:   _stage_input_address,
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
    if fn is None:
        logger.error("[repair] unknown stage: %s", stage)
        return _error(f"内部错误：未知步骤 {stage}")

    return await fn(session, affirm=affirm, value=value)


# ══════════════════════════════════════════════════════════════
# 锁定 prompt
# ══════════════════════════════════════════════════════════════
_STAGE_HINTS = {
    S_ADDR_CONFIRM:    "等待客户确认系统查到的地址（是/否）",
    S_COLLECT_ACCOUNT: "等待客户提供宽带账号或绑定手机号码",
    S_ACCOUNT_CONFIRM: "等待客户确认账号（是/否）",
    S_INPUT_ADDRESS:   "等待客户口述报修地址",
    S_ADDRESS_CONFIRM: "等待客户确认口述地址（是/否）",
    S_FAULT_INPUT:     "等待客户描述故障情况",
    S_FAULT_CONFIRM:   "等待客户确认故障描述（是/否）",
    S_PHONE_ASK:       "等待客户确认是否使用来电号码作为联系电话（是/否）",
    S_PHONE_INPUT:     "等待客户提供联系电话",
    S_PHONE_CONFIRM:   "等待客户确认联系电话（是/否）",
    S_TIME_INPUT:      "等待客户说出预约上门时间",
    S_TIME_CONFIRM:    "等待客户确认预约时间（是/否）",
    S_SUMMARY_CONFIRM: "等待客户确认所有报修信息并提交（是/否），或指定修改某项",
}


def build_locked_prompt(session, caller_phone: str) -> str:
    stage = _get_stage(session) or "初始化"
    hint = _STAGE_HINTS.get(stage, stage)
    draft = _get_draft(session)
    temp = _get_temp(session)

    collected = ""
    if draft:
        lines = []
        labels = {
            "address": "地址", "fault_desc": "故障描述",
            "contact_phone": "联系电话", "contact_time": "预约时间"
        }
        for k, v in draft.items():
            lines.append(f"  - {labels.get(k, k)}：{v}")
        collected = "\n已确认字段：\n" + "\n".join(lines)

    temp_hint = f"\n待确认内容：{temp}" if temp else ""

    return f"""# Role: 智能客服助理（宽带报修模式）

## Context
- 当前来电手机号: {caller_phone}（系统自动注入）
- 当前步骤: {hint}{collected}{temp_hint}

## 规则
- 客户提供了信息（账号/地址/故障描述/电话/时间等）→ 调用 internet_repair_collect(value=客户说的内容)
- 客户明确确认（是/对/没错/确认/提交等）→ 调用 internet_repair_collect(affirm=true)
- 客户明确否认（不对/不是/错了/重新等）→ 调用 internet_repair_collect(affirm=false)
- 客户既提供信息又确认 → 调用 internet_repair_collect(affirm=true, value=内容)
- 客户明确放弃/取消 → 调用 cancel_skill
- 其他无关输入 → 不调工具，根据当前步骤自然语言引导客户
- 禁止讨论快递查询、投诉等其他话题
"""


# ══════════════════════════════════════════════════════════════
# Tool Schema
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
        "description": "用户明确表示放弃、取消当前流程时调用。",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string", "description": "用户放弃的原因，可选"}},
            "required": [],
        },
    },
}


# ══════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════
register_skill(SkillModule(
    name="internet_repair",
    tools=[_TOOL_ENTRY],
    trigger_keywords=["宽带坏了", "网络不通", "宽带报修", "网络故障", "宽带故障", "断网", "网络断了"],
    locked_tools=[_TOOL_COLLECT, _TOOL_CANCEL],
    build_locked_prompt=build_locked_prompt,
    handle=handle,
    tool_names=["internet_repair_skill", "internet_repair_collect"],
))



