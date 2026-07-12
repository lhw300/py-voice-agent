"""
chat_skill_layer.py
─────────────────────────────────────────────────────────────
个性化业务 Skill 路由总控（分层版 / Layer 版）

与 chat_skill.py、chat_skill_classify.py 的核心区别：
─────────────────────────────────────────────────────────────
两个旧版本的分支B，都是让模型在【4个真实业务工具】之间做 auto 选择，
"不调用任何工具"只是一种隐含的、沉默的负面信号（auto 模式下模型没有
调用任何工具，才代表"这不是业务操作"）。这种"沉默表达否定"的方式，
对小模型（如 qwen3.5:9b）不够可靠——已实测会把"老师密码多少"这类知识
问答，误判成调用 express_query_skill_by_phone。

本文件的改动：把"是否为业务操作"做成一次【显式的、强制的4选1决策】：

    3个真实业务工具（express / complaint / internet_repair）
    + 1个显式的 "not_business_related" 工具（代表"以上都不是"）

    tool_choice="required" —— 模型必须从这4个选项里明确选一个，
    不存在"什么都不选"这种模糊状态。

这个手法直接借用了 chat_skill.py 分支A里 _OFF_TOPIC_TOOL 的思路
（用一个显式工具表达"跟当前诉求无关"），现在把同样的模式用在分支B，
用"强制显式选择"替代"auto模式下的沉默否定"。

命中 not_business_related → return None，交给外层 session.ask()
走既有的独立 intentClassifier.classify() + RAG，不做任何 JSON 解析
或格式切换，避免重蹈 chat_skill_classify.py 里"合并输出格式"导致的
额外复杂度。

分支A（有等待状态时的 Tool Masking）逻辑与旧版本完全一致，未做改动。

chat_skill.py / chat_skill_classify.py 保持原样，均不受影响，可随时切换。

用法：
    from chat_skill_layer import ask_skill as _ask_skill

    async def ask_skill(self, text: str):
        return await _ask_skill(self, text)

─────────────────────────────────────────────────────────────
2026-07-10 修复说明：
OllamaNativeClient 返回的 response / tool_calls 是原生 dict，
不是带属性的对象（如 openai SDK 返回的 ChatCompletionMessage）。
之前代码里混用了 getattr(response, "tool_calls", None) 以及
tc.function.name 这类"点号属性访问"，对 dict 永远取不到值，
会被误判为 tool_calls=no，进而错误地回退到独立 classify()。

同时 arguments 字段本身也可能已经是 dict（而不是 JSON 字符串），
直接 json.loads() 会报 TypeError。

以下加入 _get() / _parse_args() / _tool_call_to_dict() 三个小
helper，统一兼容 dict 和对象两种形态，避免以后切换 client（比如
换回标准 OpenAI SDK 对象）时又要满文件搜索修改。
─────────────────────────────────────────────────────────────
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
import skill.skill_express    # noqa: F401
import skill.skill_complaint  # noqa: F401
import skill.skill_internet   # noqa: F401

if TYPE_CHECKING:
    from session.chat_session import ChatSession

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 0. dict / 对象兼容 helper（本次修复新增）
# ══════════════════════════════════════════════════════════════
def _get(obj, key, default=None):
    """兼容 dict 和带属性对象的统一取值。

    OllamaNativeClient 返回的 response / message / tool_call 都是原生
    dict；但如果以后切回标准 OpenAI SDK（返回带属性的对象），同一段代码
    不用改，直接兼容两种形态。
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _parse_args(arguments):
    """兼容 arguments 已经是 dict，或者是 JSON 字符串两种情况。"""
    if isinstance(arguments, dict):
        return arguments
    if not arguments:
        return {}
    return json.loads(arguments)


def _tool_call_to_dict(tc) -> dict:
    """把单个 tool_call（dict 或对象）统一转成可序列化的 dict，
    用于拼回 messages 历史（assistant 消息里的 tool_calls 字段）。"""
    if isinstance(tc, dict):
        return tc
    if hasattr(tc, "model_dump"):
        return tc.model_dump()
    func = _get(tc, "function")
    return {
        "id": _get(tc, "id"),
        "function": {
            "name": _get(func, "name"),
            "arguments": _get(func, "arguments"),
        },
    }


