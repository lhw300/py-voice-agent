# intent_test_runner.py
#
# Mirrors Java IntentTestRunner.java
#
# Local run:
#   python intent_test_runner.py [config_path]
#
# Config path priority:
#   1. Command-line argument sys.argv[1]
#   2. Environment variable AI_CONFIG_PATH
#   3. Default value e:\ai  (local dev fallback)

import logging
import os
import sys
import uuid
import sys, os
import ai_config as AiConfig
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


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# __file__
# # 当前文件的绝对路径
# # E:\EIT\py-LLM-integration\test\intent_test_runner.py
#
# os.path.abspath(__file__)
# # 转成绝对路径（已经是绝对路径，这里主要是做规范化）
# # E:\EIT\py-LLM-integration\test\intent_test_runner.py
# os.path.dirname(os.path.abspath(__file__))
# # 取上一级目录 → test/ 的父目录是什么？不对，dirname 是取当前文件所在目录
# # E:\EIT\py-LLM-integration\test
# os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# # 再取一次上级目录
# # E:\EIT\py-LLM-integration   ← 项目根目录
# sys.path.insert(0, ...)
# # 把项目根目录插入到 Python 模块搜索路径的第一位
# # Python import 时会优先从这里找

# Java: private static int totalPass = 0; private static int totalFail = 0;
total_pass = 0
total_fail = 0


