# search/cache_export.py
#
# Export K1/K2 cache entries and interactively delete them.
#
# Run:
#   python search/cache_export.py [config_path]
# ---------------------------------------------------------------------------

import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.WARNING,
    stream=sys.stdout,
)

import ai_config as AiConfig
from search.cache_service import init, _get_redis, _K1_INDEX, _K2_INDEX, _PREFIX_K1, _PREFIX_K2


def ensure_str(val) -> str:
    """Helper to convert bytes to string if Redis returns bytes."""
    if isinstance(val, bytes):
        return val.decode("utf-8")
    return str(val) if val is not None else ""


def delete_by_ids(r, input_ids: list):
    """Loop through given IDs and delete from K1 or K2 if they exist."""
    for raw_id in input_ids:
        target_id = raw_id.strip()
        if not target_id:
            continue

        deleted_any = False

        # Try deleting from K1 (using target_id as Hash)
        if r.zrem(_K1_INDEX, target_id):
            r.delete(_PREFIX_K1 + target_id)
            print(f"  [✔] 成功删除 K1 缓存 (Hash: {target_id})")
            deleted_any = True

        # Try deleting from K2 (using target_id as EID)
        if r.zrem(_K2_INDEX, target_id):
            r.delete(_PREFIX_K2 + target_id)
            print(f"  [✔] 成功删除 K2 缓存 (EID: {target_id})")
            deleted_any = True

        if not deleted_any:
            print(f"  [✘] 未找到对应的缓存 ID: {target_id}")


def export_and_interactive_delete(config_dir: str):
    AiConfig.init(config_dir)
    init(config_dir)
    r = _get_redis()

    # >>>>>>>>>> 修改点：将查询和打印放进循环内 >>>>>>>>>>
    while True:
        lines = []

        # ── K1 ──────────────────────────────────────────────────────────────
        lines.append("=" * 60)
        lines.append("K1 EXACT MATCH CACHE")
        lines.append("=" * 60)

        k1_keys = r.zrange(_K1_INDEX, 0, -1)
        for i, h_bytes in enumerate(k1_keys, 1):
            h = ensure_str(h_bytes)
            val = r.get(_PREFIX_K1 + h)
            if not val:
                continue
            d = json.loads(ensure_str(val))
            q = d.get("question", f"[hash:{h}]")

            a = d.get("answer", "")[:80] + "..." if len(d.get("answer", "")) > 80 else d.get("answer", "")
            src = d.get("hit_source", "rag")
            ttl = r.ttl(_PREFIX_K1 + h)
            ttl_str = "permanent" if ttl == -1 else f"ttl={ttl}s"

            lines.append(f"[{i}] ({src}) ({ttl_str}) [ID: {h}]")
            lines.append(f"  Q: {q}")
            lines.append(f"  A: {a}")
            lines.append("")

        # ── K2 ──────────────────────────────────────────────────────────────
        lines.append("=" * 60)
        lines.append("K2 SEMANTIC CACHE")
        lines.append("=" * 60)

        k2_keys = r.zrange(_K2_INDEX, 0, -1)
        for i, eid_bytes in enumerate(k2_keys, 1):
            eid = ensure_str(eid_bytes)
            raw = r.hgetall(_PREFIX_K2 + eid)
            if not raw:
                continue

            raw_decoded = {ensure_str(k): ensure_str(v) for k, v in raw.items()}

            q = raw_decoded.get("question", "")
            a = raw_decoded.get("answer", "")[:80] + "..." if len(raw_decoded.get("answer", "")) > 80 else raw_decoded.get("answer", "")
            ttl = r.ttl(_PREFIX_K2 + eid)
            ttl_str = "permanent" if ttl == -1 else f"ttl={ttl}s"

            lines.append(f"[{i}] ({ttl_str}) [ID: {eid}]")
            lines.append(f"  Q: {q}")
            lines.append(f"  A: {a}")
            lines.append("")

        # ── Summary ─────────────────────────────────────────────────────────
        lines.append("=" * 60)
        lines.append(f"K1 total: {len(k1_keys)}   K2 total: {len(k2_keys)}")
        lines.append("=" * 60)

        # 打印当前数据库里的缓存
        print("\n".join(lines))
        print("\n" + "=" * 60)

        # 进入交互
        try:
            # 提示语中加入了 run 命令的说明
            user_input = input("\n👉 输入 ID 删除(空格隔开) | 输入 run 重新查询刷新 | 直接回车退出: ").strip()

            # 1. 检查是否直接回车退出
            if not user_input:
                print("退出程序。")
                break

            # 2. 检查是否是 run 命令（不区分大小写）
            if user_input.lower() == "run":
                print("\n🔄 正在重新从 Redis 查询并刷新列表...\n")
                continue  # 跳过后面的删除逻辑，直接进入下一次循环（即重新拉取数据并打印）

            # 3. 否则，执行删除逻辑
            target_ids = user_input.split()
            print(f"正在处理删除请求...")
            delete_by_ids(r, target_ids)

            # 删除完后，为了防止屏幕太乱，加个分割线
            print("\n" + "*" * 40)
            print("提示：删除已完成。你可以输入 run 查看最新缓存列表。")
            print("*" * 40)

        except KeyboardInterrupt:
            print("\n程序已被强行终止。")
            break
    # <<<<<<<<<< 修改点结束 <<<<<<<<<<



if __name__ == "__main__":

    config_path = os.environ.get("AI_CONFIG_DIR", "/home/call/py-voice-agent")
    args = sys.argv[1:]
    if args:
        config_path = args[0]

    export_and_interactive_delete(config_path)