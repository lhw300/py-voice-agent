# search/rerank_client.py
# Java: DJLLocalClient.rerank(String query, String document) -> double
import logging
# import os
#
# # 🌟 核心提速：在导入 torch / sentence_transformers 之前，通过环境变量掐死 PyTorch 的多线程风暴
# # 限制底层 OMP/MKL 矩阵计算只允许使用 1~2 个核心，彻底杜绝 CPU 核心之间的死锁冲突
# os.environ["OMP_NUM_THREADS"] = "2"
# os.environ["MKL_NUM_THREADS"] = "2"
#
# import torch
# # 显式在代码层施加线程紧箍咒
# torch.set_num_threads(2)
# torch.set_num_interop_threads(2)
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
        logger.debug("⏳ loading Rerank model: " + model_path)
        self._model = CrossEncoder(model_path)
        logger.debug("✅ Rerank model loaded")
        #logger.info("⏳ 正在预热精排模型 (Warming up Reranker)...")
       # self._model.predict([["warmup", "warmup"]], max_length=16, show_progress_bar=False)
       # logger.info("✅ 精排模型预热完毕")
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
        raw_logit = float(self._model.predict([[query, document]] , show_progress_bar=False    )[0])
        #CrossEncoder 模型输入一对文本 [query, document]，输出一个原始 logit（未归一化的实数，
        #可能是 -5、2.3、8.1 这类任意值）。数值越大表示越相关，但没有固定范围。
        # Java: double temperature = 0.5;
        # Java: double finalScore = 1.0 / (1.0 + Math.exp(-rawLogit / temperature));
        # 这是 Sigmoid 函数，作用是把任意实数压缩到 (0, 1) 区间：
        #
        # raw_logit 很大（很相关）→ final_score 接近 1.0
        # raw_logit 接近 0 → final_score 接近 0.5
        # raw_logit 很小（不相关）→ final_score 接近 0.0
        #
        # temperature = 0.5 是温度系数，控制曲线的陡峭程度。温度越小，曲线越陡，得分分布越极端（更容易接近 0 或 1），区分度更高。

        temperature  = 0.5
        final_score  = 1.0 / (1.0 + math.exp(-raw_logit / temperature))
        return final_score

    def rerank_batch2(self, query: str, documents: list) -> list:
        import math
        pairs = [[query, doc] for doc in documents]
        logger.debug("pairs "+ str(pairs))
        raw_logits = self._model.predict(pairs,max_length=512, show_progress_bar=False, precision="fp16")
        temperature = 0.5
        return [
            round((1.0 - 1.0 / (1.0 + math.exp(-float(logit) / temperature))) * 100.0) / 100.0
            for logit in raw_logits
        ]

        # 🌟 核心打印：让你在日志中清晰看到归一化后的真实得分曲线 (如 [0.97, 0.98, 0.5, 0.5, 0.5])
        logger.debug(f"🚨 精排原始 Logits: {[float(l) for l in raw_logits]} -> 归一化后最终得分: {final_scores}")
        return final_scores

    def rerank_batch(self, query: str, documents: list) -> list:
        import math
        if not documents:
            return []

        pairs = [[query, doc] for doc in documents]
        logger.debug("pairs " + str(pairs))

        # 1. 底层高性能推理
        raw_logits = self._model.predict(pairs, max_length=512, show_progress_bar=False, precision="fp16")

        # 2. 🌟 调整温度系数为 0.05，强行放大微小的语义差距
        temperature = 0.1

        # 3. 计算标准的正向相似度分数 (Score)
        # logit 越大 -> score 越接近 1.0 (高度相关)
        # logit 趋近 0 -> score 越接近 0.5 (不相关)
        scores = [
            1.0 / (1.0 + math.exp(-float(logit) / temperature))
            for logit in raw_logits
        ]

        # 4. 🌟 核心适配：因为外层不改，我们必须在内部把 Score 转化为符合外层排序的小距离 Distance
        # 相似度 0.98 (极好) -> 转换后变成 0.02 (超短距离，满足外层从小到大升序排列)
        # 相似度 0.50 (垃圾) -> 转换后变成 0.50 (远距离，从而被排到最后淘汰)
        final_distances = [
            round((1.0 - score) * 100.0) / 100.0
            for score in scores
        ]

        # 打印黄金日志，方便对齐调试
        logger.debug(f"🚨 精排原始 Logits: {[float(l) for l in raw_logits]} "
                     f"-> 内部临时分 Scores: {[round(s, 2) for s in scores]} "
                     f"-> 最终输出距离 Distances: {final_distances}")

        return final_distances