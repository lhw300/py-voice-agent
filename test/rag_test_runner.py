# test/rag_test_runner.py
#
# RAG end-to-end CI test entry point.
# Mirrors Java RagTestRunner.java — scenarios and question order are identical.
#
# Validation logic (dual check):
#   1. rewrite_keywords : refined_query must contain all keywords (coreference resolution)
#   2. answer_keywords  : final answer must contain all keywords (RAG retrieval correctness)
#   Both pass → PASS, either fails → FAIL
#
# Fill-in guide:
#   - rewrite_keywords = None or [] → skip rewrite check
#   - answer_keywords  = None or [] → skip answer check
#   - Keywords are case-insensitive
#   - "|" separator = OR logic, e.g. "可以|支持|能"
#
# Local run:
#   python test/rag_test_runner.py [config_path]

import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    format="%(levelname)s: %(asctime)s %(name)s:%(lineno)s %(message)s",
    level=logging.DEBUG,
    stream=sys.stdout,
    force=True,
)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

import session.session_manager as session_manager

# Java: private static int totalPass = 0; private static int totalFail = 0;
total_pass = 0
total_fail = 0


# =============================================================================
# Java: static class RagCase { String question; String[] rewriteKeywords; String[] answerKeywords; }
# =============================================================================
@dataclass
class RagCase:
    question:         str
    rewrite_keywords: Optional[List[str]]  # None or [] → skip rewrite check
    answer_keywords:  Optional[List[str]]  # None or [] → skip answer check


# =============================================================================
# Scenario definitions — identical to Java RagTestRunner.java
# =============================================================================

# Java: static RagCase[] scenarioCorrect = { ... };
scenario_correct = [
    RagCase(
        "我是老师，请问那个教师云盘是什么东西？",
        rewrite_keywords=[],
        answer_keywords=["教材", "课件", "小测"],
    ),

    RagCase(
        "那个备课云盘里面都能放些什么资源？",
        rewrite_keywords=["云教案", "资源"],
        answer_keywords=["课件", "数字教材"],
    ),
    RagCase(
        "那在 Windows 10 电脑上能装吗？",
        rewrite_keywords=["Windows"],
        answer_keywords=["可以|支持|能装|是的"],
    ),
]

# Java: static RagCase[] scenarioInherit = { ... };
scenario_inherit = [
    RagCase(
        "我想要参加那个省市级的培训，具体怎么操作？",
        rewrite_keywords=[],
        answer_keywords=["学生", "老师"],
    ),
    RagCase(
        "我是管理员。",
        rewrite_keywords=[],
        answer_keywords=["登录粤教翔云数字教材", "教研天地"],
    ),
    RagCase(
        "那是在哪点击参加？",
        rewrite_keywords=[],
        answer_keywords=["客户端", "教研天地"],
    ),
    RagCase(
        "顺便查下我的初始密码是多少？",
        rewrite_keywords=["管理员", "初始密码"],
        answer_keywords=["下发"],
    ),
    RagCase(
        "如果这个密码忘了该找谁找回？",
        rewrite_keywords=["管理员"],
        answer_keywords=["手机验证码"],
    ),
]

# Java: static RagCase[] scenarioRelation = { ... };
scenario_relation = [
    RagCase(
        "我小孩想登录平台，但不知道账号。",
        rewrite_keywords=[],
        answer_keywords=["身份证号"],
    ),
    RagCase(
        "我是家长",
        rewrite_keywords=None,
        answer_keywords=[],
    ),
    RagCase(
        "他的初始密码是什么？",
        rewrite_keywords=[],
        answer_keywords=["A202101"],
    ),
    RagCase(
        "他如果没绑手机号，密码忘了能自助找回吗？",
        rewrite_keywords=[],
        answer_keywords=["班主任|老师|管理员"],
    ),
    RagCase(
        "这种情况要找谁处理？",
        rewrite_keywords=[],
        answer_keywords=["班主任|老师|管理员"],
    ),
]

# Java: static RagCase[] scenarioBoundary = { ... };
scenario_boundary = [
    RagCase(
        "我是学生，我也想参加那个市级培训。",
        rewrite_keywords=[],
        answer_keywords=["没有|抱歉"],
    ),
    RagCase(
        "苹果手机系统版本低了会报错吗？",
        rewrite_keywords=[],
        answer_keywords=["13"],
    ),
    RagCase(
        "平台支持在 Mac 电脑上用吗？",
        rewrite_keywords=[],
        answer_keywords=[],
    ),
    RagCase(
        "安卓手机版本太低会有影响吗？",
        rewrite_keywords=[],
        answer_keywords=["6"],
    ),
    RagCase(
        "老师参加培训呢?",
        rewrite_keywords=[],
        answer_keywords=[],
    ),
]


# =============================================================================
# Java: public static void main(String[] args)
# =============================================================================
def main():
    global total_pass, total_fail

    client_id = "user_001"

    # Java: config path resolution
    config_path = "e:\\ai"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
        logger.debug("📂 检测到命令行参数，使用配置路径: " + config_path)
    elif os.environ.get("AI_CONFIG_PATH"):
        config_path = os.environ["AI_CONFIG_PATH"]
        logger.debug("📂 使用环境变量路径: " + config_path)
    else:
        logger.debug("ℹ️ 未检测到参数，使用默认路径: " + config_path)

    # Java: SessionManager.init(configPath); SessionManager.warmUp();
    session_manager.init(config_dir=config_path)
    session_manager.warm_up()
