# intent/intent_classifier.py
# Java: package com.lcallai.intent;
import json
import logging
import re
from typing import List, Optional
from session.chat_history import ChatHistory
from intent.intent_result import Intent, IntentResult, Sentiment
from intent.fast_track import fast_track
import ai_config as AiConfig
logger = logging.getLogger(__name__)

# Java: private static final int HISTORY_WINDOW = 16;
HISTORY_WINDOW = 16

# Java: private static final String SYSTEM_PROMPT = """...""";
SYSTEM_PROMPT = """\
你是一个对话意图分类器，只输出合法 JSON，禁止输出任何额外文字或 Markdown 标记。

intent 枚举值（必须且只能是以下之一）：
[QUERY, COMMAND, INFORM, FEEDBACK, ACK, GREETING, CHITCHAT]

输出字段规则：
1. intent      (string)      必填，枚举值之一,注意：仅当动作完全匹配下述 action_code 枚举时才准许判定为 COMMAND。
2. sub_intent  (string|null) 仅 ACK 时必填：affirm（肯定）/ negate（否定）/ ack（普通确认）
3. sentiment   (string|null) 仅 FEEDBACK 时必填：positive / negative
4. refined_query (string)    必填：
   - QUERY：同时完成以下两件事后输出一个最终问句：
     第一步【指代补全】结合对话历史，将"他""那个""这个"等代词还原为具体实体。
     第二步【检索优化】去掉礼貌语气词，突出核心实体和动词，使问句更适合向量检索。
     例："他的密码忘了怎么办"（上文说的是学生）
       → "学生忘记登录密码如何找回？"  ✓
     例："Win10能装吗"（上文在讨论翔云3.0软件）
       → "翔云3.0支持在Windows10系统上安装吗？"  ✓
   - 其他 intent：直接返回用户原始输入，不做任何修改
5. action_code (string|null) 仅 COMMAND 时必填，枚举值之一：
   ACTION_REPLAY / ACTION_TRANSFER / ACTION_VOL_UP / ACTION_VOL_DOWN / ACTION_HANGUP
   【重要约束】：只有当用户明确要求"重放/重听 (REPLAY)"、"转人工 (TRANSFER)"或"调节音量 (VOL)"或 再见(HANGUP)时，才允许返回对应的 action_code。
       - ACTION_REPLAY：仅在对话历史中已有 AI 回复且用户要求重复/重听上一句话时触发。
         触发词示例：重放、重听、再说一遍、你刚才说什么、你说什么、没听清、听不清、再说一次、什么、啊？
         【反例】：若用户说"你说什么意思"、"你说的什么产品"，含业务实体，判 QUERY。
       - ACTION_TRANSFER：用户明确要求转人工时触发。
       - ACTION_VOL_UP / ACTION_VOL_DOWN：用户要求调节音量时触发。
       - ACTION_HANGUP：用户明确表示结束通话时触发。
6. FEEDBACK 定义：凡是包含用户对服务、产品或解决结果的主观态度、情绪评价、感谢表扬或抱怨建议的内容，必须判定为 FEEDBACK，并强制标注 sentiment 极性。
7. 若输入内容无法解析为具体业务意图且字数极少或语义混乱，请统一归类为 CHITCHAT

判定示例：
输入"好的"      → {"intent":"ACK","sub_intent":"ack","sentiment":null,"refined_query":"好的","action_code":null}
输入"对就是这个" → {"intent":"ACK","sub_intent":"affirm","sentiment":null,"refined_query":"对就是这个","action_code":null}
输入"不用了"    → {"intent":"ACK","sub_intent":"negate","sentiment":null,"refined_query":"不用了","action_code":null}
输入"这软件太卡" → {"intent":"FEEDBACK","sub_intent":null,"sentiment":"negative","refined_query":"这软件太卡","action_code":null}
输入"再见"      → {"intent":"COMMAND","sub_intent":null,"sentiment":null,"refined_query":"再见","action_code":"ACTION_HANGUP"}
"""


