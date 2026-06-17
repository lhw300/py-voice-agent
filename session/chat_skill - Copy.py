"""
chat_skill.py
─────────────────────────────────────────────────────────────
个性化业务 Skill 路由层

职责：
  - 定义 SKILL_TOOLS（express_query_skill / complaint_skill）
  - 实现各 skill 的业务逻辑（mock，替换为真实 DB 调用）
  - ask_skill() 挂载到 ChatSession，作为 ask() 的前置路由

用法：
    from chat_skill import ask_skill as _ask_skill

    # chat_session.py 里：
    async def ask_skill(self, text: str):
        return await _ask_skill(self, text)

    # ai_send.py 里：
    session._caller_phone = req.phone or ""
    answer = await session.ask_skill(req.text)
    if answer is None:
        answer = await run_in_threadpool(session.ask, req.text)
"""

import json
import logging
import time
from starlette.concurrency import run_in_threadpool
from typing import Optional, TYPE_CHECKING

from models import ChatAnswer, Action, CODE_OK

if TYPE_CHECKING:
    from session.chat_session import ChatSession

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 1. 关键词预检（兜底 qwen-plus tool_choice=auto 触发不稳定）
# ══════════════════════════════════════════════════════════════
# 精确短语匹配，避免"投诉流程是什么"误判
COMPLAINT_TRIGGER = ["我要投诉", "我想投诉", "要投诉", "想投诉", "投诉你们", "我要举报", "想举报", "我不满意"]
EXPRESS_TRIGGER   = ["查快递", "查物流", "快递到哪", "包裹在哪", "物流查询", "查一下快递", "查下快递"]

def _keyword_force_skill(text: str) -> Optional[str]:
    """精确短语预检，命中返回 skill 名，否则返回 None 走 LLM 路由"""
    for kw in COMPLAINT_TRIGGER:
        if kw in text:
            return "complaint_skill"
    for kw in EXPRESS_TRIGGER:
        if kw in text:
            return "express_query_skill"
    return None


# ══════════════════════════════════════════════════════════════
# 2. Tools 定义
# ══════════════════════════════════════════════════════════════
SKILL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "express_query_skill",
            "description": (
                "用户询问快递、物流、包裹状态时调用。"
                "未指定日期时返回该手机号有快递记录的日期列表，由 AI 询问客户要查哪天；"
                "用户指定日期后再次调用，返回当天最后一条快递状态。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "来电手机号，从系统 Context 自动获取，禁止向用户索取"
                    },
                    "date": {
                        "type": "string",
                        "description": "可选，用户指定的日期，格式 YYYY-MM-DD"
                    }
                },
                "required": ["phone"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complaint_skill",
            "description": (
                "用户表达投诉意图时调用。分三个阶段："
                "阶段1：用户只表达投诉意向未描述内容，只传 phone；"
                "阶段2：用户描述了内容但未确认，传 phone + content；"
                "阶段3：用户明确确认，传 phone + content + confirmed=true 完成受理。"
                "若用户否认或要重新描述，只传 phone 重新进入阶段1。"
                "【触发示例】'我要投诉'、'我想投诉'、'投诉你们'、'我不满意'、'举报'、'服务态度差'。"
                "【不触发】'投诉流程是什么'、'投诉渠道有哪些'等知识性问题不调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "来电手机号，从系统 Context 自动获取，禁止向用户索取"
                    },
                    "content": {
                        "type": "string",
                        "description": "用户描述的投诉内容，阶段1不传"
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": "用户明确确认后传 true，阶段1/2不传"
                    }
                },
                "required": ["phone"]
            }
        }
    }
]


