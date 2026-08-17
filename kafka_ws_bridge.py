# kafka_ws_bridge.py
#
# 把 Kafka topic `call.asr.transcript` 桥接到浏览器可用的 WebSocket。
# 挂载到你现有的 FastAPI app 上即可（跟 chat_skill_layer.py 同一个进程或单独进程都行）。
#
# 依赖: pip install aiokafka
#
# ── 实际消息格式（KafkaAsrProducer.java 输出）──────────────────
#   {
#     "sn":       "20010173",   # 通话唯一标识（呼入流水号）
#     "ch":       "0",          # 声道号：0 = 外线，4 = 坐席
#     "index":    "0",          # 该通话内的句子序号（递增）
#     "text":     "好学生的密码是多少",
#     "ts":       1786869401368,  # epoch ms
#     "agentCh":  "4",            # 该通话绑定的坐席线路号（cust/agent 两种消息都带这个字段）
#     "msgType":  "cust" | "agent"
#   }
# 每条消息本身就是一句完整识别结果（没有流式中间态字段），所以下面统一按
# is_final=true 处理。agentCh 用于坐席端按自己的固定线路号订阅，见下方
# transcript_ws 的 agent_ch 参数。
#
# ── 稳定性设计（2026-08-17 加固）──────────────────────────────────
# 踩过的两个坑，这版都做了防护：
#   1. 单条消息不是合法 JSON（脏消息/空 payload/BOM头）会让 value_deserializer
#      直接抛异常，导致整个 consume 循环崩溃且不会自动恢复。
#      → 解决：不用 value_deserializer，改成拿原始 bytes 自己 try/except 解析，
#        单条失败只跳过，不影响后续消息。
#   2. aiokafka 在网络抖动（比如 WSL2/Docker Desktop 挂起唤醒）时，内部
#      fetcher 协程可能因为自身的边界 bug（KeyError on _conns）而“假死”——
#      不抛异常给外层 async for，但也再不产生任何新消息，外部完全无感知。
#      → 解决：不用 `async for msg in consumer`，改用 `consumer.getmany()`
#        + 外层 asyncio.wait_for 做主动超时探测；超时就判定 consumer 已经
#        不健康，主动抛异常触发外层重建，而不是被动等它“自愈”。
#   加上最外层 `_consume_loop_forever` 兜底：不管是显式异常还是我们主动
#   探测出的假死，都会在几秒后自动重建 consumer，不需要人工重启进程。

import asyncio
import contextlib
import json
import logging
from typing import Optional

from aiokafka import AIOKafkaConsumer
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

import ai_config as AiConfig

logger = logging.getLogger("kafka_ws_bridge")
import os
if os.environ.get("KAFKA_BRIDGE_DEBUG", "1") == "1":
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)
logging.getLogger("aiokafka").setLevel(logging.WARNING)

router = APIRouter()

# 复用项目现有的 ai.conf 配置系统，没配置就用这两个默认值兜底。
# ai.conf 里可以加：
#   kafka.bootstrap_servers = localhost:9092
#   kafka.topic.asr_transcript = call.asr.transcript
KAFKA_BOOTSTRAP = AiConfig.getStringConfig("kafka.bootstrap_servers", "localhost:9092")
KAFKA_TOPIC = AiConfig.getStringConfig("kafka.topic.asr_transcript", "call.asr.transcript")
KAFKA_GROUP_ID = "copilot-ws-bridge"  # 独立 group，不影响你其他消费者

# poll 看门狗超时：这段时间内如果一次 getmany() 都拿不到结果（无论有没有
# 新消息，getmany 本身应该在 timeout_ms 内正常返回，哪怕是空结果），就认为
# consumer 内部可能已经假死，主动重建。
# ⚠️ 这个值要比 getmany 自己的 timeout_ms 大得多，否则会跟正常的空轮询打架。
# 如果业务本身可能长时间没有通话（比如夜间），可以调大，避免误杀重建。
POLL_WATCHDOG_TIMEOUT_SEC = 90
GETMANY_TIMEOUT_MS = 5000

