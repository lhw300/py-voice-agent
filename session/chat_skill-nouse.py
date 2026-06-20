"""
chat_skill.py
─────────────────────────────────────────────────────────────
个性化业务 Skill 路由层  ——  动态工具隐藏架构（Dynamic Tool Masking）

核心设计：
  - 正常状态：传全量 SKILL_TOOLS，LLM 自由路由
  - 等待投诉内容（complaint_content）：只传 COMPLAINT_ONLY_TOOLS，LLM 无路可跳
  - 等待快递日期（express_date）：只传 EXPRESS_ONLY_TOOLS，LLM 无路可跳
  - 等待状态下 tool_calls=no → LLM 文本直接回复追问，不 fallback RAG
  - 关键词触发另一个 skill → 话题切换，清状态，换工具组

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
# 1. 关键词预检 + 状态机常量
# ══════════════════════════════════════════════════════════════
COMPLAINT_TRIGGER = ["我要投诉", "我想投诉", "要投诉", "想投诉", "投诉你们", "我要举报", "想举报", "我不满意"]
EXPRESS_TRIGGER   = ["查快递", "查物流", "快递到哪", "包裹在哪", "物流查询", "查一下快递", "查下快递"]
_ABORT_SIGNALS    = ["算了", "不投诉", "取消", "不查了", "没事了", "不用了"]

# session 等待状态 key
_STATE_KEY       = "_skill_wait"    # 值: "complaint_content" | "express_date" | None
_REJECT_COUNT_KEY = "_skill_reject" # 锁定状态下被拒绝次数计数器
_REJECT_MAX       = 2               # 超过此次数强制退出锁定状态


def _keyword_force_skill(text: str) -> Optional[str]:
    for kw in COMPLAINT_TRIGGER:
        if kw in text:
            return "complaint_skill"
    for kw in EXPRESS_TRIGGER:
        if kw in text:
            return "express_query_skill"
    return None


def _get_wait_state(session) -> Optional[str]:
    return getattr(session, _STATE_KEY, None)


def _set_wait_state(session, state: Optional[str]) -> None:
    setattr(session, _STATE_KEY, state)
    logger.debug(f"{session.sinfo}[skill_state] → {state!r}")


def _is_abort(text: str) -> bool:
    return any(sig in text for sig in _ABORT_SIGNALS)


def _get_reject_count(session) -> int:
    return getattr(session, _REJECT_COUNT_KEY, 0)


def _inc_reject_count(session) -> int:
    count = _get_reject_count(session) + 1
    setattr(session, _REJECT_COUNT_KEY, count)
    logger.debug(f"{session.sinfo}[skill_reject] count={count}/{_REJECT_MAX}")
    return count


def _clear_reject_count(session) -> None:
    setattr(session, _REJECT_COUNT_KEY, 0)


# ══════════════════════════════════════════════════════════════
# 2. 动态工具组（Tool Masking 核心）
# ══════════════════════════════════════════════════════════════
_TOOL_EXPRESS = {
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
                "phone": {"type": "string", "description": "来电手机号，从系统 Context 自动获取"},
                "date":  {"type": "string", "description": "可选，用户指定的日期，格式 YYYY-MM-DD"}
            },
            "required": ["phone"]
        }
    }
}

_TOOL_COMPLAINT = {
    "type": "function",
    "function": {
        "name": "complaint_skill",
        "description": (
            "用户表达投诉意图时调用。分三个阶段：\n"
            "阶段1（意向）：用户只表达投诉意向未描述内容，只传 phone，不传 content 和 confirmed。\n"
            "阶段2（收集内容）：用户描述了投诉内容，传 phone + content，confirmed=false。"
            "此时工具会复述内容并询问用户是否确认提交，不会生成工单。\n"
            "阶段3（确认提交）：用户明确表示确认/对/没错/提交等同意语义后，"
            "再次调用并传 phone + content（沿用阶段2的内容）+ confirmed=true，"
            "此时才真正生成工单。\n"
            "若用户在确认环节要求修改内容，回到阶段2重新收集，confirmed 重置为 false。"
            "【触发示例】'我要投诉'、'我想投诉'、'投诉你们'、'我不满意'、'举报'、'服务态度差'。"
            "【不触发】'投诉流程是什么'、'投诉渠道有哪些'等知识性问题不调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {
                    "type": "string",
                    "description": "来电手机号，从系统 Context 自动获取"
                },
                "content": {
                    "type": "string",
                    "description": "用户描述的投诉内容，阶段1不传，阶段2/3必传"
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "用户是否已明确确认提交。默认 false。"
                        "只有用户说出确认类语义（如'对'、'没错'、'提交'、'确认'）后才传 true。"
                        "true 时才会真正落库生成工单，false 时仅返回内容供用户确认。"
                    )
                }
            },
            "required": ["phone"]
        }
    }
}

_TOOL_CANCEL = {
    "type": "function",
    "function": {
        "name": "cancel_skill",
        "description": (
            "用户明确表示放弃、取消当前流程时调用。"
            "【触发示例】'算了'、'不投诉了'、'取消'、'不查了'、'没事了'、'不用了'、'放弃'、'我不想说了'。"
            "触发后立即清除当前流程，恢复正常对话。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "用户放弃的原因，可选"}
            },
            "required": []
        }
    }
}

# 完整工具集（正常状态）
SKILL_TOOLS_ALL       = [_TOOL_EXPRESS, _TOOL_COMPLAINT]
# 等待投诉内容时：投诉工具 + 取消工具
SKILL_TOOLS_COMPLAINT = [_TOOL_COMPLAINT, _TOOL_CANCEL]
# 等待快递日期时：快递工具 + 取消工具
SKILL_TOOLS_EXPRESS   = [_TOOL_EXPRESS, _TOOL_CANCEL]

# 兼容旧引用
SKILL_TOOLS = SKILL_TOOLS_ALL


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
- 阶段1 用户只表达投诉意向，未描述内容       → 只传 phone，skill 返回追问话术
- 阶段2 用户描述了投诉内容，但未确认提交     → 传 phone + content，confirmed=false，skill 复述内容并询问是否确认提交
- 阶段3 用户明确确认提交（如"对""没错""提交"）→ 传 phone + content + confirmed=true，直接完成受理生成工单

若用户在阶段3要求修改内容，回到阶段2重新收集，confirmed 重置为 false。

## Routing Rules

| 用户输入特征 | 动作 |
|---|---|
| 询问快递/物流/包裹/单号 | 调用 express_query_skill |
| 表达投诉/不满/举报/态度差 | 调用 complaint_skill |
| 回复日期（上轮在查快递） | 调用 express_query_skill(phone, date) |
| 回复投诉内容（上轮在问投诉内容） | 调用 complaint_skill(phone, content) |
| 其他（问候/知识问题/闲聊/无关话题） | 不调任何工具，输出空字符串 |

## 重要约束
1. phone 始终从 Context 自动获取，禁止向用户索取
2. 没有进行中的流程时，按用户当前意图正常路由；若已进入某个 skill 的等待状态
   （如等待投诉内容、等待快递日期），用户必须明确放弃（cancel_skill）才能退出，
   不会因为提及其他话题而自动切换
3. 工具返回的原始数据不得直接输出，必须用自然语言组织后回复
4. 不得暴露工具名称、参数名称等内部信息给用户
"""