# ══════════════════════════════════════════════════════════════
# 3. System prompt
# ══════════════════════════════════════════════════════════════
def build_skill_prompt(caller_phone: str) -> str:
    return f"""# Role: 智能客服助理

## Context
- 当前来电手机号: {caller_phone}（系统自动注入，禁止向用户索取）

## Available Tools

### 1. express_query_skill
用于查询来电客户的快递/物流/包裹状态。
- 用户未指定日期 → 只传 phone，返回日期列表后询问客户要查哪天
- 用户已指定日期 → 传 phone + date，直接返回当天最后状态

### 2. complaint_skill
用于受理客户投诉，分三个阶段：
- 阶段1 用户只表达投诉意向，未描述内容 → 只传 phone，skill 返回追问话术
- 阶段2 用户描述了投诉内容，尚未确认   → 传 phone + content，skill 返回复述请用户确认
- 阶段3 用户明确确认                   → 传 phone + content + confirmed=true，完成受理生成工单

## Routing Rules

| 用户输入特征 | 动作 |
|---|---|
| 询问快递/物流/包裹/单号 | 调用 express_query_skill |
| 表达投诉/不满/举报/态度差 | 调用 complaint_skill |
| 回复日期（上轮在查快递） | 调用 express_query_skill(phone, date) |
| 回复投诉内容（上轮在问投诉内容） | 调用 complaint_skill(phone, content) |
| 确认投诉（说"对/是/好/确认/提交/没错"等类似表达） | 调用 complaint_skill(phone, content=上轮内容, confirmed=true) |
| 拒绝或重新描述（说"不/不对/不确认/不确定/算了/重说/重新说/取消"等类似表达） | 调用 complaint_skill(phone)，重新进入阶段1 |
| 其他（问候/知识问题/闲聊/无关话题） | 不调任何工具，输出空字符串 |

## 重要约束
1. phone 始终从 Context 自动获取，禁止向用户索取
2. 用户切换话题时，优先响应新话题，放弃当前未完成流程
3. 工具返回的原始数据不得直接输出，必须用自然语言组织后回复
4. 不得暴露工具名称、参数名称等内部信息给用户
"""


# ══════════════════════════════════════════════════════════════
# 4. Skill 实现
# ══════════════════════════════════════════════════════════════

async def _express_query_skill(phone: str, date: Optional[str] = None) -> str:
    if date is None:
        # TODO: 替换为真实 DB 查询
        dates = ["2024-03-01", "2024-03-05", "2024-03-10"]  # mock
        if not dates:
            return json.dumps({"status": "no_record", "msg": "未查询到该手机号的快递记录"}, ensure_ascii=False)
        return json.dumps({"status": "need_date", "dates": dates, "msg": f"查询到您有 {len(dates)} 条快递记录"}, ensure_ascii=False)
    else:
        # TODO: 替换为真实 DB 查询
        record = {"date": date, "status": "已到达广州转运中心", "update_time": "14:32"}  # mock
        if not record:
            return json.dumps({"status": "not_found", "msg": f"未找到 {date} 的快递记录"}, ensure_ascii=False)
        return json.dumps({"status": "ok", "date": record["date"], "express_status": record["status"], "update_time": record["update_time"]}, ensure_ascii=False)


async def _complaint_skill(
        phone: str,
        content: Optional[str] = None,
        confirmed: Optional[bool] = None
) -> str:
    if not content:
        return json.dumps({"status": "need_content", "msg": "请简要描述您要投诉的问题"}, ensure_ascii=False)

    if not confirmed:
        return json.dumps({
            "status": "need_confirm",
            "content": content,
            "msg": f"您投诉的是：{content}，确认提交吗？"
        }, ensure_ascii=False)

    # TODO: 替换为真实 DB 写入
    ticket_id = f"CMP{int(time.time())}"
    logger.info(f"complaint accepted | phone={phone} ticket={ticket_id} content={content}")
    return json.dumps({
        "status": "accepted",
        "ticket_id": ticket_id,
        "msg": f"您的投诉已受理，工单号 {ticket_id}，我们将尽快跟进处理"
    }, ensure_ascii=False)


_SKILL_MAP = {
    "express_query_skill": _express_query_skill,
    "complaint_skill":     _complaint_skill,
}


