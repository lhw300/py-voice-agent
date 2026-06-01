# session/session_manager.py
#
# Java: package com.lcallai;
#
# Java: import java.util.Map;
# Java: import java.util.concurrent.ConcurrentHashMap;
# Java: import java.util.concurrent.TimeUnit;
# Java: import java.util.concurrent.Executors;
# Java: import java.util.concurrent.ScheduledExecutorService;
import logging                        # Java: import org.apache.logging.log4j.*
import os
import threading                      # Java: ScheduledExecutorService / Runnable
import time                           # Java: System.currentTimeMillis()
from typing import Dict, Optional

# Java: import com.lcallai.handler.*;
# Java: import com.lcallai.intent.*;
from openai import OpenAI              # Java: OkHttpClient — shared HTTP connection pool

import ai_config as AiConfig
from session.model_router      import ModelRouter
from search.rerank_client      import RerankClient
from search.embedding_client   import EmbeddingClient
from intent.intent_classifier  import IntentClassifier, SimpleIntentClassifier

from search.search_service import init as search_init

# ===========================================================================
# LlmClient — mirrors Java interface com.lcallai.LlmClient
#
# Java: public interface LlmClient {
# Java:     String generate(String systemPrompt, String userPrompt);
# Java:     String chat(JSONArray messages);
# Java: }
#
# Java implementations (OllamaClient / OpenAIClient) encapsulate:
#   - the HTTP client (OkHttpClient connection pool)
#   - the model name ("qwen-turbo", "qwen-plus", etc.)
#   - the base URL
#
# IntentClassifier only ever calls llmClient.generate() — it never knows
# which model or endpoint is behind it.  This class is the Python equivalent.
# ===========================================================================
class LlmClient:
    """
    Thin wrapper that encapsulates OpenAI client + model name.
    Mirrors Java OllamaClient / OpenAIClient: model is fixed at construction time,
    not passed per-call.
    """

    # Java: public OllamaClient(String baseUrl, String model, String embedModel,
    # Java:                      OkHttpClient client, String apiKey) { ... }
    def __init__(self, client: OpenAI, model: str):
        self._client = client   # Java: private final OkHttpClient client
        self._model  = model    # Java: private final String model — fixed at construction
        logger.debug(f"LlmClient created: model={model} httpx_client_id={id(client._client)}")

    # Java: public String generate(String systemPrompt, String userPrompt)
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        logger.debug("generate send to AI url=" + str(self._client.base_url) + " model=" + self._model)
        logger.debug("system_prompt=" + system_prompt[:80])
        #logger.debug("user_prompt=" + user_prompt)
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.0,
            top_p=1.0,  # ✅ 新增：配合 temp=0 彻底关闭采样扰动
            max_tokens=256,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content.strip()

    def chat(self, messages: list) -> str:
        logger.debug("chat send to AI url=" + str(self._client.base_url) + " model=" + self._model)
        logger.debug("messages=\n" + str(messages))
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.1,     # ✅ 从 0.7 降到 0.1，平衡自然度+稳定性
            top_p=0.9,           # ✅ 新增：关闭极端采样
            max_tokens=1024,

        )
        return resp.choices[0].message.content.strip()


from intent.intent_dispatcher  import IntentDispatcher
from intent.intent_result      import Intent
from session.chat_session      import ChatSession

from handler.greeting_handler  import GreetingHandler
from handler.query_handler     import QueryHandler
#from handler.filling_handler   import FillingHandler   # INFORM → FillingHandler

# Optional handlers — graceful degradation when not yet implemented
# (mirrors Java: all 7 handlers registered in IntentDispatcher assembly)
try:
    from handler.chitchat_handler  import ChitchatHandler
except ImportError:
    ChitchatHandler = None

try:
    from handler.command_handler   import CommandHandler
except ImportError:
    CommandHandler = None

try:
    from handler.feedback_handler  import FeedbackHandler
except ImportError:
    FeedbackHandler = None

try:
    from handler.ack_handler       import AckHandler
except ImportError:
    AckHandler = None

try:
    from handler.inform_handler    import InformHandler
except ImportError:
    InformHandler = None


# Java: public class SessionManager {

# Java: private static final Logger logger = LogManager.getLogger(SessionManager.class);
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Java: public static String configPath = "d:\\ai";
configPath: str = "."

# Java: private static String G_QUERY_MODE = "retrieveRerank";
G_QUERY_MODE: str = "retrieveRerank"

# Java: private static String GLOBAL_QWEN_KEY = null;
GLOBAL_QWEN_KEY: Optional[str] = None

# Java: // 定义全局变量（默认兜底值）
# Java: private static double G_SIMILARITY = 0.82;
# Java: private static double G_TRUST      = 0.25;
# Java: private static double G_COMP_EMBED = 0.45;
# Java: private static double G_COMP_RERANK = 0.80;
# Java: private static int    G_MAX_RERANK  = 5;
# Java: private static int    G_FINAL_LIMIT = 3;
# Java: private static int    G_RERANK_TIMEOUT = 5;
G_SIMILARITY      = 0.82
G_TRUST           = 0.25
G_COMP_EMBED      = 0.45
G_COMP_RERANK     = 0.80
G_MAX_RERANK      = 5
G_FINAL_LIMIT     = 3
G_RERANK_TIMEOUT  = 5

