"""
ai.conf 配置管理后端 API
FastAPI + Python

安装依赖:
    pip install fastapi uvicorn python-multipart

运行:
    uvicorn ai_config_server:app --reload --port 8000

前端通过 http://localhost:8000 访问
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any
import re
import os

app = FastAPI(title="AI Config Manager", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_FILE = os.environ.get("AI_CONF_PATH", "ai.conf")


def parse_conf(text: str) -> dict[str, Any]:
    """解析 key=value 配置文件，保留注释行原始内容用于写回"""
    result = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # 去掉行尾注释（# 之后的内容），但保留值内部的 # 符号（如 URL）
        # 规则：第一个空格后跟 # 视为行尾注释
        kv = re.split(r"\s+#", stripped, maxsplit=1)[0]
        if "=" in kv:
            k, _, v = kv.partition("=")
            result[k.strip()] = v.strip()
    return result


def write_conf(original: str, updates: dict[str, str]) -> str:
    """将更新写回原始文件，保留注释和格式"""
    lines = original.splitlines()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            out.append(line)
            continue
        kv = re.split(r"\s+#", stripped, maxsplit=1)[0]
        if "=" in kv:
            k, _, _ = kv.partition("=")
            key = k.strip()
            if key in updates:
                # 保留原有行尾注释
                comment_match = re.search(r"\s+(#.*)$", line)
                comment = f"  {comment_match.group(1)}" if comment_match else ""
                out.append(f"{key}={updates[key]}{comment}")
                continue
        out.append(line)
    return "\n".join(out)


def load_config() -> dict[str, str]:
    if not os.path.exists(CONFIG_FILE):
        raise HTTPException(status_code=404, detail=f"配置文件未找到: {CONFIG_FILE}")
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return parse_conf(f.read())


def load_raw() -> str:
    if not os.path.exists(CONFIG_FILE):
        raise HTTPException(status_code=404, detail=f"配置文件未找到: {CONFIG_FILE}")
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return f.read()


# ── 模型 ──────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    updates: dict[str, str]


class SingleUpdate(BaseModel):
    key: str
    value: str


# ── 路由 ──────────────────────────────────────────────

@app.get("/api/config")
def get_all_config():
    """获取全部配置（key-value 字典）"""
    return {"data": load_config(), "file": CONFIG_FILE}


@app.get("/api/config/raw")
def get_raw_config():
    """获取原始文件内容"""
    return {"content": load_raw()}


@app.put("/api/config")
def update_config(body: ConfigUpdate):
    """批量更新配置项"""
    raw = load_raw()
    new_raw = write_conf(raw, body.updates)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(new_raw)
    return {"ok": True, "updated": list(body.updates.keys())}


@app.patch("/api/config/item")
def update_single(body: SingleUpdate):
    """更新单个配置项"""
    raw = load_raw()
    new_raw = write_conf(raw, {body.key: body.value})
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(new_raw)
    return {"ok": True, "key": body.key, "value": body.value}


@app.get("/api/config/section/{prefix}")
def get_section(prefix: str):
    """按前缀获取配置（如 rag, db, cache）"""
    all_conf = load_config()
    section = {k: v for k, v in all_conf.items() if k.startswith(prefix)}
    return {"prefix": prefix, "data": section}


@app.post("/api/config/reload")
def reload_config():
    """重新读取配置文件（不做任何写入）"""
    return {"ok": True, "data": load_config()}


@app.get("/health")
def health():
    return {"status": "ok", "config_file": CONFIG_FILE}
