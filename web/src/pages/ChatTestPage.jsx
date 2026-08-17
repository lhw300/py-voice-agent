import { useState, useRef, useEffect } from "react"
import { Send, RotateCcw } from "lucide-react"
import { Button } from "@/components/ui/button"

// 生成一个新会话的 sn / call_date / start_time
function newSessionMeta() {
  const sn = String(Math.floor(1000 + Math.random() * 9000))
  const now = new Date()
  const call_date = now.toISOString().slice(0, 10)
  const start_time = now.toTimeString().slice(0, 8)
  return { sn, call_date, start_time }
}

function formatCost(cost) {
  if (!cost) return null
  return Object.entries(cost)
    .map(([k, v]) => `${k} ${v}ms`)
    .join(", ")
}

function formatShortFields(data) {
  const skip = new Set(["answer", "cost"])
  return Object.entries(data)
    .filter(([k]) => !skip.has(k))
    .map(([k, v]) => `${k}=${v ?? "None"}`)
    .join(" ")
}

// 把输入拆成多条连环消息：按 / 或换行分隔，去掉空白项
function splitBatch(raw) {
  return raw
    .split(/[/\n]/)
    .map(s => s.trim())
    .filter(Boolean)
}

// 耗时字段关系图（跟 chat_test.py 里的 COST_DIAGRAM 保持一致）
const COST_DIAGRAM = `客户端总耗时
└── server_total                    main_ai.py: ai_send() 全程
    │
    ├── upsert_call                 MongoDB 写通话记录（线程池）
    │
    └── ask_layer_total             session.ask_skill() + session.ask()
        │
        ├── 【路径一】命中技能工具（hit_source=skill，如报修/投诉/查快递）
        │   直接从 ask_skill() 返回，不会进入 session.ask()
        │   │
        │   ├── tools        ★LLM调用①  判断要调用哪个工具
        │   ├── skill_exec              执行工具本身
        │   ├── final_reply  ★LLM调用②  把工具结果转述成自然语言
        │   └── skill_total             = tools + skill_exec + final_reply
        │
        └── 【路径二】未命中工具 → fallback 到 session.ask()（普通问答/闲聊）
            │
            ├── tools        ★LLM调用①  判断要不要调工具（判断结果：不需要）
            │
            └── ask_total                session.ask() 内部小计
                │
                ├── classify  ★LLM调用②  意图分类
                │                         (命中fast-track时为0ms)
                ├── k1                    精确缓存查找（仅QUERY走）
                │
                └── handler                intentDispatcher.dispatch()
                    │
                    ├── k2                语义缓存命中 → 直接返回
                    ├── retrieval         (K2未命中) 两阶段向量检索+rerank
                    └── final_ask         (K2未命中) ★LLM调用③ 生成最终答案

加法关系：
  【路径一】tools + skill_exec + final_reply ≈ skill_total
  【路径二】tools + ask_total ≈ ask_layer_total
           classify + k1 + handler ≈ ask_total
           k2 ≈ handler（K2命中）；retrieval + final_ask ≈ handler（K2未命中）
  两条路径共同：upsert_call + ask_layer_total ≈ server_total

批量连环发送：
  用 / 或换行分隔多条消息即可依次发送，例如：
  hi/学生密码多少/学生密码是什么
  会自动按顺序逐条发送、等上一条回复完成后再发下一条`

// sessionStorage 存储 key，用于在切换 tab / 组件重新挂载后恢复聊天状态
const STORAGE_KEY = "chatTestPage_state_v1"

function loadPersistedState() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function savePersistedState(session, messages, turn) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ session, messages, turn }))
  } catch {
    // sessionStorage 不可用时静默忽略，不影响正常聊天功能
  }
}

