"""
chat_skill.py
─────────────────────────────────────────────────────────────
个性化业务 Skill 路由总控（重构版）

设计原则：
  - 本文件不包含任何业务逻辑（字段是什么、怎么校验、怎么落库一概不知）
  - 只负责：关键词预检 → 选业务 → 工具掩蔽（Tool Masking）→ 调用 handle()
            → 根据统一 status 决定锁定/解锁 → 组织自然语言回复
  - 新增一个业务：写一个 skill_xxx.py，调用 register_skill() 注册即可，
    本文件不需要任何改动（除了 import 一下新模块触发注册）

用法：
    from chat_skill import ask_skill as _ask_skill

    async def ask_skill(self, text: str):
        return await _ask_skill(self, text)
"""

import json
import logging
import time
from starlette.concurrency import run_in_threadpool
from typing import Optional, TYPE_CHECKING
from datetime import date
from models import ChatAnswer, Action, CODE_OK
from skill.skill_base import (
    SkillStatus, SKILL_REGISTRY, get_skill,
    all_tools, find_skill_by_keyword, find_skill_by_tool_name,
)

# 触发各业务模块的 register_skill() —— import 即注册，必须放在 skill_base 之后
import skill.skill_express   # noqa: F401
import skill.skill_complaint  # noqa: F401
import skill.skill_internet   # noqa: F401

if TYPE_CHECKING:
    from session.chat_session import ChatSession

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 1. 状态机常量
# ══════════════════════════════════════════════════════════════
_ABORT_SIGNALS = ["算了", "不投诉", "取消", "不查了", "没事了", "不用了"]

_STATE_KEY        = "_skill_wait"     # 值: skill name（如 "complaint"）或 None
_REJECT_COUNT_KEY = "_skill_reject"
_REJECT_MAX       = 2

