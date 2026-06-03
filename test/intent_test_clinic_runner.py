# intent_test_clinic_runner.py
#
# English Clinic — Intent Classification Test Runner
# Mirrors the structure of intent_test_runner.py, all test cases replaced
# with English Clinic business scenarios.
#
# Local run:
#   python intent_test_clinic_runner.py [config_path]
#
# Config path priority:
#   1. Command-line argument sys.argv[1]
#   2. Environment variable AI_CONFIG_PATH
#   3. Default value e:\ai  (local dev fallback)

import logging
import os
import sys
import uuid

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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import session.session_manager as session_manager

total_pass = 0
total_fail = 0


# =============================================================================
# main
# =============================================================================
def main():
    global total_pass, total_fail

    config_path = "e:\\ai"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
        logger.debug("📂 Command-line argument detected, using config path: " + config_path)
    elif os.environ.get("AI_CONFIG_PATH"):
        config_path = os.environ["AI_CONFIG_PATH"]
        logger.debug("📂 Using environment variable path: " + config_path)
    else:
        logger.debug("ℹ️  No argument detected, using default path: " + config_path)

    session_manager.init(config_dir=config_path)
    logger.debug("=== English Clinic — Intent Classification Test ===\n")

    # =========================================================================
    # Unit test suites  (each runs in its own fresh session)
    # =========================================================================

    # ------------------------------------------------------------------
    # GREETING
    # ------------------------------------------------------------------
    greeting_tests = [
        # Standard
        ["Hello",                        "GREETING"],
        ["Hi there",                     "GREETING"],
        ["Good morning",                 "GREETING"],
        ["Good afternoon",               "GREETING"],
        ["Hey, is anyone there?",        "GREETING"],
        # Boundary: greeting + business request → should NOT be GREETING
        ["Hi, I'd like to book an appointment.", "QUERY"],
        ["Hello, how do I reset my password?",   "QUERY"],
    ]

    # ------------------------------------------------------------------
    # ACK
    # ------------------------------------------------------------------
    ack_tests = [
        # Case A: affirm
        ["Yes",                  "ACK"],
        ["Yes, that's correct",  "ACK"],
        ["Correct",              "ACK"],
        ["Confirmed",            "ACK"],
        ["That's right",         "ACK"],
        ["Sure",                 "ACK"],
        # Case B: negate
        ["No",                   "ACK"],
        ["No thanks",            "ACK"],
        ["Not needed",           "ACK"],
        ["Cancel that",          "ACK"],
        ["Never mind",           "ACK"],
        # Case C: plain ack
        ["OK",                   "ACK"],
        ["Okay",                 "ACK"],
        ["Got it",               "ACK"],
        ["I see",                "ACK"],
        ["Understood",           "ACK"],
        ["All right",            "ACK"],
    ]

    # ------------------------------------------------------------------
    # COMMAND
    # ------------------------------------------------------------------
    command_tests = [
        # Case A: standard hits
        ["Can you repeat that?",                          "COMMAND"],   # ACTION_REPLAY
        ["Please say that again",                         "COMMAND"],   # ACTION_REPLAY
        ["Sorry, I didn't catch that",                    "COMMAND"],   # ACTION_REPLAY
        ["Can you speak up a bit?",                       "COMMAND"],   # ACTION_VOL_UP
        ["Could you speak a little louder?",              "COMMAND"],   # ACTION_VOL_UP
        ["Please lower your voice",                       "COMMAND"],   # ACTION_VOL_DOWN
        ["Can I speak to a real person?",                 "COMMAND"],   # ACTION_TRANSFER
        ["Transfer me to a human agent",                  "COMMAND"],   # ACTION_TRANSFER
        ["Goodbye",                                       "COMMAND"],   # ACTION_HANGUP
        ["Bye, thanks",                                   "COMMAND"],   # ACTION_HANGUP
        # Case B: semantic variants
        ["I can't hear you",                              "COMMAND"],   # ACTION_VOL_UP
        ["Turn it down please",                           "COMMAND"],   # ACTION_VOL_DOWN
        ["Connect me to someone",                         "COMMAND"],   # ACTION_TRANSFER
        # Case C: out-of-scope → falls back to QUERY
        ["Can you book me an appointment?",               "QUERY"],
        ["What are your opening hours?",                  "QUERY"],
        ["Thanks, could you repeat that one more time?", "COMMAND"],
        # Case D: compound intent — COMMAND priority
        ["Hello, I'd like to speak to a staff member",   "COMMAND"],

    ]

    # ------------------------------------------------------------------
    # INFORM
    # ------------------------------------------------------------------
    inform_tests = [
        # Case A: personal info
        ["My name is John Smith",                        "INFORM"],
        ["I'm calling from London",                      "INFORM"],
        ["My phone number is 07700 900 123",             "INFORM"],
        ["My email is john@example.com",                 "INFORM"],
        # Case B: medical / appointment background
        ["I have a follow-up appointment on Friday",     "INFORM"],
        ["I'm a new patient",                            "INFORM"],
        ["I'm calling on behalf of my mother",           "INFORM|QUERY"],
        # Case C: symptom / condition description
        ["I've had a sore throat for three days",        "INFORM|QUERY"],
        ["My child has a fever",                         "INFORM|QUERY"],
        ["The error code shown is E404",                 "INFORM"],
        # Case D: correction
        ["Sorry, my appointment is on Thursday not Wednesday", "INFORM"],
        ["I gave the wrong number, it ends in 456",      "INFORM"],
    ]

    # ------------------------------------------------------------------
    # FEEDBACK
    # ------------------------------------------------------------------
    feedback_tests = [
        # Case A: positive
        ["The service was excellent, thank you!",            "FEEDBACK"],
        ["You were really helpful, I appreciate it",         "FEEDBACK"],
        ["Great experience overall",                         "FEEDBACK"],
        # Case B: negative
        ["I've been waiting for 20 minutes, this is awful",  "FEEDBACK"],
        ["The app keeps crashing, it's unusable",            "FEEDBACK"],
        ["I want to make a complaint",                       "FEEDBACK"],
        # Case C: neutral / suggestion
        ["It would be nice if you had evening slots",        "FEEDBACK"],
        ["The hold music is a bit too loud",                 "FEEDBACK"],
        # Case D: boundary — COMMAND/QUERY takes priority
        ["This is terrible, get me a human now",             "COMMAND"],
        ["Why does the system keep logging me out?",         "QUERY"],
    ]

    # ------------------------------------------------------------------
    # CHITCHAT
    # ------------------------------------------------------------------
    chitchat_tests = [
        # Case A: pure casual
        ["How are you today?",                     "CHITCHAT"],
        ["What's the weather like?",               "CHITCHAT"],
        ["Do you think AI will replace doctors?",  "CHITCHAT|QUERY"],
        # Case B: filler / meaningless
        ["Hahaha",                                 "CHITCHAT"],
        ["Umm, let me think",                      "CHITCHAT|ACK"],
        ["Oh wow",                                 "CHITCHAT"],
        # Case C: humor
        ["Tell me a joke",                         "CHITCHAT"],
        ["Have you had lunch?",                    "CHITCHAT"],
        # Case D: boundary CHITCHAT vs QUERY
        ["What year did the NHS start?",           "CHITCHAT|QUERY"],
        ["What is paracetamol used for?",          "QUERY"],
        ["You're very helpful!",                   "CHITCHAT|FEEDBACK"],
    ]

    # =========================================================================
    # Multi-turn stress sessions  (each session is an independent conversation)
    # =========================================================================

    # Session 1 — Full end-to-end clinic flow
    session1 = [
        ["Hello",                                           "GREETING"],
        ["I'm a new patient",                               "INFORM"],
        ["How do I book an appointment?",                   "QUERY"],
        ["That was really helpful, thank you!",             "FEEDBACK"],
        ["Tell me a joke",                                  "CHITCHAT"],
        ["Could you repeat that?",                          "COMMAND"],
        ["Goodbye",                                         "COMMAND"],
    ]

    # Session 2 — REPLAY boundary test
    # ⚠️  First "pardon?" fires before AI has replied → must NOT trigger REPLAY
    session2 = [
        ["Hello",                                           "GREETING"],
        ["Pardon?",                                         "COMMAND"],   # no AI reply yet → NOT REPLAY
        ["Hi, I'm a returning patient. How do I reschedule?", "QUERY"],
        ["What?",                                           "COMMAND"],    # AI has replied → ACTION_REPLAY
        ["Sorry?",                                          "COMMAND"],
        ["Could you say that again please?",                "COMMAND"],
        ["I'd rather speak to a person",                    "COMMAND"],
    ]

    # Session 3 — Off-topic drift + recovery
    session3 = [
        ["Hi, I'm Dr. Adams",                                    "INFORM"],
        ["What do you think about the weather today?",           "CHITCHAT"],
        ["Never mind, how do patients reset their portal password?", "QUERY"],
    ]

    # Session 4 — Identity switch + context inheritance
    session4 = [
        ["Hello, I'm a patient",                                 "INFORM"],
        ["How do I view my test results?",                       "QUERY"],
        ["What about a doctor — how do they upload results?",    "QUERY"],
        ["And what can a receptionist do in the system?",        "QUERY"],
    ]

    # Session 5 — Negative emotion escalation → transfer
    session5 = [
        ["Hello, I'm a patient",                                       "INFORM"],
        ["I need to reschedule my appointment",                         "QUERY"],
        ["This is taking forever, I'm very frustrated",                "FEEDBACK"],
        ["That's not helpful at all, I want to speak to someone now",  "COMMAND"],
    ]

    # Session 6 — Mixed rapid-fire (REPLAY colloquial variants)
    session6 = [
        ["Hello",                            "GREETING"],
        ["I'm a new patient",                "INFORM"],
        ["How do I register?",               "QUERY"],
        ["What?",                            "COMMAND"],   # ACTION_REPLAY
        ["Huh?",                             "COMMAND"],   # ACTION_REPLAY
        ["Can you say that one more time?",  "COMMAND"],   # ACTION_REPLAY
        ["OK, got it",                       "ACK"],
        ["Bye",                              "COMMAND"],   # ACTION_HANGUP
    ]

    # =========================================================================
    # Run suites — uncomment / comment to control which suites run
    # =========================================================================
    #run_suite("GREETING Suite",    greeting_tests)
    #run_suite("ACK Suite",         ack_tests)
    #run_suite("COMMAND Suite",     command_tests)
    #run_suite("INFORM Suite",      inform_tests)
    # run_suite("FEEDBACK Suite",    feedback_tests)
    #run_suite("CHITCHAT Suite",    chitchat_tests)
    #
    #run_suite("Session 1 — Full clinic flow",              session1)
    run_suite("Session 2 — REPLAY boundary",               session2)
    run_suite("Session 3 — Off-topic drift + recovery",    session3)
    run_suite("Session 4 — Identity switch + inheritance", session4)
    run_suite("Session 5 — Negative escalation",           session5)
    run_suite("Session 6 — Rapid REPLAY variants",         session6)

    # =========================================================================
    # Summary
    # =========================================================================
    total = total_pass + total_fail
    pass_rate = 0.0 if total == 0 else total_pass / total * 100

    logger.debug("\n" + "═" * 60)
    logger.debug("📊 Test Summary  Total: %d  ✅Pass: %d  ❌Fail: %d"
                 % (total, total_pass, total_fail))
    logger.debug("📈 Pass rate: %.1f%%" % pass_rate)
    logger.debug("═" * 60)

    PASS_THRESHOLD = 92.0
    if pass_rate >= PASS_THRESHOLD:
        logger.debug("✅ Tests passed! Pass rate %.1f%% >= %.0f%%" % (pass_rate, PASS_THRESHOLD))
        sys.exit(0)
    else:
        logger.debug("❌ Tests failed! Pass rate %.1f%% < %.0f%%" % (pass_rate, PASS_THRESHOLD))
        sys.exit(1)


