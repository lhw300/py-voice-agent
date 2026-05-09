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

from config.ai_config import AiConfig

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
    # Java: AiConfig.init(baseDir);
    base_dir = base_dir.replace("\\", "/").rstrip("/")
    AiConfig.init(base_dir)

    # Java: String storageType = AiConfig.getStringConfig("storage.type", "lucene");
    storage_type = AiConfig.getStringConfig("storage.type", "online")

    # Java: String rawFilePath = AiConfig.getStringConfig("path.knowledge", "config/publishknowledge.txt");
    raw_file_path = AiConfig.getStringConfig("path.knowledge", "config/publishknowledge.txt")

    # Java: String filePath = Paths.get(baseDir, rawFilePath).toString();
    file_path = str(Path(base_dir) / raw_file_path)

    # DB connection params from AiConfig
    db_url  = AiConfig.getStringConfig("db.postgres.url",      "jdbc:postgresql://localhost:5432/postgres")
    db_user = AiConfig.getStringConfig("db.postgres.user",     "postgres")
    db_pass = AiConfig.getStringConfig("db.postgres.password", "call")

    logger.debug("🚀 启动知识库导入流水线...storageType " + storage_type + " filePath " + file_path)

    # Java: EmbeddingClient embedClient = SessionManager.createQwenTurboClient();
    # Python: use EmbeddingClient (local) or cloud embed via LlmClient
    embed_client = _create_embed_client(base_dir)

    # Java: tableName = "enterprise_knowledge_" + (dim == 768 ? "768" : "qwen_1024");
    dim        = embed_client.getDimension()
    table_name = "enterprise_knowledge_" + ("768" if dim == 768 else "qwen_1024")
    logger.debug("🚀 模式: " + storage_type + " | 维度: " + str(dim) + " | 表名: " + table_name)

    # Java: 根据后缀名选择读取办法
    if file_path.lower().endswith(".txt"):
        entries = _readFromTxt(file_path)
    elif file_path.lower().endswith((".xlsx", ".xls")):
        entries = _readFromExcel(file_path)
    else:
        logger.error("❌ 不支持的文件格式，仅限 .txt 或 .xlsx")
        return

    logger.debug("📂 正在解析文件: " + file_path + "，共 " + str(len(entries)) + " 条")

    success_count = 0
    for i, entry in enumerate(entries):
        # Java: if ("ID".equalsIgnoreCase(entry.id)) continue;
        if entry.id.upper() == "ID":
            continue

        # Java: 截断保护与数据清洗
        raw_category = entry.category.strip() if entry.category else "未分类"
        raw_summary  = entry.summary.strip()  if entry.summary  else "无摘要"
        content      = entry.content.strip()  if entry.content  else ""

        if not content:
            logger.debug("⚠️ 第 " + str(i + 1) + " 条记录内容为空，已跳过")
            continue

        # Java: category = rawCategory.length() > 50 ? rawCategory.substring(0, 50) : rawCategory;
        category = raw_category[:50]
        summary  = raw_summary[:255]

        logger.debug("--------------------------------------------------")
        logger.debug("🔍 正在处理第 " + str(i + 1) + " 条数据:")
        logger.debug("   [分类]: " + category)
        logger.debug("   [摘要]: " + summary)
        logger.debug("   [内容长度]: " + str(len(content)) + " 字")

        try:
            # Java: String semanticText = String.format("分类：【%s】。摘要：%s。内容：%s", ...)
            semantic_text = "分类：【" + category + "】。摘要：" + summary + "。内容：" + content

            # Java: double[] vector = embedClient.embed(semanticText);
            vector = embed_client.embed(semantic_text)

            # Java: upsertToDatabase(tableName, entry, vector);
            _upsertToDatabase(table_name, entry, vector, db_url, db_user, db_pass)

            logger.debug("   ✅ ID [" + entry.id + "] 处理成功 (Insert/Update)")
            success_count += 1

        except Exception as e:
            logger.error("   ❌ ID [" + entry.id + "] 失败: " + str(e))

    logger.debug("✨ 导入完成！共成功处理 " + str(success_count) + " 条知识。")


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
    """Build EmbeddingClient from AiConfig — mirrors SessionManager.createQwenTurboClient() logic."""
    from search.embedding_client import EmbeddingClient
    embed_name = AiConfig.getStringConfig("djl.model.embed.name",
                                          "text2vec-base-chinese-paraphrase-pt")
    model_path = str(Path(base_dir) / embed_name)
    return EmbeddingClient(model_path)


# ---------------------------------------------------------------------------
# Entry point — mirrors Java main(String[] args)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s %(levelname)s %(message)s")
    base = sys.argv[1] if len(sys.argv) > 1 else "e:\\ai"
    run(base)
