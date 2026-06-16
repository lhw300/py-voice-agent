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

    run_type = AiConfig.getStringConfig("system.run.type", "hybrid-qwen").lower()

    success_count = 0
    total_start   = time.time()

    for i, entry in enumerate(entries):
        if entry.id.upper() == "ID":
            continue

        category = (entry.category.strip() if entry.category else "Uncategorized")[:50]
        summary  = (entry.summary.strip()  if entry.summary  else "No summary")[:255]
        content  = _cleanContent(entry.content) if entry.content else ""

        if not content:
            logger.debug("⚠️ Entry " + str(i + 1) + " has empty content, skipped")
            continue

        logger.debug("--------------------------------------------------")
        logger.debug("🔍 [" + str(i + 1) + "] category=" + category + "  summary=" + summary)

        try:
            if run_type in ("qwen", "openai"):
                semantic_text = f"Category: [{category}]. Summary: {summary}. Content: {content}"
            else:
                semantic_text = f"Category: [{category}]. Summary: {summary}. Content: {content}"

            t0     = time.time()
            vector = embed_client.embed(semantic_text)
            embed_ms = int((time.time() - t0) * 1000)

            t1 = time.time()
            _upsertToDatabase(table_name, entry, vector, db_url, db_user, db_pass)
            db_ms = int((time.time() - t1) * 1000)

            logger.debug("   ✅ ID [" + entry.id + "]  embed=" + str(embed_ms)
                         + "ms  db=" + str(db_ms) + "ms")
            success_count += 1

        except Exception as e:
            logger.error("   ❌ ID [" + entry.id + "] failed: " + str(e))

    total_ms = int((time.time() - total_start) * 1000)
    logger.debug("✨ Import complete! success: " + str(success_count) + " / " + str(len(entries))
                 + "  total=" + str(total_ms) + "ms"
                 + "  avg=" + str(total_ms // max(success_count, 1)) + "ms/entry")


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
    vector: List[float],
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

    # Java: 将 double[] 转换为 pgvector 字符串格式 "[v1,v2...]"
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

    conn = psycopg2.connect(host=host, port=port, dbname=dbname,
                             user=db_user, password=db_pass)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (entry.id, entry.category, entry.summary,
                              entry.content, vec_str))
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
