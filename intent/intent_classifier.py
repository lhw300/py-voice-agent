# intent/intent_classifier.py
#
# Java: package com.lcallai.intent;
#
# Java: import com.fasterxml.jackson.databind.JsonNode;
# Java: import com.fasterxml.jackson.databind.ObjectMapper;
# Java: import com.lcallai.LlmClient;
# Java: import com.lcallai.ChatHistory;
import json                           # Java: ObjectMapper / JsonNode
import logging                        # Java: import org.apache.logging.log4j.*
import os
import re
from typing import List, Optional

from openai import OpenAI             # Java: LlmClient  (cloud impl) — used by SessionManager to build the client

from intent.intent_result import Intent, IntentResult, Sentiment

# Java: private static final Logger logger = LogManager.getLogger(IntentClassifier.class);
logger = logging.getLogger(__name__)

# Java: /**
# Java:  * 意图分类器
# Java:  * 职责：调用轻量 LLM（建议 turbo 级），将用户输入解析为标准化 IntentResult。
# Java:  * 设计原则：
# Java:  *   - 解析失败时始终降级为 QUERY，确保主流程不中断
# Java:  *   - 历史上下文只取最近 N 条，降低 Token 成本
# Java:  *   - JSON 解析容错：兼容带 ```json``` 包装的模型输出
# Java:  */


# Java: private static final ObjectMapper MAPPER = new ObjectMapper();
#   → replaced by json.loads() / re.sub() inline — no separate constant needed

# Java: // 只使用最近 N 条历史（3 轮 = 6 条：3 User + 3 Context）
# Java: private static final int HISTORY_WINDOW = 16;
HISTORY_WINDOW = 16

# ---------------------------------------------------------------------------
# Java: private static final String SYSTEM_PROMPT = """...""";
# Hard-coded fallback — used when the external prompt file fails to load.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
你是一个对话意图分类器，只输出合法 JSON，禁止输出任何额外文字或 Markdown 标记。

intent 枚举值（必须且只能是以下之一）：
[QUERY, COMMAND, INFORM, FEEDBACK, ACK, GREETING, CHITCHAT]

输出字段规则：
1. intent      (string)      必填，枚举值之一
2. sub_intent  (string|null) 仅 ACK 时必填：affirm（肯定）/ negate（否定）/ ack（普通确认）
3. sentiment   (string|null) 仅 FEEDBACK 时必填：positive / negative
4. refined_query (string)    必填：
   - QUERY：完成指代补全 + 检索优化后输出最终问句
   - 其他 intent：直接返回用户原始输入，不做任何修改
5. action_code (string|null) 仅 COMMAND 时必填，枚举值之一：
   ACTION_REPLAY / ACTION_TRANSFER / ACTION_VOL_UP / ACTION_VOL_DOWN / ACTION_HANGUP
6. category    (string|null) 用户身份（老师/学生/管理员），无法确定时为 null

