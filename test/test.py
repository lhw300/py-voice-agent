# test.py
import requests
import random
BASE_URL = "http://localhost:8010"

def test(vo_id: str, text: str, sn: str = "001"):
    url = f"{BASE_URL}/{vo_id}"
    payload = {
        "sn":         sn,
        "crid":       "c1",
        "ch":         "1",
        "call_date":  "2026-05-04",
        "start_time": "10:00:00",
        "phone":      "13800000000",
        "vo_id":      vo_id,
        "text":       text
    }
    resp = requests.post(url, json=payload)
    print(f"[{vo_id}] text='{text}'")
    print(f"  status={resp.status_code}")   # ← 加这行
    print(f"  body={resp.text}")            # ← 加这行，看原始返回
    print()

if __name__ == "__main__":

    #test("ai_send", "你好")
    #test("ai_send", "再见")
    #test("ai_send", "我的宽带坏了")


    # 模拟多轮对话，用同一个sn
    # 测试非法输入
    # sn_value = f"r{random.randint(1000, 9999)}"
    # test("filling", "我的宽带坏了",  sn=sn_value)
    #
    # test("filling", "孙悟空大圣",    sn=sn_value)  # 非法姓名 → 提示重说
    # test("filling", "张三",         sn=sn_value)  # 正确姓名
    # test("filling", "孙悟空",      sn=sn_value)  # 非法电话 → 提示重说
    # test("filling", "13800138000",   sn=sn_value)  # 正确电话
    # test("filling", "对",            sn=sn_value)  # 确认电话
    # test("filling", "花果山水帘洞",   sn=sn_value)  # 非法地址 → 提示重说
    # test("filling", "鼓楼区莲花小区3栋201",  sn=sn_value)  # 正确地址
    # test("filling", "不是",            sn=sn_value)  # 确认地址
    # test("filling", "鼓楼区莲花小区3栋2011",  sn=sn_value)  # 正确地址
    # test("filling", "没错",            sn=sn_value)  # 确认电话


    sn_value = str(random.randint(1000, 9999))

    # print("=== AI版 正常流程 ===")
    # test("filling_ai", "我的宽带坏了",        sn=sn_value)
    # test("filling_ai", "张三",                sn=sn_value)
    # test("filling_ai", "13800138000",         sn=sn_value)
    # test("filling_ai", "对",                  sn=sn_value)
    # test("filling_ai", "鼓楼区莲花小区3栋201", sn=sn_value)
    # test("filling_ai", "对",                  sn=sn_value)
    #
    # # ═══════════════════════════════════════════════
    # # 超范围地址 + 中途各种异常输入
    # # ═══════════════════════════════════════════════
    sn_value = str(random.randint(1000, 9999))
    print("=== 超范围地址 + 异常输入 ===")
    test("filling_ai", "我的宽带坏了",             sn=sn_value)
    test("filling_ai", "张三",                     sn=sn_value)
    test("filling_ai", "啥",                       sn=sn_value)  # 无效电话
    test("filling_ai", "没错",                 sn=sn_value)  # 听不清
    test("filling_ai", "不记得手机号了",            sn=sn_value)  # 不记得
    test("filling_ai", "13900139000",              sn=sn_value)
    test("filling_ai", "说错了",                   sn=sn_value)  # 否认
    test("filling_ai", "没错，就是13900139000",    sn=sn_value)  # 带号码确认
    test("filling_ai", "这次对了",                 sn=sn_value)  # 确认
    test("filling_ai", "江宁区某小区",             sn=sn_value)  # 超范围地址
    test("filling_ai", "鼓楼区莲花小区3栋201",     sn=sn_value)  # 正确地址
    test("filling_ai", "这次对了",                 sn=sn_value)  # 确认地址

    # ═══════════════════════════════════════════════
    # 公司名称报修
    # ═══════════════════════════════════════════════
    # sn_value = str(random.randint(1000, 9999))
    # print("=== 公司名称报修 ===")
    # test("filling_ai", "我的宽带坏了",             sn=sn_value)
    # test("filling_ai", "北方科技公司",           sn=sn_value)
    # test("filling_ai", "对",                       sn=sn_value)
    # test("filling_ai", "13800138000",              sn=sn_value)
    # test("filling_ai", "对",                       sn=sn_value)
    # test("filling_ai", "秦淮区中山路100号",        sn=sn_value)
    # test("filling_ai", "对",                       sn=sn_value)

    # # ═══════════════════════════════════════════════
    # # 地址否认重填
    # # ═══════════════════════════════════════════════
    # sn_value = str(random.randint(1000, 9999))
    # print("=== 地址否认重填 ===")
    # test("filling_ai", "我的宽带坏了",             sn=sn_value)
    # test("filling_ai", "李四",                     sn=sn_value)
    # test("filling_ai", "嗯",                       sn=sn_value)
    # test("filling_ai", "13700137000",              sn=sn_value)
    # test("filling_ai", "对",                       sn=sn_value)
    # test("filling_ai", "建邺区河西大街88号",       sn=sn_value)
    # test("filling_ai", "不对",                     sn=sn_value)  # 否认地址
    # test("filling_ai", "建邺区奥体大街200号",      sn=sn_value)  # 重新输入
    # test("filling_ai", "对",                       sn=sn_value)
    # #
    # # ═══════════════════════════════════════════════
    # # 非法姓名
    # # ═══════════════════════════════════════════════
    # sn_value = str(random.randint(1000, 9999))
    # print("=== 非法姓名 ===")
    # test("filling_ai", "我的宽带坏了",             sn=sn_value)
    # test("filling_ai", "孙悟空大圣",               sn=sn_value)  # 非法姓名
    # test("filling_ai", "王五",                     sn=sn_value)  # 正确姓名
    # test("filling_ai", "嗯",                     sn=sn_value)  # 正确姓名
    # test("filling_ai", "13600136000",              sn=sn_value)
    # test("filling_ai", "对",                       sn=sn_value)
    # test("filling_ai", "鼓楼区湖南路50号",        sn=sn_value)
    # test("filling_ai", "对",                       sn=sn_value)