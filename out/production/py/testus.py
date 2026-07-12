import requests
import json

# =================配置区=================
# 🔑 请替换为你在北美控制台创建的 Key (sk-us-xxxx)
API_KEY = "sk-ba43cfbdbb554a1c969a779b196b754b"

# 🌍 北美端点
URL = "https://dashscope-us.aliyuncs.com/compatible-mode/v1/chat/completions"
# =======================================

def test_qwen_us():
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "qwen-plus",  # 用最基础的模型测试连通性
        "messages": [
            {"role": "user", "content": "Hi, are you working?"}
        ],
        "temperature": 0.0,
        "top_p": 1.0
    }

    try:
        print("🚀 正在请求北美节点...")
        response = requests.post(URL, headers=headers, json=payload, timeout=10)

        if response.status_code == 200:
            data = response.json()
            content = data['choices'][0]['message']['content']
            print(f"✅ 成功！回复: {content}")
        else:
            print(f"❌ 失败！状态码: {response.status_code}")
            print(f"   错误信息: {response.text}")

    except Exception as e:
        print(f"❌ 异常: {e}")

if __name__ == "__main__":
    test_qwen_us()