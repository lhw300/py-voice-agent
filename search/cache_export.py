# search/cache_export.py
#
# Export K1/K2 cache entries to console or file for review and correction.
#
# Run:
#   python search/cache_export.py [config_path]
#   python search/cache_export.py [config_path] --output cache_dump.txt
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


def export(config_dir: str, output_file: str = None):
    AiConfig.init(config_dir)
    init(config_dir)
    r = _get_redis()

    lines = []

    # ── K1 ──────────────────────────────────────────────────────────────────
    lines.append("=" * 60)
    lines.append("K1 EXACT MATCH CACHE")
    lines.append("=" * 60)

    k1_keys = r.zrange(_K1_INDEX, 0, -1)
    for i, h in enumerate(k1_keys, 1):
        val = r.get(_PREFIX_K1 + h)
        if not val:
            continue
        d = json.loads(val)
        q = d.get("question", f"[hash:{h}]")

        a = d.get("answer", "")[:80] + "..." if len(d.get("answer", "")) > 80 else d.get("answer", "")
        src = d.get("hit_source", "rag")
        ttl = r.ttl(_PREFIX_K1 + h)
        ttl_str = "permanent" if ttl == -1 else f"ttl={ttl}s"
        lines.append(f"[{i}] ({src}) ({ttl_str})")
        lines.append(f"  Q: {q}")
        lines.append(f"  A: {a}")
        lines.append("")

    # ── K2 ──────────────────────────────────────────────────────────────────
    lines.append("=" * 60)
    lines.append("K2 SEMANTIC CACHE")
    lines.append("=" * 60)

    k2_keys = r.zrange(_K2_INDEX, 0, -1)
    for i, eid in enumerate(k2_keys, 1):
        raw = r.hgetall(_PREFIX_K2 + eid)
        if not raw:
            continue
        q = raw.get("question", "")
        a = raw.get("answer", "")[:80] + "..." if len(raw.get("answer", "")) > 80 else raw.get("answer", "")
        ttl = r.ttl(_PREFIX_K2 + eid)
        ttl_str = "permanent" if ttl == -1 else f"ttl={ttl}s"
        lines.append(f"[{i}] ({ttl_str})")
        lines.append(f"  Q: {q}")
        lines.append(f"  A: {a}")
        lines.append("")

    # ── Summary ─────────────────────────────────────────────────────────────
    lines.append("=" * 60)
    lines.append(f"K1 total: {len(k1_keys)}   K2 total: {len(k2_keys)}")
    lines.append("=" * 60)

    output = "\n".join(lines)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Exported to {output_file}")
    else:
        print(output)


if __name__ == "__main__":
    config_path = "e:/ai"
    output_path = None

    args = sys.argv[1:]
    if args:
        config_path = args[0]
    if "--output" in args:
        idx = args.index("--output")
        if idx + 1 < len(args):
            output_path = args[idx + 1]

    export(config_path, output_path)
