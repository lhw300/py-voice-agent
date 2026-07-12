# search/model_router.py
# Java: package com.lcallai;
import logging
import time as _time
from typing import Optional

logger = logging.getLogger(__name__)


class ModelRouter:
    """
    public class ModelRouter {
        private final LlmClient rewriter;
        private final LlmClient reranker;   // used as LLM reranker
        private final LlmClient finalLlm;

        public ModelRouter(LlmClient rewriter, LlmClient reranker, LlmClient finalLlm) { ... }
        public LlmClient rewriter()  { return rewriter;  }
        public LlmClient finalLlm()  { return finalLlm;  }
        public double rerank(String query, String document) { ... }
        public void setRerankPrompt(String prompt) { ... }
    }

    Python note:
      reranker here is RerankClient (local CrossEncoder), not LlmClient.
      rewriter / finalLlm are LlmClient instances (from session_manager.py).
    """

    def __init__(self, rewriter_client, rerank_client, final_llm_client,
                 skill_router_client=None, embed_client=None):
        self._rewriter      = rewriter_client
        self._reranker       = rerank_client
        self._final_llm      = final_llm_client
        self._skill_router    = skill_router_client if skill_router_client is not None else final_llm_client
        self._embed           = embed_client                    # 新增
        self._rerank_prompt: Optional[str] = None

    def rewriter(self):
        return self._rewriter

    def skillRouter(self):
        return self._skill_router

    def finalLlm(self):
        return self._final_llm

    def embed(self):                                            # 新增
        return self._embed

    def rerank(self, query: str, document: str) -> float:
        return self._reranker.rerank(query, document)

    def rerank_batch(self, query: str, documents: list) -> list:
        return self._reranker.rerank_batch(query, documents)

    def setRerankPrompt(self, prompt: str) -> None:
        self._rerank_prompt = prompt

    # ★ 新增：统一预热入口 ★
    def warmUp(self) -> None:
        total_start = _time.time()

        def _warm(name, fn):
            try:
                t = _time.time()
                fn()
                logger.debug(f"✅ {name} warm-up done  t={int((_time.time() - t) * 1000)}ms")
            except Exception as e:
                logger.error(f"⚠️ {name} warm-up failed: {e}")

        if self._rewriter:
            _warm("rewriter", lambda: self._rewriter.generate("Output json.", 'respond with json: {"ok":1}'))

        if self._reranker:
            _warm("rerank", lambda: self.rerank("Beijing", "Beijing is the capital of China."))

        if self._final_llm:
            _warm("finalLlm", lambda: self._final_llm.generate("Output json.", 'respond with json: {"ok":1}'))

        if self._skill_router:
            dummy_tool = [{
                "type": "function",
                "function": {
                    "name": "warmup_probe",
                    "description": "内部预热探针，忽略",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }]
            _warm("skillRouter(chat_with_tools)", lambda: self._skill_router.chat_with_tools(
                [{"role": "user", "content": "hello"}], tools=dummy_tool, tool_choice="auto"
            ))

        if self._embed:
            _warm("embed", lambda: self._embed.embed("hello"))
        else:
            logger.debug("⏭️  embed warm-up skipped: embed_client not set on router")

        logger.debug(f"✅ full router warm-up complete  total={int((_time.time() - total_start) * 1000)}ms")