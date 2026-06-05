# test/test_cache_runner.py
#
# K1 / K2 cache integration test.
# All queries go through session.ask() — no direct cache calls.
#
# Timing thresholds:
#   K1 hit : intent(~1000ms) + K1(~1ms)              ≈ 1100ms
#   K2 hit : intent(~1000ms) + embed(~300ms) + K2     ≈ 1400ms
#   RAG    : intent(~1000ms) + embed + rerank + LLM   ≈ 3500ms+
#   → cache hit threshold: < 2000ms
#
# Run:
#   python test/test_cache_runner.py [config_path]
# ---------------------------------------------------------------------------

import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.DEBUG,
    stream=sys.stdout,
    force=True,
)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

import session.session_manager as session_manager

# ---------------------------------------------------------------------------
# Threshold: responses under this ms are considered cache hits
# ---------------------------------------------------------------------------
CACHE_HIT_MS = 2000

# ---------------------------------------------------------------------------
# Round 1 — first ask, all go to RAG, write K1 + K2
# Round 2 — exact same questions, expect K1 hit
# Round 3 — paraphrased questions (new session), expect K2 hit
# ---------------------------------------------------------------------------
QUESTIONS = [
    "What are your clinic hours?",
    "Can I get a prescription refill by phone?",
    "Do you accept walk-ins?",
    "How do I book an appointment?",
    "Do you accept insurance?",
]

PARAPHRASES = [
    "Could you tell me when you are open?",
    "Can I renew my medication over the phone?",
    "Can I come in without an appointment?",
    "How can I schedule a visit?",
    "Do you take my insurance?",
]


def _ask(session, question: str) -> tuple[int, str]:
    """Returns (elapsed_ms, answer)."""
    t0 = time.time()
    ca = session.ask(question)
    elapsed = int((time.time() - t0) * 1000)
    answer = ca.answer or ""
    return elapsed, answer


def run(config_dir: str) -> None:
    logger.debug("=" * 60)
    logger.debug("K1/K2 Cache Integration Test")
    logger.debug("=" * 60)

    session_manager.init(config_dir)

    pass_count = 0
    fail_count = 0

    # ------------------------------------------------------------------
    # Round 1 — first ask, expect RAG (slow)
    # ------------------------------------------------------------------
    logger.debug("\n── Round 1: first ask (expected: RAG, slow) ──")
    session1 = session_manager.get_session("cache_test_s1")
    for q in QUESTIONS:
        elapsed, answer = _ask(session1, q)
        is_rag = elapsed >= CACHE_HIT_MS
        status = "PASS" if is_rag else "WARN"
        logger.debug(f"  [{status}] elapsed={elapsed}ms  Q: {q}")
        logger.debug(f"          A: {answer[:70]}...")
        if is_rag:
            pass_count += 1
        else:
            fail_count += 1

    # ------------------------------------------------------------------
    # Round 2 — exact repeat, expect K1 hit (fast)
    # ------------------------------------------------------------------
    logger.debug("\n── Round 2: exact repeat (expected: K1 hit, fast) ──")
    session2 = session_manager.get_session("cache_test_s2")
    for q in QUESTIONS:
        elapsed, answer = _ask(session2, q)
        is_hit = elapsed < CACHE_HIT_MS
        status = "PASS" if is_hit else "FAIL"
        label  = "K1 HIT" if is_hit else "K1 MISS"
        logger.debug(f"  [{status}] [{label}] elapsed={elapsed}ms  Q: {q}")
        if answer:
            logger.debug(f"          A: {answer[:70]}...")
        if is_hit:
            pass_count += 1
        else:
            fail_count += 1

    # ------------------------------------------------------------------
    # Round 3 — paraphrased, new session, expect K2 hit (fast)
    # ------------------------------------------------------------------
    logger.debug("\n── Round 3: paraphrase / new session (expected: K2 hit, fast) ──")
    session3 = session_manager.get_session("cache_test_s3")
    for q in PARAPHRASES:
        elapsed, answer = _ask(session3, q)
        is_hit = elapsed < CACHE_HIT_MS
        status = "PASS" if is_hit else "FAIL"
        label  = "K2 HIT" if is_hit else "MISS"
        logger.debug(f"  [{status}] [{label}] elapsed={elapsed}ms  Q: {q}")
        if answer:
            logger.debug(f"          A: {answer[:70]}...")
        if is_hit:
            pass_count += 1
        else:
            fail_count += 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    total     = pass_count + fail_count
    pass_rate = pass_count / total * 100 if total else 0

    logger.debug("\n" + "=" * 60)
    logger.debug(f"Total: {total}  PASS: {pass_count}  FAIL: {fail_count}")
    logger.debug(f"Pass rate: {pass_rate:.1f}%")
    logger.debug("=" * 60)


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "e:/ai"
    run(config_path)