import { useState, useEffect, useRef, useCallback } from "react"
import { searchKnowledge, listCategories } from "@/api/knowledge"
import { Button } from "@/components/ui/button"
import { Input }  from "@/components/ui/input"
import { Badge }  from "@/components/ui/badge"
import {
  MessageCircle, User, Headphones, Sparkles, Send, Database,
  Search, Zap, Loader2, ArrowLeftRight, Info, Radio, RadioTower,
} from "lucide-react"

// WebSocket 桥接地址：由后端 kafka_ws_bridge.py 提供，实时转发
// call.asr.transcript topic 的消息。可选带 ?call_id= 只订阅一通电话。
// 按你的实际部署改这里（或改成从环境变量 / 配置接口读取）。
const TRANSCRIPT_WS_BASE =
  (import.meta?.env?.VITE_TRANSCRIPT_WS_URL) || "ws://localhost:7626/ws/transcript"

// 坐席端固定线路号。真实场景下这个值应该来自坐席登录/工位分配（比如登录接口
// 返回、或者话机/软电话配置），而不是写死在前端代码里。这里先支持两种来源：
// 1) 构建时环境变量 VITE_AGENT_CH（同一坐席机器长期固定用这个最省事）
// 2) 页面 URL 上的 ?agentCh=4（工位切换坐席、或多坐席共用一个部署时更灵活）
// URL 参数优先级更高。
function resolveAgentCh() {
  const fromUrl = new URLSearchParams(window.location.search).get("agentCh")
  if (fromUrl) return fromUrl
  return import.meta?.env?.VITE_AGENT_CH || ""
}

const RECONNECT_DELAY_MS = 3000

// Quick example utterances that are known to match the seed knowledge base,
// so clicking them always produces a non-empty demo result instead of an
// empty "no matches" panel.
const QUICK_EXAMPLES = [
  "忘记密码怎么办",
  "怎么参加省市级培训",
  "电脑最低配置要求是什么",
]

// ── Demo-only suggestion generator ──────────────────────────────────────
// This is NOT a real LLM call — it turns the top KB matches into 1-2
// candidate replies so the "AI建议" column has something concrete to show.
// Wiring this to a real generation endpoint (e.g. main_ai chat completion)
// is the natural next step once the layout/UX is confirmed.
function buildSuggestions(query, kbResults) {
  if (!kbResults.length) return []
  const top = kbResults[0]
  const suggestions = [
    {
      id: "concise",
      label: "简洁回复",
      confidence: Math.max(0, Math.round((1 - top.distance) * 100)),
      text: top.content,
    },
  ]
  if (kbResults.length > 1) {
    const second = kbResults[1]
    suggestions.push({
      id: "detailed",
      label: "补充说明",
      confidence: Math.max(0, Math.round((1 - second.distance) * 100)),
      text: `${top.content}\n\n另外：${second.content}`,
    })
  }
  return suggestions
}

function Bubble({ role, text }) {
  const isCustomer = role === "customer"
  return (
    <div className={`flex gap-2 ${isCustomer ? "" : "flex-row-reverse"}`}>
      <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 mt-0.5
        ${isCustomer ? "bg-muted text-muted-foreground" : "bg-blue-500 text-white"}`}>
        {isCustomer ? <User className="w-3.5 h-3.5" /> : <Headphones className="w-3.5 h-3.5" />}
      </div>
      <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap
        ${isCustomer ? "bg-muted" : "bg-blue-500 text-white"}`}>
        {text}
      </div>
    </div>
  )
}

