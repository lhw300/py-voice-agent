"""
skill_complaint.py
─────────────────────────────────────────────────────────────
投诉业务模块。

业务特点：多字段收集 + 确认后提交。
字段定义、merge 逻辑、confirm 判断全部写在本文件内部，
不依赖任何共享的 draft engine —— 即使将来要换实现方式
（比如改成更简单的单 content 字段，或加更多字段），
只需要改这一个文件，不会牵动其他业务。
"""

import json
import logging
import time
from typing import Optional

from skill.skill_base import SkillModule, SkillStatus, register_skill, \
    skill_get, skill_set, skill_clear, \
    skill_need, skill_pending, skill_done, skill_error, skill_merge_fields

logger = logging.getLogger(__name__)

_DRAFT_KEY = "_complaint_draft"  # session 上暂存本次投诉收集到的字段
#draft — 用户逐步填写、尚未提交的表单字段，如 {category, content, expect}
# 本业务自己定义需要哪些字段，写死在这个文件里，不走外部 schema 配置
_REQUIRED_FIELDS = ["category", "content"]
_OPTIONAL_FIELDS = ["expect", "need_callback"]
_CATEGORY_ENUM = ["快递问题", "服务态度", "商品质量", "其他"]

_FIELD_LABELS = {
    "category": "投诉类型",
    "content": "具体描述",
    "expect": "期望处理方式",
    "need_callback": "是否需要人工回访",
}

_FIELD_META = {
    "category":     ("投诉类型",     f"{'、'.join(_CATEGORY_ENUM)}"),
    "content":      ("具体描述",     "30字以内"),
    "expect":       ("期望处理方式", "退款、道歉、整改、其他"),
    "need_callback":("是否需要人工回访", "是/否"),
}