_CANCEL_TOOL = {
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

def _format_response(response) -> str:
    """兼容 pydantic 对象（有 tool_calls 时）和字符串（无 tool_calls 时）两种返回类型"""
    if hasattr(response, "model_dump"):
        return json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
    return str(response)
def _clear_skill(session, skill_name: str) -> None:
    module = get_skill(skill_name)
    if module and module.clear:
        module.clear(session)

# status → 是否应该保持锁定（由总控统一解读，业务模块不需要关心 wait_state 怎么存）
_LOCKING_STATUSES = (SkillStatus.NEED_INFO, SkillStatus.PENDING_CONFIRM)


async def _cancel_skill_handler(reason: Optional[str] = None) -> dict:
    logger.info(f"cancel_skill triggered | reason={reason!r}")
    return {"status": SkillStatus.CANCELLED, "msg": "已为您取消当前流程"}


async def _dispatch(skill_name: str, tool_name: str, session, args: dict) -> dict:
    """统一调用入口：cancel_skill 是总控内置的，其他都走业务模块的 handle()"""
    if tool_name == "cancel_skill":
        return await _cancel_skill_handler(**args)

    module = get_skill(skill_name)
    if not module:
        return {"status": SkillStatus.ERROR, "msg": f"未知业务: {skill_name}"}
    return await module.handle(session,tool_name=tool_name, **args)


# ══════════════════════════════════════════════════════════════
# 2. ask_skill —— 挂载到 ChatSession 的方法
# ══════════════════════════════════════════════════════════════
async def ask_skill(session: "ChatSession", text: str) -> Optional[ChatAnswer]:
    import ai_config as AiConfig
    logger.debug(session.sinfo + " text %s",text)
    if AiConfig.getStringConfig("skill_tools.enabled", "true").lower() != "true":
        return None

    caller_phone = getattr(session, "_caller_phone", "") or ""
    t0 = time.time()
    last_tool_name = None
    answer_text = None
    skip_history = False
    try:
        llm = session.router.finalLlm() if session.router else None
        if llm is None:
            logger.warning(session.sinfo + "[ask_skill] router/llm not available, fallback to ask()")
            return None

        wait_state = _get_wait_state(session)  # 值是 skill name，如 "complaint" / "express" / None
        logger.debug(session.sinfo + " _get_wait_state %s ",wait_state)
        if _is_abort(text) and not wait_state:
            logger.debug(session.sinfo + "[ask_skill] abort signal (no state), fallback")
            return None

        # ════════════════════════════════════════════════════════
        # 分支 A：有等待状态 → 只暴露当前业务的工具（Tool Masking）
        # ════════════════════════════════════════════════════════
        if wait_state and wait_state in SKILL_REGISTRY:
            logger.debug(session.sinfo + " 分支 A：有等待状态 → 只暴露当前业务的工具 ...")
            module = get_skill(wait_state)
            locked_prompt = module.build_locked_prompt(session, caller_phone)
            masked_tools = module.locked_tools

            logger.debug("=== locked_prompt ===")
            #logger.debug(locked_prompt)
            logger.debug("=== masked_tools ===")
            logger.debug(json.dumps(masked_tools, ensure_ascii=False, indent=2))

            # locked_messages = [
            #     {"role": "system", "content": locked_prompt},
            #     {"role": "user", "content": text},
            # ]
            locked_history = session.history.toJsonArrayWithWindow()
            locked_non_system = [m for m in locked_history if m.get("role") != "system"]

            locked_messages = [{"role": "system", "content": locked_prompt}]
            if module.use_history_in_locked:
                locked_messages.extend(locked_non_system)
            locked_messages.append({"role": "user", "content": text})
# masked_tools 是工具列表，告诉 LLM 有哪些工具可用。
# tool_choice 是调用策略，告诉 LLM 怎么用这些工具：
#
# tool_choice 不传（默认 auto）→ LLM 自己决定调不调
# tool_choice="required" → 必须从 masked_tools 里选一个调
# tool_choice={"type":"function","function":{"name":"xxx"}} → 强制调 xxx，且 xxx 必须存在于 masked_tools 里，
# 否则 400
            response = await run_in_threadpool(
                llm.chat_with_tools, locked_messages, tools=masked_tools,
                tool_choice="auto"
               # tool_choice={"type": "function", "function": {"name": module.tool_names[0]}}
            )

            logger.debug(session.sinfo + "branch A after llm call, response:\n%s", _format_response(response))

            tool_calls = getattr(response, "tool_calls", None)
            logger.debug("===after ai, tool calls ===%s",tool_calls)
            logger.debug(session.sinfo + f"[ask_skill] masked({wait_state}) elapsed="
                         f"{int((time.time()-t0)*1000)}ms tool_calls={'yes' if tool_calls else 'no'}")

            if tool_calls:
                locked_messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [tc.model_dump() for tc in tool_calls],
                })
                logger.debug("===branch A,locked_messages === append role=assistant \n");#, json.dumps(locked_messages, ensure_ascii=False, indent=2))
                result = None
                for tc in tool_calls:
                    last_tool_name = tc.function.name
                    args = json.loads(tc.function.arguments)
                    if last_tool_name != "cancel_skill":
                        if "phone" not in args or not args["phone"]:
                            args["phone"] = caller_phone
                    logger.debug("===after ai, tool calls,last_tool_name ===%s",last_tool_name)
                    logger.debug("===_dispatchA.....")
                    result = await _dispatch(wait_state, last_tool_name, session, args)
                    logger.debug("===after _dispatchA,result ===%s",result)
                    result_json = json.dumps(result, ensure_ascii=False)
                    logger.debug(session.sinfo + f"[ask_skill] tool result: {result_json}")
                    locked_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": last_tool_name,
                        "content": result_json,
                    })
                logger.debug("===branch A,locked_messages === append role=tool \n ");#, json.dumps(locked_messages, ensure_ascii=False, indent=2))

                # 根据统一 status 决定锁定状态
                status = result.get("status") if result else SkillStatus.ERROR
                if status in _LOCKING_STATUSES:
                    _set_wait_state(session, wait_state)  # 继续锁定在同一业务
                else:
                    _set_wait_state(session, None)  # DONE / CANCELLED / ERROR 都解锁
                    _clear_skill(session, wait_state)
                    session.history.clear()
                    skip_history = True
                _clear_reject_count(session)

                locked_messages[0] = {
                    "role": "system",
                    "content": (
                        "你是智能电话客服播报助手。"
                        "根据工具返回的 msg 字段，用自然口语转述给客户，不得使用 markdown、换行、emoji、序号。"
                        "不要调用任何工具，只输出纯文本。"
                    )
                }

                answer_text = await run_in_threadpool(llm.chat_with_tools, locked_messages)
                logger.debug(session.sinfo + "branch A after 2nd llm call, answer_text:\n%s", answer_text)

            else:
                answer_text = response if isinstance(response, str) else (response.content or "")
                last_tool_name = module.tool_names[0]
                logger.debug(session.sinfo + "[ask_skill] masked no-tool, use LLM text as reply")

                reject_count = _inc_reject_count(session)
                if reject_count >= _REJECT_MAX:
                    logger.info(session.sinfo + f"[ask_skill] reject limit reached ({reject_count}), "
                                f"force exit lock state={wait_state!r}, replay text through normal routing")
                    _set_wait_state(session, None)
                    _clear_reject_count(session)
                    _clear_skill(session, wait_state)
                    session.history.clear()
                    #return await ask_skill(session, text)
                    return ChatAnswer(
                        code=CODE_OK,
                        answer="抱歉，未能获取到有效信息，本流程已结束，如有其他问题欢迎继续咨询。",
                        action=Action.NONE,
                        intent="COMMAND",
                        sub_intent=last_tool_name,
                        hit_source="skill",
                    )




                # else: 保持锁定，下一轮继续

        # ════════════════════════════════════════════════════════
        # 分支 B：正常状态 → 全量工具，关键词/auto 路由
        # ════════════════════════════════════════════════════════
        else:
            logger.debug(session.sinfo + " 全量工具 分支B ...")
            history_msgs = session.history.toJsonArrayWithWindow()
            non_system = [m for m in history_msgs if m.get("role") != "system"]

            skill_system = _build_normal_prompt(caller_phone)
            messages = [{"role": "system", "content": skill_system}] + non_system
            messages.append({"role": "user", "content": text})

            kw_forced = find_skill_by_keyword(text)
            forced_tool_name = None
            if kw_forced:
                module = get_skill(kw_forced)
                forced_tool_name = module.tool_names[0]
                logger.debug(session.sinfo + f"[ask_skill] keyword forced → {kw_forced}")

            tool_choice = {"type": "function", "function": {"name": forced_tool_name}} if forced_tool_name else "auto"
            logger.debug(session.sinfo + "tool_choice: %s", json.dumps(tool_choice, ensure_ascii=False))
            #logger.debug(session.sinfo + "all_tools:\n%s", json.dumps(all_tools(), ensure_ascii=False, indent=2))
            logger.debug(session.sinfo + "all_tools:submitted")

            response = await run_in_threadpool(
                llm.chat_with_tools, messages, tools=all_tools(), tool_choice=tool_choice
            )
            logger.debug(session.sinfo + "branch B,after llm call, response:\n%s", _format_response(response))

            tool_calls = getattr(response, "tool_calls", None)

            logger.debug(session.sinfo + f"[ask_skill] normal routing elapsed={int((time.time()-t0)*1000)}ms "
                         f"tool_calls={'yes' if tool_calls else 'no'}")

            if not tool_calls:
                logger.debug(session.sinfo+f" return None , not tool_call")
                return None  # 正常状态下 no-tool → fallback RAG

            messages.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [tc.model_dump() for tc in tool_calls],
            })

            result = None
            matched_skill = None
            for tc in tool_calls:
                last_tool_name = tc.function.name
                args = json.loads(tc.function.arguments)
                if "phone" not in args or not args["phone"]:
                    args["phone"] = caller_phone

                matched_skill = find_skill_by_tool_name(last_tool_name)
                if not matched_skill:
                    logger.warning(session.sinfo + f"[ask_skill] unknown skill tool: {last_tool_name}")
                    result = {"status": SkillStatus.ERROR, "msg": f"未知工具: {last_tool_name}"}
                else:
                    result = await _dispatch(matched_skill, last_tool_name, session, args)
                    logger.debug(session.sinfo + f"[ask_skill] dispatchB finished")

                result_json = json.dumps(result, ensure_ascii=False)
                logger.debug(session.sinfo + f"[ask_skill] tool result: name={last_tool_name} result={result_json}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": last_tool_name,
                    "content": result_json,
                })

            status = result.get("status") if result else SkillStatus.ERROR
            if matched_skill and status in _LOCKING_STATUSES:
                session.history.clear()
                _set_wait_state(session, matched_skill)
                logger.debug(session.sinfo + f"_set_wait_state set wait state---> {matched_skill}")
            else:
                _set_wait_state(session, None)
                logger.debug(session.sinfo + f"_set_wait_state set wait state--> None")

            answer_text = await run_in_threadpool(llm.chat_with_tools, messages)

        # ── 公共：日志 + history + 返回 ──────────────────────────────
        logger.debug(session.sinfo + f"[ask_skill] after branch A or B,after 2nd llm call  total elapsed={int((time.time()-t0)*1000)}ms "
                     f"skill={last_tool_name} answer={answer_text[:80] if answer_text else ''}")
        if not skip_history:
            session._history_add("user", text)
            if answer_text and answer_text.strip():
                session._history_add("assistant", answer_text)
                session._history_trim(60)

        return ChatAnswer(
            code=CODE_OK,
            answer=answer_text,
            action=Action.NONE,
            intent="COMMAND",
            sub_intent=last_tool_name,
            hit_source="skill",
        )

    except Exception as e:
        logger.error(session.sinfo + f"[ask_skill] error: {e}", exc_info=True)
        return ChatAnswer.of_system_error(e)


