# test/rag_test_clinic_runner.py
#
# RAG end-to-end CI test for English medical clinic.
# Mirrors rag_test_runner.py structure.
#
# Validation logic (dual check):
#   1. rewrite_keywords : refined_query must contain all keywords
#   2. answer_keywords  : final answer must contain all keywords
#   Both pass → PASS, either fails → FAIL
#
# Fill-in guide:
#   - rewrite_keywords = None or [] → skip rewrite check
#   - answer_keywords  = None or [] → skip answer check
#   - Keywords are case-insensitive
#   - "|" separator = OR logic, e.g. "911|emergency room"
#
# Local run:
#   python test/rag_test_clinic_runner.py [config_path]

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

total_pass = 0
total_fail = 0


# =============================================================================
# RagCase dataclass
# =============================================================================
@dataclass
class RagCase:
    question:         str
    rewrite_keywords: Optional[List[str]]  # None or [] → skip rewrite check
    answer_keywords:  Optional[List[str]]  # None or [] → skip answer check


# =============================================================================
# Scenario 1: General clinic info
# =============================================================================
scenario_general = [
    RagCase(
        "What are your clinic hours?",
        rewrite_keywords=[],
        answer_keywords=["9|9:00", "5|5:00", "Monday|monday"],
    ),
    RagCase(
        "Are you open on weekends?",
        rewrite_keywords=[],
        answer_keywords=["closed|not open"],
    ),
    RagCase(
        "Do you answer phones during lunch?",
        rewrite_keywords=["lunch|phone"],
        answer_keywords=["12|noon|unmonitored"],
    ),
    RagCase(
        "Are you closed on BC statutory holidays?",
        rewrite_keywords=[],
        answer_keywords=["closed|holiday"],
    ),
]

# =============================================================================
# Scenario 2: Patient services — entity normalization
# =============================================================================
scenario_patient = [
    RagCase(
        "Can I get a refill over the phone?",
        rewrite_keywords=["refill|prescription"],
        answer_keywords=["fax|pharmacy|telehealth"],
    ),
    RagCase(
        "I need a sick note for work.",
        rewrite_keywords=["doctor's note|sick note"],
        answer_keywords=["appointment|30|fee"],
    ),
    RagCase(
        "Will you call me about my blood work results?",
        rewrite_keywords=["lab results"],
        answer_keywords=["abnormal|normal|MyCareCompass|call"],
    ),
    RagCase(
        "I'm calling to check on my specialist referral.",
        rewrite_keywords=["specialist referral"],
        answer_keywords=["2|4|week|specialist"],
    ),
    RagCase(
        "Can I do a phone appointment for my chronic condition?",
        rewrite_keywords=["telehealth|appointment"],
        answer_keywords=["stable|chronic|virtual|telehealth"],
    ),
]

# =============================================================================
# Scenario 3: Multi-turn — implicit inheritance
# =============================================================================
scenario_multiturn = [
    RagCase(
        "I'm running about 15 minutes late for my appointment.",
        rewrite_keywords=[],
        answer_keywords=["10|late|reschedule|urgent"],
    ),
    RagCase(
        "What if I can't make it at all?",
        rewrite_keywords=[],
        answer_keywords=["24|cancel|fee|reschedule"],
    ),
    RagCase(
        "How much is the cancellation fee?",
        rewrite_keywords=[],
        answer_keywords=["40|80|fee"],
    ),
]

# =============================================================================
# Scenario 4: Urgent / emergency fast-track
# =============================================================================
scenario_urgent = [
    RagCase(
        "I'm having chest pain and can't breathe.",
        rewrite_keywords=[],
        answer_keywords=["911|emergency|hang up"],
    ),
    RagCase(
        "My mother collapsed and is unconscious.",
        rewrite_keywords=[],
        answer_keywords=["911|emergency room"],
    ),
]

