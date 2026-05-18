# session/chat_session.py
# Java: package com.lcallai;
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from models import ChatAnswer
from intent.intent_result import Intent, IntentResult
from session.chat_history import ChatHistory

logger = logging.getLogger(__name__)

# Java: private static final int MAX_HISTORY        = 60;
# Java: private static final int MAX_QUERY_HISTORY  = 16;
# Java: private static final int MAX_ASK_HISTORY    = 40;
# Java: private static final int MAX_MESSAGE_LENGTH = 1000;
MAX_HISTORY        = 60
MAX_QUERY_HISTORY  = 16
MAX_ASK_HISTORY    = 40
MAX_MESSAGE_LENGTH = 1000

# Java: private static final ThreadPoolExecutor rerankExecutor = new ThreadPoolExecutor(8, 16, 60L, ...)
_rerank_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="rerank-pool")


class ChatSession:

    # -------------------------------------------------------------------------
    # Fields — mirrors Java field declarations
    # Java: private ChatHistory history; private String systemMessage = "";
    # Java: private final ModelRouter router; private final EmbeddingClient embeddingClient;
    # Java: private final String tableName;
    # Java: String rewrite_prompt, ask_prompt, rerankSys_prompt, fulltext;
    # Java: String queryMode = "fullText"; static String sinfo; String crid;
    # Java: private double similarityThreshold=0.82, trustThreshold=0.25,
    # Java:   compensateEmbedMax=0.45, compensateRerankMin=0.80,
    # Java:   rerankTriggerMax=0.60, rescueScore=0.60;
    # Java: private int maxRerankCandidates=5, finalContextLimit=3, rerankTimeoutSeconds=5;
    # Java: public IntentClassifier intentClassifier; public IntentDispatcher intentDispatcher;
    # Java: public IntentResult currentIntentResult;
    # Java: private String currentCategory=null, pendingQuery=null, sessionId="";
    # Java: public String lastRawText=null;
    # -------------------------------------------------------------------------

    """
    /*
     * public ChatSession(ModelRouter router, EmbeddingClient embeddingClient, String tableName) {
     *     this.router          = router;
     *     this.embeddingClient = embeddingClient;
     *     this.tableName       = tableName;
     * }
     */
    """
    def __init__(self, session_id: str):
        self.sessionId: str          = session_id
        self.sinfo: str              = "[sn=" + session_id + "] "
        self.crid: Optional[str]     = None
        self.history = ChatHistory(MAX_ASK_HISTORY)
        self.systemMessage: str      = ""
        self.rewrite_prompt: Optional[str]  = None
        self.ask_prompt: Optional[str]      = None
        self.rerankSys_prompt: Optional[str]= None
        self.fulltext: Optional[str]        = None
        self.queryMode: str                 = "fullText"
        self.router                         = None   # RAG layer stub
        self.embeddingClient                = None
        self.tableName: Optional[str]       = None
        self.intentClassifier               = None
        self.intentDispatcher               = None
        self.currentIntentResult: Optional[IntentResult] = None
        self.currentCategory: Optional[str] = None
        self.pendingQuery: Optional[str]    = None
        self.lastRawText: Optional[str]     = None
        self.similarityThreshold: float     = 0.82
        self.trustThreshold: float          = 0.25
        self.compensateEmbedMax: float      = 0.45
        self.compensateRerankMin: float     = 0.80
        self.rerankTriggerMax: float        = 0.60
        self.rescueScore: float             = 0.60
        self.maxRerankCandidates: int       = 5
        self.finalContextLimit: int         = 3
        self.rerankTimeoutSeconds: int      = 5

    """
    /*
     * public void setThresholds(double similarity, double trust,
     *                            double compEmbedMax, double compRerankMin) {
     *     this.similarityThreshold = similarity; this.trustThreshold = trust;
     *     this.compensateEmbedMax  = compEmbedMax; this.compensateRerankMin = compRerankMin;
     * }
     */
    """
    def setThresholds(self, similarity: float, trust: float,
                      compEmbedMax: float, compRerankMin: float) -> None:
        self.similarityThreshold = similarity
        self.trustThreshold      = trust
        self.compensateEmbedMax  = compEmbedMax
        self.compensateRerankMin = compRerankMin

    """
    /*
     * public void setAdvancedThresholds(double triggerMax, double rescueScore) {
     *     this.rerankTriggerMax = triggerMax; this.rescueScore = rescueScore;
     * }
     */
    """
    def setAdvancedThresholds(self, triggerMax: float, rescueScore: float) -> None:
        self.rerankTriggerMax = triggerMax
        self.rescueScore      = rescueScore

    # ── Getters / Setters (in Java source order) ──────────────────────────────

    def getSessionId(self) -> str:             return self.sessionId
    def setSessionId(self, v: str) -> None:    self.sessionId = v

    def set_intent_pipeline(self, classifier, dispatcher) -> None:
        self.intentClassifier = classifier
        self.intentDispatcher = dispatcher

    def setTopK(self, rerankCandidates: int, contextLimit: int, timeout: int) -> None:
        self.maxRerankCandidates  = rerankCandidates
        self.finalContextLimit    = contextLimit
        self.rerankTimeoutSeconds = timeout

    def setRewrite_prompt(self, v: str) -> None:    self.rewrite_prompt  = v
    def setAsk_prompt(self, v: str) -> None:        self.ask_prompt      = v
    def setRerankSys_prompt(self, v: str) -> None:  self.rerankSys_prompt = v
    def setFulltext(self, v: str) -> None:          self.fulltext        = v
    def setQueryMode(self, v: str) -> None:         self.queryMode       = v
    def getQueryMode(self) -> str:                  return self.queryMode
    def setSInfo(self, v: str) -> None:             self.sinfo           = v
    def getSInfo(self) -> str:                      return self.sinfo
    def getHistory(self) -> List[dict]:             return self.history
    def getCurrentCategory(self) -> Optional[str]:  return self.currentCategory
    def setCurrentCategory(self, v: str) -> None:   self.currentCategory = v
    def setPendingQuery(self, v: str) -> None:      self.pendingQuery    = v
    def getPendingQuery(self) -> Optional[str]:     return self.pendingQuery
    def clearPendingQuery(self) -> None:            self.pendingQuery    = None
    def getRouter(self):                            return self.router

    def setCRID(self, crid: str) -> None:
        logger.debug(self.sinfo + " crid=" + crid)
        self.crid = crid

    # -------------------------------------------------------------------------

    """
    /*
     * void setSystemMessage(String system) {
     *     buildSystem(system);
     *     history.addMessage("system", systemMessage);
     * }
     */
    """
    def setSystemMessage(self, system: str) -> None:
        self.buildSystem(system)
        self._history_add("system", self.systemMessage)

    """
    /*
     * public void buildSystem(String knowledgeContext) {
     *     if (knowledgeContext == null) return;
     *     systemMessage = ask_prompt + "=== CONTEXT ===\n" + knowledgeContext + "\n=== END CONTEXT ===\n";
     * }
     */
    """
    def buildSystem(self, knowledgeContext: str) -> None:
        if knowledgeContext is None:
            return
        self.systemMessage = (
                (self.ask_prompt or "")
                + "=== CONTEXT ===\n"
                + knowledgeContext
                + "\n=== END CONTEXT ===\n"
        )

    """
    /*
     * public void addUserHis(String text) {
     *     history.addMessage("user", text);
     *     history.trim(MAX_HISTORY);
     * }
     */
    """
    def addUserHis(self, text: str) -> None:
        self._history_add("user", text)
        self._history_trim(MAX_HISTORY)

    """
    /*
     * private Map<String, String> parseArgsFromAiResponse(String answer) {
     *     Map<String, String> args = new HashMap<>();
     *     try {
     *         String jsonStr = answer.substring(10);
     *         JsonNode root  = MAPPER.readTree(jsonStr);
     *         String argsStr = root.path("function").path("arguments").asText();
     *         JsonNode argsNode = MAPPER.readTree(argsStr);
     *         args.put("country",     argsNode.path("country").asText(""));
     *         args.put("citizenship", argsNode.path("citizenship").asText(""));
     *     } catch (Exception e) { logger.error("", e); }
     *     return args;
     * }
     */
    """
    def _parseArgsFromAiResponse(self, answer: str) -> Dict[str, str]:
        args: Dict[str, str] = {}
        try:
            json_str  = answer[10:]
            root      = json.loads(json_str)
            args_str  = root.get("function", {}).get("arguments", "{}")
            args_node = json.loads(args_str)
            args["country"]     = args_node.get("country", "")
            args["citizenship"] = args_node.get("citizenship", "")
        except Exception as e:
            logger.error(str(e))
        return args

    """
    /*
     * private ChatAnswer handleEmptyResult(String text, ChatAnswer ca) {
     *     ca.code = -100; ca.answer = "知识库中没有找到任何内容";
     *     recordHistory(text, "【未匹配到相关知识】", "抱歉，知识库中没有找到任何内容。");
     *     return ca;
     * }
     */
    """
    def _handleEmptyResult(self, text: str, ca: ChatAnswer) -> ChatAnswer:
        ca.code   = -100
        ca.answer = "知识库中没有找到任何内容"
        self._recordHistory(text, "【未匹配到相关知识】", "抱歉，知识库中没有找到任何内容。")
        return ca

    """
    /*
     * private ChatAnswer handleLowSimilarity(String text, ChatAnswer ca) {
     *     ca.code = -101; ca.answer = "抱歉，我在知识库中未找到与您问题完全相关的信息。";
     *     return ca;
     * }
     */
    """
    def _handleLowSimilarity(self, text: str, ca: ChatAnswer) -> ChatAnswer:
        ca.code   = -101
        ca.answer = "抱歉，我在知识库中未找到与您问题完全相关的信息。"
        return ca

    """
    /*
     * private void recordHistory(String userText, String contextText, String assistantText) {
     *     // body commented out in Java
     * }
     */
    """
    def _recordHistory(self, userText: str, contextText: str, assistantText: str) -> None:
        pass

    """
    /*
     * public String getLastAnswer() {
     *     List<ChatHistory.Message> msgs = history.getMessages();
     *     for (int i = msgs.size() - 1; i >= 0; i--) {
     *         if ("assistant".equalsIgnoreCase(msgs.get(i).getRole()))
     *             return msgs.get(i).getContent();
     *     }
     *     return null;
     * }
     */
    """
    def getLastAnswer(self) -> Optional[str]:
        #reversed(obj) 会自动调用 obj.__reversed__()，这是 Python 的协议机制：
        for msg in reversed(self.history):  ## 等价于 self.history.__reversed__()
            if msg.get("role", "").lower() == "assistant":
                return msg.get("content")
        return None

    """
    /*
     * public String askString(String text) {
     *     ChatAnswer ca = ask(text);
     *     return ca.toJsonString();
     * }
     */
    """
    def askString(self, text: str) -> str:
        ca = self.ask(text)
        return json.dumps({"code": ca.code, "answer": ca.answer, "action": ca.action})

    """
    /*
     * public ChatAnswer ask(String text) {
     *     if (text == null || text.trim().isEmpty()) return new ChatAnswer(-1, "输入为空");
     *     long t0 = System.currentTimeMillis();
     *     IntentResult intentResult = intentClassifier.classify(text, history);
     *     long t1 = System.currentTimeMillis();
     *     logger.debug(sinfo+" [1] 意图分类耗时: " + (t1-t0) + " ms  intent=" + intentResult.intent);
     *     if (intentResult.intent == QUERY && intentResult.category == null)
     *         this.pendingQuery = text;
     *     else if (intentResult.category != null)
     *         this.currentCategory = intentResult.category;
     *     this.currentIntentResult = intentResult;
     *     this.lastRawText = text;
     *     logger.debug(sinfo+"[intentResult]= " + intentResult);
     *     logger.debug(sinfo+"[Intent] " + intentResult.intent + " | Refined: " + intentResult.refinedQuery);
     *     String userMsg = (refinedQuery != null && !refinedQuery.isBlank()
     *             && similarity(text, refinedQuery) < 0.9)
     *             ? text + "\n" + refinedQuery : text;
     *     history.addMessage("user", userMsg); history.trim(MAX_HISTORY);
     *     ChatAnswer ca = intentDispatcher.dispatch(text, intentResult, this);
     *     ca.intentResult = currentIntentResult;
     *     long t2 = System.currentTimeMillis();
     *     logger.debug(sinfo+" [2] Handler执行耗时: " + (t2-t1) + " ms");
     *     logger.debug(sinfo+" [总] ask()全链路耗时: " + (t2-t0) + " ms");
     *     if (ca.answer != null && !ca.answer.isBlank()) {
     *         history.addMessage("assistant", ca.answer); history.trim(MAX_HISTORY); }
     *     return ca;
     * }
     */
    """
    def ask(self, text: str) -> ChatAnswer:
        if not text or not text.strip():
            return ChatAnswer(code=-1, answer="输入为空")

        t0 = time.time()
        intentResult: IntentResult = self.intentClassifier.classify(text, self.history)
        t1 = time.time()
        logger.debug(self.sinfo + " [1] 意图分类耗时: " + str(int((t1 - t0) * 1000)) + " ms  intent=" + str(intentResult.intent))

        if intentResult.intent == Intent.QUERY and intentResult.category is None:
            self.pendingQuery = text
        elif intentResult.category is not None:
            self.currentCategory = intentResult.category

        self.currentIntentResult = intentResult
        self.lastRawText         = text
        logger.debug(self.sinfo + "[intentResult]= " + str(intentResult))
        logger.debug(self.sinfo + "[Intent] " + str(intentResult.intent) + " | Refined: " + str(intentResult.refined_query))

        refined = intentResult.refined_query
        if refined and refined.strip() and self._similarity(text, refined) < 0.9:
            userMsg = text + " " + refined
        else:
            userMsg = text

        self._history_add("user", userMsg)
        self._history_trim(MAX_HISTORY)

        ca: ChatAnswer= self.intentDispatcher.dispatch(text, intentResult, self)

        t2 = time.time()
        logger.debug(self.sinfo + " [2] Handler执行耗时: " + str(int((t2 - t1) * 1000)) + " ms")
        logger.debug(self.sinfo + " [总] ask()全链路耗时: " + str(int((t2 - t0) * 1000)) + " ms")

        if ca.answer and ca.answer.strip():
            self._history_add("assistant", ca.answer)
            self._history_trim(MAX_HISTORY)

        return ca

    """
    /*
     * public ChatAnswer askByQueryMode(String text, boolean isrewrite) {
     *     if ("fullText".equalsIgnoreCase(queryMode))    return askFullContext(text, isrewrite);
     *     else if ("simple".equalsIgnoreCase(queryMode)) return askSimple(text);
     *     else                                           return askRerank(text, isrewrite);
     * }
     */
    """
    def askByQueryMode(self, text: str, isrewrite: bool = False) -> ChatAnswer:
        if self.queryMode and self.queryMode.lower() == "fulltext":
            return self.askFullContext(text, isrewrite)
        elif self.queryMode and self.queryMode.lower() == "simple":
            return self.askSimple(text)
        else:
            return self.askRerank(text, isrewrite)

    """
    /*
     * public ChatAnswer askSimple(String text) {
     *     logger.debug(sinfo + "[askSimple] text=" + text);
     *     ChatAnswer ca = new ChatAnswer(-1, null);
     *     if (fulltext == null || fulltext.trim().length() < 10) {
     *         ca.code = -404; ca.answer = "Knowledge base is empty"; return ca; }
     *     try {
     *         String ans = executeFinalChat(fulltext, "");
     *         if (ans != null && !ans.isEmpty()) { ca.code = 0; ca.answer = ans; }
     *         else { ca.code = -500; ca.answer = "Empty response from AI"; }
     *     } catch (Exception e) {
     *         logger.error("[askSimple] exception", e);
     *         ca.code = -1; ca.answer = "System error: " + e.getMessage();
     *     }
     *     return ca;
     * }
     */
    """
    def askSimple(self, text: str) -> ChatAnswer:
        logger.debug(self.sinfo + "[askSimple] text=" + text)
        ca = ChatAnswer(code=-1, answer=None)

        if not self.fulltext or len(self.fulltext.strip()) < 10:
            ca.code = -404; ca.answer = "Knowledge base is empty"; return ca

        try:
            ans = self._executeFinalChat(self.fulltext, "")
            if ans:
                ca.code = 0; ca.answer = ans
            else:
                ca.code = -500; ca.answer = "Empty response from AI"
        except Exception as e:
            logger.error(self.sinfo + "[askSimple] exception " + str(e))
            ca.code = -1; ca.answer = "System error: " + str(e)

        return ca

    """
    /*
     * public ChatAnswer askFullContext(String text, boolean isrewrite) {
     *     logger.debug(sinfo+"🚀 执行全量知识库 Stuffing 流程 (askFullContext)...");
     *     ChatAnswer ca = new ChatAnswer(-1, null);
     *     if (text == null || text.trim().isEmpty()) { ca.code=-1; ca.answer="客户问题为空"; return ca; }
     *     String processedText = text.length() > MAX_MESSAGE_LENGTH ? text.substring(0, MAX_MESSAGE_LENGTH) : text;
     *     try {
     *         String optimizedQuery = processedText;
     *         if (isrewrite) optimizedQuery = performQueryRewrite(processedText);
     *         if (fulltext == null || fulltext.trim().length() < 10) {
     *             ca.code=-404; ca.answer="知识库内容为空或加载失败，请检查"; return ca; }
     *         String filteredContext = filterKnowledgeByCategory(fulltext, currentCategory);
     *         if (filteredContext == null || filteredContext.isBlank()) {
     *             ca.code=0; ca.answer="抱歉，我这暂时没有查询到您身份相关的业务说明，请您提供更多信息。"; return ca; }
     *         long chatStart = System.currentTimeMillis();
     *         String ans = executeFinalChat(filteredContext, "");
     *         logger.debug(sinfo+" [Step 2] AI executeFinalChat 生成答案耗时: " + chatDuration + " ms");
     *         if (ans != null) { ca.answer = ans; ca.code = 0; }
     *         else { ca.code=-500; ca.answer="AI 响应为空，请稍后重试。"; }
     *         return ca;
     *     } catch (Exception e) {
     *         logger.error("", e);
     *         ca.code=-1; ca.answer="机器人系统故障: " + e.getMessage(); return ca; }
     * }
     */
    """
    def askFullContext(self, text: str, isrewrite: bool = False) -> ChatAnswer:
        logger.debug(self.sinfo + "🚀 执行全量知识库 Stuffing 流程 (askFullContext)...")
        ca = ChatAnswer(code=-1, answer=None)

        if not text or not text.strip():
            ca.code = -1; ca.answer = "客户问题为空"; return ca

        processedText = text[:MAX_MESSAGE_LENGTH] if len(text) > MAX_MESSAGE_LENGTH else text

        try:
            optimizedQuery = processedText
            if isrewrite:
                optimizedQuery = self._performQueryRewrite(processedText)

            if not self.fulltext or len(self.fulltext.strip()) < 10:
                ca.code = -404; ca.answer = "知识库内容为空或加载失败，请检查"; return ca

            filteredContext = self._filterKnowledgeByCategory(self.fulltext, self.currentCategory)
            if not filteredContext or not filteredContext.strip():
                ca.code = 0
                ca.answer = "抱歉，我这暂时没有查询到您身份相关的业务说明，请您提供更多信息。"
                return ca

            chatStart = time.time()
            ans = self._executeFinalChat(filteredContext, "")
            logger.debug(self.sinfo + " [Step 2] AI executeFinalChat 生成答案耗时: " + str(int((time.time() - chatStart) * 1000)) + " ms")

            if ans is not None:
                ca.answer = ans; ca.code = 0
            else:
                ca.code = -500; ca.answer = "AI 响应为空，请稍后重试。"
            return ca

        except Exception as e:
            logger.error(self.sinfo + "机器人系统故障: " + str(e), exc_info=True)
            ca.code = -1; ca.answer = "机器人系统故障: " + str(e); return ca

    """
    /*
     * public ChatAnswer askRerank(String text, boolean isrewrite) {
     *     logger.debug(sinfo+"🚀 执行高级 RAG 流程 (重构版 ask3)...isrewrite " + isrewrite);
     *     ChatAnswer ca = new ChatAnswer(-1, null);
     *     if (text == null || text.trim().isEmpty()) { ca.code=-1; ca.answer="客户问题为空"; return ca; }
     *     String processedText = text.length() > MAX_MESSAGE_LENGTH ? ... : text;
     *     try {
     *         long requeryStart = System.currentTimeMillis();
     *         String optimizedQuery = processedText;
     *         if (isrewrite) optimizedQuery = performQueryRewrite(processedText);
     *         logger.debug(sinfo+"rewrite耗时=" + (System.currentTimeMillis()-requeryStart) + " ms");
     *         List<KnowledgeItem> finalItems = performTwoStageRetrievalAsync(optimizedQuery);
     *         logger.debug(sinfo+"🔍 检索到的候选列表 after Retrieve - 两阶段检索:");
     *         finalItems.forEach(item -> logger.debug(sinfo+"距离: " + item.distance + ...));
     *         if (finalItems.isEmpty()) return handleEmptyResult(processedText, ca);
     *         if (finalItems.get(0).distance > similarityThreshold) return handleLowSimilarity(processedText, ca);
     *         StringBuilder fullCtx = new StringBuilder();
     *         for (int i=0; i<finalItems.size(); i++)
     *             fullCtx.append(String.format("%d. 【%s-%s】%s\n", i+1, category, summary, content));
     *         logger.debug(sinfo+"executeFinalChat fullCtx: " + fullCtx);
     *         String ans = executeFinalChat(fullCtx.toString(), "");
     *         if (ans != null) { ca.answer=ans; ca.code=0; }
     *         else { ca.code=-500; ca.answer="AI 响应为空，请稍后重试。"; }
     *         return ca;
     *     } catch (Exception e) { logger.error("",e); ca.code=-1; ca.answer="机器人系统故障"; return ca; }
     * }
     */
    """
    def askRerank(self, text: str, isrewrite: bool = False) -> ChatAnswer:
        logger.debug(self.sinfo + "🚀 执行高级 RAG 流程 (重构版 ask3)...isrewrite " + str(isrewrite))
        ca = ChatAnswer(code=-1, answer=None)

        if not text or not text.strip():
            ca.code = -1; ca.answer = "客户问题为空"; return ca

        processedText = text[:MAX_MESSAGE_LENGTH] if len(text) > MAX_MESSAGE_LENGTH else text

        try:
            requeryStart   = time.time()
            optimizedQuery = processedText
            if isrewrite:
                optimizedQuery = self._performQueryRewrite(processedText)
            logger.debug(self.sinfo + "rewrite耗时=" + str(int((time.time() - requeryStart) * 1000)) + " ms")

            finalItems = self._performTwoStageRetrievalAsync(optimizedQuery)

            logger.debug(self.sinfo + "🔍 检索到的候选列表 after Retrieve - 两阶段检索:")
            for item in finalItems:
                logger.debug(self.sinfo + "距离: " + self.formatDouble(item.get("distance", 0))
                             + " 分类:" + str(item.get("category"))
                             + " | 摘要: " + str(item.get("summary")))

            if not finalItems:
                return self._handleEmptyResult(processedText, ca)
            if finalItems[0].get("distance", 1.0) > self.similarityThreshold:
                return self._handleLowSimilarity(processedText, ca)

            fullCtx_parts = []
            for i, item in enumerate(finalItems):
                fullCtx_parts.append(
                    str(i + 1) + ". 【" + str(item.get("category", ""))
                    + "-" + str(item.get("summary", "")) + "】" + str(item.get("content", ""))
                )
            fullCtx = "\n".join(fullCtx_parts)
            logger.debug(self.sinfo + "executeFinalChat fullCtx: " + fullCtx)

            ans = self._executeFinalChat(fullCtx, "")
            if ans is not None:
                ca.answer = ans; ca.code = 0
            else:
                ca.code = -500; ca.answer = "AI 响应为空，请稍后重试。"
            return ca

        except Exception as e:
            logger.error(self.sinfo + str(e), exc_info=True)
            ca.code = -1; ca.answer = "机器人系统故障"; return ca

    """
    /*
     * private String performQueryRewrite(String text) throws Exception {
     *     String historyContextStr = history.toPlainText(MAX_QUERY_HISTORY);
     *     if (historyContextStr.trim().isEmpty() || rewrite_prompt == null) return text;
     *     String userPrompt = "Conversation History:\n(" + historyContextStr
     *                       + ")\n\nCurrent Question: (" + text + ")";
     *     logger.debug(sinfo+"🔄 正在利用上下文重写用户查询...userPrompt=" + userPrompt);
     *     long startTime = System.currentTimeMillis();
     *     String rewritten = router.rewriter().generate(rewrite_prompt, userPrompt);
     *     logger.debug(sinfo+" AI rewritten Time: " + (System.currentTimeMillis()-startTime) + " ms 重写后:" + rewritten);
     *     return (rewritten != null && !rewritten.isEmpty()) ? rewritten : text;
     * }
     */
    """
    def _performQueryRewrite(self, text: str) -> str:
        historyContextStr = self._toPlainText(MAX_QUERY_HISTORY)
        if not historyContextStr.strip() or not self.rewrite_prompt:
            return text

        userPrompt = "Conversation History:\n(" + historyContextStr + ")\n\nCurrent Question: (" + text + ")"
        logger.debug(self.sinfo + "🔄 正在利用上下文重写用户查询...userPrompt=" + userPrompt)
        startTime = time.time()

        try:
            rewritten = self.router.rewriter().generate(self.rewrite_prompt, userPrompt) if self.router else None
        except Exception:
            rewritten = None

        logger.debug(self.sinfo + " AI rewritten Time: " + str(int((time.time() - startTime) * 1000)) + " ms 重写后:" + str(rewritten))
        return rewritten if rewritten else text

    """
    /*
     * private List<KnowledgeItem> performTwoStageRetrievalAsync(String query) throws Exception {
     *     // fast-track + slow pool split + parallel rerank + rescue score
     *     // TODO: wire to SearchService
     * }
     */
    """
    def _performTwoStageRetrievalAsync(self, query: str) -> List[dict]:
        from search.search_service import getRelevantKnowledge, KnowledgeItem
        from concurrent.futures import as_completed
        import time as _time

        queryStart = _time.time()

        # Java: List<KnowledgeItem> allCandidates = SearchService.getRelevantKnowledge(...)
        allCandidates = getRelevantKnowledge(
            self.tableName, query, self.embeddingClient,
            category_filter=self.currentCategory
        )

        if not allCandidates:
            return []

        logger.debug(self.sinfo + "🔍 检索到的候选列表getRelevantKnowledge: 粗排耗时="
                     + str(int((_time.time() - queryStart) * 1000)) + " ms")
        for item in allCandidates:
            logger.debug(self.sinfo + "距离: " + self.formatDouble(item.distance)
                         + " 分类: " + str(item.category) + " | 摘要: " + str(item.summary))

        # Java: if ("retrieveOnly".equalsIgnoreCase(queryMode)) return subList(0, 3);
        if self.queryMode and self.queryMode.lower() == "retrieveonly":
            logger.debug(self.sinfo + "⚠️ 混合模式性能优化：跳过精排，直接返回粗排结果。")
            return [self._item_to_dict(i) for i in allCandidates[:3]]

        # Java: List<KnowledgeItem> fastTrackItems = new ArrayList<>();
        # Java: List<KnowledgeItem> slowPool = new ArrayList<>();
        fastTrackItems = []
        slowPool       = []

        # Java: for (KnowledgeItem item : allCandidates) { if (distance < trustThreshold) ... }
        for item in allCandidates:
            if item.distance < self.trustThreshold:  #0.25
                # Java: 🚀 [绝对信任] 直接命中，跳过精排
                logger.debug(self.sinfo + "绝对信任 直接命中 距离: "
                             + self.formatDouble(item.distance) + " | 摘要: " + str(item.summary))
                fastTrackItems.append(item)
            elif item.distance < self.rerankTriggerMax: #0.6
                # Java: 🔍 [待定筛选] 送去精排
                slowPool.append(item)

        # Java: if (fastTrackItems.size() >= 1) return fastTrackItems.subList(0, 3);
        if len(fastTrackItems) >= 1:
            logger.debug(self.sinfo + "🚀 [性能熔断] 命中上帝视角条目，直接返回，彻底跳过精排任务。")
            return [self._item_to_dict(i) for i in fastTrackItems[:3]]

        # Java: if (slowPool.isEmpty()) return fastTrackItems;
        if not slowPool:
            logger.debug(self.sinfo + "没有候选需要精排，直接返回已有的 跳过精排任务。")
            return [self._item_to_dict(i) for i in fastTrackItems]

        # Java: needRerankItems = slowPool.stream().limit(maxRerankCandidates).toList();
        needRerankItems = slowPool[:self.maxRerankCandidates] #5

        logger.debug(self.sinfo + "🎯 启动并行精排，样本数: " + str(len(needRerankItems)))
        rerankStart = _time.time()

        # Java: CompletableFuture.runAsync(() -> { calculateSemanticDistance(...) }, rerankExecutor)

        # is equivalent to running this in a background thread:
        # pythonself._rerank_item(query, item, original_dist)
        # The arguments:
        # self._rerank_item — the function to run
        # query — the user's search query string
        # item — the candidate knowledge item to score
        # original_dist — the coarse-ranking distance of that item (saved before reranking overwrites it)

        futures = {}
        for item in needRerankItems:
            original_dist = item.distance
            fut = _rerank_executor.submit(
                self._rerank_item, query, item, original_dist
            )
            futures[fut] = item #fut 代表一个正在后台执行的任务的"凭证"



        # Java: CompletableFuture.allOf(...).get(5, TimeUnit.SECONDS)