def _build_normal_prompt(caller_phone: str) -> str:
    """正常状态下的总控 prompt，路由规则汇总各业务的触发关键词"""


    today = date.today().strftime("%Y-%m-%d")  # "2026-06-23"


    lines = [f"# Role: 智能客服助理\n", f"## Context\n- 当前来电手机号: {caller_phone}（系统自动注入，禁止向用户索取）,今天的日期是 {today}\n", "## Routing Rules\n"]
    for name, module in SKILL_REGISTRY.items():
        kw_sample = "、".join(module.trigger_keywords[:10])
        lines.append(f"- 用户提及「{kw_sample}」等 → 调用 {module.tool_names[0]}")
    lines.append("- 其他（问候/知识问题/闲聊/无关话题）→ 不调任何工具，输出空字符串\n")
    lines.append("## 重要约束")
    lines.append("1. phone 始终从 Context 自动获取，禁止向用户索取")
    lines.append("2. 没有进行中的流程时，按用户当前意图正常路由")
    lines.append("3. 工具返回的原始数据不得直接输出，必须用自然语言组织后回复")
    lines.append("4. 不得暴露工具名称、参数名称等内部信息给用户")
    lines.append("5. 回复必须是纯文本，不得使用 markdown、换行、emoji、序号，用自然口语连续表达，适合直接语音播放")
    return "\n".join(lines)