# =============================================================================
# Java: public static void main(String[] args)
# =============================================================================
def main():
    global total_pass, total_fail

    # Java: config path resolution
    config_path = "e:\\ai"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
        logger.debug("📂 Command-line argument detected, using config path: " + config_path)
    elif os.environ.get("AI_CONFIG_PATH"):
        config_path = os.environ["AI_CONFIG_PATH"]
        logger.debug("📂 Using environment variable path: " + config_path)
    else:
        logger.debug("ℹ️ No argument detected, using default path: " + config_path)

    # Java: SessionManager.init(configPath);
    session_manager.init(config_dir=config_path)
    logger.debug("=== Automated Intent Dispatch Test (based on SessionManager built-in registry) ===\n")

    # =========================================================================
    # Test data — identical to Java IntentTestRunner.java
    # =========================================================================

    greeting_tests = [
        # 1. Standard greeting (simplest case)
        ["你好",               "GREETING"],
        ["Hello",             "GREETING"],
        ["嗨，有人在吗？",      "GREETING|CHITCHAT"],
        # 2. Time-sensitive
        ["早上好，今天心情不错。", "GREETING|CHITCHAT"],
        ["晚安，辛苦了。",       "GREETING|ACK|COMMAND"],
        # 3. Strong emotion / colloquial
        ["哈喽哇！小助手，我想死你啦！", "GREETING|CHITCHAT"],
        ["喂？能听到我说话吗？",         "GREETING"],
        # 4. Boundary test
        ["你好，帮我查下流量。",   "QUERY"],
        ["早安，Win11怎么激活？", "QUERY"],
    ]

    ack_tests = [
        # Case A: Affirmative reply (affirm)
        ["是的",       "ACK"],
        ["对，就是这个", "ACK"],
        ["没错，请执行", "ACK"],
        ["确认安装",    "ACK|COMMAND"],
        # Case B: Negative / rejection (negate)
        ["不，不是这个", "ACK"],
        ["不用了，谢谢", "ACK"],
        ["取消操作",    "ACK"],
        ["不需要",      "ACK"],
        # Case C: General acknowledgement (ack)
        ["好的",   "ACK"],
        ["嗯",     "ACK"],
        ["知道了", "ACK"],
        ["行吧",   "ACK"],
    ]

    command_tests = [
        # Case A: Standard hit (exact enum match)
        ["帮我转人工服务。",   "COMMAND"],
        ["声音太小了，大声点。", "COMMAND"],
        ["调低音量。",         "COMMAND"],
        ["刚才那段再放一遍。", "COMMAND"],
        # Case B: Semantic generalization
        ["找个真人来跟我说话。", "COMMAND"],
        ["吵死了，小声些。",    "COMMAND|FEEDBACK"],
        ["重新播放。",          "COMMAND"],
        # Case C: Out-of-scope commands (falls back to QUERY)
        ["帮我查一下话费流量。", "QUERY"],
        ["帮我重启一下宽带猫。", "QUERY|COMMAND"],
        ["打开电视机。",         "QUERY|COMMAND"],
        # Case D: Compound intent
        ["你好，请帮我转人工。",   "COMMAND"],
        ["太感谢了，再播放一次吧。", "COMMAND"],
    ]

    inform_tests = [
        # Case A: Contact info
        ["我的手机号是13800138000。", "INFORM"],
        ["我叫张三。",               "INFORM"],
        ["你可以拨打 021-66668888 联系我。", "INFORM"],
        # Case B: Location / address
        ["我家在上海市浦东新区张江路1号。",    "INFORM"],
        ["宽带安装地址是锦绣路100弄3号楼。", "INFORM|QUERY"],
        # Case C: Fault description
        ["我的光猫红灯一直在闪。", "INFORM|QUERY|FEEDBACK"],
        ["家里断网快半小时了。",   "INFORM|QUERY"],
        ["报错代码是 691。",       "INFORM|QUERY"],
        # Case D: Correction
        ["不对，刚才那个地址写错了，应该是2号楼。", "INFORM"],
        ["改一下，手机号尾号是 5678。",           "INFORM"],
    ]

    feedback_tests = [
        # Case A: Positive
        ["你们的客服态度真好，赞一个！", "FEEDBACK"],
        ["问题解决了，小助手很给力。",  "FEEDBACK"],
        ["非常感谢，帮了大忙了。",      "FEEDBACK"],
        # Case B: Negative
        ["这软件太卡了，简直没法用。",    "FEEDBACK"],
        ["等了半天没人理，差评！",        "FEEDBACK"],
        ["你们的收费极其不合理，我要投诉。", "FEEDBACK"],
        # Case C: Neutral / functional
        ["界面要是能再简洁点就好了。", "FEEDBACK"],
        ["我觉得这个颜色有点刺眼。",   "FEEDBACK"],
        # Case D: Boundary
        ["太慢了，赶紧帮我转人工！", "COMMAND"],
        ["为什么你们的系统总报错？", "QUERY"],
    ]

    chitchat_tests = [
        # Case A: Pure casual chat
        ["你今天心情怎么样？",     "CHITCHAT"],
        ["今天天气真不错，适合出去玩。", "CHITCHAT"],
        ["你觉得 AI 会取代人类吗？",    "CHITCHAT|QUERY"],
        # Case B: Meaningless filler
        ["哈哈哈哈哈哈。", "CHITCHAT"],
        ["呃，让我想想。", "CHITCHAT|ACK"],
        ["哦吼。",         "CHITCHAT"],
        # Case C: Humor
        ["讲个笑话听听。", "CHITCHAT"],
        ["你吃饭了吗？",   "CHITCHAT"],
        # Case D: Boundary CHITCHAT vs QUERY
        ["北京的首都是哪里？", "CHITCHAT|QUERY"],
        ["Win10 是哪年发布的？", "QUERY"],
        ["你好帅啊。",           "CHITCHAT|FEEDBACK"],
    ]

    stress_data = [
        ["你好",             "GREETING"],
        ["我是李老师",        "INFORM"],
        ["怎么重置密码？",    "QUERY"],
        ["太感谢了，帮了大忙！", "FEEDBACK"],
        ["讲个笑话吧",        "CHITCHAT"],
        ["再见",              "COMMAND"],
    ]

    stress_data2 = [
        ["你好",           "GREETING"],
        ["我是李老师",      "INFORM"],
        ["怎么重置密码？",  "QUERY"],
        ["讲个笑话吧",      "CHITCHAT"],
        ["你会写 Java 吗？", "CHITCHAT|QUERY"],
        ["声音太小了，大声一点", "COMMAND"],
        ["帮我转接人工客服",    "COMMAND"],
        ["刚才那个密码不对，你们这系统真行", "FEEDBACK"],
        ["好的，我知道了", "ACK"],
        ["再见",           "COMMAND"],
    ]

    stress_data3 = [
        ["你好",       "GREETING"],
        ["我是李老师",  "INFORM"],
        ["怎么重置密码？", "QUERY"],
        ["我没听清楚",    "COMMAND"],
        ["你说什么",      "COMMAND"],
    ]

    stress_data4 = [
        # REPLAY boundary: colloquial variants
        ["什么",         "COMMAND|QUERY"],
        ["啊？",         "COMMAND"],
        ["能再说一遍吗",  "COMMAND"],
        ["刚才你说的是什么", "COMMAND"],
        # REPLAY vs CHITCHAT boundary
        ["你好",     "GREETING"],
        ["你说什么", "COMMAND"],
    ]

    # Scenario 1: Extreme off-topic and forced pull-back
    stress_data5 = [
        ["你好",                       "GREETING"],
        ["我是李老师",                  "INFORM"],
        ["你觉得今天天气怎么样？适合备课吗？", "CHITCHAT|QUERY"],
        ["你平时都吃什么牌子的电量？",   "CHITCHAT"],
        ["算了不扯了，老师的初始密码是多少来着？", "QUERY"],
    ]

    # Scenario 2: Emotional outburst and transfer after soothing
    stress_data6 = [
        ["你好，我是李老师",                         "GREETING|INFORM"],
        ["我想查一下怎么重置密码",                   "QUERY"],
        ["你们这系统太垃圾了，密码根本不对，快给我找个活人！", "COMMAND"],
    ]

    # Scenario 3: Coreference resolution and colloquial replay
    stress_data7 = [
        ["你好，我是李老师，请问怎么重置密码？", "QUERY"],
        ["什么？",           "COMMAND"],
        ["没听清，你再说一遍", "COMMAND"],
    ]

    # Scenario 4: Multi-identity confusion and fail-safe design
    stress_data8 = [
        ["你好，我是老师",             "INFORM"],
        ["怎么重置密码？",             "QUERY"],
        ["那我们班学生的初始密码是多少？", "QUERY"],
    ]
    fast_track_tests = [
        # REPLAY
        ["什么",         "COMMAND"],
        ["啊？",         "COMMAND"],
        ["再说一遍",      "COMMAND"],
        ["没听清",       "COMMAND"],
        ["听不清",       "COMMAND"],
        ["你说什么",      "COMMAND"],
        ["刚才说什么",    "COMMAND"],
        ["能再说一遍吗",  "COMMAND"],

        # HANGUP
        ["再见",   "COMMAND"],
        ["拜拜",   "COMMAND"],
        ["不聊了", "COMMAND"],
        ["挂了",   "COMMAND"],

        # TRANSFER
        ["转人工", "COMMAND"],
        ["找真人", "COMMAND"],
        ["转客服", "COMMAND"],

        # VOL
        ["大声点",   "COMMAND"],
        ["小声点",   "COMMAND"],
        ["音量调大", "COMMAND"],
        ["音量调小", "COMMAND"],

        # GREETING
        ["你好",  "GREETING"],
        ["您好",  "GREETING"],
        ["hello", "GREETING"],
        ["嗨",    "GREETING"],

        # ACK affirm
        ["是的",  "ACK"],
        ["对的",  "ACK"],
        ["没错",  "ACK"],
        ["确认",  "ACK"],

        # ACK negate
        ["不用了", "ACK"],
        ["不是",   "ACK"],
        ["不对",   "ACK"],
        ["取消",   "ACK"],

        # ACK plain
        ["好的",   "ACK"],
        ["嗯",     "ACK"],
        ["知道了", "ACK"],
    ]