class IntentClassifier:
    """
    public class IntentClassifier {
        private final LlmClient llmClient;
        private final String systemPrompt;
    }
    """

    """
    public IntentClassifier(LlmClient llmClient) {
        this(llmClient, null);
    }

    public IntentClassifier(LlmClient llmClient, String systemPrompt) {
        this.llmClient    = llmClient;
        this.systemPrompt = (systemPrompt != null && !systemPrompt.isBlank())
                ? systemPrompt : SYSTEM_PROMPT;
    }
    """
    def __init__(self, llmClient, system_prompt: Optional[str] = None):
        # Java: this.llmClient = llmClient;
        self.llmClient = llmClient
        # Java: this.systemPrompt = (systemPrompt != null && !systemPrompt.isBlank()) ? systemPrompt : SYSTEM_PROMPT;
        self.systemPrompt = (
            system_prompt.strip()
            if (system_prompt and system_prompt.strip())
            else SYSTEM_PROMPT
        )

    """
    public IntentResult classify(String userText, ChatHistory history) {
        try {
            String historyCtx = history.toPlainText(HISTORY_WINDOW);
            String userPrompt = historyCtx == null || historyCtx.isBlank()
                    ? "用户输入：" + userText
                    : "对话历史：\n" + historyCtx + "\n\n用户最新输入：" + userText;
            logger.debug("原始输入: " + userPrompt);
            String raw = llmClient.generate(this.systemPrompt, userPrompt);
            logger.debug("原始输出: " + raw);
            return parse(raw, userText);
        } catch (Exception e) {
            logger.error("分类异常，降级为 QUERY: " + e.getMessage());
            return fallback(userText);
        }
    }
    """
    def classify(self, userText: str, history: Optional[ChatHistory] = None) -> IntentResult:
        # Fast-track: regex shortcut for high-frequency simple inputs
        hit = fast_track(userText)
        if hit is not None:
            logger.debug("[IntentClassifier] fast-track hit: " + userText + " → " + hit.intent.value)
            return hit

        try:
            # Java: String historyCtx = history.toPlainText(HISTORY_WINDOW);
            historyCtx = self._toPlainText(history, HISTORY_WINDOW)
            label_input   = AiConfig.getStringConfig("prompt.label.user_input",  "User input:")
            label_history = AiConfig.getStringConfig("prompt.label.history",     "Conversation history:")
            label_latest  = AiConfig.getStringConfig("prompt.label.user_latest", "Latest user input:")
            if not historyCtx:
                userPrompt = f"{label_input} {userText}"
            else:
                userPrompt = f"{label_history}\n{historyCtx}\n{label_latest} {userText}"
            # if not historyCtx:
            #     userPrompt = "用户输入：" + userText
            # else:
            #     userPrompt = "对话历史：\n" + historyCtx + "\n用户最新输入：" + userText

            #logger.debug("User Input:\n " + userPrompt)
            AiConfig.log(logger, "log.intent.input.chars", "User Input", userPrompt)

            # Java: String raw = llmClient.generate(this.systemPrompt, userPrompt);

            raw = self.llmClient.generate(self.systemPrompt, userPrompt)
            #logger.debug("AI response:\n " + raw)
            AiConfig.log(logger, "log.ai.response.chars", "AI response", raw)
            return self._parse(raw, userText)

        except Exception as e:
            logger.error("分类异常，降级为 QUERY: " + str(e))
            return self._fallback(userText)

    """
    private IntentResult parse(String raw, String fallbackText) {
        try {
            String json = raw.replaceAll("(?s)```json|```", "").trim();
            JsonNode node = MAPPER.readTree(json);

            String intentStr = node.path("intent").asText("QUERY").toUpperCase();
            IntentResult.Intent intent;
            try {
                intent = IntentResult.Intent.valueOf(intentStr);
            } catch (IllegalArgumentException ex) {
                logger.error("未知 intent 值: " + intentStr + "，降级 QUERY");
                return fallback(fallbackText);
            }

            IntentResult.Sentiment sentiment = IntentResult.Sentiment.NEUTRAL;
            String sentimentStr = node.path("sentiment").asText("").toLowerCase();
            if ("positive".equals(sentimentStr)) sentiment = IntentResult.Sentiment.POSITIVE;
            else if ("negative".equals(sentimentStr)) sentiment = IntentResult.Sentiment.NEGATIVE;

            String refinedQuery = node.path("refined_query").asText(fallbackText);
            if (refinedQuery.isBlank()) refinedQuery = fallbackText;

            String category = nullIfBlank(node.path("category").asText(null));

            return IntentResult.builder(intent)
                    .subIntent(nullIfBlank(node.path("sub_intent").asText(null)))
                    .sentiment(sentiment)
                    .refinedQuery(refinedQuery)
                    .actionCode(nullIfBlank(node.path("action_code").asText(null)))
                    .category(category)
                    .build();
        } catch (Exception e) {
            logger.error("JSON 解析失败，降级 QUERY。原始内容: " + raw);
            return fallback(fallbackText);
        }
    }
    """
    def _parse(self, raw: str, fallbackText: str) -> IntentResult:
        try:
            # Java: String json = raw.replaceAll("(?s)```json|```", "").trim();
            json_str = re.sub(r"(?s)```json|```", "", raw).strip()
            node = json.loads(json_str)

            # Java: String intentStr = node.path("intent").asText("QUERY").toUpperCase();
            intentStr = node.get("intent", "QUERY").upper()

            try:
                intent = Intent[intentStr]
            except KeyError:
                logger.error("未知 intent 值: " + intentStr + "，降级 QUERY")
                return self._fallback(fallbackText)

            # Java: Sentiment sentiment = Sentiment.NEUTRAL; if ("positive"...) ...
            sentiment   = Sentiment.NEUTRAL
            sentimentStr = (node.get("sentiment") or "").lower()
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

            return IntentResult(
                intent=intent,
                sub_intent=self._nullIfBlank(node.get("sub_intent")),
                sentiment=sentiment,
                refined_query=refinedQuery,
                action_code=self._nullIfBlank(node.get("action_code")),
                category=category,
            )

        except Exception as e:
            logger.error("JSON 解析失败，降级 QUERY。原始内容: " + raw)
            return self._fallback(fallbackText)

    """
    private IntentResult fallback(String text) {
        return IntentResult.builder(IntentResult.Intent.QUERY).refinedQuery(text).build();
    }
    """
    def _fallback(self, text: str) -> IntentResult:
        return IntentResult(intent=Intent.QUERY, refined_query=text)

    """
    private String nullIfBlank(String s) {
        return (s == null || s.isBlank() || "null".equalsIgnoreCase(s)) ? null : s;
    }
    """
    @staticmethod
    def _nullIfBlank(s: Optional[str]) -> Optional[str]:
        if s is None:
            return None
        stripped = s.strip()
        return None if (not stripped or stripped.lower() == "null") else stripped

    @staticmethod
    def _toPlainText(history, window: int) -> Optional[str]:
        if not history:
            return None
        return history.toPlainText(window) or None


class SimpleIntentClassifier(IntentClassifier):
    """
    public class SimpleIntentClassifier extends IntentClassifier {
        public SimpleIntentClassifier() { super(null, null); }

        @Override
        public IntentResult classify(String userText, ChatHistory history) {
            return IntentResult.builder(IntentResult.Intent.QUERY).refinedQuery(userText).build();
        }
    }
    """

    def __init__(self):
        # Java: super(null, null);
        super().__init__(llmClient=None, system_prompt=None)

    def classify(self, userText: str, history: Optional[ChatHistory] = None) -> IntentResult:
        # Java: return IntentResult.builder(IntentResult.Intent.QUERY).refinedQuery(userText).build();
        return IntentResult(intent=Intent.QUERY, refined_query=userText)