# Java: // 新增：高级配置参数
# Java: private static double G_RERANK_TRIGGER_MAX = 0.60;
# Java: private static double G_RESCUE_SCORE       = 0.60;
G_RERANK_TRIGGER_MAX = 0.60
G_RESCUE_SCORE       = 0.60

# Java: // 定义全局唯一的 Prompts 和知识库内容
# Java: private static String globalRewritePrompt;
# Java: private static String globalAskPrompt;
# Java: private static String globalRerankPrompt;
# Java: private static String globalFullText;
# Java: private static String globalChitchatPrompt;
# Java: private static String globalClassifyPrompt;
globalRewritePrompt:  Optional[str] = None
globalAskPrompt:      Optional[str] = None
globalRerankPrompt:   Optional[str] = None
globalFullText:       Optional[str] = None
globalChitchatPrompt: Optional[str] = None
globalClassifyPrompt: Optional[str] = None

# Java: private static ModelRouter     ACTIVE_ROUTER = null;
# Java: private static LlmClient       ACTIVE_LLM    = null;
# Java: private static EmbeddingClient ACTIVE_EMBED  = null;
# Java: private static String          ACTIVE_TABLE  = null;
# (RAG/embedding objects not needed at py-voice-agent layer; kept as None placeholders)
ACTIVE_ROUTER = None
ACTIVE_LLM    = None
ACTIVE_EMBED  = None
ACTIVE_TABLE: Optional[str] = None

# Java: public static IntentClassifier ACTIVE_INTENT_CLASSIFIER;
# Java: public static IntentDispatcher ACTIVE_INTENT_DISPATCHER;
ACTIVE_INTENT_CLASSIFIER = None
ACTIVE_INTENT_DISPATCHER = None

# Java: private static final Map<String, ChatSession> sessions = new ConcurrentHashMap<>();
sessions: Dict[str, ChatSession] = {}

# Java: private static final Map<String, Long> lastActiveTime = new ConcurrentHashMap<>();
lastActiveTime: Dict[str, float] = {}

# Java: private static final ScheduledExecutorService cleaner =
# Java:         Executors.newSingleThreadScheduledExecutor();
# → Python: daemon thread started in startAutoCleanup()
_lock = threading.Lock()             # guards sessions + lastActiveTime

# init() guard — not needed in Java (static block runs once); required in Python
_initialized: bool = False

# TTL constants — mirrors Java hardcoded values in cleanExpiredSessions()
# Java: long timeoutMs = 30 * 60 * 1000L;
_SESSION_TTL_SEC      = int(os.environ.get("SESSION_TTL_SEC",      "1800"))  # 30 min
# Java: cleaner.scheduleAtFixedRate(..., 5, 5, TimeUnit.MINUTES)
_CLEANUP_INTERVAL_SEC = int(os.environ.get("CLEANUP_INTERVAL_SEC", "300"))   # 5 min


# ===========================================================================
# Java: public static void init(String configPath) {
# Java:     logger.debug("sessionmanager init ... ");
# Java:     AiConfig.init(configPath);
# Java:     String configType = AiConfig.getStringConfig("system.run.type", "hybrid2");
# Java:     init(configType, configPath);
# Java: }
# ===========================================================================
def init(config_dir: Optional[str] = None) -> None:
    """
    One-arg entry point — reads system.run.type from config, then delegates.
    Mirrors Java: public static void init(String configPath)
    """
    # Java: logger.debug("sessionmanager init ... ");
    logger.debug("sessionmanager init ... ")

    # Java: AiConfig.init(configPath);
    _dir = config_dir or "."
    AiConfig.init(_dir)

    # Java: String configType = AiConfig.getStringConfig("system.run.type", "hybrid2");
    configType = AiConfig.getStringConfig("system.run.type", "hybrid")

    # Java: init(configType, configPath);
    _init_with_type(configType, _dir)


