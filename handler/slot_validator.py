# handler/slot_validator.py
import re
import os
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

# 从环境变量获取key
client = OpenAI(
    api_key=os.environ.get("QWEN_API_KEY"),  # ← 改这里
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# ── phone：规则验证 ────────────────────────────────────────────
def validate_phone(text: str) -> tuple[bool, str]:
    cleaned = re.sub(r"[\s\-]", "", text)
    if re.fullmatch(r"1\d{10}", cleaned):
        return True, ""
    else:
        return False, "您说的好像不是手机号码，请重新告诉我您的联系电话？"


# ── name / address：AI验证 ────────────────────────────────────
VALIDATE_PROMPT = """你是一个字段验证助手。
判断用户输入是否是合法的"{field}"。
只回答 YES 或 NO，不要解释。

合法{field}的例子：
{examples}

用户输入："{value}"
"""

FIELD_EXAMPLES = {
    "姓名": "张三、李小明、欧阳娜娜",
    "地址": "翠湖花园3栋201、广州市天河区天河路100号、育才小区5单元302",
}

FIELD_ERROR = {
    "姓名": "您说的好像不是姓名，请重新告诉我您的姓名？",
    "地址": "您说的好像不是地址，请重新告诉我您的装机地址？",
}


def validate_by_ai(field_cn: str, value: str) -> tuple[bool, str]:
    prompt = VALIDATE_PROMPT.format(
        field=field_cn,
        examples=FIELD_EXAMPLES[field_cn],
        value=value
    )
    try:
        resp = client.chat.completions.create(
            model="qwen-plus",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )
        answer = resp.choices[0].message.content.strip().upper()

        logger.debug(f"AI验证 field={field_cn} value={value} result={answer}")

        if "YES" in answer:
            return True, ""
        else:
            return False, FIELD_ERROR[field_cn]

    except Exception as e:
        logger.error(f"AI验证异常: {e}，默认放行")
        return True, ""  # 验证失败时默认放行，不影响主流程


# ── 统一入口 ──────────────────────────────────────────────────
def validate_slot(key: str, value: str) -> tuple[bool, str]:
    if key == "phone":
        return validate_phone(value)
    elif key == "name":
        return validate_by_ai("姓名", value)
    elif key == "address":
        return validate_by_ai("地址", value)
    return True, ""