# ══════════════════════════════════════════════════════════════
# 5. ask_skill —— 挂载到 ChatSession 的方法
# ══════════════════════════════════════════════════════════════
async def ask_skill(session: "ChatSession", text: str) -> Optional[ChatAnswer]:
    """
    返回 ChatAnswer  → 命中 skill，直接使用
    返回 None        → 未命中，交给原有 session.ask() 处理
    """
    import ai_config as AiConfig

    if AiConfig.getStringConfig("skill_tools.enabled", "true").lower() != "true":
        return None

    caller_phone = getattr(session, "_caller_phone", "") or ""

    history_msgs = session.history.toJsonArrayWithWindow()
    logger.debug(session.sinfo + f"_messages={session.history._messages}")
    non_system = [m for m in history_msgs if m.get("role") != "system"]
    logger.debug(session.sinfo + "non_system=" + str(non_system))

    skill_system = build_skill_prompt(caller_phone)
    messages = [{"role": "system", "content": skill_system}] + non_system
    messages.append({"role": "user", "content": text})

    t0 = time.time()
    last_tool_name = None
    result = None

    try:
        llm = session.router.finalLlm() if session.router else None
        if llm is None:
            logger.warning(session.sinfo + "[ask_skill] router/llm not available, fallback to ask()")
            return None

        # ── 关键词预检：强制指定 tool_choice ────────────────────────
        forced = _keyword_force_skill(text)
        if forced:
            tool_choice = {"type": "function", "function": {"name": forced}}
            logger.debug(session.sinfo + f"[ask_skill] keyword forced → {forced}")
        else:
            tool_choice = "auto"

        # ── 第一次 LLM：路由判断 ────────────────────────────────────
        response = await run_in_threadpool(
            llm.chat_with_tools, messages, tools=SKILL_TOOLS, tool_choice=tool_choice
        )
        tool_calls = getattr(response, "tool_calls", None)

        logger.debug(session.sinfo + f"[ask_skill] tool routing elapsed={int((time.time()-t0)*1000)}ms "
                     + f"tool_calls={'yes' if tool_calls else 'no'}")

        if not tool_calls:
            return None

        # ── 执行 skill ───────────────────────────────────────────────
        messages.append({
            "role":       "assistant",
            "content":    response.content or "",
            "tool_calls": [tc.model_dump() for tc in response.tool_calls],
        })
        logger.debug(f"{session.sinfo}[第一次 chat with tool后 content={response.content} tool_calls={response.tool_calls}")

        for tc in tool_calls:
            last_tool_name = tc.function.name
            args = json.loads(tc.function.arguments)
            if "phone" not in args or not args["phone"]:
                args["phone"] = caller_phone
            fn = _SKILL_MAP.get(last_tool_name)

            if fn is None:
                logger.warning(session.sinfo + f"[ask_skill] unknown skill: {last_tool_name}")
                result = json.dumps({"error": f"unknown skill: {last_tool_name}"})
            else:
                logger.info(session.sinfo + f"[ask_skill] calling {last_tool_name} args={args}")
                result = await fn(**args)

            logger.debug(f"{session.sinfo}[ask_skill] tool result: name={last_tool_name} result={result}")
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "name":         last_tool_name,
                "content":      result,
            })

        # ── 第二次 LLM：组织自然语言回复 ────────────────────────────
        answer_text = await run_in_threadpool(llm.chat_with_tools, messages)

        logger.debug(session.sinfo + f"[ask_skill] total elapsed={int((time.time()-t0)*1000)}ms "
                     + f"skill={last_tool_name} answer={answer_text[:80] if answer_text else ''}")

        # ── 写入 session history ─────────────────────────────────────
        session._history_add("user", text)
        if answer_text and answer_text.strip():
            session._history_add("assistant", answer_text)
            session._history_trim(60)

        return ChatAnswer(
            code       = CODE_OK,
            answer     = answer_text,
            action     = Action.NONE,
            intent     = "COMMAND",
            sub_intent = last_tool_name,
            hit_source = "skill",
        )

    except Exception as e:
        logger.error(session.sinfo + f"[ask_skill] error: {e}", exc_info=True)
        return ChatAnswer.of_system_error(e)