# ===========================================================================
# Java: public static void init(String type, String configPath) {
# Java:     try {
# Java:         logger.debug("📂 [System Init] 正在预加载全局配置文件和知识库...");
# Java:         SessionManager.configPath = configPath;
# Java:         AiConfig.init(configPath);
# Java:
# Java:         // 1. 统一处理根路径格式：将反斜杠替换为正斜杠，确保 Linux 兼容性
# Java:         String base = configPath.replace("\\", "/");
# Java:
# Java:         // 2. 动态拼接：根路径 + 配置文件中的子路径
# Java:         String promptRewritePath = base + AiConfig.getStringConfig("path.prompt.rewrite", "/config/prompt_rewritequery_v1_publish.txt");
# Java:         String promptAskPath     = base + AiConfig.getStringConfig("path.prompt.ask",     "/config/prompt_finalask_v1_publish.txt");
# Java:         String promptRerankPath  = base + AiConfig.getStringConfig("path.prompt.rerank",  "/config/prompt_rerank_v1_publish.txt");
# Java:         String knowledgePath     = base + AiConfig.getStringConfig("path.knowledge",      "/config/knowledge_full.txt");
# Java:         String globalChitchatPromptPath = base + AiConfig.getStringConfig("path.prompt.chitchat", "/config/chitchat_prompt.txt");
# Java:         String globalClassifyPromptPath = base + AiConfig.getStringConfig("path.prompt.classify", "/config/prompt_classify_v1.txt");
# Java:         logger.debug("globalClassifyPromptPath " + globalClassifyPromptPath);
# Java:
# Java:         G_QUERY_MODE = AiConfig.getStringConfig("rag.query.mode", "retrieveRerank");
# Java:
# Java:         // 4. 加载 Prompt 和知识库内容
# Java:         globalRewritePrompt = loadPromptFromFile(promptRewritePath, "");
# Java:         globalAskPrompt     = loadPromptFromFile(promptAskPath, "");
# Java:         globalRerankPrompt  = loadPromptFromFile(promptRerankPath, "");
# Java:         globalFullText      = loadKnowledgeBase(knowledgePath);
# Java:         globalChitchatPrompt = loadPromptFromFile(globalChitchatPromptPath,
# Java:                 "你是一个专业且幽默的智能电话客服。请简要回答用户的闲聊，并引导其咨询规定的业务。");
# Java:         globalClassifyPrompt = loadPromptFromFile(globalClassifyPromptPath, "");
# Java:
# Java:         GLOBAL_QWEN_KEY = AiConfig.getStringConfig("api.key.qwen", System.getenv("QWEN_API_KEY"));
# Java:
# Java:         // ... LLM client assembly (qwen / ollama / hybrid) ...
# Java:
# Java:         // if ("simple".equalsIgnoreCase(G_QUERY_MODE)) {
# Java:         //     intentClassifier = new SimpleIntentClassifier();
# Java:         // } else {
# Java:         //     intentClassifier = new IntentClassifier(ACTIVE_ROUTER.rewriter(), globalClassifyPrompt);
# Java:         // }
# Java:         // ACTIVE_INTENT_CLASSIFIER = intentClassifier;
# Java:
# Java:         // IntentDispatcher intentDispatcher = new IntentDispatcher()
# Java:         //         .register(IntentResult.Intent.QUERY,    new QueryHandler())
# Java:         //         .register(IntentResult.Intent.FEEDBACK, new FeedbackHandler())
# Java:         //         .register(IntentResult.Intent.COMMAND,  new CommandHandler())
# Java:         //         .register(IntentResult.Intent.ACK,      new AckHandler())
# Java:         //         .register(IntentResult.Intent.INFORM,   new InformHandler())
# Java:         //         .register(IntentResult.Intent.GREETING, new GreetingHandler())
# Java:         //         .register(IntentResult.Intent.CHITCHAT, new ChitchatHandler(globalChitchatPrompt));
# Java:         // ACTIVE_INTENT_DISPATCHER = intentDispatcher;
# Java:
# Java:         // startAutoCleanup();
# Java:
# Java:     } catch (Exception e) {
# Java:         logger.error("❌ [System Init] 初始化失败！");
# Java:         throw new RuntimeException("SessionManager 初始化失败", e);
# Java:     }
# Java: }
# ===========================================================================
def _init_with_type(type_: str, config_dir: str) -> None:
    global configPath, G_QUERY_MODE, GLOBAL_QWEN_KEY
    global globalRewritePrompt, globalAskPrompt, globalRerankPrompt
    global globalFullText, globalChitchatPrompt, globalClassifyPrompt
    global ACTIVE_ROUTER, ACTIVE_EMBED, ACTIVE_TABLE
    global ACTIVE_INTENT_CLASSIFIER, ACTIVE_INTENT_DISPATCHER, _initialized

    global G_SIMILARITY, G_TRUST, G_COMP_EMBED, G_COMP_RERANK
    global G_MAX_RERANK, G_FINAL_LIMIT, G_RERANK_TIMEOUT
    global G_RERANK_TRIGGER_MAX, G_RESCUE_SCORE

    if _initialized:
        logger.warning("[SessionManager] init() already called — skipping")
        return









    try:
        logger.debug("📂 [System Init] loading configure files and knowledge base...")

        # Java: SessionManager.configPath = configPath;
        configPath = config_dir

        # Java: AiConfig.init(configPath);
        AiConfig.init(config_dir)

        # Java: String base = configPath.replace("\\", "/");
        base = config_dir.replace("\\", "/")

        # Java: String promptRewritePath = base + AiConfig.getStringConfig(...)
        promptRewritePath  = base + AiConfig.getStringConfig("path.prompt.rewrite",  "/config/prompt_rewritequery_v1_publish.txt")
        promptAskPath      = base + AiConfig.getStringConfig("path.prompt.ask",      "/config/prompt_finalask_v1_publish.txt")
        promptRerankPath   = base + AiConfig.getStringConfig("path.prompt.rerank",   "/config/prompt_rerank_v1_publish.txt")
        knowledgePath      = base + AiConfig.getStringConfig("path.knowledge",       "/config/knowledge_full.txt")
        globalChitchatPath = base + AiConfig.getStringConfig("path.prompt.chitchat", "/config/chitchat_prompt.txt")
        globalClassifyPath = base + AiConfig.getStringConfig("path.prompt.classify", "/config/prompt_classify_v1.txt")

        logger.debug("globalClassifyPromptPath " + globalClassifyPath)

        # Java: G_QUERY_MODE = AiConfig.getStringConfig("rag.query.mode", "retrieveRerank");
        G_QUERY_MODE = AiConfig.getStringConfig("rag.query.mode", "retrieveRerank")

        globalRewritePrompt  = _loadPromptFromFile(promptRewritePath, "")
        globalAskPrompt      = _loadPromptFromFile(promptAskPath, "")
        globalRerankPrompt   = _loadPromptFromFile(promptRerankPath, "")
        globalFullText       = _loadKnowledgeBase(knowledgePath)
        globalChitchatPrompt = _loadPromptFromFile(
            globalChitchatPath,
            "你是一个专业且幽默的智能电话客服。请简要回答用户的闲聊，并引导其咨询规定的业务。"
        )
        globalClassifyPrompt = _loadPromptFromFile(globalClassifyPath, "")


        # =========================================================================
        # 1. 统一加载参数初始化 (Parameter Initialization)
        #    优先从 AiConfig 读取，若无则使用默认值兜底。后续若需针对不同 type 变异，只需修改 conf 文件
        # =========================================================================
        G_SIMILARITY         = AiConfig.getDoubleConfig("rag.threshold.similarity", 0.82)
        G_TRUST              = AiConfig.getDoubleConfig("rag.threshold.trust", 0.25)
        G_COMP_EMBED         = AiConfig.getDoubleConfig("rag.threshold.comp_embed", 0.45)
        G_COMP_RERANK        = AiConfig.getDoubleConfig("rag.threshold.comp_rerank", 0.80)

        # 🌟 新增：动态加载粗排过滤防线与补偿机制参数
        G_RERANK_TRIGGER_MAX = AiConfig.getDoubleConfig("rag.threshold.rerank_trigger_max", 0.60)
        G_RESCUE_SCORE       = AiConfig.getDoubleConfig("rag.threshold.rescue_score", 0.60)

        G_MAX_RERANK         = AiConfig.getIntConfig("rag.limit.max_rerank", 5)
        G_FINAL_LIMIT        = AiConfig.getIntConfig("rag.limit.final_limit", 3)
        G_RERANK_TIMEOUT     = AiConfig.getIntConfig("rag.timeout.rerank", 5)

        logger.info(f"📊 parameters inited OK: SIMILARITY={G_SIMILARITY}, RERANK_TRIGGER_MAX={G_RERANK_TRIGGER_MAX}, RESCUE_SCORE={G_RESCUE_SCORE}")






        # ── LLM client assembly — 4 types ────────────────────────────────────
        # Java: if (type.equalsIgnoreCase("qwen"))   { ... }
        # Java: else if (type.equalsIgnoreCase("hybrid")) { ... }
        # Java: else if (type.equalsIgnoreCase("openai")) { ... }
        # Java: else if (type.equalsIgnoreCase("simple")) { ... }
        # Java: else { throw new IllegalArgumentException("不支持的大模型类型: " + type); }

        ALIYUN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        #ALIYUN_BASE_URL = "https://dashscope-us.aliyuncs.com/compatible-mode/v1"

        OPENAI_BASE_URL = "https://api.openai.com/v1"

        if type_.lower() == "qwen":
            # Full cloud — Alibaba DashScope
            # rewriter: qwen-turbo  finalLlm: qwen-plus  rerank: qwen-turbo(LLM)  embed: cloud
            GLOBAL_QWEN_KEY = AiConfig.getStringConfig(
                "api.key.qwen", os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY") or ""
            )
            if not GLOBAL_QWEN_KEY:
                raise RuntimeError("❌ type=qwen not set api.key.qwen / DASHSCOPE_API_KEY")
            logger.debug("DEBUG:   QWEN_API_KEY len = " + str(len(GLOBAL_QWEN_KEY)))

            _client     = OpenAI(api_key=GLOBAL_QWEN_KEY, base_url=ALIYUN_BASE_URL)
            turboClient = LlmClient(_client, model="qwen-plus")
            plusClient  = LlmClient(_client, model="qwen-plus")

            # rerank: LLM-based (turboClient), no local CrossEncoder
            ACTIVE_ROUTER = ModelRouter(turboClient, turboClient, plusClient)
            ACTIVE_EMBED  = None   # cloud embed via DashScope — RAG to be wired via SearchService
            ACTIVE_TABLE  = AiConfig.getStringConfig("db.postgres.table.online", "enterprise_knowledge_qwen_1024")

        elif type_.lower() == "hybrid-qwen":
            # Cloud LLM + local rerank/embed (recommended for production)
            # rewriter: qwen-turbo  finalLlm: qwen-plus  rerank: local CrossEncoder  embed: local ST
            GLOBAL_QWEN_KEY = AiConfig.getStringConfig(
                "api.key.qwen", os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY") or ""
            )
            if not GLOBAL_QWEN_KEY:
                raise RuntimeError("❌ type=hybrid not set api.key.qwen / DASHSCOPE_API_KEY")
            logger.debug("DEBUG: read QWEN_API_KEY len = " + str(len(GLOBAL_QWEN_KEY)))

            _client     = OpenAI(api_key=GLOBAL_QWEN_KEY, base_url=ALIYUN_BASE_URL)
            turboClient = LlmClient(_client, model="qwen-turbo")
            plusClient  = LlmClient(_client, model="qwen-plus")

            # Java: DJLLocalClient reranker = new DJLLocalClient();
            rerank_name = AiConfig.getStringConfig("djl.model.rerank.name", "bge-reranker-v2-m3")
            rerank_path = base.rstrip("/") + "/" + rerank_name
            reranker    = RerankClient(rerank_path)

            ACTIVE_ROUTER = ModelRouter(turboClient, reranker, plusClient)

            # Java: ACTIVE_EMBED = new DJLLocalClient(); (local sentence-transformers)
            embed_name  = AiConfig.getStringConfig("djl.model.embed.name", "text2vec-base-chinese-paraphrase-pt")
            embed_path  = base.rstrip("/") + "/" + embed_name
            ACTIVE_EMBED = EmbeddingClient(embed_path)
            ACTIVE_TABLE = AiConfig.getStringConfig(
                "db.postgres.table.online",
                "enterprise_knowledge_" + ("768" if ACTIVE_EMBED.getDimension() == 768 else "qwen_1024")
            )

        elif type_.lower() == "hybrid-openai":
            # Cloud LLM (OpenAI) + local rerank/embed
            # intent/rewriter: gpt-4o-mini   finalLlm: gpt-4o
            # rerank: local CrossEncoder      embed: local SentenceTransformer
            openai_key = AiConfig.getStringConfig(
                "api.key.openai", os.environ.get("OPENAI_API_KEY") or ""
            )
            if not openai_key:
                raise RuntimeError("❌ type=hybrid-openai requires api.key.openai / OPENAI_API_KEY")
            logger.debug("DEBUG: OPENAI_API_KEY length = " + str(len(openai_key)))

            _client    = OpenAI(api_key=openai_key, base_url=OPENAI_BASE_URL)
            miniClient = LlmClient(_client, model="gpt-4.1-mini")   # intent classifier + rewriter
            gpt4oClient= LlmClient(_client, model="gpt-4o")        # final answer

            # local rerank — same as hybrid
            rerank_name = AiConfig.getStringConfig("djl.model.rerank.name", "bge-reranker-v2-m3")
            rerank_path = base.rstrip("/") + "/" + rerank_name
            reranker    = RerankClient(rerank_path)

            ACTIVE_ROUTER = ModelRouter(miniClient, reranker, gpt4oClient)

            # local embed — same as hybrid
            embed_name   = AiConfig.getStringConfig("djl.model.embed.name", "bge-large-zh-v1.5")
            embed_path   = base.rstrip("/") + "/" + embed_name
            ACTIVE_EMBED = EmbeddingClient(embed_path)
            ACTIVE_TABLE = AiConfig.getStringConfig(
                "db.postgres.table.online",
                "enterprise_knowledge_" + ("768" if ACTIVE_EMBED.getDimension() == 768 else "1024")
            )
        elif type_.lower() == "openai":
            # Full cloud — OpenAI
            # rewriter: gpt-4o-mini  finalLlm: gpt-4o  rerank: gpt-4o-mini(LLM)  embed: text-embedding-3-small
            openai_key = AiConfig.getStringConfig(
                "api.key.openai", os.environ.get("OPENAI_API_KEY") or ""
            )
            if not openai_key:
                raise RuntimeError("❌ type=openai not set api.key.openai / OPENAI_API_KEY")

            _client    = OpenAI(api_key=openai_key, base_url=OPENAI_BASE_URL)
            miniClient = LlmClient(_client, model="gpt-4o-mini")
            gpt4oClient= LlmClient(_client, model="gpt-4o")

            # rerank: LLM-based (miniClient), no local CrossEncoder
            ACTIVE_ROUTER = ModelRouter(miniClient, miniClient, gpt4oClient)
            ACTIVE_EMBED  = None   # cloud embed — text-embedding-3-small (1536-dim)
            ACTIVE_TABLE  = AiConfig.getStringConfig("db.postgres.table.online", "enterprise_knowledge_openai_1536")

        elif type_.lower() == "simple":
            # No LLM — all input treated as QUERY, used for slot-filling / debug
            ACTIVE_ROUTER = None
            ACTIVE_EMBED  = None
            ACTIVE_TABLE  = None
            logger.debug("✅ [System Init] type=simple — LLM skipped")

        else:
            raise ValueError("unsupported models: " + type_ + "  support: qwen / hybrid / openai / simple")
        search_init()
        logger.debug("✅ [System Init] global resource type=" + type_)

        # ── Intent classifier assembly ────────────────────────────────────────
        # Java: if ("simple".equalsIgnoreCase(G_QUERY_MODE)) {
        # Java:     intentClassifier = new SimpleIntentClassifier();
        # Java: } else {
        # Java:     intentClassifier = new IntentClassifier(ACTIVE_ROUTER.rewriter(), globalClassifyPrompt);
        # Java: }
        if type_.lower() == "simple" or G_QUERY_MODE.lower() == "simple":
            ACTIVE_INTENT_CLASSIFIER = SimpleIntentClassifier()
            logger.debug("SimpleIntentClassifier activated — all input treated as QUERY")
        else:
            # Java: new IntentClassifier(ACTIVE_ROUTER.rewriter(), globalClassifyPrompt)
            ACTIVE_INTENT_CLASSIFIER = IntentClassifier(ACTIVE_ROUTER.rewriter(), system_prompt=globalClassifyPrompt)

        # ── IntentDispatcher assembly ─────────────────────────────────────────
        # Java: IntentDispatcher intentDispatcher = new IntentDispatcher()
        # Java:         .register(IntentResult.Intent.QUERY,    new QueryHandler())
        # Java:         .register(IntentResult.Intent.FEEDBACK, new FeedbackHandler())
        # Java:         .register(IntentResult.Intent.COMMAND,  new CommandHandler())
        # Java:         .register(IntentResult.Intent.ACK,      new AckHandler())
        # Java:         .register(IntentResult.Intent.INFORM,   new InformHandler())
        # Java:         .register(IntentResult.Intent.GREETING, new GreetingHandler())
        # Java:         .register(IntentResult.Intent.CHITCHAT, new ChitchatHandler(globalChitchatPrompt));
        intentDispatcher = IntentDispatcher()
        intentDispatcher.register(Intent.QUERY,    QueryHandler())
        intentDispatcher.register(Intent.FEEDBACK, FeedbackHandler())
        intentDispatcher.register(Intent.COMMAND,  CommandHandler())
        intentDispatcher.register(Intent.ACK,      AckHandler())
        intentDispatcher.register(Intent.INFORM,   InformHandler())
        intentDispatcher.register(Intent.GREETING, GreetingHandler())
        intentDispatcher.register(Intent.CHITCHAT, ChitchatHandler(globalChitchatPrompt))
        ACTIVE_INTENT_DISPATCHER = intentDispatcher

        # Java: startAutoCleanup();
        startAutoCleanup()

        _initialized = True

    except Exception as e:
        logger.error("❌ [System Init] inited failed！")
        logger.error("", exc_info=True)
        raise RuntimeError("SessionManager inited failed") from e