CHTYPE_TO_SPEAKER = {
    "cust":  "customer",
    "agent": "agent",
}


def normalize_record(raw: dict) -> Optional[dict]:
    """把 {sn, ch, index, msgType, text, ts, agentCh} 映射成前端要的
    {call_id, speaker, text, is_final, ts, index, agent_ch}。"""
    try:
        call_id = raw.get("sn")
        msg_type = raw.get("msgType")
        speaker = CHTYPE_TO_SPEAKER.get(msg_type)
        text = raw.get("text") or ""

        if not call_id:
            logger.warning("[normalize] 丢弃：缺少 sn 字段。raw=%s", raw)
            return None
        if speaker is None:
            logger.warning(
                "[normalize] 丢弃：msgType=%r 无法映射到 speaker（只认 'cust'/'agent'）。raw=%s",
                msg_type, raw,
            )
            return None
        if not text:
            logger.warning("[normalize] 丢弃：text 为空。raw=%s", raw)
            return None

        record = {
            "call_id": call_id,
            "speaker": speaker,
            "text": text,
            "is_final": True,  # 该 topic 上的消息本身就是完整句子，没有流式中间态
            "ts": raw.get("ts"),
            "index": raw.get("index"),   # 保留供前端排序/去重用
            "agent_ch": raw.get("agentCh"),  # 该通话绑定的坐席线路号，用于按坐席过滤
        }
        logger.debug("[normalize] 成功: sn=%s agent_ch=%s speaker=%s text=%r",
                     record["call_id"], record["agent_ch"], record["speaker"], record["text"])
        return record
    except Exception:
        logger.exception("[normalize] 解析异常，原始消息: %s", raw)
        return None


def _safe_parse_kafka_value(raw_value: Optional[bytes]) -> Optional[dict]:
    """把 Kafka 消息的原始 bytes 安全地解析成 dict。
    单条消息解析失败只返回 None（调用方负责跳过），不会向上抛异常，
    避免一条脏消息（空 payload / BOM头 / 非 UTF-8 / 非 JSON）打死整个消费循环。
    """
    if not raw_value:
        return None
    try:
        text = raw_value.decode("utf-8")
    except UnicodeDecodeError as e:
        logger.warning("[consumer] 消息不是合法 UTF-8，已跳过: err=%s raw=%r", e, raw_value[:200])
        return None

    try:
        value = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("[consumer] 消息不是合法 JSON，已跳过: err=%s raw=%r", e, text[:200])
        return None

    if not isinstance(value, dict):
        logger.warning("[consumer] 消息解析后不是 dict，已跳过: type=%s raw=%r", type(value).__name__, text[:200])
        return None

    return value


