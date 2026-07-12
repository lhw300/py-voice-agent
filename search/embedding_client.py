# search/embedding_client.py
# Java: interface EmbeddingClient { double[] embed(String text); int getDimension(); }
import logging
import os
from typing import List

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """
    public interface EmbeddingClient {
        double[] embed(String text) throws Exception;
        int getDimension();
        String modeType();
    }
    Implemented here using sentence-transformers (replaces Java DJLLocalClient).
    Model: text2vec-base-chinese-paraphrase-pt (768-dim)
    loaded from AiConfig: djl.model.embed.name + configPath
    """

    def __init__(self, model_path: str):
        """
        Java: DJLLocalClient() reads model path from AiConfig.
        Python: model_path passed in directly from SessionManager after AiConfig read.
        """
        from sentence_transformers import SentenceTransformer
        logger.debug("⏳ loading Embedding model: " + model_path)
        self._model = SentenceTransformer(model_path)
        self._model_path = model_path                                          # 补上这行
        self._model_name = os.path.basename(model_path.rstrip("/\\"))          # 补上这行
        self._dimension = len(self._model.encode("test"))
        logger.debug("✅ Embedding model loaded, dimension=" + str(self._dimension) + " device=" + str(next(self._model.parameters()).device))

        """
    public double[] embed(String text) throws Exception {
        try (var predictor = model.newPredictor()) {
            float[] fVec = predictor.predict(text);
            double[] dVec = new double[fVec.length];
            for (int i = 0; i < fVec.length; i++) dVec[i] = fVec[i];
            return dVec;
        }
    }
    """
    def embed(self, text: str) -> List[float]:
        # Java: returns double[] — Python returns list of float
        vec = self._model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    """
    public int getDimension() { return 768; }
    """
    def getDimension(self) -> int:
        return self._dimension

    """
    public String modeType() { return "local"; }
    """
    def modeType(self) -> str:
        return "local"
    def describe(self) -> str:                            # ← 新增：统一描述接口
        return f"local:{self._model_name} (dim={self._dimension})"
class CloudEmbeddingClient:
    """
    Cloud embedding via Aliyun text-embedding-v3 (1024-dim)
    Mirrors Java OllamaClient used as EmbeddingClient
    """
    def __init__(self, client, model: str = "text-embedding-v3", dimensions: int = 1024):
        self._client     = client
        self._model      = model
        self._dim        = dimensions

    def embed(self, text: str) -> list:
        response = self._client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=self._dim,
            encoding_format="float"
        )
        return response.data[0].embedding

    def getDimension(self) -> int:
        return self._dim

    def modeType(self) -> str:
        return "cloud"
    def describe(self) -> str:                             # ← 新增
        return f"cloud:{self._model} (dim={self._dim})"