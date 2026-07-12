"""
chat_skill_classify.py
─────────────────────────────────────────────────────────────
个性化业务 Skill 路由总控（合并 classify 版）

在 chat_skill.py 的基础上，把 tools 调用（判断要不要调工具）和
classify 调用（意图分类）合并成一次 LLM 调用：

  - 分支B（正常状态）里，system prompt 改为 _build_general_prompt()，
    额外要求模型在【不调用任何工具】时，把 response.content 输出为
    符合 Classify Rules 的 JSON，而不是纯文本闲聊。
  - 没有 tool_calls 时，尝试用 _try_parse_general_classify() 解析
    response.content；解析成功就把结果挂到 session._pending_intent_result
    上，session.ask() 里会优先复用它，跳过一次独立的 classify() 调用。
  - 解析失败（模型没按格式输出）时静默回退：不设置 _pending_intent_result，
    session.ask() 会照常调用 intentClassifier.classify()，行为等同于
    合并优化之前，不会引入新的错误路径。

chat_skill.py 保持原样不动，作为可随时回退的备份。
ask_skill2（chat_skill.py 里的旧版本，未被外部调用）在本文件里原样保留，不做任何修改。

用法：
    from chat_skill_classify import ask_skill as _ask_skill

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
from intent.intent_result import Intent, Sentiment, IntentResult
import ai_config as AiConfig
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


# 通用安全出口：required 模式下，本轮内容与当前流程完全无关时调用，
# 不取消流程、不查任何数据，只用于礼貌地重新引导客户。
_OFF_TOPIC_TOOL = {
    "type": "function",
    "function": {
        "name": "off_topic",
        "description": (
            "当客户本轮说的内容与当前流程完全无关时调用（如问候、闲聊、"
            "提到其他业务但未明确要求切换等）。用于礼貌地重新引导客户提供"
            "当前流程所需的信息，不会取消当前流程，也不会查询任何数据。"
        ),
        "parameters": {
            "type": "object",
            "properties": {"note": {"type": "string", "description": "简要说明用户说了什么无关内容，可选"}},
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

async def _off_topic_handler(note: Optional[str] = None) -> dict:
    logger.info(f"off_topic triggered | note={note!r}")
    # NEED_INFO 会保持锁定状态，等同于原来 tool_calls=no 时"保持锁定，下一轮继续"的效果
    return {"status": SkillStatus.NEED_INFO, "msg": "本轮内容与当前流程无关，请礼貌地重新引导客户提供当前需要的信息，不要回答任何无关话题。"}

async def _dispatch(skill_name: str, tool_name: str, session, args: dict) -> dict:
    """统一调用入口：cancel_skill 是总控内置的，其他都走业务模块的 handle()"""
    if tool_name == "cancel_skill":
        return await _cancel_skill_handler(**args)
    if tool_name == "off_topic":
        return await _off_topic_handler(**args)
    module = get_skill(skill_name)
    if not module:
        return {"status": SkillStatus.ERROR, "msg": f"未知业务: {skill_name}"}
    return await module.handle(session,tool_name=tool_name, **args)


# ══════════════════════════════════════════════════════════════
# 2. ask_skill —— 挂载到 ChatSession 的方法（合并 classify 版）
# ══════════════════════════════════════════════════════════════
async def ask_skill(session: "ChatSession", text: str) -> Optional[ChatAnswer]:
    import ai_config as AiConfig
    logger.debug(session.sinfo + " chat_skill_classify text %s", text)


    caller_phone = getattr(session, "_caller_phone", "") or ""
    t0 = time.time()
    last_tool_name = None
    answer_text = None
    skip_history = False

    if not hasattr(session, "_stage_costs"):        # ← 新增：统一在函数入口初始化
        session._stage_costs = {}

    try:
        llm = session.router.finalLlm() if session.router else None
        if llm is None:
            logger.warning(session.sinfo + "[ask_skill] router/llm not available, fallback to ask()")
            return None
        reply_llm = session.router.skillRouter() if session.router else llm   # ← 新增：专门用于"组织语言回复"，用turbo

        wait_state = _get_wait_state(session)
        logger.debug(session.sinfo + " _get_wait_state %s ", wait_state)
        if _is_abort(text) and not wait_state:
            logger.debug(session.sinfo + "[ask_skill] abort signal (no state), fallback")
            return None

        # ════════════════════════════════════════════════════════
        # 分支 A：有等待状态 → 只暴露当前业务的工具（Tool Masking）
        # 不涉及 classify 合并，逻辑与 chat_skill.py 完全一致
        # ════════════════════════════════════════════════════════
        if wait_state and wait_state in SKILL_REGISTRY:
            logger.debug(session.sinfo + " 分支 A：有等待状态 → 只暴露当前业务的工具 ...")
            module = get_skill(wait_state)
            locked_prompt = module.build_locked_prompt(session, caller_phone)
            masked_tools = module.locked_tools + [_OFF_TOPIC_TOOL]

            logger.debug("=== locked_prompt ===")
            logger.debug("=== masked_tools ===")
            logger.debug(json.dumps(masked_tools, ensure_ascii=False, indent=2))

            locked_history = session.history.toJsonArrayWithWindow()
            locked_non_system = [m for m in locked_history if m.get("role") != "system"]

            locked_messages = [{"role": "system", "content": locked_prompt}]
            if module.use_history_in_locked:
                locked_messages.extend(locked_non_system)
            locked_messages.append({"role": "user", "content": text})

            t_tool_a = time.time()                                          # ← 新增
            response = await run_in_threadpool(
                llm.chat_with_tools, locked_messages, tools=masked_tools,
                tool_choice="required"
            )
            session._stage_costs["tools"] = int((time.time() - t_tool_a) * 1000)   # ← 新增

            logger.debug(session.sinfo + "branch A after llm call, response:\n%s", _format_response(response))

            #tool_calls = getattr(response, "tool_calls", None)
            tool_calls = response.get("tool_calls") if isinstance(response, dict) else getattr(response, "tool_calls", None)

            logger.debug("===after ai, tool calls ===%s", tool_calls)
            logger.debug(session.sinfo + f"[ask_skill] masked({wait_state}) elapsed="
                                         f"{int((time.time()-t0)*1000)}ms tool_calls={'yes' if tool_calls else 'no'}")

            if tool_calls:
                locked_messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [tc.model_dump() for tc in tool_calls],
                })
                logger.debug("===branch A,locked_messages === append role=assistant \n")
                result = None

                t_skill_a = time.time()                                     # ← 新增
                for tc in tool_calls:
                    last_tool_name = tc.function.name
                    args = json.loads(tc.function.arguments)
                    if last_tool_name not in ("cancel_skill", "off_topic"):
                        if "phone" not in args or not args["phone"]:
                            args["phone"] = caller_phone
                    logger.debug("===after ai, tool calls,last_tool_name ===%s", last_tool_name)
                    logger.debug("===_dispatchA.....")
                    result = await _dispatch(wait_state, last_tool_name, session, args)
                    logger.debug("===after _dispatchA,result ===%s", result)
                    result_json = json.dumps(result, ensure_ascii=False)
                    logger.debug(session.sinfo + f"[ask_skill] tool result: {result_json}")
                    locked_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": last_tool_name,
                        "content": result_json,
                    })
                session._stage_costs["skill_exec"] = int((time.time() - t_skill_a) * 1000)   # ← 新增
                logger.debug("===branch A,locked_messages === append role=tool \n ")

                status = result.get("status") if result else SkillStatus.ERROR
                # auto模式
                # if status in _LOCKING_STATUSES:
                #     _set_wait_state(session, wait_state)
                # else:
                #     _set_wait_state(session, None)
                #     _clear_skill(session, wait_state)
                #     session.history.clear()
                #     skip_history = True
                # _clear_reject_count(session)

                # required模式
                if last_tool_name == "off_topic":
                    # off_topic 不算真正推进流程，单独计数，不走下面统一清零
                    reject_count = _inc_reject_count(session)
                    if reject_count >= _REJECT_MAX:
                        _set_wait_state(session, None)
                        _clear_reject_count(session)
                        _clear_skill(session, wait_state)
                        session.history.clear()
                        session._stage_costs["skill_exec"] = int((time.time() - t_skill_a) * 1000)
                        total_ms = int((time.time() - t0) * 1000)
                        cost = {**session._stage_costs, "skill_total": total_ms}
                        session._stage_costs = {}
                        return ChatAnswer(
                            code=CODE_OK,
                            answer="抱歉，未能获取到有效信息，本流程已结束，如有其他问题欢迎继续咨询。",
                            action=Action.NONE,
                            intent="COMMAND",
                            sub_intent=last_tool_name,
                            hit_source="skill",
                            cost=cost,
                        )
                    _set_wait_state(session, wait_state)   # 未超限，继续保持锁定
                else:
                    # 真正调用了业务工具（无论结果是继续锁定还是解锁），跟老逻辑保持一致
                    if status in _LOCKING_STATUSES:
                        _set_wait_state(session, wait_state)
                    else:
                        _set_wait_state(session, None)
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

                t_reply_a = time.time()                                     # ← 新增
                answer_text = await run_in_threadpool(reply_llm.chat_with_tools, locked_messages)
                session._stage_costs["final_reply"] = int((time.time() - t_reply_a) * 1000)   # ← 新增
                logger.debug(session.sinfo + "branch A after 2nd llm call, answer_text:\n%s", answer_text)

            else:
                #既然理论上不该发生,一旦真的走进这个分支,这件事本身就值得你关注——
                #说明 required 约束在某次调用里失效了,这是排查模型/API稳定性问题的信号。
                answer_text = response if isinstance(response, str) else (response.content or "")
                last_tool_name = module.tool_names[0]
                #logger.debug(session.sinfo + "[ask_skill] masked no-tool, use LLM text as reply")
                logger.warning(session.sinfo + "[ask_skill] masked no-tool despite tool_choice=required, use LLM text as reply — 理论上不应发生，需关注")
                reject_count = _inc_reject_count(session)
                if reject_count >= _REJECT_MAX:
                    logger.info(session.sinfo + f"[ask_skill] reject limit reached ({reject_count}), "
                                                f"force exit lock state={wait_state!r}, replay text through normal routing")
                    _set_wait_state(session, None)
                    _clear_reject_count(session)
                    _clear_skill(session, wait_state)
                    session.history.clear()

                    total_ms = int((time.time() - t0) * 1000)                          # ← 新增
                    cost = {**session._stage_costs, "skill_total": total_ms}            # ← 新增
                    session._stage_costs = {}                                          # ← 新增
                    return ChatAnswer(
                        code=CODE_OK,
                        answer="抱歉，未能获取到有效信息，本流程已结束，如有其他问题欢迎继续咨询。",
                        action=Action.NONE,
                        intent="COMMAND",
                        sub_intent=last_tool_name,
                        hit_source="skill",
                        cost=cost,                                                       # ← 新增
                    )

        # ════════════════════════════════════════════════════════
        # 分支 B：正常状态 → 全量工具，关键词/auto 路由
        # ★ 这里是合并 classify 的核心改动 ★
        # ════════════════════════════════════════════════════════
        else:
            logger.debug(session.sinfo + " 全量工具 分支B ...")
            history_msgs = session.history.toJsonArrayWithWindow()
            non_system = [m for m in history_msgs if m.get("role") != "system"]

            skill_system = _build_general_prompt(caller_phone)   # ← 改动：合并版 prompt（原为 _build_normal_prompt）
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
            logger.debug(session.sinfo + "all_tools:submitted")

            response = await run_in_threadpool(
                llm.chat_with_tools, messages, tools=all_tools(), tool_choice=tool_choice
            )
            logger.debug(session.sinfo + "branch B,after llm call, response:\n%s", _format_response(response))

            #tool_calls = getattr(response, "tool_calls", None)
            tool_calls = response.get("tool_calls") if isinstance(response, dict) else getattr(response, "tool_calls", None)

            elapsed = int((time.time() - t0) * 1000)
            session._stage_costs["tools"] = elapsed
            logger.debug(session.sinfo + f"[ask_skill] normal routing elapsed={elapsed}ms tool_calls={'yes' if tool_calls else 'no'}")
            if not tool_calls:
                # ★ 新增：尝试把这次调用的 content 解析成分类结果，供 session.ask() 短路复用 ★

                # response 在无 tool_calls 时是裸字符串，有 tool_calls 时才是带 .content 的对象
                raw_content = response if isinstance(response, str) else getattr(response, "content", None)
                parsed_intent = _try_parse_general_classify(raw_content, text)

                if parsed_intent is not None:
                    session._pending_intent_result = parsed_intent   # ← session.ask() 会优先读取这个
                    session._stage_costs["classify"] = 0             # ← 复用同一次调用，无额外耗时
                    logger.debug(session.sinfo + f"[merged-classify] intent={parsed_intent.intent} 命中，跳过独立classify调用")
                else:
                    logger.warning("[chat_skill_classify] content 不是合法 JSON")

                    # ★ 新增：判断这是不是一段"看起来合理的自然语言抢答"，
                    #   如果是，直接采纳，不再走独立classify()降级 ★
                    if raw_content and len(raw_content.strip()) > 10 and not raw_content.strip().startswith("{"):
                        logger.info(f"[chat_skill_classify] 检测到抢答内容，直接采纳: {raw_content[:50]}...")
                        return ChatAnswer(
                            code=CODE_OK,
                            answer=raw_content.strip(),
                            action=Action.NONE,
                            intent="QUERY",
                            hit_source="skill_direct_answer",   # 标记来源，方便后续统计
                        )

                    logger.debug(session.sinfo + "[merged-classify] 解析失败，回退到独立 classify()")


                logger.debug(session.sinfo + f" return None , not tool_call")
                return None  # 正常状态下 no-tool → fallback RAG

            messages.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [tc.model_dump() for tc in tool_calls],
            })

            result = None
            matched_skill = None

            t_skill_b = time.time()                                         # ← 新增
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
            session._stage_costs["skill_exec"] = int((time.time() - t_skill_b) * 1000)   # ← 新增

            status = result.get("status") if result else SkillStatus.ERROR
            if matched_skill and status in _LOCKING_STATUSES:
                session.history.clear()
                _set_wait_state(session, matched_skill)
                logger.debug(session.sinfo + f"_set_wait_state set wait state---> {matched_skill}")
            else:
                _set_wait_state(session, None)
                logger.debug(session.sinfo + f"_set_wait_state set wait state--> None")
            # ★ 修复：dispatch之后必须替换成精简播报system prompt，
            #   否则模型会拿着完整的Routing Rules+Classify Rules去组织回复，
            #   导致输出Classify Rules要求的JSON格式，而不是自然语言转述 ★
            messages[0] = {
                "role": "system",
                "content": (
                    "你是智能电话客服播报助手。"
                    "根据工具返回的 msg 字段，用自然口语转述给客户，不得使用 markdown、换行、emoji、序号。"
                    "不要调用任何工具，只输出纯文本。"
                )
            }

            t_reply_b = time.time()                                          # ← 新增
            answer_text = await run_in_threadpool(reply_llm.chat_with_tools, messages)
            session._stage_costs["final_reply"] = int((time.time() - t_reply_b) * 1000)   # ← 新增

        # ── 公共：日志 + history + 返回 ──────────────────────────────
        total_ms = int((time.time() - t0) * 1000)
        logger.debug(session.sinfo + f"[ask_skill] after branch A or B,after 2nd llm call  total elapsed={total_ms}ms "
                                     f"skill={last_tool_name} answer={answer_text[:80] if answer_text else ''}")
        if not skip_history:
            session._history_add("user", text)
            if answer_text and answer_text.strip():
                session._history_add("assistant", answer_text)
                session._history_trim(60)

        cost = {**session._stage_costs, "skill_total": total_ms}   # ← 新增
        session._stage_costs = {}                                  # ← 新增

        return ChatAnswer(
            code=CODE_OK,
            answer=answer_text,
            action=Action.NONE,
            intent="COMMAND",
            sub_intent=last_tool_name,
            hit_source="skill",
            cost=cost,                                              # ← 新增
        )

    except Exception as e:
        logger.error(session.sinfo + f"[ask_skill] error: {e}", exc_info=True)
        session._stage_costs = {}                                   # ← 新增：异常时也清空，避免污染下一轮
        return ChatAnswer.of_system_error(e)


# ══════════════════════════════════════════════════════════════
# 3. 合并 prompt 构造 + 分类结果解析
# ══════════════════════════════════════════════════════════════
_general_classify_body: Optional[str] = None  # 模块级缓存，避免每次请求都读文件


def _build_general_prompt(caller_phone: str) -> str:
    """在原 _build_normal_prompt 基础上追加 Classify Rules，
    要求模型在【不调用任何工具】时改为输出分类 JSON，而不是纯文本闲聊。"""
    today = date.today().strftime("%Y-%m-%d")

    lines = [
        "# Role: 智能客服助理\n",
        f"## Context\n- 当前来电手机号: {caller_phone}（系统自动注入，禁止向用户索取）,今天的日期是 {today}\n",
        "## Routing Rules\n",
    ]
    for name, module in SKILL_REGISTRY.items():
        kw_sample = "、".join(module.trigger_keywords[:10])
        lines.append(f"- 用户提及「{kw_sample}」等 → 调用 {module.tool_names[0]}")
    lines.append(
        "- 注意：账号、密码、登录、忘记密码等身份认证类问题，"
        "与上述任何工具场景均无关，禁止调用任何工具，应严格按下方【Classify Rules】处理\n"
    )
    lines.append(
        "- 其他情况（问候/知识问题/闲聊/无关话题）→ 不调用任何工具，"
        "改为严格按下方【Classify Rules】的格式，只输出一个 JSON 对象\n"
    )
    lines.append("## 重要约束（调用工具时生效）")
    lines.append("1. phone 始终从 Context 自动获取，禁止向用户索取")
    lines.append("2. 没有进行中的流程时，按用户当前意图正常路由")
    lines.append("3. 工具返回的原始数据不得直接输出，必须用自然语言组织后回复")
    lines.append("4. 不得暴露工具名称、参数名称等内部信息给用户")
    lines.append("5. 回复必须是纯文本，不得使用 markdown、换行、emoji、序号，用自然口语连续表达，适合直接语音播放\n")
    lines.append("## Classify Rules（未调用任何工具时必须遵守，只输出 JSON，不得输出任何解释或额外文字）")

    lines.append(_load_general_classify_body())
    return "\n".join(lines)


def _load_general_classify_body() -> str:
    global _general_classify_body
    if _general_classify_body is None:
        base = (AiConfig.configPath or "").replace("\\", "/")   # ← 新增：和 session_manager.py 里 path.prompt.classify 同样的拼接方式
        rel  = AiConfig.getStringConfig("path.prompt.general", "/config/prompt_general_v1_en_category.txt")
        path = base + rel
        try:
            with open(path, "r", encoding="utf-8") as f:
                _general_classify_body = f.read()
            logger.debug(f"[chat_skill_classify] 合并 classify prompt 加载成功: {path} (长度: {len(_general_classify_body)} 字符)")
        except Exception as e:
            logger.error(f"[chat_skill_classify] 加载合并 prompt 失败: {path} err={e}")
            _general_classify_body = ""
    return _general_classify_body


def _null_if_blank(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    stripped = s.strip()
    return None if (not stripped or stripped.lower() == "null") else stripped


def _try_parse_general_classify(content: Optional[str], fallback_text: str) -> Optional[IntentResult]:
    """把 tools 调用没有 tool_calls 时的 response.content 尝试解析成 IntentResult。
    解析失败返回 None，调用方会回退到独立 classify() 调用，不影响正确性，只损失这次的加速。"""
    if not content or not content.strip():
        return None
    try:
        node = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("[chat_skill_classify] content 不是合法 JSON，回退独立 classify")
        return None

    try:
        intent = Intent(str(node.get("intent", "")).upper())
    except ValueError:
        logger.warning(f"[chat_skill_classify] 非法 intent 值: {node.get('intent')!r}，回退独立 classify")
        return None

    sentiment_str = str(node.get("sentiment") or "").lower()
    if sentiment_str == "positive":
        sentiment = Sentiment.POSITIVE
    elif sentiment_str == "negative":
        sentiment = Sentiment.NEGATIVE
    else:
        sentiment = Sentiment.NEUTRAL

    refined_query = node.get("refined_query") or fallback_text
    if not str(refined_query).strip():
        refined_query = fallback_text

    return IntentResult(
        intent=intent,
        sub_intent=_null_if_blank(node.get("sub_intent")),
        sentiment=sentiment,
        refined_query=refined_query,
        action_code=_null_if_blank(node.get("action_code")),
        category=_null_if_blank(node.get("category")),
    )