# =============================================================================
# Scenario 5: IVR end-to-end — mirrors Java main() test cases (Group 1)
# =============================================================================
scenario_ivr_1 = [
    RagCase(
        "what are your clinic hours",
        rewrite_keywords=[],
        answer_keywords=["9|9:00", "5|5:00", "Monday|monday"],
    ),
    RagCase(
        "do you accept walk-ins",
        rewrite_keywords=["walk-in|walk in"],
        answer_keywords=["walk-in|walk in", "9:00|9 AM|capacity"],
    ),
    RagCase(
        "can I get a prescription refill over the phone",
        rewrite_keywords=["refill|prescription"],
        answer_keywords=["fax|pharmacy|telehealth"],
    ),
]

# =============================================================================
# Scenario 6: IVR end-to-end — Java main() test cases (Group 2)
# =============================================================================
scenario_ivr_2 = [
    RagCase(
        "I need a sick note for work",
        rewrite_keywords=["doctor's note|sick note"],
        answer_keywords=["appointment|30|fee"],
    ),
    RagCase(
        "my chest hurts and I can't breathe",
        rewrite_keywords=[],
        answer_keywords=["911|emergency"],
    ),
    RagCase(
        "how do I book an appointment",
        rewrite_keywords=["appointment|book"],
        answer_keywords=["portal|PHN|online|phone|reception"],
    ),
]

# =============================================================================
# Scenario 7: IVR end-to-end — Java main() test cases (Group 3)
# =============================================================================
scenario_ivr_3 = [
    RagCase(
        "I'm running 15 minutes late for my appointment",
        rewrite_keywords=[],
        answer_keywords=["10|reschedule|late|urgent"],
    ),
    RagCase(
        "what happens if I miss my appointment",
        rewrite_keywords=[],
        answer_keywords=["40|80|fee|24|cancel"],
    ),
    RagCase(
        "I'm calling to check on my specialist referral",
        rewrite_keywords=["specialist referral"],
        answer_keywords=["2|4|week|specialist"],
    ),
]

# =============================================================================
# Scenario 8: IVR end-to-end — Java main() test cases (Group 4)
# =============================================================================
scenario_ivr_4 = [
    RagCase(
        "are you open on weekends",
        rewrite_keywords=[],
        answer_keywords=["closed|not open|weekend"],
    ),
]

# =============================================================================
# Scenario 9: Boundary — out of scope
# =============================================================================
scenario_boundary = [
    RagCase(
        "Can I get a prescription for antibiotics without coming in?",
        rewrite_keywords=[],
        answer_keywords=["in-person|appointment|telehealth|sorry"],
    ),
    RagCase(
        "Do you accept walk-ins?",
        rewrite_keywords=[],
        answer_keywords=[],
    ),
    RagCase(
        "Can a new patient register with your clinic?",
        rewrite_keywords=[],
        answer_keywords=["not accepting|waitlist|BC Health Connect"],
    ),
]