# ══════════════════════════════════════════════════════════════
# Tool Schema（手写，不依赖动态生成）
# ══════════════════════════════════════════════════════════════
_TOOL_COMPLAINT = {
    "type": "function",
    "function": {
        "name": "complaint_skill",
        "description": (
            "用户表达投诉意图，或在投诉流程中继续提供信息/确认时调用。\n"
            "字段说明：\n"
            "  - category（投诉类型，必填）：快递问题/服务态度/商品质量/其他\n"
            "  - content（具体描述，必填）：用户描述的投诉具体内容\n"
            "  - expect（期望处理方式，选填）：用户期望如何解决，未提及可不填\n"
            "  - need_callback（是否需要人工回访，选填）：true/false，未提及默认 false\n"
            "调用原则：\n"
            "  - 只传本轮用户话里实际提到的字段，没提到的字段不要传\n"
            "  - 必填字段未集齐前 confirmed 始终为 false\n"
            "  - 必填字段集齐后会返回确认话术，用户明确同意后再次调用并传 confirmed=true\n"
            "  - 用户要修改某个已收集字段时，只传该字段新值即可\n"
            "【触发示例】'我要投诉'、'我想投诉'、'投诉你们'、'我不满意'、'举报'、'服务态度差'。\n"
            "【不触发】'投诉流程是什么'等知识性问题不调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "来电手机号，从系统 Context 自动获取"},
                "category": {"type": "string", "description": "投诉类型", "enum": _CATEGORY_ENUM},
                "content": {"type": "string", "description": "用户描述的投诉具体内容"},
                "expect": {"type": "string", "description": "用户期望如何解决，如退款、道歉、整改等"},
                "need_callback": {"type": "string", "description": "是否需要人工回访", "enum": ["true", "false"]},
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
# 字段 merge / 校验（本文件内部私有，不对外暴露通用接口）
# ══════════════════════════════════════════════════════════════




def _validate(draft: dict) -> Optional[str]:
    logger.debug(f"_validate | draft contents: {draft}")
    if "category" in draft:
        logger.debug(f"_validate|  draft[category] { draft['category']} ")
    else:
        logger.debug(f"_validate| category  in draft")

    if "category" in draft and draft["category"] not in _CATEGORY_ENUM:
        return f"投诉类型必须是以下之一：{ '、'.join(_CATEGORY_ENUM) }"
    return None


def _missing(draft: dict) -> list:
    return [f for f in _REQUIRED_FIELDS if f not in draft or not draft[f]]


def _format_confirm_text2(draft: dict) -> str:
    parts = [f"{_FIELD_LABELS[k]}：{draft[k]}" for k in _REQUIRED_FIELDS + _OPTIONAL_FIELDS if k in draft]
    return f"请确认以下投诉信息 — { '；'.join(parts) }。确认提交吗？"

def _format_confirm_text(draft: dict) -> str:
    parts = [f"{_FIELD_META[k][0]}：{draft[k]}" for k in _REQUIRED_FIELDS + _OPTIONAL_FIELDS if k in draft]
    return f"请确认以下投诉信息 — {'；'.join(parts)}。确认提交吗？"

def _format_missing_prompt2(missing: list) -> str:
    labels = [_FIELD_LABELS[m] for m in missing]
    return f"请问您的{ '、'.join(labels) }是？"

def _format_missing_prompt(missing: list) -> str:
    parts = [f"{_FIELD_META[m][0]}（{_FIELD_META[m][1]}）" for m in missing]
    return f"请问您的{'、'.join(parts)}是？"

async def _create_ticket(phone: str, draft: dict) -> dict:
    # TODO: 替换为真实落库逻辑
    ticket_id = f"CMP{int(time.time())}"
    logger.info(f"complaint accepted | phone={phone} ticket={ticket_id} draft={draft}")
    return {"ticket_id": ticket_id}


# ══════════════════════════════════════════════════════════════
# handle —— 对外统一入口
# ══════════════════════════════════════════════════════════════
async def handle(
        session,
        tool_name: str = None,
        phone: str = "",
        category: Optional[str] = None,
        content: Optional[str] = None,
        expect: Optional[str] = None,
        need_callback: Optional[str] = None,
        confirmed: bool = False,
) -> dict:
    draft = getattr(session, _DRAFT_KEY, None) or {}
    draft = skill_merge_fields(draft, category=category, content=content, expect=expect, need_callback=need_callback)
    setattr(session, _DRAFT_KEY, draft)

    err = _validate(draft)
    logger.debug(f"_validate err {err}")
    if err:
        return {"status": SkillStatus.NEED_INFO, "msg": err}

    missing = _missing(draft)
    logger.debug(f"_validate missing {missing}")
    if missing:
        return {"status": SkillStatus.NEED_INFO, "msg": _format_missing_prompt(missing)}
    logger.debug(f"confirmed {confirmed}")

    if not confirmed:
        return {"status": SkillStatus.PENDING_CONFIRM, "msg": _format_confirm_text(draft)}

    result = await _create_ticket(phone, draft)


    setattr(session, _DRAFT_KEY, None)
    return {
        "status": SkillStatus.DONE,
        "msg": f"您的投诉已受理，工单号 {result['ticket_id']}，我们将尽快跟进处理",
        "ticket_id": result["ticket_id"],
    }


# ══════════════════════════════════════════════════════════════
# 锁定 prompt
# ══════════════════════════════════════════════════════════════
def build_locked_prompt(session, caller_phone: str) -> str:
    draft = getattr(session, _DRAFT_KEY, None) or {}
    if draft:
        collected = "\n".join(f"  - {_FIELD_LABELS[k]}：{v}" for k, v in draft.items() if k in _FIELD_LABELS)
    else:
        collected = "  （暂未收集到任何字段）"

    return f"""# Role: 智能客服助理（投诉受理模式）

## Context
- 当前来电手机号: {caller_phone}（系统自动注入）
- 当前状态: 正在收集投诉信息
- 已收集字段:
{collected}

## 规则
- 用户提供了新字段信息 → 调用 complaint_skill(phone, 对应字段=值, confirmed=false)
- 已收集到完整确认话术后，用户明确确认（如"对"、"确认"、"提交"、"嗯"）
  → 调用 complaint_skill(phone, confirmed=true)，无需重传已有字段
- 用户要修改某个已收集字段 → 只传该字段新值即可，confirmed=false
- 用户明确放弃/取消 → 调用 cancel_skill
- 其他任何输入（既不提供信息、也不确认、也不取消）→ 不调工具，自然语言追问缺失信息
- 禁止讨论快递查询、宽带报修、知识问答等任何其他话题
## 输出格式
- 回复必须是纯文本，不得使用 markdown、bullet point、换行、emoji、序号
- 所有内容用自然口语连续表达，适合直接语音播放
"""


# ══════════════════════════════════════════════════════════════
# 注册
# ══════════════════════════════════════════════════════════════
register_skill(SkillModule(
    name="complaint",
    tools=[_TOOL_COMPLAINT],
    trigger_keywords=["我要投诉", "我想投诉", "要投诉", "想投诉", "投诉你们", "我要举报", "想举报", "我不满意"],
    locked_tools=[_TOOL_COMPLAINT, _TOOL_CANCEL],
    build_locked_prompt=build_locked_prompt,
    handle=handle,
    clear=lambda session: setattr(session, _DRAFT_KEY, None),
))
