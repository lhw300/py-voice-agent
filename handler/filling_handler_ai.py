# handler/filling_handler_ai.py
import logging
import json
import os
from openai import OpenAI
from handler.base_handler import BaseHandler
from intent.intent_result import IntentResult
from models import EivrResponse

logger = logging.getLogger(__name__)

client = OpenAI(
    api_key=os.environ.get("QWEN_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 读取prompt文件
PROMPT_PATH = r"e:\AI\config\prompt_internet_repair.txt"

def load_prompt() -> str:
    with open(PROMPT_PATH, "r", encoding="gbk") as f:
        return f.read()

def ask_ai(system_prompt: str, history: list) -> dict:

    for attempt in range(3):  # 最多重试3次
        content = "" # 初始化 content，防止异常时 logger 引用不到
        try:
            messages = [{"role": "system", "content": system_prompt}] + history
            logger.debug(f"发送给AI的messages={json.dumps(messages, ensure_ascii=False, indent=2)}")

            resp = client.choices = client.chat.completions.create(
                model="qwen-plus",
                messages=messages,
                timeout=10,  # 强制 15 秒超时
                response_format={"type": "json_object"} # 强制模型底层尽量输出 JSON
            )

            content = resp.choices[0].message.content.strip()
            logger.debug(f"AI原始返回={content}")

            # 尝试解析 JSON
            data = json.loads(content)

            # 即使解析成功，也要确保它是字典类型
            if isinstance(data, dict):
                return data
            else:
                raise json.JSONDecodeError("Not a dictionary", content, 0)

        except (json.JSONDecodeError, Exception) as e:
            # 如果是最后一次尝试，或者 AI 直接返回了裸字符串（如 "清凉门大街"）
            # 我们手动构造一个合法的 JSON 结构返回，防止 handle 函数崩溃
            if attempt == 2 or (content and not content.startswith("{")):
                logger.warning(f"AI返回格式异常，手动包装数据返回。内容={content}")
                return {
                    "answer": content.strip('"'), # 去掉 AI 偶尔带的引号
                    "slots": {},  # 返回空字典，handle.py 的 .get("slots", {}) 会处理它
                    "is_complete": False
                }

            logger.warning(f"AI返回非JSON，第{attempt+1}次重试，错误={str(e)}")
            continue

    # 极端的网络/API 故障兜底
    return {"answer": "抱歉，系统忙，请稍后再试", "slots": {}, "is_complete": False}

def ask_ai2(system_prompt: str, history: list) -> dict:
    # 在system prompt里再次强调
    #strict_prompt = system_prompt + "\n\n【重要】你的回复必须且只能是JSON格式，不能包含任何其他文字。"

    for attempt in range(3):  # 最多重试3次
        try:
            messages = [{"role": "system", "content": system_prompt}] + history
            logger.debug(f"发送给AI的messages={json.dumps(messages, ensure_ascii=False, indent=2)}")

            resp = client.chat.completions.create(
                model="qwen-plus",
                messages=messages,
                response_format={"type": "json_object"} # 强制模型底层只输出 JSON
            )

            content = resp.choices[0].message.content.strip()
            logger.debug(f"AI原始返回={content}")
            return json.loads(content)

        except json.JSONDecodeError:
            logger.warning(f"AI返回非JSON，第{attempt+1}次重试，内容={content}")
            continue

    logger.error("AI多次返回非JSON，使用兜底回复")
    return {"answer": "抱歉，请重新说一遍", "slots": {}, "is_complete": False}


class FillingHandlerAI(BaseHandler):

    def __init__(self):
        self.system_prompt = load_prompt()

    def handle(self, raw_text: str, result: IntentResult, session) -> EivrResponse:
        logger.debug(f"raw_text={raw_text}")

        # 初始化对话历史
        if not hasattr(session, "filling_history"):
            session.filling_history = []

        # 1. 先获取current_slots
        current_slots = getattr(session, "filling_slots", None)
        if current_slots is None:
            current_slots = {"name": None, "phone": None, "address": None}
            session.filling_slots   = current_slots
           # session.filling_history = []

        # 2. 再用current_slots算pending
        pending = next((k for k, v in current_slots.items() if v is None), None)

        # 3. 把pending注入user消息
        current_text = f"[系统提示：当前正在收集{pending}字段]\n{raw_text}"
        session.filling_history.append({"role": "user", "content": current_text})
        # 只保留最近6条（3轮对话），防止早期混乱历史干扰
        if len(session.filling_history) > 6:
            session.filling_history = session.filling_history[-6:]

        # 4. 构建strict_prompt
        strict_prompt = (
                self.system_prompt
                + f"\n\n当前已收集信息：{json.dumps(current_slots, ensure_ascii=False)}"
                + f"\n当前正在收集字段：{pending}"
                + "\n【重要】只能是JSON格式，不能包含任何其他文字。"
        )

        # 5. 调用AI
        response = ask_ai(strict_prompt, session.filling_history)

        # 更新slots，只允许填入，不允许清空
        new_slots = response.get("slots", {})
        for k, v in new_slots.items():
            if v is not None:
                current_slots[k] = v
        session.filling_slots = current_slots

        answer      = response.get("answer", "系统繁忙，请稍后再试")
        is_complete = response.get("is_complete", False)
        logger.debug(f"slots={session.filling_slots} is_complete={is_complete}")

        # 把AI回复加入历史
        session.filling_history.append({"role": "assistant", "content": answer})

        # 完成后清空历史
        if is_complete:
            logger.info(f"报修完成 slots={session.filling_slots}")
            session.filling_history = None
            session.filling_slots   = None

        return EivrResponse(code=0, answer=answer)