# =============================================================================
# main
# =============================================================================
def main():
    global total_pass, total_fail

    client_id = "clinic_test_001"

    config_path = "e:\\ai"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
        logger.debug("📂 Argument detected, using config path: " + config_path)
    elif os.environ.get("AI_CONFIG_PATH"):
        config_path = os.environ["AI_CONFIG_PATH"]
        logger.debug("📂 Using env var path: " + config_path)
    else:
        logger.debug("ℹ️  No argument detected, using default path: " + config_path)

    session_manager.init(config_dir=config_path)
    session_manager.warm_up()

    logger.debug("=== English Clinic — RAG End-to-End Test ===\n")

    all_scenarios2 = [
        scenario_general,
        scenario_patient,
        scenario_multiturn,
        scenario_urgent,
        scenario_ivr_1,
        scenario_ivr_2,
        scenario_ivr_3,
        scenario_ivr_4,
        scenario_boundary,
    ]
    all_scenarios = [

        scenario_ivr_2,

    ]


    scenario_names = [
        "Scenario 1: General Clinic Info",
        "Scenario 2: Patient Services & Entity Normalization",
        "Scenario 3: Multi-turn Implicit Inheritance",
        "Scenario 4: Urgent / Emergency Fast-track",
        "Scenario 5: IVR Group 1 (Hours / Walk-in / Refill)",
        "Scenario 6: IVR Group 2 (Sick Note / Urgent / Booking)",
        "Scenario 7: IVR Group 3 (Late / No-show / Referral)",
        "Scenario 8: IVR Group 4 (Weekend)",
        "Scenario 9: Boundary & Out-of-scope",
    ]

    for s, cases in enumerate(all_scenarios):
        run_scenario(
            client_id + "_s" + str(s + 1),
            scenario_names[s],
            cases,
        )

    total = total_pass + total_fail
    pass_rate = 0.0 if total == 0 else total_pass / total * 100

    logger.debug("\n" + "═" * 60)
    logger.debug("📊 Test Summary  Total: " + str(total)
                 + "  ✅Pass: " + str(total_pass)
                 + "  ❌Fail: " + str(total_fail))
    logger.debug("📈 Pass rate: %.1f%%" % pass_rate)
    logger.debug("═" * 60)

    PASS_THRESHOLD = 92.0

    if pass_rate >= PASS_THRESHOLD:
        logger.debug("✅ Tests passed! Pass rate %.1f%% ≥ %.0f%%" % (pass_rate, PASS_THRESHOLD))
        sys.exit(0)
    else:
        logger.debug("❌ Tests failed! Pass rate %.1f%% < %.0f%%" % (pass_rate, PASS_THRESHOLD))
        sys.exit(1)


# =============================================================================
# run_scenario
# =============================================================================
def run_scenario(session_id: str, scenario_name: str, cases: List[RagCase]):
    global total_pass, total_fail

    logger.debug("##################################################")
    logger.debug("🚩 Running: " + scenario_name)
    logger.debug("##################################################")

    session = session_manager.get_session(session_id)

    for i, rc in enumerate(cases):
        logger.debug("==================================================")
        logger.debug("👤 [" + str(i + 1) + "] User: " + rc.question)
        logger.debug("⏳ Requesting AI pipeline...")

        start = time.time()
        answer = session.ask(rc.question)
        elapsed = int((time.time() - start) * 1000)

        rewritten_query = ""
        result = session.currentIntentResult
        if result and result.refined_query:
            rewritten_query = result.refined_query

        final_answer = answer.answer if answer and answer.answer else ""

        rewrite_pass = _check_keywords("rewrite", rc.question, rewritten_query, rc.rewrite_keywords)
        answer_pass  = _check_keywords("answer",  rc.question, final_answer,    rc.answer_keywords)
        passed = rewrite_pass and answer_pass

        if passed:
            total_pass += 1
        else:
            total_fail += 1

        status = "PASS" if passed else "FAIL"
        logger.debug("[" + status + "] Turn " + str(i + 1) + " | elapsed: " + str(elapsed) + " ms")
        logger.debug("     └─ [User input]:    " + rc.question)
        logger.debug("     └─ [Refined query]: " + rewritten_query)
        logger.debug("     └─ [AI reply]:      "
                     + (final_answer[:100] + "..." if len(final_answer) > 100 else final_answer))

        time.sleep(1.5)

    logger.debug("✅ Scenario done: " + scenario_name)


# =============================================================================
# _check_keywords
# =============================================================================
def _check_keywords(
    label: str,
    question: str,
    target: str,
    keywords: Optional[List[str]],
) -> bool:
    if not keywords:
        return True

    lower_target = target.lower()
    all_match = True

    for kw in keywords:
        if not kw:
            continue
        or_options = kw.split("|")
        any_hit = any(opt.strip().lower() in lower_target for opt in or_options)
        if not any_hit:
            logger.debug("     ❌ [" + label + " check failed] Q: \""
                         + question + "\" | missing keyword: \"" + kw + "\"")
            all_match = False

    return all_match


if __name__ == "__main__":
    main()
