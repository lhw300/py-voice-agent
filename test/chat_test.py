
# chat_test.py
import requests
import random
from pprint import pprint
BASE_URL = "http://localhost:7626"

def chat(vo_id: str, text: str, sn: str) -> str:
    url = f"{BASE_URL}/{vo_id}"
    payload = {
        "sn":         sn,
        "crid":       "c1",
        "ch":         "1",
        "call_date":  "2026-05-05",
        "start_time": "10:00:00",
        "phone":      "13800000000",
        "vo_id":      vo_id,
        "text":       text
    }
    resp = requests.post(url, json=payload)
    pprint(resp.json())
    if resp.status_code == 200:
        return resp.json().get("answer", "")
    else:
        return f"[错误 {resp.status_code}] {resp.text}"


if __name__ == "__main__":
    sn = str(random.randint(1000, 9999))
    vo_id = "filling_ai"
    vo_id = "ai_send"
    print(f"=== 交互测试 vo_id={vo_id} sn={sn} ===")
    print("输入 'quit' 或 'exit' 退出，输入 'new' 开始新会话\n")

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit"):
            print("退出")
            break

        if user_input.lower() == "new":
            sn = str(random.randint(1000, 9999))
            print(f"--- 新会话 sn={sn} ---\n")
            continue

        answer = chat(vo_id, user_input, sn)
        print(f"AI: {answer}\n")
