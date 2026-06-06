# test/test_cache_runner.py
#
# K1 / K2 cache integration test.
# All queries go through session.ask() — no direct cache calls.
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


def _ask(session, question: str) -> tuple[int, str, str]:
    t0 = time.time()
    ca = session.ask(question)
    elapsed = int((time.time() - t0) * 1000)
    return elapsed, ca.answer or "", getattr(ca, "hit_source", "rag")


def run(config_dir: str) -> None:
    logger.debug("=" * 60)
    logger.debug("K1/K2 Cache Integration Test")
    logger.debug("=" * 60)

    session_manager.init(config_dir)

    pass_count = 0
    fail_count = 0
    k1_count   = 0
    k2_count   = 0
    rag_count  = 0
    k1_times   = []
    k2_times   = []
    rag_times  = []
    test_start = time.time()

    # ------------------------------------------------------------------
    # Round 1 — warm up cache
    # ------------------------------------------------------------------
    logger.debug("\n── Round 1: warm up cache ──")
    session1 = session_manager.get_session("cache_test_s1")
    for q in QUESTIONS:
        elapsed, answer, hit_source = _ask(session1, q)
        if hit_source == "k1":
            k1_count += 1
            k1_times.append(elapsed)
            label = "K1 HIT"
        elif hit_source == "k2":
            k2_count += 1
            k2_times.append(elapsed)
            label = "K2 HIT"
        else:
            rag_count += 1
            rag_times.append(elapsed)
            label = "RAG"
        logger.debug(f"  [{label}] elapsed={elapsed}ms  Q: {q}")
        logger.debug(f"          A: {answer[:70]}...")

    # ------------------------------------------------------------------
    # Round 2 — exact repeat, expect K1 hit
    # ------------------------------------------------------------------
    logger.debug("\n── Round 2: exact repeat (expected: K1 hit) ──")
    session2 = session_manager.get_session("cache_test_s2")
    for q in QUESTIONS:
        elapsed, answer, hit_source = _ask(session2, q)
        if hit_source in ("k1", "k2"):
            k1_count += 1
            k1_times.append(elapsed)
            pass_count += 1
            status = "PASS"
            label  = hit_source.upper() + " HIT"
        else:
            rag_count += 1
            rag_times.append(elapsed)
            fail_count += 1
            status = "FAIL"
            label  = "RAG"
        logger.debug(f"  [{status}] [{label}] elapsed={elapsed}ms  Q: {q}")
        if answer:
            logger.debug(f"          A: {answer[:70]}...")

    # ------------------------------------------------------------------
    # Round 3 — paraphrased, expect K2 (or K1 via rewrite)
    # ------------------------------------------------------------------
    logger.debug("\n── Round 3: paraphrase / new session (expected: K2 hit) ──")
    session3 = session_manager.get_session("cache_test_s3")
    for q in PARAPHRASES:
        elapsed, answer, hit_source = _ask(session3, q)
        if hit_source == "k1":
            k1_count += 1
            k1_times.append(elapsed)
            pass_count += 1
            status = "PASS"
            label  = "K1 HIT"
        elif hit_source == "k2":
            k2_count += 1
            k2_times.append(elapsed)
            pass_count += 1
            status = "PASS"
            label  = "K2 HIT"
        else:
            rag_count += 1
            rag_times.append(elapsed)
            fail_count += 1
            status = "FAIL"
            label  = "RAG"
        logger.debug(f"  [{status}] [{label}] elapsed={elapsed}ms  Q: {q}")
        if answer:
            logger.debug(f"          A: {answer[:70]}...")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    total_elapsed = int((time.time() - test_start) * 1000)
    total         = pass_count + fail_count
    pass_rate     = pass_count / total * 100 if total else 0
    total_qs      = k1_count + k2_count + rag_count
    hit_rate      = (k1_count + k2_count) / total_qs * 100 if total_qs else 0

    def avg(lst): return int(sum(lst) / len(lst)) if lst else 0

    logger.debug("\n" + "=" * 60)
    logger.debug("Cache Hit Summary")
    logger.debug(f"  K1 hits : {k1_count:3d}   avg {avg(k1_times):5d}ms")
    logger.debug(f"  K2 hits : {k2_count:3d}   avg {avg(k2_times):5d}ms")
    logger.debug(f"  RAG     : {rag_count:3d}   avg {avg(rag_times):5d}ms")
    logger.debug("-" * 60)
    logger.debug(f"  Total questions : {total_qs}")
    logger.debug(f"  Cache hit rate  : {hit_rate:.1f}%  (K1+K2 / total)")
    logger.debug(f"  PASS/FAIL       : {pass_count} / {fail_count}   ({pass_rate:.1f}%)")
    logger.debug(f"  Total elapsed   : {total_elapsed}ms")
    logger.debug("=" * 60)


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "e:/ai"
    run(config_path)