# ===========================================================================
# Java: public static ChatSession getSession(String clientId) {
# Java:     // 增加一道安全防线：防止忘记调用 init()
# Java:     if (ACTIVE_ROUTER == null) {
# Java:         throw new IllegalStateException("大模型客户端尚未初始化！...");
# Java:     }
# Java:     ChatSession session = sessions.get(clientId);
# Java:     if (session == null) {
# Java:         session = new ChatSession(ACTIVE_ROUTER, ACTIVE_EMBED, ACTIVE_TABLE);
# Java:         session.setSessionId(clientId);
# Java:         session.setThresholds(...);
# Java:         session.setFulltext(globalFullText);
# Java:         session.setRewrite_prompt(globalRewritePrompt);
# Java:         session.setAsk_prompt(globalAskPrompt);
# Java:         session.setRerankSys_prompt(globalRerankPrompt);
# Java:         session.setQueryMode(G_QUERY_MODE);
# Java:         session.setIntentPipeline(ACTIVE_INTENT_CLASSIFIER, ACTIVE_INTENT_DISPATCHER);
# Java:         sessions.put(clientId, session);
# Java:         logger.debug("为客户端 [ sn=" + clientId + "] 创建了新会话...");
# Java:     }
# Java:     lastActiveTime.put(clientId, System.currentTimeMillis());
# Java:     return session;
# Java: }
# ===========================================================================
def get_session(session_id: str) -> ChatSession:
    # Java: if (ACTIVE_ROUTER == null) throw new IllegalStateException(...)
    if not _initialized:
        raise RuntimeError(
            "models client not inited！use session_manager.init()"
        )

    with _lock:
        # Java: ChatSession session = sessions.get(clientId);
        # Java: if (session == null) {
        if session_id not in sessions:
            # Java: session = new ChatSession(ACTIVE_ROUTER, ACTIVE_EMBED, ACTIVE_TABLE);
            session = ChatSession(session_id)

            # Java: session.setSessionId(clientId);
            # (session_id already stored in constructor)

            # Java: session.setThresholds(G_SIMILARITY, G_TRUST, G_COMP_EMBED, G_COMP_RERANK);
            session.setThresholds(G_SIMILARITY, G_TRUST, G_COMP_EMBED, G_COMP_RERANK)

            # Java: session.setAdvancedThresholds(G_RERANK_TRIGGER_MAX, G_RESCUE_SCORE);
            session.setAdvancedThresholds(G_RERANK_TRIGGER_MAX, G_RESCUE_SCORE)

            # Java: session.setTopK(G_MAX_RERANK, G_FINAL_LIMIT, G_RERANK_TIMEOUT);
            session.setTopK(G_MAX_RERANK, G_FINAL_LIMIT, G_RERANK_TIMEOUT)

            # Java: session.setFulltext(globalFullText);
            session.setFulltext(globalFullText)

            # Java: session.setRewrite_prompt(globalRewritePrompt);
            session.setRewrite_prompt(globalRewritePrompt)

            # Java: session.setAsk_prompt(globalAskPrompt);
            session.setAsk_prompt(globalAskPrompt)

            # Java: session.setRerankSys_prompt(globalRerankPrompt);
            session.setRerankSys_prompt(globalRerankPrompt)
            if ACTIVE_ROUTER:
                ACTIVE_ROUTER.setRerankPrompt(globalRerankPrompt)

            # Java: session.setQueryMode(G_QUERY_MODE);
            session.setQueryMode(G_QUERY_MODE)

            # Java: inject router and embed into session
            session.router          = ACTIVE_ROUTER
            session.embeddingClient = ACTIVE_EMBED
            session.tableName       = ACTIVE_TABLE

            # Java: session.setIntentPipeline(ACTIVE_INTENT_CLASSIFIER, ACTIVE_INTENT_DISPATCHER);
            session.set_intent_pipeline(ACTIVE_INTENT_CLASSIFIER, ACTIVE_INTENT_DISPATCHER)

            # Java: sessions.put(clientId, session);
            sessions[session_id] = session

            # Java: logger.debug("为客户端 [ sn=" + clientId + "] 创建了新会话...");
            logger.debug("session [ sn=" + session_id + "] created, injected global Prompt and knowledge")

        # Java: lastActiveTime.put(clientId, System.currentTimeMillis());
        lastActiveTime[session_id] = time.time()

    # Java: return session;
    return sessions[session_id]