export default function CopilotPage() {
  const [messages,    setMessages]    = useState([
    { role: "agent", text: "您好，这里是客服中心，请问有什么可以帮您？" },
  ])
  const [draftCustomer, setDraftCustomer] = useState("")
  const [draftAgent,    setDraftAgent]    = useState("")
  const [cats,        setCats]        = useState([])
  const [kbResults,   setKbResults]   = useState([])
  const [suggestions, setSuggestions] = useState([])
  const [kbLoading,   setKbLoading]   = useState(false)
  const [lastQuery,   setLastQuery]   = useState("")

  // ── 实时模式（订阅 Kafka call.asr.transcript）状态 ──────────────
  const [liveMode, setLiveMode] = useState(true)
  const [agentCh,  setAgentCh]  = useState(() => resolveAgentCh()) // 坐席固定线路号，主过滤条件
  const [callId,   setCallId]   = useState("")       // 可选，进一步只看某一通具体通话
  const [wsStatus, setWsStatus] = useState("idle")   // idle | connecting | connected | error
  const wsRef = useRef(null)
  const reconnectTimerRef = useRef(null)
  const seenFinalIdsRef = useRef(new Set()) // 简单去重（同一句 final 消息可能重复到达）

  const scrollRef = useRef()

  useEffect(() => { listCategories().then(setCats).catch(() => {}) }, [])
  useEffect(() => {
    // Whole page scrolls now (no per-column overflow), so just bring the
    // latest message into view instead of setting an internal scrollTop.
    scrollRef.current?.scrollIntoView({ block: "end", behavior: "smooth" })
  }, [messages])

  async function runCopilot(query) {
    setLastQuery(query)
    setKbLoading(true)
    try {
      const items = await searchKnowledge({ q: query })
      setKbResults(items || [])
      setSuggestions(buildSuggestions(query, items || []))
    } catch {
      setKbResults([]); setSuggestions([])
    }
    setKbLoading(false)
  }

  function sendCustomerMessage(text) {
    const t = (text ?? draftCustomer).trim()
    if (!t) return
    setMessages(m => [...m, { role: "customer", text: t }])
    setDraftCustomer("")
    runCopilot(t)
  }

  function sendAgentMessage() {
    const t = draftAgent.trim()
    if (!t) return
    setMessages(m => [...m, { role: "agent", text: t }])
    setDraftAgent("")
  }

  // 收到一条来自 Kafka 的转写消息（经 kafka_ws_bridge.py 转发过来）
  const handleTranscriptRecord = useCallback((record) => {
    // record: { call_id, speaker: "customer"|"agent", text, is_final, ts }
    if (!record?.text) return
    if (!record.is_final) return // 中间态（流式部分结果）先不上屏，避免气泡狂跳；需要的话这里可以做"实时更新最后一条"逻辑

    const dedupeKey = `${record.call_id}:${record.speaker}:${record.ts}:${record.text}`
    if (seenFinalIdsRef.current.has(dedupeKey)) return
    seenFinalIdsRef.current.add(dedupeKey)

    const role = record.speaker === "agent" ? "agent" : "customer"
    setMessages(m => [...m, { role, text: record.text }])

    // 客户说话 → 自动触发知识库检索 + AI 建议生成
    if (role === "customer") runCopilot(record.text)
  }, [])

  // 建立/维护 WebSocket 连接（实时模式开启时）
  useEffect(() => {
    if (!liveMode) {
      wsRef.current?.close()
      wsRef.current = null
      setWsStatus("idle")
      return
    }

    let cancelled = false

    function connect() {
      if (cancelled) return
      setWsStatus("connecting")
      const params = new URLSearchParams()
      if (agentCh) params.set("agent_ch", agentCh)
      if (callId)  params.set("call_id", callId)
      const qs = params.toString()
      const url = qs ? `${TRANSCRIPT_WS_BASE}?${qs}` : TRANSCRIPT_WS_BASE
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => { if (!cancelled) setWsStatus("connected") }
      ws.onmessage = (evt) => {
        try { handleTranscriptRecord(JSON.parse(evt.data)) }
        catch { /* 忽略解析失败的心跳/非 JSON 消息 */ }
      }
      ws.onerror = () => { if (!cancelled) setWsStatus("error") }
      ws.onclose = () => {
        if (cancelled) return
        setWsStatus("error")
        reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS)
      }
    }
    connect()

    return () => {
      cancelled = true
      clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [liveMode, agentCh, callId, handleTranscriptRecord])

  return (
    <div className="flex flex-col min-h-full">
      <div className="border-b bg-card px-4 flex items-center h-10 shrink-0 gap-2">
        <Sparkles className="w-4 h-4 text-blue-500" />
        <span className="text-sm font-medium">AI 副驾驶</span>
        <span className="text-xs text-muted-foreground">坐席实时辅助</span>

        <div className="ml-auto flex items-center gap-2">
          {liveMode && (
            <Badge
              variant="outline"
              className={`text-[10px] gap-1 ${
                wsStatus === "connected" ? "text-green-600 border-green-300" :
                wsStatus === "error"     ? "text-red-600 border-red-300" :
                                            "text-amber-600 border-amber-300"
              }`}
            >
              {wsStatus === "connected" ? <Radio className="w-2.5 h-2.5" /> : <Loader2 className="w-2.5 h-2.5 animate-spin" />}
              {wsStatus === "connected" ? "Kafka 已连接" : wsStatus === "error" ? "重连中…" : "连接中…"}
            </Badge>
          )}
          <Button
            size="sm" variant={liveMode ? "default" : "outline"} className="h-7 text-xs gap-1"
            onClick={() => setLiveMode(v => !v)}
          >
            <RadioTower className="w-3 h-3" />
            {liveMode ? "实时模式" : "模拟模式"}
          </Button>
        </div>
      </div>

      <div className="flex-1 grid grid-cols-3 gap-3 p-3">

        {/* ── Column 1: live customer / agent conversation ───────────── */}
        <div className="flex flex-col border rounded-lg bg-card">
          <div className="px-3 py-2 border-b flex items-center gap-1.5">
            <MessageCircle className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs font-medium">客户 / 坐席 实时对话</span>
            {liveMode && (
              <div className="ml-auto flex items-center gap-1">
                <span className="text-[10px] text-muted-foreground">线路</span>
                <Input value={agentCh} onChange={e => setAgentCh(e.target.value)}
                  placeholder="agentCh" className="h-6 text-[10px] w-14" />
                <Input value={callId} onChange={e => setCallId(e.target.value)}
                  placeholder="call_id（可选）"
                  className="h-6 text-[10px] w-28" />
              </div>
            )}
          </div>

          <div ref={scrollRef} className="p-3 space-y-3">
            {messages.map((m, i) => <Bubble key={i} role={m.role} text={m.text} />)}
            {liveMode && messages.length <= 1 && (
              <p className="text-[11px] text-muted-foreground text-center py-4">
                {agentCh
                  ? `等待线路 ${agentCh} 上的 Kafka 转写结果…`
                  : "未绑定坐席线路号（agentCh），将收到所有通话的转写结果"}
              </p>
            )}
          </div>

          <div className="border-t p-2 space-y-2">
            {!liveMode && (
              <>
                <div className="flex flex-wrap gap-1">
                  {QUICK_EXAMPLES.map(q => (
                    <button key={q} onClick={() => sendCustomerMessage(q)}
                      className="text-[10px] px-2 py-1 rounded-full border text-muted-foreground hover:bg-muted hover:text-foreground transition-colors">
                      {q}
                    </button>
                  ))}
                </div>
                <div className="flex gap-1.5">
                  <Input value={draftCustomer} onChange={e => setDraftCustomer(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && sendCustomerMessage()}
                    placeholder="模拟客户发言…" className="h-8 text-xs" />
                  <Button size="sm" className="h-8 px-2" onClick={() => sendCustomerMessage()}>
                    <Send className="w-3.5 h-3.5" />
                  </Button>
                </div>
              </>
            )}
            <div className="flex gap-1.5">
              <Input value={draftAgent} onChange={e => setDraftAgent(e.target.value)}
                onKeyDown={e => e.key === "Enter" && sendAgentMessage()}
                placeholder="坐席回复（可从右侧 AI 建议一键插入）…" className="h-8 text-xs" />
              <Button size="sm" variant="outline" className="h-8 px-2" onClick={sendAgentMessage}>
                <Headphones className="w-3.5 h-3.5" />
              </Button>
            </div>
          </div>
        </div>

        {/* ── Column 2: AI suggestions ─────────────────────────────────── */}
        <div className="flex flex-col border rounded-lg bg-card">
          <div className="px-3 py-2 border-b flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs font-medium">AI 建议</span>
            {lastQuery && <Badge variant="secondary" className="text-[10px] ml-auto max-w-[45%] truncate">对: {lastQuery}</Badge>}
          </div>

          <div className="p-3 space-y-3">
            {kbLoading && (
              <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground py-8">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />生成建议中…
              </div>
            )}
            {!kbLoading && suggestions.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-8">
                发送一条客户消息，AI 会根据知识库检索结果生成建议回复
              </p>
            )}
            {!kbLoading && suggestions.map(s => (
              <div key={s.id} className="border rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="text-[10px]">{s.label}</Badge>
                  <span className="ml-auto text-[10px] text-muted-foreground">
                    置信度 <span className={s.confidence >= 65 ? "text-green-600 font-medium" : "text-amber-600 font-medium"}>{s.confidence}%</span>
                  </span>
                </div>
                <p className="text-xs leading-relaxed whitespace-pre-wrap">{s.text}</p>
                <Button size="sm" variant="outline" className="w-full h-7 text-xs"
                  onClick={() => setDraftAgent(s.text)}>
                  <ArrowLeftRight className="w-3 h-3 mr-1" />插入到坐席回复
                </Button>
              </div>
            ))}
          </div>

          <div className="border-t px-3 py-2">
            <p className="text-[10px] text-muted-foreground flex items-start gap-1">
              <Info className="w-3 h-3 mt-0.5 shrink-0" />
              Demo：建议由知识库检索结果拼装生成，可对接正式的生成式回复接口
            </p>
          </div>
        </div>

        {/* ── Column 3: knowledge base panel ──────────────────────────── */}
        <div className="flex flex-col border rounded-lg bg-card">
          <div className="px-3 py-2 border-b flex items-center gap-1.5">
            <Database className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs font-medium">知识库</span>
            {cats.length > 0 && <Badge variant="secondary" className="text-[10px] ml-auto">{cats.length} 个分类</Badge>}
          </div>

          <div className="p-3 space-y-2.5">
            {kbLoading && (
              <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground py-8">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />检索中…
              </div>
            )}
            {!kbLoading && kbResults.length === 0 && (
              <div className="text-xs text-muted-foreground text-center py-8 flex flex-col items-center gap-1.5">
                <Search className="w-4 h-4 opacity-40" />
                随对话自动检索相关知识条目
              </div>
            )}
            {!kbLoading && kbResults.map((r, i) => (
              <div key={i} className={`p-2.5 border rounded-lg ${i === 0 ? "border-blue-400" : "border-border"}`}>
                <div className="flex items-center gap-1.5 mb-1">
                  <span className={`w-4 h-4 rounded text-[10px] font-bold flex items-center justify-center shrink-0
                    ${i === 0 ? "bg-blue-500 text-white" : "bg-muted text-muted-foreground"}`}>{i + 1}</span>
                  <Badge variant="outline" className="text-[10px]">{r.category}</Badge>
                  <span className="text-xs font-medium truncate">{r.summary}</span>
                </div>
                <p className="text-[11px] text-muted-foreground leading-relaxed">{r.content}</p>
                <div className="text-[10px] mt-1 text-right">
                  distance: <span className={`font-bold ${r.distance < 0.35 ? "text-green-600" : r.distance < 0.55 ? "text-amber-600" : "text-red-600"}`}>{r.distance}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
