# ingestion_service.py
# Java: package com.lcallai;
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

import ai_config as AiConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Java: static class KnowledgeEntry { String id, category, summary, content; }
# ---------------------------------------------------------------------------
@dataclass
class KnowledgeEntry:
    id:       str
    category: str
    summary:  str
    content:  str


# ---------------------------------------------------------------------------
"""
public static void main(String[] args) throws Exception {
    String baseDir = (args.length > 0) ? args[0] : "e:\\ai";
    baseDir = baseDir.replace("\\", "/");
    AiConfig.init(baseDir);

    String storageType = AiConfig.getStringConfig("storage.type", "lucene");
    String rawFilePath = AiConfig.getStringConfig("path.knowledge", "config/publishknowledge.txt");
    String filePath    = Paths.get(baseDir, rawFilePath).toString();

    EmbeddingClient embedClient = SessionManager.createQwenTurboClient();
    tableName = "enterprise_knowledge_" + (embedClient.getDimension() == 768 ? "768" : "qwen_1024");

    List<KnowledgeEntry> entries = readFromTxt(filePath);  // or readFromExcel

    for (KnowledgeEntry entry : entries) {
        String semanticText = String.format("分类：【%s】。摘要：%s。内容：%s",
                category, summary, content);
        double[] vector = embedClient.embed(semanticText);
        upsertToDatabase(tableName, entry, vector);
    }
}
"""
# ---------------------------------------------------------------------------
def build_semantic_text(category: str, summary: str, content: str) -> str:
    """向量化文本的唯一拼接入口，批量导入和网页单条向量化都调用这个函数，
    确保任何地方计算出来的向量都用同一套格式，不会产生向量空间不一致的问题。"""
    return f"Category: [{category}]. Summary: {summary}. Content: {content}"

def ingest_entries(
        table_name: str,
        entries: List[KnowledgeEntry],
        db_url: str,
        db_user: str,
        db_pass: str,
) -> dict:
    """
    共享的"条目列表 → 逐条清洗 + upsert（不含向量化）"核心逻辑。
    命令行批量导入（run()）和网页TXT导入（main_web.py 的 import_txt）都调用这个函数，
    确保两条入口的清洗规则、默认值、跳过逻辑完全一致。

    导入阶段不做向量化，写入后记录状态为"待向量化"(pending)，
    后续通过网页"更新向量"按钮或单独的向量化流程统一处理，
    避免导入时被 Embedding API 调用拖慢、也让导入和向量化两个操作互相独立、便于分别重试。
    """
    import time
    results = {"success": 0, "failed": 0, "total": len(entries)}
    total_start = time.time()

    for i, entry in enumerate(entries):
        if entry.id.upper() == "ID":
            continue

        category = (entry.category.strip() if entry.category else "Uncategorized")[:50]
        summary  = (entry.summary.strip()  if entry.summary  else "No summary")[:255]
        content  = _cleanContent(entry.content) if entry.content else ""

        if not content:
            logger.debug(f"⚠️ Entry {i + 1} has empty content, skipped")
            continue

        try:
            t1 = time.time()
            _upsertToDatabase(table_name, entry, None, db_url, db_user, db_pass)
            db_ms = int((time.time() - t1) * 1000)

            logger.debug(f"   ✅ ID [{entry.id}]  db={db_ms}ms（待向量化）")
            results["success"] += 1
        except Exception as e:
            logger.error(f"   ❌ ID [{entry.id}] failed: {e}")
            results["failed"] += 1

    total_ms = int((time.time() - total_start) * 1000)
    logger.debug(f"✨ Import complete! success: {results['success']} / {results['total']}"
                 f"  total={total_ms}ms  avg={total_ms // max(results['success'], 1)}ms/entry"
                 f"  （注意：仅写入文本，向量化需后续手动触发）")
    results["total_ms"] = total_ms
    return results