# ===========================================================================
# Java: public static void startAutoCleanup() {
# Java:     cleaner.scheduleAtFixedRate(
# Java:             SessionManager::cleanExpiredSessions,
# Java:             5, 5, TimeUnit.MINUTES
# Java:     );
# Java: }
# ===========================================================================
def startAutoCleanup() -> None:
    def _loop() -> None:
        # Java: scheduleAtFixedRate — fires every 5 minutes
        while True:
            time.sleep(_CLEANUP_INTERVAL_SEC)
            _cleanExpiredSessions()

    t = threading.Thread(target=_loop, daemon=True, name="session-cleanup")
    t.start()


# ===========================================================================
# Java: private static void cleanExpiredSessions() {
# Java:     long now = System.currentTimeMillis();
# Java:     long timeoutMs = 30 * 60 * 1000L;
# Java:     for (String clientId : sessions.keySet()) {
# Java:         Long lastActive = lastActiveTime.get(clientId);
# Java:         if (lastActive == null) continue;
# Java:         if (now - lastActive > timeoutMs) {
# Java:             removeSession(clientId);
# Java:             lastActiveTime.remove(clientId);
# Java:             logger.info("⏰ 会话 [{}] 超时30分钟，已自动销毁", clientId);
# Java:         }
# Java:     }
# Java: }
# ===========================================================================
def _cleanExpiredSessions() -> None:
    # Java: long now = System.currentTimeMillis();
    now = time.time()

    # Java: long timeoutMs = 30 * 60 * 1000L;
    # → _SESSION_TTL_SEC

    # Java: for (String clientId : sessions.keySet()) {
    expired = []
    for clientId, lastActive in list(lastActiveTime.items()):
        # Java: Long lastActive = lastActiveTime.get(clientId);
        # Java: if (lastActive == null) continue;
        if lastActive is None:
            continue
        # Java: if (now - lastActive > timeoutMs) {
        if (now - lastActive) > _SESSION_TTL_SEC:
            expired.append(clientId)

    for clientId in expired:
        # Java: removeSession(clientId);
        removeSession(clientId)
        # Java: lastActiveTime.remove(clientId);
        lastActiveTime.pop(clientId, None)
        # Java: logger.info("⏰ 会话 [{}] 超时30分钟，已自动销毁", clientId);
        logger.info(f"⏰ 会话 [{clientId}] 超时30分钟，已自动销毁")


