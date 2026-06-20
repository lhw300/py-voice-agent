"""
skill_internet.py
─────────────────────────────────────────────────────────────
宽带报修业务模块。

注意：本文件结构和 skill_complaint.py 看起来相似（都是多字段+confirm），
但代码完全独立、不互相 import、不共享字段 merge 函数。
这是有意为之：两个业务的字段以后很可能各自演化出不同的分支逻辑
（比如报修以后可能要加"是否在保修期"这种条件字段），
保持独立可以避免"为了复用而牵一发动全身"。
"""

import json
import logging
import time
from typing import Optional

from skill.skill_base import SkillModule, SkillStatus, register_skill

logger = logging.getLogger(__name__)

_DRAFT_KEY = "_internet_draft"

_REQUIRED_FIELDS = ["fault_type", "address"]
_OPTIONAL_FIELDS = ["contact_time", "urgent"]
_FAULT_TYPE_ENUM = ["完全断网", "网速慢", "频繁掉线", "其他"]

_FIELD_LABELS = {
    "fault_type": "故障类型",
    "address": "报修地址",
    "contact_time": "方便联系时间",
    "urgent": "是否加急",
}


# ══════════════════════════════════════════════════════════════
# Tool Schema
# ══════════════════════════════════════════════════════════════
_TOOL_INTERNET = {
    "type": "function",
    "function": {
        "name": "internet_repair_skill",
        "description": (
            "用户反映宽带、网络故障，要求报修时调用。\n"
            "字段说明：\n"
            "  - fault_type（故障类型，必填）：完全断网/网速慢/频繁掉线/其他\n"
            "  - address（报修地址，必填）：用户报修的具体地址\n"
            "  - contact_time（方便联系时间，选填）：未提及可不填\n"
            "  - urgent（是否加急，选填）：true/false，未提及默认 false\n"
            "调用原则：\n"
            "  - 只传本轮用户话里实际提到的字段，没提到的字段不要传\n"
            "  - 必填字段未集齐前 confirmed 始终为 false\n"
            "  - 必填字段集齐后会返回确认话术，用户明确同意后再次调用并传 confirmed=true\n"
            "  - 用户要修改某个已收集字段时，只传该字段新值即可\n"
            "【触发示例】'宽带坏了'、'网络不通'、'上不了网'、'宽带断了'、'网速很慢'。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "来电手机号，从系统 Context 自动获取"},
                "fault_type": {"type": "string", "description": "故障类型", "enum": _FAULT_TYPE_ENUM},
                "address": {"type": "string", "description": "用户报修的具体地址"},
                "contact_time": {"type": "string", "description": "用户方便接听或上门的时间段"},
                "urgent": {"type": "string", "description": "是否加急处理", "enum": ["true", "false"]},
                "confirmed": {
                    "type": "boolean",
                    "description": "用户是否已明确确认提交（如'对'、'确认'、'提交'）。默认 false。",
                },
            },
            "required": ["phone"],
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
# 字段 merge / 校验
# ══════════════════════════════════════════════════════════════
def _get_draft(session) -> dict:
    return getattr(session, _DRAFT_KEY, {}) or {}


def _set_draft(session, draft: dict) -> None:
    setattr(session, _DRAFT_KEY, draft)


def _clear_draft(session) -> None:
    setattr(session, _DRAFT_KEY, {})


def _merge_fields(draft: dict, **fields) -> dict:
    for k, v in fields.items():
        if v in (None, ""):
            continue
        draft[k] = v
    return draft


def _validate(draft: dict) -> Optional[str]:
    if "fault_type" in draft and draft["fault_type"] not in _FAULT_TYPE_ENUM:
        return f"故障类型必须是以下之一：{ '、'.join(_FAULT_TYPE_ENUM) }"
    return None


def _missing(draft: dict) -> list:
    return [f for f in _REQUIRED_FIELDS if f not in draft or not draft[f]]


def _format_confirm_text(draft: dict) -> str:
    parts = [f"{_FIELD_LABELS[k]}：{draft[k]}" for k in _REQUIRED_FIELDS + _OPTIONAL_FIELDS if k in draft]
    return f"请确认以下报修信息 — { '；'.join(parts) }。确认提交吗？"


def _format_missing_prompt(missing: list) -> str:
    labels = [_FIELD_LABELS[m] for m in missing]
    return f"请问您的{ '、'.join(labels) }是？"


async def _create_repair_order(phone: str, draft: dict) -> dict:
    # TODO: 替换为真实落库逻辑
    order_id = f"RPR{int(time.time())}"
    logger.info(f"repair order accepted | phone={phone} order={order_id} draft={draft}")
    return {"order_id": order_id}


# ══════════════════════════════════════════════════════════════
# handle
# ══════════════════════════════════════════════════════════════
async def handle(
    session,
    phone: str,
    fault_type: Optional[str] = None,
    address: Optional[str] = None,
    contact_time: Optional[str] = None,
    urgent: Optional[str] = None,
    confirmed: bool = False,
) -> dict:
    draft = _get_draft(session)
    draft = _merge_fields(draft, fault_type=fault_type, address=address, contact_time=contact_time, urgent=urgent)
    _set_draft(session, draft)

    err = _validate(draft)
    if err:
        return {"status": SkillStatus.NEED_INFO, "msg": err}

    missing = _missing(draft)
    if missing:
        return {"status": SkillStatus.NEED_INFO, "msg": _format_missing_prompt(missing)}

    if not confirmed:
        return {"status": SkillStatus.PENDING_CONFIRM, "msg": _format_confirm_text(draft)}

    result = await _create_repair_order(phone, draft)
    _clear_draft(session)
    return {
        "status": SkillStatus.DONE,
        "msg": f"您的报修已受理，工单号 {result['order_id']}，师傅会尽快联系您",
        "order_id": result["order_id"],
    }


# ══════════════════════════════════════════════════════════════
# 锁定 prompt
# ══════════════════════════════════════════════════════════════
def build_locked_prompt(session, caller_phone: str) -> str:
    draft = _get_draft(session)
    if draft:
        collected = "\n".join(f"  - {_FIELD_LABELS[k]}：{v}" for k, v in draft.items() if k in _FIELD_LABELS)
    else:
        collected = "  （暂未收集到任何字段）"

    return f"""# Role: 智能客服助理（宽带报修模式）

## Context
- 当前来电手机号: {caller_phone}（系统自动注入）
- 当前状态: 正在收集报修信息
- 已收集字段:
{collected}

## 规则
- 用户提供了新字段信息 → 调用 internet_repair_skill(phone, 对应字段=值, confirmed=false)
- 已收集到完整确认话术后，用户明确确认（如"对"、"确认"、"提交"）
  → 调用 internet_repair_skill(phone, confirmed=true)，无需重传已有字段
- 用户要修改某个已收集字段 → 只传该字段新值即可，confirmed=false
- 用户明确放弃/取消 → 调用 cancel_skill
- 其他任何输入（既不提供信息、也不确认、也不取消）→ 不调工具，自然语言追问缺失信息
- 禁止讨论快递查询、投诉、知识问答等任何其他话题
"""


# ══════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════
register_skill(SkillModule(
    name="internet",
    tools=[_TOOL_INTERNET],
    trigger_keywords=["宽带坏了", "网络不通", "宽带报修", "网络故障", "上不了网", "宽带断了", "网速慢"],
    locked_tools=[_TOOL_INTERNET, _TOOL_CANCEL],
    build_locked_prompt=build_locked_prompt,
    handle=handle,
))