def _tool_call_name(tc) -> Optional[str]:
    """取某个 tool_call 的函数名，兼容 dict / 对象。"""
    return _get(_get(tc, "function"), "name")


def _tool_call_args(tc) -> dict:
    """取某个 tool_call 的参数并解析成 dict，兼容 dict / 对象 /
    arguments 已是 dict / arguments 是 JSON 字符串 等各种组合。"""
    return _parse_args(_get(_get(tc, "function"), "arguments"))


# ══════════════════════════════════════════════════════════════
# 1. 状态机常量（与旧版本一致）
# ══════════════════════════════════════════════════════════════
_ABORT_SIGNALS = ["算了", "不投诉", "取消", "不查了", "没事了", "不用了"]

_STATE_KEY        = "_skill_wait"
_REJECT_COUNT_KEY = "_skill_reject"
_REJECT_MAX       = 2


# 分支A（锁定态）沿用的 off_topic 工具，逻辑与旧版本一致
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

# ★ 分支B新增：与 _OFF_TOPIC_TOOL 同一思路，但用于"正常状态、首次判断是否为业务操作" ★
_NOT_BUSINESS_TOOL = {
    "type": "function",
    "function": {
        "name": "not_business_related",
        "description": (
            "当用户本轮内容与【查快递/查物流】【投诉/举报】【宽带故障报修】"
            "这三类业务操作均无关时，必须调用此项。包括但不限于：账号、密码、"
            "登录等身份认证类知识问题；平台使用方法等知识性问题；问候、闲聊、"
            "感谢、告别等社交性发言；任何与上述三类业务操作无法对应的内容。"
            "只要不能明确、直接地对应到查快递/投诉/宽带报修其中之一，就应调用此项，"
            "不得强行归类到某个业务工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {},
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
    if hasattr(response, "model_dump"):
        return json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
    return str(response)


def _clear_skill(session, skill_name: str) -> None:
    module = get_skill(skill_name)
    if module and module.clear:
        module.clear(session)


_LOCKING_STATUSES = (SkillStatus.NEED_INFO, SkillStatus.PENDING_CONFIRM)


async def _cancel_skill_handler(reason: Optional[str] = None) -> dict:
    logger.info(f"cancel_skill triggered | reason={reason!r}")
    return {"status": SkillStatus.CANCELLED, "msg": "已为您取消当前流程"}


async def _off_topic_handler(note: Optional[str] = None) -> dict:
    logger.info(f"off_topic triggered | note={note!r}")
    return {"status": SkillStatus.NEED_INFO, "msg": "本轮内容与当前流程无关，请礼貌地重新引导客户提供当前需要的信息，不要回答任何无关话题。"}


async def _dispatch(skill_name: str, tool_name: str, session, args: dict) -> dict:
    if tool_name == "cancel_skill":
        return await _cancel_skill_handler(**args)
    if tool_name == "off_topic":
        return await _off_topic_handler(**args)
    module = get_skill(skill_name)
    if not module:
        return {"status": SkillStatus.ERROR, "msg": f"未知业务: {skill_name}"}
    return await module.handle(session, tool_name=tool_name, **args)


# ══════════════════════════════════════════════════════════════
# 2. ask_skill —— 挂载到 ChatSession 的方法（分层版）
# ══════════════════════════════════════════════════════════════
async def ask_skill(session: "ChatSession", text: str) -> Optional[ChatAnswer]:
    import ai_config as AiConfig
    logger.debug(session.sinfo + " chat_skill_layer text %s", text)


    caller_phone = getattr(session, "_caller_phone", "") or ""
    t0 = time.time()
    last_tool_name = None
    answer_text = None
    skip_history = False

    if not hasattr(session, "_stage_costs"):
        session._stage_costs = {}

    try:
        llm = session.router.finalLlm() if session.router else None
        if llm is None:
            logger.warning(session.sinfo + "[ask_skill] router/llm not available, fallback to ask()")
            return None
        reply_llm = session.router.skillRouter() if session.router else llm
        wait_state = _get_wait_state(session)
        logger.debug(session.sinfo + " _get_wait_state %s ", wait_state)
        if _is_abort(text) and not wait_state:
            logger.debug(session.sinfo + "[ask_skill] abort signal (no state), fallback")
            return None

        # ════════════════════════════════════════════════════════
        # 分支 A：有等待状态 → Tool Masking，逻辑与旧版本基本一致，
        # 仅将 dict/对象取值统一改为兼容 helper（本次修复）
        # ════════════════════════════════════════════════════════
        if wait_state and wait_state in SKILL_REGISTRY:
            logger.debug(session.sinfo + " 分支 A：有等待状态 → 只暴露当前业务的工具 ...")
            module = get_skill(wait_state)
            locked_prompt = module.build_locked_prompt(session, caller_phone)
            masked_tools = module.locked_tools + [_OFF_TOPIC_TOOL]

            locked_history = session.history.toJsonArrayWithWindow()
            locked_non_system = [m for m in locked_history if m.get("role") != "system"]

            locked_messages = [{"role": "system", "content": locked_prompt}]
            if module.use_history_in_locked:
                locked_messages.extend(locked_non_system)
            locked_messages.append({"role": "user", "content": text})

            t_tool_a = time.time()
            response = await run_in_threadpool(
                llm.chat_with_tools, locked_messages, tools=masked_tools,
                tool_choice="required"
            )
            session._stage_costs["tools"] = int((time.time() - t_tool_a) * 1000)

            logger.debug(session.sinfo + "branch A after llm call, tool_choice=\"required\" response:\n%s", _format_response(response))

            tool_calls = _get(response, "tool_calls")

            logger.debug(session.sinfo + f"[ask_skill] masked({wait_state}) elapsed="
                                         f"{int((time.time()-t0)*1000)}ms tool_calls={'yes' if tool_calls else 'no'}")

            if tool_calls:
                locked_messages.append({
                    "role": "assistant",
                    "content": _get(response, "content") or "",
                    "tool_calls": [_tool_call_to_dict(tc) for tc in tool_calls],
                })
                result = None

                t_skill_a = time.time()
                for tc in tool_calls:
                    last_tool_name = _tool_call_name(tc)
                    args = _tool_call_args(tc)
                    if last_tool_name not in ("cancel_skill", "off_topic"):
                        if "phone" not in args or not args["phone"]:
                            args["phone"] = caller_phone
                    result = await _dispatch(wait_state, last_tool_name, session, args)
                    result_json = json.dumps(result, ensure_ascii=False)
                    logger.debug(session.sinfo + f"[ask_skill] tool result: {result_json}")
                    locked_messages.append({
                        "role": "tool",
                        "tool_call_id": _get(tc, "id"),
                        "name": last_tool_name,
                        "content": result_json,
                    })
                session._stage_costs["skill_exec"] = int((time.time() - t_skill_a) * 1000)

                status = result.get("status") if result else SkillStatus.ERROR

                if last_tool_name == "off_topic":
                    reject_count = _inc_reject_count(session)
                    if reject_count >= _REJECT_MAX:
                        _set_wait_state(session, None)
                        _clear_reject_count(session)
                        _clear_skill(session, wait_state)
                        session.history.clear()
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
                    _set_wait_state(session, wait_state)
                else:
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

                t_reply_a = time.time()
                answer_text = await run_in_threadpool(reply_llm.chat_with_tools, locked_messages)
                session._stage_costs["final_reply"] = int((time.time() - t_reply_a) * 1000)

            else:
                answer_text = response if isinstance(response, str) else (_get(response, "content") or "")
                last_tool_name = module.tool_names[0]
                logger.warning(session.sinfo + "[ask_skill] masked no-tool despite tool_choice=required, use LLM text as reply — 理论上不应发生，需关注")
                reject_count = _inc_reject_count(session)
                if reject_count >= _REJECT_MAX:
                    _set_wait_state(session, None)
                    _clear_reject_count(session)
                    _clear_skill(session, wait_state)
                    session.history.clear()
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

        # ════════════════════════════════════════════════════════
        # 分支 B：正常状态 → ★ 分层核心改动 ★
        # 强制 4 选 1（3个真实业务工具 + not_business_related），
        # 不再用"auto模式下沉默不选"来隐含表达"不是业务操作"。
        # ════════════════════════════════════════════════════════
        else:
            logger.debug(session.sinfo + " 分支B（分层版：强制显式路由）...")
            history_msgs = session.history.toJsonArrayWithWindow()
            non_system = [m for m in history_msgs if m.get("role") != "system"]

            skill_system = _build_layer_prompt(caller_phone)
            messages = [{"role": "system", "content": skill_system}] + non_system
            messages.append({"role": "user", "content": text})

            kw_forced = find_skill_by_keyword(text)
            forced_tool_name = None
            if kw_forced:
                module = get_skill(kw_forced)
                forced_tool_name = module.tool_names[0]
                logger.debug(session.sinfo + f"[ask_skill] keyword forced → {kw_forced}")

            # 关键字命中时沿用强制指定；未命中时改为 required（4选1），
            # 而不是 auto（避免"沉默不选"这种模糊状态）
            if forced_tool_name:
                tool_choice = {"type": "function", "function": {"name": forced_tool_name}}
            else:
                tool_choice = "required"

            layer_tools = all_tools() + [_NOT_BUSINESS_TOOL]

            logger.debug(session.sinfo + "tool_choice: %s", json.dumps(tool_choice, ensure_ascii=False))
            logger.debug(session.sinfo + "layer_tools:submitted (3 skills + not_business_related)")

            t_tool_b = time.time()
            response = await run_in_threadpool(
                llm.chat_with_tools, messages, tools=layer_tools, tool_choice=tool_choice
            )
            session._stage_costs["tools"] = int((time.time() - t_tool_b) * 1000)
            logger.debug(session.sinfo + "branch B after llm call, response:\n%s", _format_response(response))

            tool_calls = _get(response, "tool_calls")
            elapsed = int((time.time() - t0) * 1000)
            logger.debug(session.sinfo + f"[ask_skill] layer routing elapsed={elapsed}ms tool_calls={'yes' if tool_calls else 'no'}")

            if not tool_calls:
                # 理论上 required 模式不该发生；发生了说明API/模型稳定性有问题，
                # 按"非业务操作"处理，交给独立 classify()+RAG，不强行解析任何内容。
                logger.warning(session.sinfo + "[ask_skill] required 模式下仍无 tool_calls，按非业务处理，回退独立 classify()")
                return None

            # ★ 命中 not_business_related → 明确判定"不是业务操作"，交给独立 classify()+RAG ★
            if len(tool_calls) == 1 and _tool_call_name(tool_calls[0]) == "not_business_related":
                logger.debug(session.sinfo + "[ask_skill] layer1 判定=非业务操作(not_business_related)，回退独立 classify()")
                return None

            # ── 命中真实业务工具，走原有的参数提取 + dispatch 流程 ──────────
            messages.append({
                "role": "assistant",
                "content": _get(response, "content") or "",
                "tool_calls": [_tool_call_to_dict(tc) for tc in tool_calls],
            })

            result = None
            matched_skill = None

            t_skill_b = time.time()
            for tc in tool_calls:
                last_tool_name = _tool_call_name(tc)
                if last_tool_name == "not_business_related":
                    continue  # 理论上不会和真实工具混在同一批 tool_calls 里，防御性跳过
                args = _tool_call_args(tc)
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
                    "tool_call_id": _get(tc, "id"),
                    "name": last_tool_name,
                    "content": result_json,
                })
            session._stage_costs["skill_exec"] = int((time.time() - t_skill_b) * 1000)

            status = result.get("status") if result else SkillStatus.ERROR
            if matched_skill and status in _LOCKING_STATUSES:
                session.history.clear()
                _set_wait_state(session, matched_skill)
                logger.debug(session.sinfo + f"_set_wait_state set wait state---> {matched_skill}")
            else:
                _set_wait_state(session, None)
                logger.debug(session.sinfo + f"_set_wait_state set wait state--> None")

            t_reply_b = time.time()
            messages[0] = {
                "role": "system",
                "content": (
                    "你是智能电话客服播报助手。"
                    "根据工具返回的 msg 字段，用自然口语转述给客户，不得使用 markdown、换行、emoji、序号。"
                    "不要调用任何工具，只输出纯文本。"
                )
            }
            answer_text = await run_in_threadpool(reply_llm.chat_with_tools, messages)
            session._stage_costs["final_reply"] = int((time.time() - t_reply_b) * 1000)

        # ── 公共：日志 + history + 返回 ──────────────────────────────
        total_ms = int((time.time() - t0) * 1000)
        logger.debug(session.sinfo + f"[ask_skill] after branch A or B,after 2nd llm call  total elapsed={total_ms}ms "
                                     f"skill={last_tool_name} answer={answer_text[:80] if answer_text else ''}")
        if not skip_history:
            session._history_add("user", text)
            if answer_text and answer_text.strip():
                session._history_add("assistant", answer_text)
                session._history_trim(60)

        cost = {**session._stage_costs, "skill_total": total_ms}
        session._stage_costs = {}

        return ChatAnswer(
            code=CODE_OK,
            answer=answer_text,
            action=Action.NONE,
            intent="COMMAND",
            sub_intent=last_tool_name,
            hit_source="skill",
            cost=cost,
        )

    except Exception as e:
        logger.error(session.sinfo + f"[ask_skill] error: {e}", exc_info=True)
        session._stage_costs = {}
        return ChatAnswer.of_system_error(e)


# ══════════════════════════════════════════════════════════════
# 3. 分层版 prompt 构造 —— 只含 Routing Rules，不掺 Classify Rules
# ══════════════════════════════════════════════════════════════
def _build_layer_prompt(caller_phone: str) -> str:
    """精简版 system prompt：只负责'4选1'路由判断，不涉及知识分类JSON格式，
    彻底和 chat_skill_classify.py 的"格式切换"负担脱钩。"""
    today = date.today().strftime("%Y-%m-%d")

    lines = [
        "# Role: 智能客服业务路由助理\n",
        f"## Context\n- 当前来电手机号: {caller_phone}（系统自动注入，禁止向用户索取）,今天的日期是 {today}\n",
        "## 任务说明\n",
        "你的唯一任务是从下方提供的工具列表中，选择且仅选择一个最匹配用户本轮意图的工具进行调用。"
        "这4个选项互斥、且必须选择其中之一：\n",
        "## Routing Rules\n",
    ]
    for name, module in SKILL_REGISTRY.items():
        kw_sample = "、".join(module.trigger_keywords[:10])
        lines.append(f"- 用户提及「{kw_sample}」等 → 调用 {module.tool_names[0]}")
    lines.append(
        "- 除以上三类业务场景之外的任何内容（包括账号/密码/登录等知识问题、"
        "闲聊、问候、无法明确归类的内容）→ 必须调用 not_business_related，"
        "禁止强行归类到某个业务工具\n"
    )
    lines.append("## 重要约束（调用真实业务工具时生效）")
    lines.append("1. phone 始终从 Context 自动获取，禁止向用户索取")
    lines.append("2. 没有进行中的流程时，按用户当前意图正常路由")
    lines.append("3. 工具返回的原始数据不得直接输出，必须用自然语言组织后回复")
    lines.append("4. 不得暴露工具名称、参数名称等内部信息给用户")
    lines.append("5. 回复必须是纯文本，不得使用 markdown、换行、emoji、序号，用自然口语连续表达，适合直接语音播放")
    return "\n".join(lines)