# The compensation triggers only when both conditions are met simultaneously:
# original_dist < compensateEmbedMax (0.45): the coarse-ranking distance is very close,
#         meaning the vector search considers it highly relevant
# rerank_dist > compensateRerankMin (0.80): but the reranker gave it a low score,
#         considering it irrelevant
#
# This situation is likely a reranker false negative — the coarse ranking strongly endorses
#     it but the reranker got it wrong.
#     So we force-assign a middle score rescueScore (0.60) to pull it back from elimination and
#     keep it in the final ranking.

# submit(_rerank_item)          # 提交任务
# → _rerank_item()          # 线程里执行
# → _calculateSemanticDistance()  # 计算距离
# → rerank_client.rerank()    # 模型打分
# → return round(1 - score)  # 转成距离
# → return rerank_dist       # _rerank_item 返回距离
# fut.result()                   # 取出这个返回值
# fut.done()      # 任务是否完成（True/False）
# fut.running()   # 任务是否正在运行（True/False）
# fut.cancelled() # 任务是否被取消（True/False）
        try:
            #as_completed 是 Python concurrent.futures 里的一个工具函数
            #传入一组 Future，哪个先算完就先process 哪个，不按提交顺序等待 as_completed 内部盯着所有任务，谁完成了就立刻把谁扔出来，for 循环接住它立即处理，不等其他人
            for fut in as_completed(futures, timeout=self.rerankTimeoutSeconds):
                item        = futures[fut]
                original_dist = item.distance
                try:
                    rerank_dist = fut.result()
                    # Java: if (originalDist < compensateEmbedMax && rerankDist > compensateRerankMin)
                    if original_dist < self.compensateEmbedMax and rerank_dist > self.compensateRerankMin:
                        logger.debug(self.sinfo + "💡 [命中补偿] 摘要: " + str(item.summary)
                                     + " 粗排距离 " + str(original_dist) + " 极优，强制修正精排分。")
                        item.distance = self.rescueScore
                    else:
                        item.distance = rerank_dist
                except Exception as e:
                    logger.debug(self.sinfo + "精排单项异常: " + str(e))
        except Exception:
            logger.error("⚠️ 部分精排任务超时，执行现有结果排序。")

        # Java: finalResults.addAll(fastTrackItems); finalResults.addAll(needRerankItems);
        finalResults = fastTrackItems + needRerankItems

        # Java: finalResults.sort(Comparator.comparingDouble(a -> a.distance));
        finalResults.sort(key=lambda x: x.distance) #lambda 参数: 返回值

        logger.debug(self.sinfo + " rerank检索全链路耗时: "
                     + str(int((_time.time() - rerankStart) * 1000)) + " ms")

        # Java: return finalResults.subList(0, Math.min(finalContextLimit, finalResults.size()));
        #Get the top 3 sorted items, convert each object into a dictionary, and pack them into a list to return
        return [self._item_to_dict(i) for i in finalResults[:self.finalContextLimit]]

    def _rerank_item(self, query: str, item, original_dist: float) -> float:
        """Worker submitted to thread pool — mirrors Java CompletableFuture.runAsync lambda."""
        return self._calculateSemanticDistance(
            query, item.category or "", item.summary or "", item.content or ""
        )

    @staticmethod
    def _item_to_dict(item) -> dict:
        """Convert KnowledgeItem dataclass to dict for uniform downstream handling."""
        return {
            "category": item.category,
            "summary":  item.summary,
            "content":  item.content,
            "distance": item.distance,
        }

    """
    /*
     * private double calculateSemanticDistance(String query, String category,
     *                                           String summary, String content) {
     *     String document = "分类：" + category + "\n摘要：" + summary + "\n内容：" + content;
     *     try {
     *         double score = router.rerank(query, document);
     *         double re    = 1.0 - Math.min(score, 1.0);
     *         logger.debug(sinfo+" Rerank score=" + formatDouble(re) + " category=" + category + ...);
     *         return Math.round(re * 100.0) / 100.0;
     *     } catch (Exception e) { logger.debug(sinfo+" Rerank 异常: " + e.getMessage()); }
     *     return 1.0;
     * }
     */
    """
    def _calculateSemanticDistance(self, query: str, category: str,
                                   summary: str, content: str) -> float:
        document = "分类：" + category + "\n摘要：" + summary + "\n内容：" + content
        try:
            score = self.router.rerank(query, document) if self.router else 0.0
            ## "Score (relevance) → invert → distance. The smaller the final distance, the more relevant — consistent with the coarse-ranking vector distance semantics."
            re    = 1.0 - min(score, 1.0)
            logger.debug(self.sinfo + " Rerank score=" + self.formatDouble(re)
                         + " category=" + category + " summary=" + summary + " 原始评分: " + str(score))
            return round(re * 100.0) / 100.0
        except Exception as e:
            logger.debug(self.sinfo + " Rerank 异常: " + str(e))
        return 1.0

    """
    /*
     * public String executeChitchat(String chitchatIdentity, String query) throws Exception {
     *     this.systemMessage = chitchatIdentity;
     *     history.addMessage("system", systemMessage);
     *     long chatStart = System.currentTimeMillis();
     *     String answer = router.finalLlm().chat(history.toJsonArray());
     *     logger.debug(sinfo+" 闲聊生成耗时: " + (System.currentTimeMillis()-chatStart) + " ms");
     *     return answer;
     * }
     */
    """
    def executeChitchat(self, chitchatIdentity: str, query: str) -> Optional[str]:
        self.systemMessage = chitchatIdentity
        self._history_add("system", self.systemMessage)

        chatStart = time.time()
        try:
            answer = self.router.finalLlm().chat(self.history.toJsonArrayWithWindow()) if self.router else None
        except Exception as e:
            logger.error(self.sinfo + "executeChitchat error: " + str(e))
            answer = None

        logger.debug(self.sinfo + " 闲聊生成耗时: " + str(int((time.time() - chatStart) * 1000)) + " ms")
        return answer

    """
    /*
     * private String executeFinalChat(String fullContext, String optimizedQuery) throws Exception {
     *     setSystemMessage(fullContext);
     *     long chatStart = System.currentTimeMillis();
     *     String jsonPayload = history.toJsonArray().toString();
     *     logger.debug(sinfo+"finalAsk Context 长度: " + jsonPayload.length() + " chars");
     *     String answer = router.finalLlm().chat(history.toJsonArray());
     *     logger.debug(sinfo+" finalAsk 耗时: " + (System.currentTimeMillis()-chatStart) + " ms");
     *     logger.debug(sinfo+" AI应答：" + answer);
     *     return answer;
     * }
     */
    """
    def _executeFinalChat(self, fullContext: str, optimizedQuery: str) -> Optional[str]:
        self.setSystemMessage(fullContext)

        chatStart   = time.time()
        jsonPayload = json.dumps(self.history.toJsonArrayWithWindow(), ensure_ascii=False)
        logger.debug(self.sinfo + "finalAsk Context 长度: " + str(len(jsonPayload)) + " chars")

        try:
            answer = self.router.finalLlm().chat(self.history.toJsonArrayWithWindow()) if self.router else None

        except Exception as e:
            logger.error(self.sinfo + "_executeFinalChat error: " + str(e))
            answer = None

        logger.debug(self.sinfo + " finalAsk 耗时: " + str(int((time.time() - chatStart) * 1000)) + " ms")
        logger.debug(self.sinfo + " AI应答：\n" + str(answer))
        return answer

    # Java: private void recordQueryHistory_nouse(...) — dead code stub
    def _recordQueryHistory_nouse(self, rawText: str, items: list) -> None:
        pass

    """
    /*
     * public void close() {
     *     logger.debug(sinfo+"🗑️ 正在释放 ChatSession 资源...");
     *     if (this.history != null) { this.history = null; }
     *     this.fulltext = null; this.systemMessage = null;
     *     logger.debug(sinfo+"✅ ChatSession 释放完毕。");
     * }
     */
    """
    def close(self) -> None:
        logger.debug(self.sinfo + "🗑️ 正在释放 ChatSession 资源...")
        self.history.clear()
        self.fulltext      = None
        self.systemMessage = None
        logger.debug(self.sinfo + "✅ ChatSession 释放完毕。")

    """
    /*
     * public static void shutdownExecutor() {
     *     if (rerankExecutor != null && !rerankExecutor.isShutdown()) {
     *         logger.debug(sinfo+"🛑 正在关闭 Rerank 线程池...");
     *         rerankExecutor.shutdown();
     *         if (!rerankExecutor.awaitTermination(3, TimeUnit.SECONDS)) rerankExecutor.shutdownNow();
     *     }
     * }
     */
    """
    @staticmethod
    def shutdownExecutor() -> None:
        global _rerank_executor
        logger.debug("🛑 正在关闭 Rerank 线程池...")
        _rerank_executor.shutdown(wait=False)

    """
    /*
     * private double similarity(String a, String b) {
     *     if (a == null || b == null) return 0.0;
     *     String ca = a.replaceAll("[\\pP\\s]", "");
     *     String cb = b.replaceAll("[\\pP\\s]", "");
     *     if (ca.isEmpty() && cb.isEmpty()) return 1.0;
     *     if (ca.isEmpty() || cb.isEmpty()) return 0.0;
     *     int common = 0;
     *     for (char c : ca.toCharArray())
     *         if (cb.contains(String.valueOf(c))) common++;
     *     return (double) common / Math.max(ca.length(), cb.length());
     * }
     */
    """
    @staticmethod
    def _similarity(a: Optional[str], b: Optional[str]) -> float:
        if a is None or b is None: return 0.0
        ca = re.sub(r"[\W_]", "", a)
        cb = re.sub(r"[\W_]", "", b)
        if not ca and not cb: return 1.0
        if not ca or not cb:  return 0.0
        common = sum(1 for c in ca if c in cb)
        return common / max(len(ca), len(cb))

    """
    /*
     * private String filterKnowledgeByCategory(String fulltext, String category) {
     *     if (category == null || category.isBlank()) return "";
     *     return Arrays.stream(fulltext.split("\n"))
     *             .filter(line -> line.contains("||" + category + "||"))
     *             .collect(Collectors.joining("\n"));
     * }
     */
    """
    @staticmethod
    def _filterKnowledgeByCategory(fulltext: str, category: Optional[str]) -> str:
        if not category or not category.strip():
            return ""
        lines = [line for line in fulltext.split("\n") if "||" + category + "||" in line]
        return "\n".join(lines)

    #展开写法
    # result = [] 列表
    # for line in fulltext.split("\n"):
    #     if "||" + category + "||" in line:
    #         result.append(line)
    #
    # return "\n".join(result)
