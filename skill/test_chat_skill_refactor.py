"""
test_chat_skill_refactor.py —— Verify the refactored architecture:
  1. Three business modules are registered independently with no cross-dependencies.
  2. The unified interface of skill_base correctly supports "simple tasks" (express) and "complex tasks" (complaint/internet).
  3. The status returned by handle() correctly drives the lock/unlock logic in the main controller.
"""
import asyncio
from skill.skill_base import SKILL_REGISTRY, get_skill, all_tools, find_skill_by_keyword, find_skill_by_tool_name, SkillStatus

import skill.skill_express
import skill.skill_complaint
import skill.skill_internet


class FakeSession:
    def __init__(self):
        self._caller_phone = "13800000000"
        self.sinfo = "[test] "


def test_registration():
    print("=" * 60)
    print("Test 1: All three business modules are correctly registered")
    print("=" * 60)
    assert set(SKILL_REGISTRY.keys()) == {"express", "complaint", "internet"}
    for name, module in SKILL_REGISTRY.items():
        print(f"  - {name}: tools={module.tool_names}, keywords={module.trigger_keywords[:3]}...")
    print("✅ Registration check passed\n")


def test_keyword_routing():
    print("=" * 60)
    print("Test 2: Keyword pre-check correctly routes to the corresponding business")
    print("=" * 60)
    assert find_skill_by_keyword("我要查快递") == "express"
    assert find_skill_by_keyword("我要投诉") == "complaint"
    assert find_skill_by_keyword("宽带坏了") == "internet"
    assert find_skill_by_keyword("今天天气怎么样") is None
    print("  Express keywords → express ✓")
    print("  Complaint keywords → complaint ✓")
    print("  Repair keywords → internet ✓")
    print("  Irrelevant text → None ✓")
    print("✅ Keyword routing test passed\n")


def test_tool_name_reverse_lookup():
    print("=" * 60)
    print("Test 3: Reverse lookup of business module by tool function name")
    print("=" * 60)
    assert find_skill_by_tool_name("express_query_skill") == "express"
    assert find_skill_by_tool_name("complaint_skill") == "complaint"
    assert find_skill_by_tool_name("internet_repair_skill") == "internet"
    assert find_skill_by_tool_name("unknown_tool") is None
    print("✅ Reverse lookup test passed\n")


def test_all_tools_aggregation():
    print("=" * 60)
    print("Test 4: all_tools() correctly aggregates tools from all business modules")
    print("=" * 60)
    tools = all_tools()
    names = [t["function"]["name"] for t in tools]
    print(f"  Aggregated tools: {names}")
    assert "express_query_skill" in names
    assert "complaint_skill" in names
    assert "internet_repair_skill" in names
    assert len(names) == 3  # Only one tool per business in normal state, excludes cancel_skill
    print("✅ Tool aggregation test passed\n")


async def test_express_simple_flow():
    print("=" * 60)
    print("Test 5: Express Query — Simple task, no confirm needed, two rounds to complete")
    print("=" * 60)
    session = FakeSession()
    module = get_skill("express")

    r = await module.handle(session, phone="13800000000")
    print(f"Round 1 (Date unspecified): status={r['status']}, msg={r['msg']}")
    assert r["status"] == SkillStatus.NEED_INFO

    r = await module.handle(session, phone="13800000000", date="2024-03-05")
    print(f"Round 2 (Date specified): status={r['status']}, msg={r['msg']}")
    assert r["status"] == SkillStatus.DONE
    print("✅ Express simple flow test passed\n")


async def test_complaint_multi_field_flow():
    print("=" * 60)
    print("Test 6: Complaint — Complex task, multi-field + confirm, internal state management")
    print("=" * 60)
    session = FakeSession()
    module = get_skill("complaint")

    r = await module.handle(session, phone="13800000000", category="快递问题")
    print(f"Round 1: status={r['status']}, msg={r['msg']}")
    assert r["status"] == SkillStatus.NEED_INFO

    r = await module.handle(session, phone="13800000000", content="快递丢了")
    print(f"Round 2: status={r['status']}, msg={r['msg']}")
    assert r["status"] == SkillStatus.PENDING_CONFIRM

    r = await module.handle(session, phone="13800000000", confirmed=True)
    print(f"Round 3 (Confirm): status={r['status']}, msg={r['msg']}")
    assert r["status"] == SkillStatus.DONE
    assert "ticket_id" in r
    print("✅ Complaint multi-field flow test passed\n")


async def test_internet_independent_from_complaint():
    print("=" * 60)
    print("Test 7: Internet repair is independent of complaints, drafts do not interfere")
    print("=" * 60)
    session = FakeSession()
    complaint_module = get_skill("complaint")
    internet_module = get_skill("internet")

    # Set data in complaint first
    await complaint_module.handle(session, phone="13800000000", category="服务态度")

    # Repair uses its own fields, not affected by complaint drafts
    r = await internet_module.handle(session, phone="13800000000", fault_type="完全断网")
    print(f"Repair Round 1: status={r['status']}, msg={r['msg']}")
    assert r["status"] == SkillStatus.NEED_INFO
    assert "address" in r["msg"] or "报修地址" in r["msg"]

    r = await internet_module.handle(session, phone="13800000000", address="天河区xx路")
    print(f"Repair Round 2: status={r['status']}, msg={r['msg']}")
    assert r["status"] == SkillStatus.PENDING_CONFIRM

    r = await internet_module.handle(session, phone="13800000000", confirmed=True)
    print(f"Repair Round 3 (Confirm): status={r['status']}, order_id={r.get('order_id')}")
    assert r["status"] == SkillStatus.DONE
    print("✅ Independence between complaint and repair test passed\n")


async def test_locked_prompt_generation():
    print("=" * 60)
    print("Test 8: Locked prompt correctly reflects the collection progress of each business")
    print("=" * 60)
    session = FakeSession()
    complaint_module = get_skill("complaint")

    await complaint_module.handle(session, phone="13800000000", category="商品质量", content="商品有破损")
    prompt = complaint_module.build_locked_prompt(session, "13800000000")
    print(prompt)
    assert "商品质量" in prompt
    assert "商品有破损" in prompt
    print("✅ Locked prompt generation test passed\n")


async def main():
    test_registration()
    test_keyword_routing()
    test_tool_name_reverse_lookup()
    test_all_tools_aggregation()
    await test_express_simple_flow()
    await test_complaint_multi_field_flow()
    await test_internet_independent_from_complaint()
    await test_locked_prompt_generation()
    print("=" * 60)
    print("All tests passed 🎉 Refactored architecture verification completed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())