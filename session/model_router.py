# search/model_router.py
# Java: package com.lcallai;
import logging
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

    def __init__(self, rewriter_client, rerank_client, final_llm_client):
        # Java: this.rewriter  = rewriter;
        self._rewriter   = rewriter_client
        # Java: this.reranker  = reranker;   (local CrossEncoder in hybrid mode)
        self._reranker   = rerank_client
        # Java: this.finalLlm  = finalLlm;
        self._final_llm  = final_llm_client
        self._rerank_prompt: Optional[str] = None

    """
    public LlmClient rewriter() { return rewriter; }
    """
    def rewriter(self):
        return self._rewriter

    """
    public LlmClient finalLlm() { return finalLlm; }
    """
    def finalLlm(self):
        return self._final_llm

    """
    public double rerank(String query, String document) {
        // hybrid mode: local CrossEncoder
        return reranker.rerank(query, document);
    }
    """
    def rerank(self, query: str, document: str) -> float:
        return self._reranker.rerank(query, document)
    def rerank_batch(self, query: str, documents: list) -> list:
        return self._reranker.rerank_batch(query, documents)
    """
    public void setRerankPrompt(String prompt) { this.rerankPrompt = prompt; }
    """
    def setRerankPrompt(self, prompt: str) -> None:
        self._rerank_prompt = prompt
