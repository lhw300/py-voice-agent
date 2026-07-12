import requests
import random
import time
from datetime import datetime

BASE_URL = "http://127.0.0.1:7626"

_turn_counter = 0
COST_DIAGRAM = """
=== 耗时字段关系图 ===

客户端总耗时
└── server_total                    main_ai.py: ai_send() 全程
│
├── upsert_call                 MongoDB 写通话记录（线程池）
│
└── ask_layer_total             session.ask_skill() + session.ask()
│
├── 【路径一】命中技能工具（hit_source=skill，如报修/投诉/查快递）
│   直接从 ask_skill() 返回，不会进入 session.ask()
│   │
│   ├── tools        ★LLM调用①  判断要调用哪个工具
│   ├── skill_exec              执行工具本身（查数据库/调用外部接口等）
│   ├── final_reply  ★LLM调用②  把工具结果转述成自然语言
│   └── skill_total             = tools + skill_exec + final_reply（本路径小计）
│
└── 【路径二】未命中工具 → fallback 到 session.ask()（普通问答/闲聊）
│
├── tools        ★LLM调用①  判断要不要调工具（判断结果：不需要）
│
└── ask_total                session.ask() 内部小计
│
├── classify  ★LLM调用②  意图分类 QUERY/COMMAND/...
│                         (命中fast-track时为0ms，不调LLM)
├── k1                    精确缓存查找（仅QUERY走）
│
└── handler                intentDispatcher.dispatch()
│
├── k2                语义缓存命中 → 直接返回
├── retrieval         (K2未命中时) 两阶段向量检索+rerank
└── final_ask         (K2未命中时) ★LLM调用③ 生成最终答案

加法关系：
【路径一】tools + skill_exec + final_reply ≈ skill_total
【路径二】tools + ask_total ≈ ask_layer_total
classify + k1 + handler ≈ ask_total
k2 ≈ handler（K2命中，无retrieval/final_ask）
retrieval + final_ask ≈ handler（K2未命中，走完整RAG）
两条路径共同：upsert_call + ask_layer_total ≈ server_total
======================
"""


def chat(vo_id: str, text: str, sn: str, call_date: str, start_time: str) -> str:
    url = f"{BASE_URL}/{vo_id}"
    global  _turn_counter
    _turn_counter += 1
    payload = {
        "sn":         sn,
        "crid":       "c1",
        "ch":         "1",
        "call_date":  call_date,
        "start_time": start_time,
        "turn":         str(_turn_counter),
        "phone":      "13800009999",
        "vo_id":      vo_id,
        "text":       text
    }

    t0 = time.time()
    resp = requests.post(url, json=payload)
    elapsed = int((time.time() - t0) * 1000)

    if resp.status_code != 200:
        return f"[错误 {resp.status_code}] {resp.text}", elapsed

    data = resp.json()

    cost = data.get("cost")
    short_fields = {k: v for k, v in data.items() if k not in ("answer", "cost")}
    print(" ".join(f"{k}={v}" for k, v in short_fields.items()))
    if cost:
        cost_str = ", ".join(f"{k} {v}ms" for k, v in cost.items())
        print(f"cost: {cost_str}")

    return data.get("answer", ""), elapsed


def new_session():
    sn = str(random.randint(1000, 9999))
    now = datetime.now()
    call_date = now.strftime("%Y-%m-%d")
    start_time = now.strftime("%H:%M:%S")
    global  _turn_counter
    _turn_counter = 0
    return sn, call_date, start_time


if __name__ == "__main__":
    vo_id = "ai_send"
    sn, call_date, start_time = new_session()
    print(COST_DIAGRAM)
    print(f"=== 交互测试 vo_id={vo_id} sn={sn} call_date={call_date} start_time={start_time} ===")
    print("输入 'quit' 或 'exit' 退出，输入 'new' 开始新会话")
    print("输入 'cost' 可重新查看耗时关系图\n")

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
            sn, call_date, start_time = new_session()
            print(f"--- 新会话 sn={sn} call_date={call_date} start_time={start_time} ---\n")
            continue

        if user_input.lower() == "cost":
            print(COST_DIAGRAM)
            continue

        # 支持用 / 分隔的批量测试：一次性输入多轮问题，自动依次执行
        turns = [t.strip() for t in user_input.split("/") if t.strip()]
        for i, text in enumerate(turns, 1):
            if len(turns) >= 1:
                print(f"\n--- 第{i}/{len(turns)}轮 (turn={_turn_counter + 1}): {text} ---")
            answer, elapsed = chat(vo_id, text, sn, call_date, start_time)
            print(f"AI: {answer}  [{elapsed}ms]\n")