def run(base_dir: str) -> None:
    import time
    base_dir      = base_dir.replace("\\", "/").rstrip("/")
    AiConfig.init(base_dir)

    storage_type  = AiConfig.getStringConfig("storage.type", "online")
    raw_file_path = AiConfig.getStringConfig("path.knowledge", "config/publishknowledge.txt")
    file_path     = str(Path(base_dir) / raw_file_path.lstrip("/"))

    db_url  = AiConfig.getStringConfig("db.postgres.url",      "jdbc:postgresql://127.0.0.1:5432/postgres")
    db_user = AiConfig.getStringConfig("db.postgres.user",     "postgres")
    db_pass = AiConfig.getStringConfig("db.postgres.password", "call")

    logger.debug("🚀 Starting ingestion pipeline... type=" + storage_type + " file=" + file_path)

    embed_client = _create_embed_client(base_dir)
    dim          = embed_client.getDimension()

    # Warm up the embedding client to avoid slow first call
    logger.debug("⏳ Warming up embedding client...")
    t_warm = time.time()
    embed_client.embed("warm up")
    logger.debug("✅ Embedding warm-up done  t=" + str(int((time.time() - t_warm) * 1000)) + "ms")

    # Warm up embedding client
    logger.debug("⏳ Warming up embedding client...")
    t_warmup = time.time()
    embed_client.embed("warm up")
    logger.debug("✅ Embedding warm-up done  t=" + str(int((time.time() - t_warmup) * 1000)) + "ms")

    table_name   = AiConfig.getStringConfig("db.postgres.table.online", "enterprise_knowledge_1024")
    logger.debug("🚀 Mode: " + storage_type + " | dim: " + str(dim) + " | table: " + table_name)

    clearDatabase(table_name, db_url, db_user, db_pass)

    if file_path.lower().endswith(".txt"):
        entries = _readFromTxt(file_path)
    elif file_path.lower().endswith((".xlsx", ".xls")):
        entries = _readFromExcel(file_path)
    else:
        logger.error("❌ Unsupported file format, only .txt or .xlsx")
        return

    logger.debug("📂 Total entries: " + str(len(entries)) + "")

    results = ingest_entries(table_name, entries, db_url, db_user, db_pass)
    logger.debug(f"✨ 命令行批量导入完成: {results}")

# ---------------------------------------------------------------------------
# 供 Web 管理后台调用：按 id 列表重新向量化，复用跟批量导入完全一致的
# semantic_text 拼接格式（包含 category），避免两条入口生成不一致的向量。
# conn 由调用方（router.py）传入并负责关闭，这里不新开连接。
# ---------------------------------------------------------------------------
def vectorize_ids(conn, table_name: str, ids: List[str], embed_client) -> dict:
    results = {"success": 0, "failed": 0, "errors": []}

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"SELECT id, category, summary, content FROM {table_name} WHERE id = ANY(%s)",
            (ids,)
        )
        items = cur.fetchall()

    logger.info(f"[vectorize_ids] 请求 {len(ids)} 个id，实际取到 {len(items)} 条")
    for item in items:
        try:
            # 与 run() 批量导入保持同一格式，确保向量空间一致
            semantic_text = f"Category: [{item['category']}]. Summary: {item['summary']}. Content: {item['content']}"
            vector  = embed_client.embed(semantic_text)
            vec_str = "[" + ",".join(str(v) for v in vector) + "]"

            with conn.cursor() as c:
                c.execute(f"""
                    UPDATE {table_name}
                    SET embedding = %s::vector, is_active = true, updated_at = NOW()
                    WHERE id = %s
                """, (vec_str, item["id"]))
            conn.commit()
            results["success"] += 1
            logger.debug(f"[vectorize_ids] id={item['id']} 成功")
        except Exception as e:
            logger.error(f"[vectorize_ids] id={item['id']} summary={item.get('summary','')[:30]!r} 失败: {e}")
            results["failed"] += 1
            results["errors"].append(str(e))

    logger.info(f"[vectorize_ids] 完成：成功 {results['success']} 条，失败 {results['failed']} 条")
    return results
# ---------------------------------------------------------------------------
"""
private static List<KnowledgeEntry> readFromTxt(String filePath) throws Exception {
    List<String> lines = Files.readAllLines(Paths.get(filePath), StandardCharsets.UTF_8);
    for (String line : lines) {
        String trimmed = line.trim();
        if (trimmed.isEmpty() || trimmed.startsWith("#")) continue;
        String[] parts = trimmed.split("\\|\\|", 4);
        if (parts.length >= 4) {
            list.add(new KnowledgeEntry(parts[0], parts[1], parts[2], parts[3]));
        }
    }
}
"""
# ---------------------------------------------------------------------------
def _readFromTxt(file_path: str) -> List[KnowledgeEntry]:
    entries = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            trimmed = line.strip()
            # Java: if (trimmed.isEmpty() || trimmed.startsWith("#")) continue;
            if not trimmed or trimmed.startswith("#"):
                continue
            # Java: String[] parts = trimmed.split("\\|\\|", 4);
            parts = trimmed.split("||", 3)
            if len(parts) >= 4:
                entries.append(KnowledgeEntry(
                    id=parts[0].strip(),
                    category=parts[1].strip(),
                    summary=parts[2].strip(),
                    content=parts[3].strip(),
                ))
            else:
                logger.debug("⚠️ 跳过格式错误的行: " + trimmed)
    return entries

