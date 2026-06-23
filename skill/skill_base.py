"""
skill_base.py
─────────────────────────────────────────────────────────────
业务 Skill 模块的统一接口规范。

设计目的：
  chat_skill.py（总控）不应该知道每个业务内部是怎么实现的
  （是否用了 draft 多字段引擎、是否需要 confirm、状态怎么存），
  它只应该面向这一份统一契约编程。

每个业务文件（skill_express.py / skill_complaint.py / skill_internet.py）
必须提供以下几样东西，并在模块加载时注册到 SKILL_REGISTRY：

  1. tools: List[dict]
       该业务在"正常状态"下暴露给 LLM 的工具 JSON Schema 列表
       （简单业务通常 1 个工具，复杂表单业务也可能后续拆分）

  2. trigger_keywords: List[str]
       触发该业务的关键词，用于 chat_skill 的关键词预检

  3. locked_tools: List[dict]
       进入该业务"锁定状态"后暴露的工具（通常是 [自己的工具, cancel_skill]）

  4. build_locked_prompt(session, caller_phone) -> str
       生成锁定状态下的 system prompt，由业务自己决定怎么描述当前进度
       （比如投诉/报修要把已收集字段写进 prompt，快递查询不需要）

  5. handle(session, **kwargs) -> dict
       执行业务逻辑的统一入口，kwargs 来自 LLM 的 tool_call 参数。
       返回值统一约定为一个 dict，必须包含 "status" 字段，
       status 的值必须是下面 SkillStatus 中定义的几种之一。

  6. on_state_update(session, status) -> Optional[str]
       根据本次 handle() 返回的 status，决定锁定状态的下一步：
       返回 None 表示应该解除锁定（回到正常路由）
       返回字符串表示应该保持/进入某个锁定状态 key（用于 chat_skill 的 wait_state）
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Callable, Protocol


class SkillStatus:
    """
    所有业务模块的返回 status 必须从这几个值里选，
    chat_skill.py 只认这几个状态，不关心业务内部还有什么子状态。
    """
    NEED_INFO = "need_info"            # 还缺信息，需要继续追问（不管是缺单一字段还是缺日期）
    PENDING_CONFIRM = "pending_confirm"  # 信息已集齐，等待用户确认
    DONE = "done"                      # 业务已完成（无论是成功提交还是查询返回结果）
    CANCELLED = "cancelled"            # 用户主动取消
    ERROR = "error"                    # 业务内部异常


@dataclass
class SkillModule:
    """每个业务模块注册到总控时提供的统一描述"""
    name: str                                   # 业务唯一标识，如 "express" / "complaint" / "internet"
    tools: List[Dict]                            # 正常状态下暴露的 tool schema
    trigger_keywords: List[str]                  # 关键词预检列表
    locked_tools: List[Dict]                      # 锁定状态下暴露的 tool schema
    build_locked_prompt: Callable[[object, str], str]   # (session, caller_phone) -> prompt str
    handle: Callable                              # async (session, **kwargs) -> dict，必须含 status
    tool_names: List[str] = None                  # 该业务对应的 tool function name 列表（用于状态恢复时识别）

    def __post_init__(self):
        if self.tool_names is None:
            self.tool_names = [t["function"]["name"] for t in self.tools]


# ══════════════════════════════════════════════════════════════
# 全局注册表：chat_skill.py 启动时从这里拿到所有已注册业务
# ══════════════════════════════════════════════════════════════
SKILL_REGISTRY: Dict[str, SkillModule] = {}


def register_skill(module: SkillModule) -> None:
    if module.name in SKILL_REGISTRY:
        raise ValueError(f"skill '{module.name}' 重复注册")
    SKILL_REGISTRY[module.name] = module


def get_skill(name: str) -> Optional[SkillModule]:
    return SKILL_REGISTRY.get(name)


def all_tools() -> List[Dict]:
    """正常状态下，汇总所有已注册业务的 tools，供 chat_skill 传给 LLM"""
    tools = []
    for m in SKILL_REGISTRY.values():
        tools.extend(m.tools)
    return tools


def find_skill_by_keyword(text: str) -> Optional[str]:
    """关键词预检，返回命中的 skill name，没命中返回 None"""
    for name, module in SKILL_REGISTRY.items():
        if any(kw in text for kw in module.trigger_keywords):
            return name
    return None


def find_skill_by_tool_name(tool_name: str) -> Optional[str]:
    """根据 LLM 调用的 tool function name，反查属于哪个业务模块"""
    for name, module in SKILL_REGISTRY.items():
        if tool_name in module.tool_names:
            return name
    return None
# ── session 通用读写 ──────────────────────────────
def skill_get(session, key: str, default=None):
    return getattr(session, key, default)

def skill_set(session, key: str, value) -> None:
    setattr(session, key, value)

def skill_clear(session, *keys) -> None:
    for key in keys:
        setattr(session, key, None)

def skill_get_draft(session, key: str) -> dict:
    return getattr(session, key, None) or {}

def skill_set_draft(session, key: str, draft: dict) -> None:
    setattr(session, key, draft)

def skill_merge_fields(draft: dict, **fields) -> dict:
    for k, v in fields.items():
        if v not in (None, ""):
            draft[k] = v
    return draft

# ── 返回值构造 ──────────────────────────────
def skill_need(msg: str) -> dict:
    return {"status": SkillStatus.NEED_INFO, "msg": msg}

def skill_pending(msg: str) -> dict:
    return {"status": SkillStatus.PENDING_CONFIRM, "msg": msg}

def skill_done(msg: str) -> dict:
    return {"status": SkillStatus.DONE, "msg": msg}

def skill_error(msg: str) -> dict:
    return {"status": SkillStatus.ERROR, "msg": msg}