def build_express_locked_prompt(caller_phone: str) -> str:
    """等待快递日期时的专用锁定 prompt"""
    return f"""# Role: 智能客服助理（快递查询模式）

## Context
- 当前来电手机号: {caller_phone}（系统自动注入）
- 当前状态: 正在等待客户提供快递查询日期

## 当前任务
已查到客户有多条快递记录，需要客户告知具体查哪一天。

## 规则
- 客户提供了日期 → 调用 express_query_skill(phone, date)
- 客户明确放弃/取消 → 调用 cancel_skill
- 其他任何输入 → 不调工具，只说"请问您想查哪一天的快递呢？"
- 禁止讨论投诉、知识问答等任何其他话题
"""


def build_complaint_locked_prompt(caller_phone: str) -> str:
    """等待投诉内容时的专用锁定 prompt"""
    return f"""# Role: 智能客服助理（投诉受理模式）

## Context
- 当前来电手机号: {caller_phone}（系统自动注入）
- 当前状态: 正在等待客户描述投诉内容

## 当前任务
客户已表达投诉意向，需要客户描述具体问题。

## 规则
- 客户描述了投诉内容 → 调用 complaint_skill(phone, content)
- 客户明确放弃/取消 → 调用 cancel_skill
- 其他任何输入 → 不调工具，只说"请问您具体想投诉什么问题呢？"
- 禁止讨论快递查询、知识问答等任何其他话题
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


async def _complaint_skill(phone: str, content: Optional[str] = None, confirmed: bool = False) -> str:
    if not content:
        return json.dumps({"status": "need_content", "msg": "请简要描述您要投诉的问题"}, ensure_ascii=False)

    if not confirmed:
        return json.dumps({
            "status": "pending_confirm",
            "content": content,
            "msg": f"您反馈的内容是：{content}，确认提交吗？"
        }, ensure_ascii=False)

    ticket_id = f"CMP{int(time.time())}"
    logger.info(f"complaint accepted | phone={phone} ticket={ticket_id} content={content}")
    return json.dumps({
        "status":    "accepted",
        "ticket_id": ticket_id,
        "msg":       f"您的投诉已受理，工单号 {ticket_id}，我们将尽快跟进处理"
    }, ensure_ascii=False)


async def _cancel_skill(reason: Optional[str] = None) -> str:
    logger.info(f"cancel_skill triggered | reason={reason!r}")
    return json.dumps({"status": "cancelled", "msg": "已为您取消当前流程"}, ensure_ascii=False)


_SKILL_MAP = {
    "express_query_skill": _express_query_skill,
    "complaint_skill":     _complaint_skill,
    "cancel_skill":        _cancel_skill,
}


# ══════════════════════════════════════════════════════════════
# 5. ask_skill —— 挂载到 ChatSession 的方法
# ══════════════════════════════════════════════════════════════
async def ask_skill(session: "ChatSession", text: str) -> Optional[ChatAnswer]:
    """
    动态工具隐藏架构路由逻辑：

    [正常状态] wait_state=None
        → 关键词预检命中  → tool_choice=forced，tools=ALL
        → 无关键词        → tool_choice=auto，tools=ALL
        → tool_calls=no   → return None（fallback RAG）

    [等待投诉内容] wait_state=complaint_content
        → 关键词命中另一 skill → 话题切换，清状态，换工具组
        → 放弃信号             → 清状态，fallback RAG
        → 其他                 → tools=COMPLAINT_ONLY，tool_choice=auto
                                  tool_calls=yes → 调 complaint_skill(content=text)
                                  tool_calls=no  → LLM 文本直接回复（不 fallback RAG）

    [等待快递日期] wait_state=express_date
        → 关键词命中另一 skill → 话题切换，清状态，换工具组
        → 放弃信号             → 清状态，fallback RAG
        → 其他                 → tools=EXPRESS_ONLY，tool_choice=auto
                                  tool_calls=yes → 调 express_query_skill(date=text)
                                  tool_calls=no  → LLM 文本直接回复（不 fallback RAG）
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
    result         = None
    answer_text    = None

    try:
        llm = session.router.finalLlm() if session.router else None
        if llm is None:
            logger.warning(session.sinfo + "[ask_skill] router/llm not available, fallback to ask()")
            return None

        wait_state = _get_wait_state(session)

        # ── 正常状态下的放弃信号：直接 fallback（无流程可取消）──────
        if _is_abort(text) and not wait_state:
            logger.debug(session.sinfo + "[ask_skill] abort signal (no state), fallback")
            return None

        # 注意：等待状态下不做话题切换检测，必须通过 cancel_skill 才能退出当前流程

        # ══════════════════════════════════════════════════════════
        # 分支 A：有等待状态 → 动态工具隐藏，LLM 只看到当前 skill
        # ══════════════════════════════════════════════════════════
        if wait_state in ("complaint_content", "express_date"):
            if wait_state == "complaint_content":
                masked_tools  = SKILL_TOOLS_COMPLAINT
                locked_skill  = "complaint_skill"
                locked_prompt = build_complaint_locked_prompt(caller_phone)
                logger.debug(session.sinfo + "[ask_skill] tool mask → COMPLAINT_ONLY")
            else:
                masked_tools  = SKILL_TOOLS_EXPRESS
                locked_skill  = "express_query_skill"
                locked_prompt = build_express_locked_prompt(caller_phone)
                logger.debug(session.sinfo + "[ask_skill] tool mask → EXPRESS_ONLY")

            # 锁定模式：只传 system prompt + 当前用户输入，丢弃历史
            # 历史会携带其他 skill 的对话内容，干扰 LLM 判断，锁定状态下不需要上下文
            locked_messages = [
                {"role": "system", "content": locked_prompt},
                {"role": "user",   "content": text},
            ]

            response   = await run_in_threadpool(
                llm.chat_with_tools, locked_messages, tools=masked_tools, tool_choice="auto"
            )
            tool_calls = getattr(response, "tool_calls", None)

            logger.debug(session.sinfo + f"[ask_skill] masked routing elapsed={int((time.time()-t0)*1000)}ms "
                         + f"tool_calls={'yes' if tool_calls else 'no'}")

            if tool_calls:
                locked_messages.append({
                    "role":       "assistant",
                    "content":    response.content or "",
                    "tool_calls": [tc.model_dump() for tc in tool_calls],
                })
                for tc in tool_calls:
                    last_tool_name = tc.function.name
                    args = json.loads(tc.function.arguments)
                    # cancel_skill 不需要 phone
                    if last_tool_name != "cancel_skill":
                        if "phone" not in args or not args["phone"]:
                            args["phone"] = caller_phone
                    fn = _SKILL_MAP.get(last_tool_name)
                    if fn:
                        logger.info(session.sinfo + f"[ask_skill] masked call {last_tool_name} args={args}")
                        result = await fn(**args)
                    else:
                        result = json.dumps({"error": f"unknown skill: {last_tool_name}"})
                    logger.debug(session.sinfo + f"[ask_skill] tool result: {result}")
                    locked_messages.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "name":         last_tool_name,
                        "content":      result,
                    })

                _update_state(session, result)
                _clear_reject_count(session)  # 成功调用 tool，重置拒绝计数
                answer_text = await run_in_threadpool(llm.chat_with_tools, locked_messages)

            else:
                # tool_calls=no → 锁定 prompt 下 LLM 文本就是正确的追问，直接用
                answer_text = response if isinstance(response, str) else (response.content or "")
                last_tool_name = locked_skill
                logger.debug(session.sinfo + f"[ask_skill] masked no-tool, use LLM text as reply")

                # 累计拒绝次数，超限则强制退出锁定状态（防止用户陷入死循环）
                reject_count = _inc_reject_count(session)
                if reject_count >= _REJECT_MAX:
                    logger.info(session.sinfo + f"[ask_skill] reject limit reached ({reject_count}), force exit lock state={wait_state!r}")
                    _set_wait_state(session, None)
                    _clear_reject_count(session)
                    return await ask_skill(session, text)   # ← 新增：立刻用初始流程重新处理这句话
                # else: 等待状态保持不变，下一轮继续锁定

        # ══════════════════════════════════════════════════════════
        # 分支 B：正常状态 → 全量工具，关键词/auto 路由
        # ══════════════════════════════════════════════════════════
        else:
            kw_forced  = _keyword_force_skill(text)
            tool_choice = {"type": "function", "function": {"name": kw_forced}} if kw_forced else "auto"
            if kw_forced:
                logger.debug(session.sinfo + f"[ask_skill] keyword forced → {kw_forced}")

            response   = await run_in_threadpool(
                llm.chat_with_tools, messages, tools=SKILL_TOOLS_ALL, tool_choice=tool_choice
            )
            tool_calls = getattr(response, "tool_calls", None)

            logger.debug(session.sinfo + f"[ask_skill] normal routing elapsed={int((time.time()-t0)*1000)}ms "
                         + f"tool_calls={'yes' if tool_calls else 'no'}")

            if not tool_calls:
                return None   # 正常状态下 no-tool → fallback RAG（期望行为）

            messages.append({
                "role":       "assistant",
                "content":    response.content or "",
                "tool_calls": [tc.model_dump() for tc in tool_calls],
            })
            logger.debug(session.sinfo + f"[第一次 chat with tool后] tool_calls={tool_calls}")

            for tc in tool_calls:
                last_tool_name = tc.function.name
                args = json.loads(tc.function.arguments)
                if "phone" not in args or not args["phone"]:
                    args["phone"] = caller_phone
                fn = _SKILL_MAP.get(last_tool_name)
                if fn:
                    logger.info(session.sinfo + f"[ask_skill] calling {last_tool_name} args={args}")
                    result = await fn(**args)
                else:
                    logger.warning(session.sinfo + f"[ask_skill] unknown skill: {last_tool_name}")
                    result = json.dumps({"error": f"unknown skill: {last_tool_name}"})
                logger.debug(session.sinfo + f"[ask_skill] tool result: name={last_tool_name} result={result}")
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "name":         last_tool_name,
                    "content":      result,
                })

            # 更新状态
            _update_state(session, result)
            # 第二次 LLM 组织回复
            answer_text = await run_in_threadpool(llm.chat_with_tools, messages)

        # ── 公共：日志 + history + 返回 ──────────────────────────────
        logger.debug(session.sinfo + f"[ask_skill] total elapsed={int((time.time()-t0)*1000)}ms "
                     + f"skill={last_tool_name} answer={answer_text[:80] if answer_text else ''}")

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


def _update_state(session, result: Optional[str]) -> None:
    if not result:
        return
    try:
        status = json.loads(result).get("status")
        if status == "need_content":
            _set_wait_state(session, "complaint_content")
        elif status == "pending_confirm":
            _set_wait_state(session, "complaint_content")   # 继续锁定，等待用户确认
        elif status == "need_date":
            _set_wait_state(session, "express_date")
        else:
            _set_wait_state(session, None)
    except Exception:
        _set_wait_state(session, None)