def _readFromTxt_from_str(text: str) -> List[KnowledgeEntry]:
    entries = []
    for line in text.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        parts = trimmed.split("||", 3)
        if len(parts) >= 4:
            entries.append(KnowledgeEntry(
                id=parts[0].strip(), category=parts[1].strip(),
                summary=parts[2].strip(), content=parts[3].strip(),
            ))
    return entries
# ---------------------------------------------------------------------------
"""
private static List<KnowledgeEntry> readFromExcel(String filePath) throws Exception {
    Sheet sheet = workbook.getSheetAt(0);
    // A:id, B:category, C:summary, D:content
}
"""
# ---------------------------------------------------------------------------
def _readFromExcel(file_path: str) -> List[KnowledgeEntry]:
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("请安装 openpyxl: pip install openpyxl")

    entries = []
    wb    = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    sheet = wb.active

    for row in sheet.iter_rows(min_row=2, values_only=True):  # skip header
        if not row or all(v is None for v in row):
            continue
        # A:id  B:category  C:summary  D:content
        id_val   = str(row[0]).strip() if row[0] is not None else ""
        category = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
        summary  = str(row[2]).strip() if len(row) > 2 and row[2] is not None else ""
        content  = str(row[3]).strip() if len(row) > 3 and row[3] is not None else ""

        if not id_val or id_val.upper() == "ID":
            continue
        entries.append(KnowledgeEntry(id=id_val, category=category,
                                      summary=summary, content=content))
    wb.close()
    return entries


# ---------------------------------------------------------------------------
"""
private static void upsertToDatabase(String tableName, KnowledgeEntry entry,
                                      double[] vector) throws Exception {
    String sql = "INSERT INTO " + tableName + " (" +
        "id, category, summary, content, source_name, is_active, create_time, embedding" +
        ") VALUES (?, ?, ?, ?, 'System_Import', true, CURRENT_TIMESTAMP, ?::vector) " +
        "ON CONFLICT (id) DO UPDATE SET " +
        "category=EXCLUDED.category, summary=EXCLUDED.summary, " +
        "content=EXCLUDED.content, embedding=EXCLUDED.embedding, " +
        "create_time=CURRENT_TIMESTAMP";
}
"""
# ---------------------------------------------------------------------------
def _upsertToDatabase(
        table_name: str,
        entry: KnowledgeEntry,
        vector: Optional[List[float]],
        db_url: str,
        db_user: str,
        db_pass: str,
) -> None:
    # Convert jdbc URL to psycopg2 params
    dsn      = db_url.replace("jdbc:postgresql://", "")
    host_port, dbname = dsn.split("/", 1)
    parts    = host_port.split(":")
    host     = parts[0]
    port     = int(parts[1]) if len(parts) > 1 else 5432

    conn = psycopg2.connect(host=host, port=port, dbname=dbname,
                            user=db_user, password=db_pass)
    try:
        with conn.cursor() as cur:
            if vector is not None:
                # 带向量：插入/更新时一并写入 embedding，is_active=true（可被立即检索）
                vec_str = "[" + ",".join(str(v) for v in vector) + "]"
                sql = (
                        "INSERT INTO " + table_name + " "
                                                      "(id, category, summary, content, source_name, is_active, create_time, embedding) "
                                                      "VALUES (%s, %s, %s, %s, 'System_Import', true, CURRENT_TIMESTAMP, %s::vector) "
                                                      "ON CONFLICT (id) DO UPDATE SET "
                                                      "category=EXCLUDED.category, "
                                                      "summary=EXCLUDED.summary, "
                                                      "content=EXCLUDED.content, "
                                                      "embedding=EXCLUDED.embedding, "
                                                      "create_time=CURRENT_TIMESTAMP"
                )
                cur.execute(sql, (entry.id, entry.category, entry.summary,
                                  entry.content, vec_str))
            else:
                # 不带向量：只写文本字段，embedding 留空，is_active=true
                # id 已存在时：更新文本字段，同时清空旧向量（embedding=NULL），
                # 使这条记录回到"待向量化"(pending)状态 —— 不管内容实际有没有变，
                # 只要被重新导入过，就统一要求重新向量化，逻辑简单、不会有遗漏
                sql = (
                        "INSERT INTO " + table_name + " "
                                                      "(id, category, summary, content, source_name, is_active, create_time) "
                                                      "VALUES (%s, %s, %s, %s, 'System_Import', true, CURRENT_TIMESTAMP) "
                                                      "ON CONFLICT (id) DO UPDATE SET "
                                                      "category=EXCLUDED.category, "
                                                      "summary=EXCLUDED.summary, "
                                                      "content=EXCLUDED.content, "
                                                      "embedding=NULL, "
                                                      "create_time=CURRENT_TIMESTAMP"
                )
                cur.execute(sql, (entry.id, entry.category, entry.summary, entry.content))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