# ===========================================================================
# Java: public static void removeSession(String clientId) {
# Java:     ChatSession session = sessions.remove(clientId);
# Java:     if (session != null) {
# Java:         session.close();
# Java:         logger.debug("🗑️ 会话 [" + clientId + "] 已从管理器中移除。");
# Java:     }
# Java: }
# ===========================================================================
def removeSession(session_id: str) -> None:
    with _lock:
        # Java: ChatSession session = sessions.remove(clientId);
        session = sessions.pop(session_id, None)
        lastActiveTime.pop(session_id, None)

    # Java: if (session != null) {
    if session is not None:
        # Java: session.close();
        if hasattr(session, "close"):
            session.close()
        # Java: logger.debug("🗑️ 会话 [" + clientId + "] 已从管理器中移除。");
        logger.debug(f"🗑️ 会话 [{session_id}] 已从管理器中移除。")


# ===========================================================================
# Java: public static void clearAllSessions() {
# Java:     logger.debug("🧹 正在清理所有历史会话...");
# Java:     for (ChatSession session : sessions.values()) {
# Java:         session.close();
# Java:     }
# Java:     sessions.clear();
# Java:     ChatSession.shutdownExecutor();
# Java: }
# ===========================================================================
def clearAllSessions() -> None:
    # Java: logger.debug("🧹 正在清理所有历史会话...");
    logger.debug("🧹 正在清理所有历史会话...")
    with _lock:
        # Java: for (ChatSession session : sessions.values()) { session.close(); }
        for session in sessions.values():
            if hasattr(session, "close"):
                session.close()
        # Java: sessions.clear();
        sessions.clear()
        lastActiveTime.clear()