class ConnectionManager:
    """维护所有 websocket 连接，可选按 call_id 和/或 agent_ch 过滤。"""

    def __init__(self):
        # ws -> {"call_id": Optional[str], "agent_ch": Optional[str]}
        self._clients: dict[WebSocket, dict] = {}

    async def connect(self, ws: WebSocket, call_id: Optional[str], agent_ch: Optional[str]):
        await ws.accept()
        self._clients[ws] = {"call_id": call_id, "agent_ch": agent_ch}
        logger.info(
            "[ws] 新连接建立: agent_ch=%r call_id=%r  当前在线连接数=%d",
            agent_ch, call_id, len(self._clients),
        )

    def disconnect(self, ws: WebSocket):
        filters = self._clients.pop(ws, None)
        logger.info(
            "[ws] 连接断开: agent_ch=%r call_id=%r  当前在线连接数=%d",
            (filters or {}).get("agent_ch"), (filters or {}).get("call_id"), len(self._clients),
        )

    async def broadcast(self, record: dict):
        if not self._clients:
            logger.debug(
                "[broadcast] sn=%s agent_ch=%s 到达，但当前没有任何 WebSocket 连接，直接丢弃",
                record.get("call_id"), record.get("agent_ch"),
            )
            return

        dead = []
        matched = 0
        for ws, filters in self._clients.items():
            call_id_filter = filters.get("call_id")
            agent_ch_filter = filters.get("agent_ch")

            # agent_ch 是坐席端的主过滤条件：只有绑定到这个坐席线路号的通话
            # （cust 和 agent 两种消息都带 agentCh，所以整通对话都能收到）
            if agent_ch_filter is not None:
                # 都转成字符串比较，避免 "4" vs 4 这种类型不一致导致过滤失效
                if str(record.get("agent_ch")) != str(agent_ch_filter):
                    logger.debug(
                        "[broadcast] 跳过一个连接: 消息 agent_ch=%r(类型%s) != 连接订阅的 agent_ch=%r(类型%s)",
                        record.get("agent_ch"), type(record.get("agent_ch")).__name__,
                        agent_ch_filter, type(agent_ch_filter).__name__,
                    )
                    continue

            # call_id 是可选的额外过滤（比如只想看某一通具体的通话）
            if call_id_filter and record["call_id"] != call_id_filter:
                logger.debug(
                    "[broadcast] 跳过一个连接: 消息 call_id=%r != 连接订阅的 call_id=%r",
                    record["call_id"], call_id_filter,
                )
                continue

            try:
                await ws.send_json(record)
                matched += 1
            except Exception:
                logger.exception("[broadcast] 发送失败，标记该连接为待清理")
                dead.append(ws)

        logger.debug(
            "[broadcast] sn=%s agent_ch=%s speaker=%s → 匹配并发送给 %d/%d 个连接",
            record.get("call_id"), record.get("agent_ch"), record.get("speaker"),
            matched, len(self._clients),
        )

        for ws in dead:
            self._clients.pop(ws, None)


manager = ConnectionManager()
_consumer_task: Optional[asyncio.Task] = None


async def _handle_batch(messages) -> None:
    """处理一批从 getmany() 拿到的消息（某个 TopicPartition 下的消息列表）。"""
    for msg in messages:
        logger.debug(
            "[consumer] 收到原始消息: partition=%s offset=%s key=%s",
            msg.partition, msg.offset, msg.key,
        )
        value = _safe_parse_kafka_value(msg.value)
        if value is None:
            continue
        record = normalize_record(value)
        if record:
            await manager.broadcast(record)
        # normalize_record 内部已经用 logger.warning 打了丢弃原因，这里不用重复打