"""
private static void clearDatabase(String tableName) throws Exception {
    String sql = "TRUNCATE TABLE " + tableName + " RESTART IDENTITY";
}
"""
# ---------------------------------------------------------------------------
def clearDatabase(table_name: str, db_url: str, db_user: str, db_pass: str) -> None:
    dsn       = db_url.replace("jdbc:postgresql://", "")
    host_port, dbname = dsn.split("/", 1)
    parts     = host_port.split(":")
    host      = parts[0]
    port      = int(parts[1]) if len(parts) > 1 else 5432

    conn = psycopg2.connect(host=host, port=port, dbname=dbname,
                             user=db_user, password=db_pass)
    try:
        with conn.cursor() as cur:
            logger.debug("⚠️ 正在全量清理数据库表: " + table_name + "...")
            cur.execute("TRUNCATE TABLE " + table_name + " RESTART IDENTITY")
        conn.commit()
        logger.debug("✅ 清理完成。")
    except Exception as e:
        logger.error("❌ 清理失败: " + str(e))
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Java: private static void _cleanContent(String raw)
# ---------------------------------------------------------------------------
def _cleanContent(raw: str) -> str:
    # Java: raw.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    cleaned = raw.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    # Java: cleaned.replaceAll("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]", "")
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", cleaned)
    # Java: cleaned.replaceAll("\\s+", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _create_embed_client(base_dir: str):
    """
    Build EmbeddingClient based on system.run.type:
      qwen        → CloudEmbeddingClient (Aliyun text-embedding-v3, 1024-dim)
      openai      → CloudEmbeddingClient (OpenAI text-embedding-3-small, 1024-dim)
      hybrid-qwen → EmbeddingClient (local bge-large, path from config)
      others      → EmbeddingClient (local, path from config)
    """
    run_type = AiConfig.getStringConfig("system.run.type", "hybrid-qwen").lower()

    if run_type == "qwen":
        from openai import OpenAI
        from search.embedding_client import CloudEmbeddingClient
        qwen_key = AiConfig.getStringConfig("api.key.qwen",
                                            os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY") or "")
        if not qwen_key:
            raise RuntimeError("❌ system.run.type=qwen but api.key.qwen not set")
        client = OpenAI(
            api_key=qwen_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        logger.debug("🌐 CloudEmbeddingClient: Aliyun text-embedding-v3 (1024-dim)")
        return CloudEmbeddingClient(client, model="text-embedding-v3", dimensions=1024)

    elif run_type == "openai":
        from openai import OpenAI
        from search.embedding_client import CloudEmbeddingClient
        openai_key = AiConfig.getStringConfig("api.key.openai",
                                              os.environ.get("OPENAI_API_KEY") or "")
        if not openai_key:
            raise RuntimeError("❌ system.run.type=openai but api.key.openai not set")
        client = OpenAI(api_key=openai_key)
        logger.debug("🌐 CloudEmbeddingClient: OpenAI text-embedding-3-small (1024-dim)")
        return CloudEmbeddingClient(client, model="text-embedding-3-small", dimensions=1024)

    else:
        # hybrid-qwen, hybrid-openai, etc. — local model
        from search.embedding_client import EmbeddingClient
        embed_name = AiConfig.getStringConfig("djl.model.embed.name",
                                              "text2vec-base-chinese-paraphrase-pt")
        model_path = str(Path(base_dir) / embed_name)
        logger.debug("💻 EmbeddingClient: local model " + model_path)
        return EmbeddingClient(model_path)



# ---------------------------------------------------------------------------
# Entry point — mirrors Java main(String[] args)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s %(levelname)s %(message)s")
    base = sys.argv[1] if len(sys.argv) > 1 else "E:\EIT\py-LLM-integration"
    run(base)
