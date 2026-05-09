# search/rerank_client.py
# Java: DJLLocalClient.rerank(String query, String document) -> double
import logging

logger = logging.getLogger(__name__)


class RerankClient:
    """
    Mirrors Java DJLLocalClient rerank functionality.
    Model: bge-reranker-v2-m3
    loaded from AiConfig: djl.model.rerank.name + configPath

    Java:
    public double rerank(String query, String document) {
        float rawLogit = predictor.predict(new String[]{query, document});
        double temperature = 0.5;
        double finalScore  = 1.0 / (1.0 + Math.exp(-rawLogit / temperature));
        return finalScore;
    }
    """

    def __init__(self, model_path: str):
        from sentence_transformers import CrossEncoder
        logger.debug("⏳ 正在加载 Rerank 模型: " + model_path)
        self._model = CrossEncoder(model_path)
        logger.debug("✅ Rerank 模型加载完成")

    """
    public double rerank(String query, String document) {
        float rawLogit     = predictor.predict(new String[]{query, document});
        double temperature = 0.5;
        double finalScore  = 1.0 / (1.0 + Math.exp(-rawLogit / temperature));
        return finalScore;
    }
    """
    def rerank(self, query: str, document: str) -> float:
        import math
        # Java: float rawLogit = predictor.predict(new String[]{query, document});
        raw_logit = float(self._model.predict([[query, document]])[0])

        # Java: double temperature = 0.5;
        # Java: double finalScore = 1.0 / (1.0 + Math.exp(-rawLogit / temperature));
        temperature  = 0.5
        final_score  = 1.0 / (1.0 + math.exp(-raw_logit / temperature))

        return final_score