async def _consume_loop():
    """单次 consumer 生命周期：启动 → 消费 → (异常/看门狗超时) → 停止。
    异常会向上抛给 _consume_loop_forever，由它负责重建。
    """
    logger.info(
        "[consumer] 准备启动: bootstrap=%s topic=%s group_id=%s",
        KAFKA_BOOTSTRAP, KAFKA_TOPIC, KAFKA_GROUP_ID,
    )
    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=KAFKA_GROUP_ID,
        # ⚠️ 不再用 value_deserializer 在这里直接解析 JSON。
        # 一旦某条消息解析失败，deserializer 里抛出的异常会直接冲垮
        # aiokafka 内部的 fetcher，且无法被下面的 try/except 精确捕获、
        # 定位到是"哪条消息"的问题。改成拿原始 bytes，在 _handle_batch
        # 里用 _safe_parse_kafka_value 逐条安全解析。
        auto_offset_reset="latest",  # 只推新消息，不重放历史
        enable_auto_commit=True,
    )

    try:
        await consumer.start()
    except Exception:
        # 这是最容易被忽略的失败点：Kafka 连不上（地址错、端口没开、broker 没起来）
        # 会在这里直接抛异常。有 done_callback 兜底打印，不会被静默吞掉。
        logger.exception(
            "[consumer] 启动失败！无法连接 bootstrap=%s，请检查 Kafka 是否可达、端口是否正确",
            KAFKA_BOOTSTRAP,
        )
        raise

    logger.info("[consumer] 已启动，开始消费 topic=%s", KAFKA_TOPIC)

    try:
        while True:
            try:
                # 用 getmany() + 外层 wait_for 做主动超时探测，
                # 而不是 `async for msg in consumer`。
                # 原因：aiokafka 在网络抖动后内部 fetcher 协程可能"假死"
                # （已知边界 bug：KeyError on _conns，异常被内部吞掉不会
                # 冒泡给 async for），假死之后 async for 会永远挂起、
                # 拿不到任何超时信号。getmany 配合 wait_for 能主动检测
                # "太久没有一次正常返回"，从而判定 consumer 已不健康。
                result = await asyncio.wait_for(
                    consumer.getmany(timeout_ms=GETMANY_TIMEOUT_MS),
                    timeout=POLL_WATCHDOG_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "[consumer] %d秒内未能完成一次正常poll，怀疑内部fetcher已假死，"
                    "主动触发consumer重建",
                    POLL_WATCHDOG_TIMEOUT_SEC,
                )
                raise RuntimeError("consumer poll watchdog timeout, forcing restart")

            for tp, messages in result.items():
                if messages:
                    await _handle_batch(messages)

    except asyncio.CancelledError:
        logger.info("[consumer] 收到取消信号，正常停止")
        raise
    except Exception:
        logger.exception("[consumer] 消费循环里发生异常，consumer 即将停止并由外层重建")
        raise
    finally:
        with contextlib.suppress(Exception):
            await consumer.stop()
        logger.info("[consumer] 已停止")


async def _consume_loop_forever():
    """外层兜底：不管 _consume_loop 是显式抛异常退出，还是被看门狗
    主动打断，都在这里捕获并在短暂等待后自动重建，避免需要人工重启进程。
    """
    backoff_sec = 5
    while True:
        try:
            await _consume_loop()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error(
                "[consumer] consumer 异常退出，%d 秒后自动重启...",
                backoff_sec,
            )
            await asyncio.sleep(backoff_sec)


def start_consumer_background():
    """在 FastAPI startup 事件里调用一次。"""
    global _consumer_task
    if _consumer_task is not None:
        logger.warning("[consumer] start_consumer_background 被重复调用，忽略")
        return

    _consumer_task = asyncio.create_task(_consume_loop_forever())

    def _on_done(task: asyncio.Task):
        # 正常情况下 _consume_loop_forever 是个死循环，不会主动结束；
        # 如果它意外结束了（比如内部代码逻辑错误），这里能捕获到并打印，
        # 不会被 asyncio 静默吞掉。
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("[consumer] 后台任务异常退出（不应该发生）: %r", exc, exc_info=exc)

    _consumer_task.add_done_callback(_on_done)


def stop_consumer_background():
    """在 FastAPI shutdown 事件里调用一次。"""
    global _consumer_task
    if _consumer_task:
        _consumer_task.cancel()
        _consumer_task = None


@router.websocket("/ws/transcript")
async def transcript_ws(
        websocket: WebSocket,
        call_id: Optional[str] = Query(default=None),
        agent_ch: Optional[str] = Query(default=None),
):
    """前端连接: ws://<host>:<port>/ws/transcript
    - ?agent_ch=4   坐席端启动时用，只收绑定到该线路号的通话（推荐，坐席工作台常用）
    - ?call_id=xxx  可选，进一步只看某一通具体的通话
    - 都不传        收到所有通话的消息（多路复用，前端自己按 call_id 分流，慎用于生产环境）
    两个参数可以同时传，取交集。
    """
    logger.info("[ws] 收到连接请求: agent_ch=%r call_id=%r", agent_ch, call_id)
    await manager.connect(websocket, call_id, agent_ch)
    try:
        while True:
            # 只做单向推送，读一下客户端心跳/ping 防止连接被判定为死连接即可
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)