判定示例：
输入"好的"      → {"intent":"ACK","sub_intent":"ack","sentiment":null,"refined_query":"好的","action_code":null,"category":null}
输入"这软件太卡" → {"intent":"FEEDBACK","sub_intent":null,"sentiment":"negative","refined_query":"这软件太卡","action_code":null,"category":null}
输入"再见"      → {"intent":"COMMAND","sub_intent":null,"sentiment":null,"refined_query":"再见","action_code":"ACTION_HANGUP","category":null}
"""


# ===========================================================================
# Java: public class IntentClassifier {
# ===========================================================================
class IntentClassifier:

    # Java: // 原来的单参数构造保留作兜底（使用硬编码默认值）
    # Java: public IntentClassifier(LlmClient llmClient) {
    # Java:     this(llmClient, null);
    # Java: }
    #
    # Java: // 新增：支持外部注入 prompt
    # Java: public IntentClassifier(LlmClient llmClient, String systemPrompt) {
    # Java:     this.llmClient = llmClient;
    # Java:     this.systemPrompt = (systemPrompt != null && !systemPrompt.isBlank())
    # Java:             ? systemPrompt
    # Java:             : SYSTEM_PROMPT; // 兜底，防止文件加载失败时系统崩溃
    # Java: }
    def __init__(
        self,
        llmClient,                                 # Java: LlmClient llmClient — injected by SessionManager
        system_prompt: Optional[str] = None,       # Java: String systemPrompt
        # NOTE: no model param here — model name is fixed inside llmClient,
        # just as Java's LlmClient implementation encapsulates the model name.
    ):
        # Java: this.llmClient = llmClient;
        self.llmClient = llmClient

        # Java: this.systemPrompt = (systemPrompt != null && !systemPrompt.isBlank())
        # Java:         ? systemPrompt
        # Java:         : SYSTEM_PROMPT;
        self.systemPrompt = (
            system_prompt.strip()
            if (system_prompt and system_prompt.strip())
            else SYSTEM_PROMPT
        )

        logger.info("[IntentClassifier] initialized")

    # -----------------------------------------------------------------------
    # Java: /**
    # Java:  * 对用户输入进行意图分类
    # Java:  * @param userText 用户当前输入
    # Java:  * @param history  当前会话的查询历史（用于指代词消解）
    # Java:  * @return 标准化的 IntentResult，解析失败时降级为 QUERY
    # Java:  */
    # Java: public IntentResult classify(String userText, ChatHistory history) {
    # Java:     try {
    # Java:         String historyCtx = history.toPlainText(HISTORY_WINDOW);
    # Java:         String userPrompt = historyCtx == null || historyCtx.isBlank()
    # Java:                 ? "用户输入：" + userText
    # Java:                 : "对话历史：\n" + historyCtx + "\n\n用户最新输入：" + userText;
    # Java:         logger.debug("[IntentClassifier] 原始输入: " + userPrompt);
    # Java:         String raw = llmClient.generate(this.systemPrompt, userPrompt);
    # Java:         logger.debug("[IntentClassifier] 原始输出: " + raw);
    # Java:         return parse(raw, userText);
    # Java:     } catch (Exception e) {
    # Java:         logger.error("[IntentClassifier] 分类异常，降级为 QUERY: " + e.getMessage());
    # Java:         return fallback(userText);
    # Java:     }
    # Java: }
    def classify(
        self,
        userText: str,
        history: Optional[List[dict]] = None,      # Java: ChatHistory history
    ) -> IntentResult:
        try:
            # Java: String historyCtx = history.toPlainText(HISTORY_WINDOW);
            historyCtx = self._toPlainText(history, HISTORY_WINDOW)

            # Java: String userPrompt = historyCtx == null || historyCtx.isBlank()
            # Java:         ? "用户输入：" + userText
            # Java:         : "对话历史：\n" + historyCtx + "\n\n用户最新输入：" + userText;
            if not historyCtx:
                userPrompt = "用户输入：" + userText
            else:
                userPrompt = "对话历史：\n" + historyCtx + "\n\n用户最新输入：" + userText

            # Java: logger.debug("[IntentClassifier] 原始输入: " + userPrompt);
            logger.debug("[IntentClassifier] 原始输入: " + userPrompt)

            # Java: String raw = llmClient.generate(this.systemPrompt, userPrompt);
            raw = self._generate(self.systemPrompt, userPrompt)

            # Java: logger.debug("[IntentClassifier] 原始输出: " + raw);
            logger.debug("[IntentClassifier] 原始输出: " + raw)

            # Java: return parse(raw, userText);
            return self._parse(raw, userText)

        # Java: } catch (Exception e) {
        except Exception as e:
            # Java: logger.error("[IntentClassifier] 分类异常，降级为 QUERY: " + e.getMessage());
            logger.error("[IntentClassifier] 分类异常，降级为 QUERY: " + str(e))
            # Java: return fallback(userText);
            return self._fallback(userText)

    # -----------------------------------------------------------------------
    # Java: // ── 私有方法 ──────────────────────────────────────────────────
    #
    # Java: private IntentResult parse(String raw, String fallbackText) {
    # Java:     try {
    # Java:         // 容错：去掉可能的 ```json ... ``` 包装
    # Java:         String json = raw.replaceAll("(?s)```json|```", "").trim();
    # Java:         JsonNode node = MAPPER.readTree(json);
    # Java:
    # Java:         // 解析 intent
    # Java:         String intentStr = node.path("intent").asText("QUERY").toUpperCase();
    # Java:         IntentResult.Intent intent;
    # Java:         try {
    # Java:             intent = IntentResult.Intent.valueOf(intentStr);
    # Java:         } catch (IllegalArgumentException ex) {
    # Java:             logger.error("[IntentClassifier] 未知 intent 值: " + intentStr + "，降级 QUERY");
    # Java:             return fallback(fallbackText);
    # Java:         }
    # Java:
    # Java:         // 解析 sentiment
    # Java:         IntentResult.Sentiment sentiment = IntentResult.Sentiment.NEUTRAL;
    # Java:         String sentimentStr = node.path("sentiment").asText("").toLowerCase();
    # Java:         if ("positive".equals(sentimentStr)) sentiment = IntentResult.Sentiment.POSITIVE;
    # Java:         else if ("negative".equals(sentimentStr)) sentiment = IntentResult.Sentiment.NEGATIVE;
    # Java:
    # Java:         // refined_query 不能为空
    # Java:         String refinedQuery = node.path("refined_query").asText(fallbackText);
    # Java:         if (refinedQuery.isBlank()) refinedQuery = fallbackText;
    # Java:
    # Java:         String category = nullIfBlank(node.path("category").asText(null));
    # Java:
    # Java:         return IntentResult.builder(intent)
    # Java:                 .subIntent(nullIfBlank(node.path("sub_intent").asText(null)))
    # Java:                 .sentiment(sentiment)
    # Java:                 .refinedQuery(refinedQuery)
    # Java:                 .actionCode(nullIfBlank(node.path("action_code").asText(null)))
    # Java:                 .category(category)
    # Java:                 .build();
    # Java:
    # Java:     } catch (Exception e) {
    # Java:         logger.error("[IntentClassifier] JSON 解析失败，降级 QUERY。原始内容: " + raw);
    # Java:         return fallback(fallbackText);
    # Java:     }
    # Java: }
    def _parse(self, raw: str, fallbackText: str) -> IntentResult:
        try:
            # Java: String json = raw.replaceAll("(?s)```json|```", "").trim();
            json_str = re.sub(r"(?s)```json|```", "", raw).strip()

            # Java: JsonNode node = MAPPER.readTree(json);
            node = json.loads(json_str)

            # Java: String intentStr = node.path("intent").asText("QUERY").toUpperCase();
            intentStr = node.get("intent", "QUERY").upper()

            # Java: try { intent = IntentResult.Intent.valueOf(intentStr); }
            # Java: catch (IllegalArgumentException ex) {
            # Java:     logger.error("... 未知 intent 值: " + intentStr + "，降级 QUERY");
            # Java:     return fallback(fallbackText);
            # Java: }
            try:
                intent = Intent[intentStr]
            except KeyError:
                logger.error("[IntentClassifier] 未知 intent 值: " + intentStr + "，降级 QUERY")
                return self._fallback(fallbackText)

            # Java: IntentResult.Sentiment sentiment = IntentResult.Sentiment.NEUTRAL;
            sentiment = Sentiment.NEUTRAL

            # Java: String sentimentStr = node.path("sentiment").asText("").toLowerCase();
            sentimentStr = (node.get("sentiment") or "").lower()

            # Java: if ("positive".equals(sentimentStr)) sentiment = IntentResult.Sentiment.POSITIVE;
            # Java: else if ("negative".equals(sentimentStr)) sentiment = IntentResult.Sentiment.NEGATIVE;
            if sentimentStr == "positive":
                sentiment = Sentiment.POSITIVE
            elif sentimentStr == "negative":
                sentiment = Sentiment.NEGATIVE

            # Java: String refinedQuery = node.path("refined_query").asText(fallbackText);
            # Java: if (refinedQuery.isBlank()) refinedQuery = fallbackText;
            refinedQuery = node.get("refined_query", fallbackText) or fallbackText
            if not refinedQuery.strip():
                refinedQuery = fallbackText

            # Java: String category = nullIfBlank(node.path("category").asText(null));
            category = self._nullIfBlank(node.get("category"))

            # Java: return IntentResult.builder(intent)
            # Java:         .subIntent(nullIfBlank(node.path("sub_intent").asText(null)))
            # Java:         .sentiment(sentiment)
            # Java:         .refinedQuery(refinedQuery)
            # Java:         .actionCode(nullIfBlank(node.path("action_code").asText(null)))
            # Java:         .category(category)
            # Java:         .build();
            return IntentResult(
                intent=intent,
                sub_intent=self._nullIfBlank(node.get("sub_intent")),
                sentiment=sentiment,
                refined_query=refinedQuery,
                action_code=self._nullIfBlank(node.get("action_code")),
                category=category,
            )

        # Java: } catch (Exception e) {
        except Exception as e:
            # Java: logger.error("[IntentClassifier] JSON 解析失败，降级 QUERY。原始内容: " + raw);
            logger.error("[IntentClassifier] JSON 解析失败，降级 QUERY。原始内容: " + raw)
            # Java: return fallback(fallbackText);
            return self._fallback(fallbackText)

    # -----------------------------------------------------------------------
    # Java: /** 兜底：分类失败时降级为 QUERY */
    # Java: private IntentResult fallback(String text) {
    # Java:     return IntentResult.builder(IntentResult.Intent.QUERY)
    # Java:             .refinedQuery(text)
    # Java:             .build();
    # Java: }
    @staticmethod
    def _fallback(text: str) -> IntentResult:
        return IntentResult(intent=Intent.QUERY, refined_query=text)

    # -----------------------------------------------------------------------
    # Java: private String nullIfBlank(String s) {
    # Java:     return (s == null || s.isBlank() || "null".equalsIgnoreCase(s)) ? null : s;
    # Java: }
    @staticmethod
    def _nullIfBlank(s: Optional[str]) -> Optional[str]:
        if s is None:
            return None
        stripped = s.strip()
        return None if (not stripped or stripped.lower() == "null") else stripped

    # -----------------------------------------------------------------------
    # Helper: mirrors Java ChatHistory.toPlainText(int window)
    # Java returns a plain-text block of the last N messages; we replicate that.
    @staticmethod
    def _toPlainText(
        history: Optional[List[dict]],
        window: int,
    ) -> Optional[str]:
        # Java: if (history == null || history.isEmpty()) return null;
        if not history:
            return None
        lines = []
        # Java: takes last HISTORY_WINDOW messages
        for msg in history[-window:]:
            role = "User" if msg.get("role") == "user" else "Assistant"
            lines.append(f"{role}: {msg.get('content', '')}")
        result = "\n".join(lines)
        # Java: historyCtx.isBlank() check
        return result if result.strip() else None

    # -----------------------------------------------------------------------
    # Helper: calls the LLM — mirrors Java llmClient.generate(systemPrompt, userPrompt)
    # Java: String raw = llmClient.generate(this.systemPrompt, userPrompt);
    # llmClient.generate() is the only method IntentClassifier calls on llmClient;
    # model name is encapsulated inside llmClient, not known here.
    def _generate(self, system: str, user: str) -> str:
        return self.llmClient.generate(system, user)


# ===========================================================================
# Java: public class SimpleIntentClassifier extends IntentClassifier {
# Java:     public SimpleIntentClassifier() {
# Java:         super(null, null); // 不需要 llmClient
# Java:     }
# Java:
# Java:     @Override
# Java:     public IntentResult classify(String userText, ChatHistory history) {
# Java:         // Skip LLM entirely, always return QUERY with original text
# Java:         return IntentResult.builder(IntentResult.Intent.QUERY)
# Java:                 .refinedQuery(userText)
# Java:                 .build();
# Java:     }
# Java: }
# ===========================================================================
class SimpleIntentClassifier:
    """
    Skips LLM entirely — all input treated as QUERY.
    Activated when rag.query.mode=simple (Java) or INTENT_MODE=simple (Python).
    """

    # Java: @Override
    # Java: public IntentResult classify(String userText, ChatHistory history) {
    def classify(
        self,
        userText: str,
        history: Optional[List[dict]] = None,
    ) -> IntentResult:
        # Java: logger.debug("SimpleIntentClassifier activated — all input treated as QUERY");
        logger.debug(
            "[SimpleIntentClassifier] activated — all input treated as QUERY. "
            f"text={userText}"
        )
        # Java: return IntentResult.builder(IntentResult.Intent.QUERY)
        # Java:         .refinedQuery(userText)
        # Java:         .build();
        return IntentResult(intent=Intent.QUERY, refined_query=userText)