# ===========================================================================
# Java: private static String loadPromptFromFile(String filePath, String defaultValue) {
# Java:     try {
# Java:         String content = new String(Files.readAllBytes(Paths.get(filePath)), UTF_8);
# Java:         // strip /* */ block comments
# Java:         content = content.replaceAll("(?s)/\\*.*?\\*/", "");
# Java:         // strip // line comments
# Java:         content = content.replaceAll("//.*", "");
# Java:         // strip blank lines
# Java:         content = content.replaceAll("(?m)^\\s*\\n", "");
# Java:         return content.trim();
# Java:     } catch (Exception e) {
# Java:         logger.error("⚠️ 警告：无法从 " + filePath + " 读取配置，将使用默认 Prompt。原因: " + e.getMessage());
# Java:         return defaultValue;
# Java:     }
# Java: }
# ===========================================================================
def _loadPromptFromFile(filePath: str, defaultValue: str) -> str:
    try:
        with open(filePath, "r", encoding="utf-8") as f:
            # Java: String content = new String(Files.readAllBytes(...), UTF_8);
            content = f.read()

        # Java: content = content.replaceAll("(?s)/\\*.*?\\*/", "");
        content = re.sub(r"(?s)/\*.*?\*/", "", content)

        # Java: content = content.replaceAll("//.*", "");
        content = re.sub(r"//.*", "", content)

        # Java: content = content.replaceAll("(?m)^\\s*\\n", "");
        content = re.sub(r"(?m)^\s*\n", "", content)

        return content.strip()

    # Java: } catch (Exception e) {
    except Exception as e:
        # Java: logger.error("⚠️ 警告：无法从 " + filePath + " 读取配置，将使用默认 Prompt。原因: ...");
        logger.error(f"⚠️ 警告：无法从 {filePath} 读取配置，将使用默认 Prompt。原因: {e}")
        # Java: return defaultValue;
        return defaultValue