export default function ChatTestPage() {
  const persisted = loadPersistedState()

  const [session, setSession] = useState(() => persisted?.session ?? newSessionMeta())
  const [messages, setMessages] = useState(() => persisted?.messages ?? [])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [batchProgress, setBatchProgress] = useState(null) // { current, total } | null
  const turnRef = useRef(persisted?.turn ?? 0)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)
  const abortBatchRef = useRef(false)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, loading])

  useEffect(() => {
    if (!loading) {
      inputRef.current?.focus()
    }
  }, [loading])

  // 每次 session / messages 变化时，同步存一份到 sessionStorage，
  // 这样切到别的 tab 再切回来（组件被重新挂载）时，聊天记录还在
  useEffect(() => {
    savePersistedState(session, messages, turnRef.current)
  }, [session, messages])

  function startNewSession() {
    const fresh = newSessionMeta()
    setSession(fresh)
    setMessages([])
    turnRef.current = 0
    abortBatchRef.current = false
    setBatchProgress(null)
    savePersistedState(fresh, [], 0)
  }

  function showDiagram() {
    setMessages(m => [...m, { role: "system", text: COST_DIAGRAM }])
    setInput("")
    inputRef.current?.focus()
  }

  // 发送单条消息，返回是否成功（用于连环发送时判断要不要继续）
  async function sendOne(text, batchMeta) {
    turnRef.current += 1
    const turn = turnRef.current

    setMessages(m => [...m, { role: "user", text, turn }])

    const t0 = performance.now()
    try {
      const resp = await fetch("/ai_send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sn:         session.sn,
          crid:       "c1",
          ch:         "1",
          call_date:  session.call_date,
          start_time: session.start_time,
          phone:      "13800009999",
          vo_id:      "ai_send",
          text,
          turn: String(turn),
        }),
      })
      const elapsed = Math.round(performance.now() - t0)
      const data = await resp.json()

      if (!resp.ok) {
        setMessages(m => [...m, {
          role: "assistant",
          text: `[错误 ${resp.status}] ${JSON.stringify(data)}`,
          elapsed, turn, batchMeta,
        }])
        return false
      }

      setMessages(m => [...m, {
        role: "assistant",
        text: data.answer || "",
        meta: formatShortFields(data),
        cost: formatCost(data.cost),
        elapsed, turn, batchMeta,
      }])
      return true
    } catch (e) {
      setMessages(m => [...m, { role: "assistant", text: `[网络错误] ${e.message}`, turn, batchMeta }])
      return false
    }
  }

  async function send() {
    const raw = input.trim()
    if (!raw || loading) return

    if (raw.toLowerCase() === "cost" || raw.toLowerCase() === "diagram") {
      showDiagram()
      return
    }

    const batch = splitBatch(raw)
    setInput("")

    if (batch.length <= 1) {
      // 单条消息，走原来的路径
      setLoading(true)
      await sendOne(batch[0] ?? raw)
      setLoading(false)
      return
    }

    // 连环发送：依次发送，每条等上一条回复完再发下一条
    setLoading(true)
    abortBatchRef.current = false
    for (let i = 0; i < batch.length; i++) {
      if (abortBatchRef.current) break
      setBatchProgress({ current: i + 1, total: batch.length })
      await sendOne(batch[i], { current: i + 1, total: batch.length })
    }
    setBatchProgress(null)
    setLoading(false)
  }

  function stopBatch() {
    abortBatchRef.current = true
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="border-b px-4 py-2.5 flex items-center justify-between shrink-0">
        <div className="text-sm text-muted-foreground">
          会话 sn=<span className="font-mono">{session.sn}</span>
          {"  "}call_date={session.call_date}{"  "}start_time={session.start_time}
          {"  "}<span className="text-[11px] text-muted-foreground/60">
            （输入 cost 查看耗时关系图 · 用 / 分隔多条消息可连环发送）
          </span>
        </div>
        <div className="flex items-center gap-2">
          {batchProgress && (
            <span className="text-xs text-blue-600 font-mono">
              连环发送中 {batchProgress.current}/{batchProgress.total}
            </span>
          )}
          {batchProgress && (
            <Button variant="outline" size="sm" onClick={stopBatch}>
              停止
            </Button>
          )}
          <Button variant="outline" size="sm" className="gap-1.5" onClick={startNewSession}>
            <RotateCcw className="w-3.5 h-3.5" />新会话
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground/60 text-center mt-8">
            输入内容开始测试对话，输入 cost 查看耗时关系图。
            <br />
            用 / 分隔多条消息（如 hi/学生密码多少/退出）可依次连环发送
          </p>
        )}

        {messages.map((m, i) => {
          if (m.role === "system") {
            return (
              <div key={i} className="flex justify-center">
                <pre className="max-w-[90%] bg-slate-900 text-slate-100 rounded-lg px-4 py-3 text-[11px] font-mono whitespace-pre overflow-x-auto">
                  {m.text}
                </pre>
              </div>
            )
          }
          const isUser = m.role === "user"
          return (
            <div key={i} className={isUser ? "flex justify-end" : "flex justify-start"}>
              <div className="max-w-[75%]">
                {m.batchMeta && (
                  <div className={`text-[10px] text-blue-500/70 font-mono mb-0.5 ${isUser ? "text-right" : ""}`}>
                    第{m.batchMeta.current}/{m.batchMeta.total}轮
                  </div>
                )}
                <div className={`rounded-lg px-3 py-2 text-sm
                  ${isUser ? "bg-blue-600 text-white" : "bg-muted"}`}>
                  {!isUser && m.meta && (
                    <div className="text-[11px] text-muted-foreground mb-1 font-mono break-all">{m.meta}</div>
                  )}
                  <div className="whitespace-pre-wrap">{m.text}</div>
                  {!isUser && m.cost && (
                    <div className="text-[11px] text-amber-600 mt-1 font-mono break-all">cost: {m.cost}</div>
                  )}
                  <div className="flex items-center justify-between gap-2 mt-1">
                    {m.turn != null && (
                      <span className={`text-[10px] font-mono ${isUser ? "text-white/60" : "text-muted-foreground/60"}`}>
                        turn={m.turn}
                      </span>
                    )}
                    {m.elapsed != null && (
                      <span className={`text-[10px] ${isUser ? "text-white/60" : "text-muted-foreground/60"}`}>
                        [{m.elapsed}ms]
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )
        })}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-muted rounded-lg px-3 py-2 text-sm text-muted-foreground">
              {batchProgress
                ? `思考中...（连环 ${batchProgress.current}/${batchProgress.total}）`
                : "思考中..."}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="border-t p-3 flex gap-2 shrink-0">
        <textarea
          ref={inputRef}
          className="flex-1 border rounded-lg px-3 py-2 text-sm resize-none h-10 focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="输入消息，Enter 发送（用 / 分隔多条可连环发送，如 hi/学生密码多少）"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
        />
        <Button className="gap-1.5" onClick={send} disabled={loading || !input.trim()}>
          <Send className="w-4 h-4" />发送
        </Button>
      </div>
    </div>
  )
}