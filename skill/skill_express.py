"""
skill_express.py
─────────────────────────────────────────────────────────────
快递查询业务模块。

业务特点：简单流程，无需 draft/confirm：
  1. 用户问快递 → 查到日期列表 → 返回 NEED_INFO，让用户选日期
  2. 用户选了日期 → 查到当天状态 → 返回 DONE

不依赖任何共享 draft engine，状态全部用 session 上的几个简单属性自己管理。
"""

import logging
from typing import Optional

from skill.skill_base import SkillModule, SkillStatus, register_skill

logger = logging.getLogger(__name__)

_STATE_KEY = "_express_dates"  # 暂存查到的日期列表，供用户选择后核对


# ══════════════════════════════════════════════════════════════
# Tool Schema
# ══════════════════════════════════════════════════════════════
_TOOL_EXPRESS_BY_PHONE = {
    "type": "function",
    "function": {
        "name": "express_query_skill_by_phone",
        "description": (
            "用户询问快递、物流、包裹状态，但未指定日期时调用。"
            "返回该手机号有快递记录的日期列表，再由 AI 询问客户要查哪天。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "来电手机号，从系统 Context 自动获取"},
            },
            "required": ["phone"],
        },
    },
}

_TOOL_EXPRESS_BY_DATE = {
    "type": "function",
    "function": {
        "name": "express_query_skill_by_date",
        "description": (
            "用户明确说出具体日期（如\"3月1日\"、\"2024-03-05\"）后调用，查询当天的快递物流状态。\
             必须有明确日期才能调用，用户未提供日期时禁止调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "来电手机号，从系统 Context 自动获取"},
                "date":  {"type": "string", "description": "用户指定的日期，格式 YYYY-MM-DD"},
            },
            "required": ["phone", "date"],
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
# 业务逻辑（自包含，不依赖共享引擎）
# ══════════════════════════════════════════════════════════════
async def _query_dates(phone: str) -> list:
    # TODO: 替换为真实 DB 查询
    return ["2024-03-01", "2024-03-05", "2024-03-10"]  # mock


async def _query_status_by_date(phone: str, date: str) -> Optional[dict]:
    # TODO: 替换为真实 DB 查询
    return {"date": date, "status": "已到达广州转运中心", "update_time": "14:32"}  # mock


async def handle(session, tool_name: str, phone: str, date: Optional[str] = None) -> dict:
    if tool_name == "express_query_skill_by_phone":
        dates = await _query_dates(phone)
        if not dates:
            return {"status": SkillStatus.DONE, "msg": "未查询到该手机号的快递记录"}
        setattr(session, _STATE_KEY, dates)
        return {
            "status": SkillStatus.NEED_INFO,
            "msg": f"记录数: {len(dates)} ,日期是: {', '.join(dates)}",
        }

    # express_query_skill_by_date
    record = await _query_status_by_date(phone, date)
    setattr(session, _STATE_KEY, None)
    if not record:
        return {"status": SkillStatus.DONE, "msg": f"未找到 {date} 的快递记录"}

    return {
        "status": SkillStatus.DONE,
        "msg": f"{record['date']} 的快递状态：{record['status']}（更新于 {record['update_time']}）",
    }


# ══════════════════════════════════════════════════════════════
# 锁定 prompt
# ══════════════════════════════════════════════════════════════
def build_locked_prompt(session, caller_phone: str) -> str:
    dates = getattr(session, _STATE_KEY, None) or []
    date_hint = f"（可选日期：{', '.join(dates)}）" if dates else ""
    return f"""# Role: 智能客服助理（快递查询模式）

## Context
- 当前来电手机号: {caller_phone}（系统自动注入）
- 当前状态: 正在等待客户提供快递查询日期 {date_hint}

## 规则
- 客户明确说出具体日期（如"3月1日"、"第一个"、"2024-03-05"）→ 调用 express_query_skill_by_date(phone, date)
- 客户明确放弃/取消 → 调用 cancel_skill
- 其他任何输入，包括投诉、报修、问候等与日期无关的内容 → 不调任何工具，只回复"请问您想查哪一天的快递呢？"
- 禁止讨论投诉、报修、知识问答等任何其他话题
"""


# ══════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════
register_skill(SkillModule(
    name="express",
    tools=[_TOOL_EXPRESS_BY_PHONE, _TOOL_EXPRESS_BY_DATE],
    trigger_keywords=["查快递", "查物流", "快递到哪", "包裹在哪", "物流查询", "查一下快递", "查下快递"],
    locked_tools=[_TOOL_EXPRESS_BY_DATE, _TOOL_CANCEL],
    build_locked_prompt=build_locked_prompt,
    handle=handle,
))