#"\n".join(result) 的意思是：用 \n 把列表里每个元素连接成一个字符串。
# join 做的事
#line1 + "\n" + line2 + "\n" + line3


    """
    /*
     * private static String extractSummary(String content) {
     *     if (content == null || content.isEmpty()) return "";
     *     Pattern pattern = Pattern.compile("【([^】]+)】");
     *     Matcher matcher = pattern.matcher(content);
     *     StringBuilder summary = new StringBuilder();
     *     while (matcher.find()) summary.append(matcher.group(1)).append(" ");
     *     String result = summary.toString().trim();
     *     if (result.isEmpty())
     *         return content.length() > 30 ? content.substring(0, 30) + "..." : content;
     *     return result;
     * }
     */
    """
    @staticmethod
    def _extractSummary(content: Optional[str]) -> str:
        if not content:
            return ""
        matches = re.findall(r"【([^】]+)】", content)
        result  = " ".join(matches).strip()
        if not result:
            return (content[:30] + "...") if len(content) > 30 else content
        return result

    """
    /*
     * public static String formatDouble(double value) {
     *     return String.format("%.2f", value);
     * }
     */
    """
    @staticmethod
    def formatDouble(value: float) -> str:
        return "%.2f" % value

    """
    /*
     * private static String loadPromptFromFile(String filePath, String defauts) {
     *     try {
     *         String content = new String(Files.readAllBytes(Paths.get(filePath)), UTF_8);
     *         content = content.replaceAll("(?s)/\\*.*?\\*/", "");
     *         content = content.replaceAll("//.*", "");
     *         content = content.replaceAll("(?m)^\\s*\\n", "");
     *         return content.trim();
     *     } catch (Exception e) {
     *         logger.error("⚠️ 警告：无法从 " + filePath + " 读取配置，将使用默认 Prompt。原因: " + e.getMessage());
     *         return defauts;
     *     }
     * }
     */
    """
    @staticmethod
    def _loadPromptFromFile(filePath: str, defauts: str) -> str:
        try:
            with open(filePath, "r", encoding="utf-8") as f:
                content = f.read()
            content = re.sub(r"(?s)/\*.*?\*/", "", content)
            content = re.sub(r"//.*", "", content)
            content = re.sub(r"(?m)^\s*\n", "", content)
            return content.strip()
        except Exception as e:
            logger.error("⚠️ 警告：无法从 " + filePath + " 读取配置，将使用默认 Prompt。原因: " + str(e))
            return defauts

    """
    /*
     * private String loadKnowledgeBase(String filePath) {
     *     try {
     *         File file = new File(filePath);
     *         if (!file.exists()) { logger.error("❌ 知识库文件不存在: " + filePath); return ""; }
     *         byte[] bytes = Files.readAllBytes(Paths.get(filePath));
     *         String content = new String(bytes, StandardCharsets.UTF_8);
     *         if (content.length() > 0 && content.charAt(0) == '\uFEFF') content = content.substring(1);
     *         logger.debug("📚 知识库加载成功: " + filePath + " (长度: " + content.length() + " 字符)");
     *         return content.trim();
     *     } catch (IOException e) { logger.error("💥 加载知识库时发生 I/O 异常: " + e.getMessage()); return ""; }
     *     } catch (Exception e)  { logger.error("💥 加载知识库时发生未知错误: " + e.getMessage()); return ""; }
     * }
     */
    """
    def _loadKnowledgeBase(self, filePath: str) -> str:
        import os
        if not os.path.exists(filePath):
            logger.error("❌ 知识库文件不存在: " + filePath)
            return ""
        try:
            with open(filePath, "rb") as f:
                raw = f.read()
            content = raw.decode("utf-8")
            if content.startswith("\uFEFF"):
                content = content[1:]
            logger.debug(self.sinfo + "📚 知识库加载成功: " + filePath + " (长度: " + str(len(content)) + " 字符)")
            return content.strip()
        except IOError as e:
            logger.error("💥 加载知识库时发生 I/O 异常: " + str(e))
            return ""
        except Exception as e:
            logger.error("💥 加载知识库时发生未知错误: " + str(e))
            return ""

    # ── ChatHistory helpers (mirrors Java ChatHistory.addMessage / trim / toPlainText) ──

    def _history_add(self, role: str, content: str) -> None:
        self.history.addMessage(role, content)

    def _history_trim(self, max_size: int) -> None:
        self.history.trim(max_size)

    def _toPlainText(self, windowSize: int) -> str:
        return self.history.toPlainText(windowSize)