# 混合测试用例
# 4 Sessions，每个 Session 为独立对话，测试时需重新建立 session

    # Session 1 — 全链路业务连贯性测试
    session1 = [
        ["你好",                             "GREETING"],
        ["我是李老师",                        "INFORM"],
        ["怎么重置密码？",                     "QUERY"],
        ["讲个笑话吧",                        "CHITCHAT"],
        ["声音太小了，大声一点",               "COMMAND"],
        ["刚才那个密码不对，你们这系统真行",    "FEEDBACK"],
        ["好的，我知道了",                    "ACK"],
        ["再见",                             "COMMAND"],
    ]

    # Session 2 — REPLAY 重播极简口语边界测试
    session2 = [
        ["你好",                              "GREETING"],
        ["你说什么",                          "CHITCHAT"],   # ⚠️ 机器人未作答，绝不能触发 REPLAY
        ["你好，我是李老师，请问怎么重置密码？", "QUERY"],
        ["什么",                             "COMMAND"],    # 机器人刚回复 → 必须触发 ACTION_REPLAY
        ["啊？",                             "COMMAND"],
        ["刚才你说的是什么",                   "COMMAND"],
        ["还是转人工服务吧，你说不明白",        "COMMAND"],
    ]

    # Session 3 — 极限歪楼与强行拉回
    session3 = [
        ["你好，我是李老师",                       "INFORM"],
        ["你觉得今天天气怎么样？适合备课吗？",     "CHITCHAT"],
        ["你平时都吃什么牌子的电量？",            "CHITCHAT"],
        ["算了不扯了，老师的初始密码是多少来着？", "QUERY"],
    ]

    # Session 4 — 多身份隔离防呆设计
    session4 = [
        ["你好，我是李老师",              "INFORM"],
        ["怎么重置密码？",                "QUERY"],
        ["那我们班学生的初始密码是多少？", "QUERY"],
    ]


    # =========================================================================
    # Run suites — uncomment to enable each suite
    # =========================================================================
    # run_suite("GREETING Suite",    greeting_tests)
    # run_suite("ACK Suite",         ack_tests)
    # run_suite("COMMAND Suite",     command_tests)
    # run_suite("INFORM Suite",      inform_tests)
    # run_suite("FEEDBACK Suite",    feedback_tests)
    # run_suite("CHITCHAT Suite",    chitchat_tests)
    # run_suite("Mixed Scenario stressData",  stress_data)
    # run_suite("Mixed Scenario stressData2", stress_data2)
    # run_suite("Mixed Scenario stressData3 (REPLAY Colloquial)",       stress_data3)
    # run_suite("Mixed Scenario stressData4 (REPLAY Extreme Variants)", stress_data4)
    # run_suite("Mixed Scenario stressData5 (Extreme Off-topic)",       stress_data5)
    # run_suite("Mixed Scenario stressData6 (Emotional Outburst + Command Priority)", stress_data6)
    # run_suite("Mixed Scenario stressData7 (Colloquial Replay Boundary)", stress_data7)
    #
    run_suite("Mixed test", session4)

    # =========================================================================
    # Java: Summary — pass/fail determined by pass rate
    # =========================================================================
    total = total_pass + total_fail
    pass_rate = 0.0 if total == 0 else total_pass / total * 100

    logger.debug("\n" + "═" * 60)
    logger.debug("📊 Intent Classification Test Summary  Total: " + str(total)
                 + "  ✅Pass: " + str(total_pass)
                 + "  ❌Fail: " + str(total_fail))
    logger.debug("📈 Pass rate: " + "%.1f%%" % pass_rate)
    logger.debug("═" * 60)

    # Java: double PASS_THRESHOLD = 92;
    PASS_THRESHOLD = 92.0

    if pass_rate >= PASS_THRESHOLD:
        logger.debug("✅  Intent Classification Tests passed! Pass rate %.1f%% >= %.0f%%" % (pass_rate, PASS_THRESHOLD))
        sys.exit(0)
    else:
        logger.debug("❌ Tests failed! Pass rate %.1f%% < %.0f%%" % (pass_rate, PASS_THRESHOLD))
        sys.exit(1)