# =============================================================================
# run_suite  (mirrors Java runSuite)
# =============================================================================
def run_suite(suite_name: str, test_data: list):
    global total_pass, total_fail

    logger.debug("\n" + "─" * 60)
    logger.debug("🧪 Suite: " + suite_name)
    logger.debug("─" * 60)

    session_id = "CLINIC_" + str(uuid.uuid4())[:4].upper()
    session = session_manager.get_session(session_id)

    for test in test_data:
        user_input      = test[0]
        expected_intent = test[1]

        logger.debug("=" * 50)
        logger.debug("👤 User: " + user_input + "  | Expected: " + expected_intent)

        ca     = session.ask(user_input)
        result = session.currentIntentResult

        if result is not None:
            actual    = result.intent.value
            pass_flag = actual in expected_intent.split("|")

            if pass_flag:
                total_pass += 1
            else:
                total_fail += 1

            logger.debug("[%s] Actual: %-10s | Expected: %s"
                         % ("PASS" if pass_flag else "FAIL", actual, expected_intent))

            logger.debug(f"     └─ [User input]:    {user_input}")
            if result.refined_query:
                logger.debug("     └─ [Refined query]: " + result.refined_query)
            if result.sub_intent:
                logger.debug("     └─ [Sub-intent]:    " + result.sub_intent)
            if result.action_code:
                logger.debug("     └─ [Action code]:   " + result.action_code)

            from intent.intent_result import Sentiment
            if result.sentiment and result.sentiment != Sentiment.NEUTRAL:
                logger.debug("     └─ [Sentiment]:     " + result.sentiment.value)
        else:
            total_fail += 1
            logger.debug("[FAIL] intentResult is None")

        logger.debug("     └─ [Status code]: " + str(ca.code))
        logger.debug("     └─ [Action]:      " + str(ca.action))
        logger.debug("     └─ [AI reply]:    " + str(ca.answer))
        logger.debug("-" * 50)


if __name__ == "__main__":
    main()