# Java: RagCase[][] allScenarios = { scenarioCorrect, scenarioInherit, ... };
    all_scenarios = [
        scenario_correct,
        scenario_inherit,
        scenario_relation,
        scenario_boundary,
    ]
    scenario_names = [
        "Scenario 1: Entity Correction",
        "Scenario 2: Implicit Inheritance",
        "Scenario 3: Anaphora Resolution",
        "Scenario 4: Negative Boundary",
    ]

    # Java: allScenarios2 = { scenarioCorrect } — run subset for now
    all_scenarios2 = [scenario_boundary]

    # Java: for (int s = 0; s < allScenarios2.length; s++) { runScenario(...) }
    for s, cases in enumerate(all_scenarios2[:1]):
        run_scenario(
            client_id + "_scenario_" + str(s + 1),
            scenario_names[s],
            cases,
        )

    # ── Summary ──────────────────────────────────────────────────────────────
    # Java: int total = totalPass + totalFail; double passRate = ...;
    total = total_pass + total_fail
    pass_rate = 0.0 if total == 0 else total_pass / total * 100

    logger.debug("\n" + "═" * 60)
    logger.debug("📊 测试汇总  总计: " + str(total)
                 + "  ✅通过: " + str(total_pass)
                 + "  ❌失败: " + str(total_fail))
    logger.debug("📈 通过率: %.1f%%" % pass_rate)
    logger.debug("═" * 60)

    # Java: double PASS_THRESHOLD = 92;
    PASS_THRESHOLD = 92.0

    if pass_rate >= PASS_THRESHOLD:
        logger.debug("✅ 测试通过！通过率 %.1f%% ≥ %.0f%%" % (pass_rate, PASS_THRESHOLD))
        sys.exit(0)
    else:
        logger.debug("❌ 测试未通过！通过率 %.1f%% < %.0f%%" % (pass_rate, PASS_THRESHOLD))
        sys.exit(1)


# =============================================================================
# Java: private static void runScenario(String sessionId, String scenarioName, RagCase[] cases)
# =============================================================================
def run_scenario(session_id: str, scenario_name: str, cases: List[RagCase]):
    global total_pass, total_fail

    logger.debug("##################################################")
    logger.debug("🚩 正在执行：" + scenario_name)
    logger.debug("##################################################")

    # Java: ChatSession session = SessionManager.getSession(sessionId);
    session = session_manager.get_session(session_id)

    for i, rc in enumerate(cases):
        logger.debug("==================================================")
        logger.debug("👤 轮次 [" + str(i + 1) + "] 提问: " + rc.question)
        logger.debug("⏳ 正在请求 AI 及其重写/检索链路...")

        # Java: long start = System.currentTimeMillis();
        start = time.time()

        # Java: ChatAnswer answer = session.ask(rc.question);
        answer = session.ask(rc.question)

        # Java: long elapsed = System.currentTimeMillis() - start;
        elapsed = int((time.time() - start) * 1000)

        # Java: String rewrittenQuery = answer.intentResult.refinedQuery;
        rewritten_query = ""
        result = session.currentIntentResult
        if result and result.refined_query:
            rewritten_query = result.refined_query

        # Java: String finalAnswer = answer.answer;
        final_answer = answer.answer if answer and answer.answer else ""

        # Java: boolean rewritePass = checkKeywords(...); boolean answerPass = checkKeywords(...);
        rewrite_pass = _check_keywords("rewrite", rc.question, rewritten_query, rc.rewrite_keywords)
        answer_pass  = _check_keywords("answer",  rc.question, final_answer,    rc.answer_keywords)
        passed = rewrite_pass and answer_pass

        if passed:
            total_pass += 1
        else:
            total_fail += 1

        logger.debug("[" + ("PASS" if passed else "FAIL") + "] 轮次 "
                     + str(i + 1) + " | 耗时: " + str(elapsed) + " ms")
        logger.debug("     └─ [重写query]: " + rewritten_query)
        logger.debug("     └─ [AI回答]:   " + final_answer)
        logger.debug("==================================================\n")

        # Java: Thread.sleep(1500); — rate limiting
        time.sleep(1.5)

    logger.debug("✅ 场景执行完毕：" + scenario_name)


# =============================================================================
# Java: private static boolean checkKeywords(String label, String question,
#                                             String target, String[] keywords)
# =============================================================================
def _check_keywords(
    label: str,
    question: str,
    target: str,
    keywords: Optional[List[str]],
) -> bool:
    # Java: if (keywords == null || keywords.length == 0) return true;
    if not keywords:
        return True

    lower_target = target.lower()
    all_match = True

    for kw in keywords:
        # Java: if (kw == null || kw.isEmpty()) continue;
        if not kw:
            continue

        # Java: String[] orOptions = kw.split("\\|");  — OR logic
        or_options = kw.split("|")
        any_hit = any(opt.strip().lower() in lower_target for opt in or_options)

        if not any_hit:
            logger.debug("     ❌ [" + label + "校验失败] 问题: \""
                         + question + "\" | 缺失关键词: \"" + kw + "\"")
            all_match = False

    return all_match


if __name__ == "__main__":
    main()