# =============================================================================
# Java: private static void runSuite(String suiteName, String[][] testData)
# =============================================================================
def run_suite(suite_name: str, test_data: list):
    global total_pass, total_fail

    logger.debug("\n" + "─" * 60)
    logger.debug("🧪 Suite: " + suite_name)
    logger.debug("─" * 60)

    # Java: String sessionId = "SESSION_" + UUID.randomUUID().toString().substring(0, 8);
    session_id = "" + str(uuid.uuid4())[:4].upper()

    # Java: ChatSession session = SessionManager.getSession(sessionId);
    session = session_manager.get_session(session_id)

    for test in test_data:
        user_input      = test[0]
        expected_intent = test[1]

        logger.debug("=" * 50)
        logger.debug("👤 User input: " + user_input + " | Expected intent: " + expected_intent)

        # Java: ChatAnswer ca = session.ask(userInput);
        ca = session.ask(user_input)

        # Java: IntentResult result = ca.intentResult;
        result = session.currentIntentResult

        if result is not None:
            # Java: String actual = result.intent.name();
            actual = result.intent.value

            # Java: boolean pass = Arrays.asList(expectedIntent.split("\\|")).contains(actual);
            pass_flag = actual in expected_intent.split("|")

            if pass_flag:
                total_pass += 1
            else:
                total_fail += 1

            logger.debug("[" + ("PASS" if pass_flag else "FAIL") + "] "
                         + "Recognized intent: %-10s" % actual
                         + " | Expected intent: " + expected_intent)

            if result.refined_query:
                logger.debug("     └─ [Refined query]: " + result.refined_query)
            if result.sub_intent:
                logger.debug("     └─ [Sub-intent]: " + result.sub_intent)
            if result.action_code:
                logger.debug("     └─ [Action code]: " + result.action_code)
            from intent.intent_result import Sentiment
            if result.sentiment != Sentiment.NEUTRAL:
                logger.debug("     └─ [Sentiment]: " + result.sentiment.value)
        else:
            total_fail += 1
            logger.debug("[FAIL] intentResult is null")

        logger.debug("     └─ [Status code]: " + str(ca.code))
        logger.debug("     └─ [Action]: " + str(ca.action))
        logger.debug("     └─ [AI reply]: " + str(ca.answer))
        logger.debug("-" * 50)


if __name__ == "__main__":
    main()