def warm_up() -> None:
    """
    Mirrors Java: public static void warmUp()
    Warms up the full pipeline: rewriter + rerank + finalLlm + embed.
    Call after init() and before the first real request.
    """
    if not AiConfig.getStringConfig("system.warmup.enabled", "true").lower() == "true":
        logger.debug("skip warmup: system.warmup.enabled=false")
        return

    if ACTIVE_ROUTER is None or ACTIVE_EMBED is None:
        logger.debug("⚠️ warm_up skipped: model clients not yet initialized.")
        return

    logger.debug("⏳ Starting full pipeline warm-up (rewriter + rerank + finalLlm + embed)...")
    import time as _time
    total_start = _time.time()

    try:
        t = _time.time()
        ACTIVE_ROUTER.rewriter().generate("Output json.", "respond with json: {\"ok\":1}")
        logger.debug("✅ rewriter warm-up done  t=" + str(int((_time.time() - t) * 1000)) + " ms")
    except Exception as e:
        logger.error("⚠️ rewriter warm-up failed: " + str(e))

    try:
        t = _time.time()
        ACTIVE_ROUTER.rerank("Beijing", "Beijing is the capital of China.")
        logger.debug("✅ rerank warm-up done    t=" + str(int((_time.time() - t) * 1000)) + " ms")
    except Exception as e:
        logger.error("⚠️ rerank warm-up failed: " + str(e))

    try:
        t = _time.time()
        ACTIVE_ROUTER.finalLlm().generate("Output json.", "respond with json: {\"ok\":1}")
        logger.debug("✅ finalLlm warm-up done  t=" + str(int((_time.time() - t) * 1000)) + " ms")
    except Exception as e:
        logger.error("⚠️ finalLlm warm-up failed: " + str(e))

    try:
        t = _time.time()
        ACTIVE_EMBED.embed("hello")
        logger.debug("✅ embed warm-up done     t=" + str(int((_time.time() - t) * 1000)) + " ms")
    except Exception as e:
        logger.error("⚠️ embed warm-up failed: " + str(e))

    logger.debug("✅ full pipeline warm-up complete  total=" + str(int((_time.time() - total_start) * 1000)) + " ms")
# ===========================================================================
# Java: private static String loadKnowledgeBase(String filePath) {
# Java:     try {
# Java:         File file = new File(filePath);
# Java:         if (!file.exists()) {
# Java:             logger.error("❌ 知识库文件不存在: " + filePath);
# Java:             return "";
# Java:         }
# Java:         // 1. 显式按字节读取，防止受 JVM 默认编码 (GBK) 干扰
# Java:         byte[] bytes = Files.readAllBytes(Paths.get(filePath));
# Java:         // 2. 转换为 UTF-8 字符串
# Java:         String content = new String(bytes, StandardCharsets.UTF_8);
# Java:         // 3. 处理 UTF-8 BOM (\uFEFF)
# Java:         if (content.length() > 0 && content.charAt(0) == '\uFEFF') {
# Java:             content = content.substring(1);
# Java:         }
# Java:         logger.debug("📚 知识库加载成功: " + filePath + " (长度: " + content.length() + " 字符)");
# Java:         return content.trim();
# Java:     } catch (IOException e) {
# Java:         logger.error("💥 加载知识库时发生 I/O 异常: " + e.getMessage());
# Java:         return "";
# Java:     } catch (Exception e) {
# Java:         logger.error("💥 加载知识库时发生未知错误: " + e.getMessage());
# Java:         return "";
# Java:     }
# Java: }
# ===========================================================================
def _loadKnowledgeBase(filePath: str) -> str:
    # Java: File file = new File(filePath); if (!file.exists()) { ... return ""; }
    if not os.path.exists(filePath):
        logger.error("❌ 知识库文件不存在: " + filePath)
        return ""

    try:
        # Java: byte[] bytes = Files.readAllBytes(Paths.get(filePath));
        with open(filePath, "rb") as f:
            raw = f.read()

        # Java: String content = new String(bytes, StandardCharsets.UTF_8);
        content = raw.decode("utf-8")

        # Java: if (content.length() > 0 && content.charAt(0) == '\uFEFF') content = content.substring(1);
        if content.startswith("\uFEFF"):
            content = content[1:]

        # Java: logger.debug("📚 knowledge loaded OK: " + filePath + " (len: " + content.length() + " )");
        logger.debug(f"📚 knowledge loaded OK: {filePath} (len: {len(content)} )")
        # Java: return content.trim();
        return content.strip()

    # Java: } catch (IOException e) {
    except IOError as e:
        # Java: logger.error("💥 加载知识库时发生 I/O 异常: " + e.getMessage());
        logger.error("💥 knowledge loaded I/O error: " + str(e))
        return ""
    # Java: } catch (Exception e) {
    except Exception as e:
        # Java: logger.error("💥 加载知识库时发生未知错误: " + e.getMessage());
        logger.error("💥 knowledge loaded error: " + str(e))
        return ""


# re import needed for _loadPromptFromFile
import re  # noqa: E402 — placed here to mirror Java's import-at-top; move to top in final file