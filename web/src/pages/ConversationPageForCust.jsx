import { useState, useEffect } from "react"
import { Badge } from "@/components/ui/badge"
import { MessageCircle, Bot, User, Calendar, Phone, RefreshCw, ArrowLeft } from "lucide-react"

const STATUS = {
  active:      { label: "进行中",   cls: "border-green-400 text-green-700 bg-green-50" },
  ended:       { label: "已结束",   cls: "border-gray-300  text-gray-500  bg-gray-50"  },
  transferred: { label: "已转人工", cls: "border-amber-400 text-amber-700 bg-amber-50" },
}

function fmt(iso) {
  return new Date(iso).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
}
function dur(s) { return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60}s` }

// 不再按日期过滤，直接取最新N条最简单可靠，避免时区问题
const LATEST_N = 10

// 根据来电号码前缀判断 Skill 类型
function getSkillType(phone) {
  if (!phone) return null
  if (phone.startsWith("1350000")) return { label: "RAG知识库",  cls: "bg-teal-50 text-teal-700 border-teal-300" }
  if (phone.startsWith("1360000")) return { label: "AI快递查询", cls: "bg-orange-50 text-orange-700 border-orange-300" }
  if (phone.startsWith("1370000")) return { label: "AI投诉工单", cls: "bg-purple-50 text-purple-700 border-purple-300" }
  if (phone.startsWith("1380000")) return { label: "AI宽带报修", cls: "bg-red-50 text-red-700 border-red-300" }
  return null
}

export default function ConversationPageForCust() {
  const [activeId, setActiveId] = useState(null)
  const [active,   setActive]   = useState(null)
  const [sessions, setSessions] = useState([])
  const [messages, setMessages] = useState([])
  const [loading,  setLoading]  = useState(false)
  const [listLoading, setListLoading] = useState(true)
  const [refresh,  setRefresh]  = useState(0)

  // 移动端：是否已进入"详情视图"（用于上下/抽屉式切换）
  const [mobileShowDetail, setMobileShowDetail] = useState(false)

  useEffect(() => {
    setListLoading(true)
    const params = new URLSearchParams()
    // 不传日期范围，只要后端按更新时间倒序返回，取最新的就行
    params.set("page", 1)
    params.set("page_size", LATEST_N)

    fetch(`/aiweb/api/conversations?${params}`)
      .then(r => r.json())
      .then(data => {
        const list = (data.data ?? []).slice().sort(
          (a, b) => new Date(b.start_at) - new Date(a.start_at)
        ).slice(0, LATEST_N)   // 再保险一道，确保最终只展示最新 N 条
        setSessions(list)
        setListLoading(false)
      })
      .catch(() => { setSessions([]); setListLoading(false) })
  }, [refresh])

  function openSession(id) {
    setActiveId(id)
    setMobileShowDetail(true)   // 移动端：点击后切到详情视图
    setLoading(true)
    fetch(`/aiweb/api/conversations/${id}`)
      .then(r => r.json())
      .then(data => {
        setActive(data)
        setMessages(data.messages ?? [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }

  function backToList() {
    setMobileShowDetail(false)
  }

  return (
    <div className="flex flex-col h-full">
      {/* 顶部条 */}
      <div className="border-b bg-card px-4 flex items-center h-11 shrink-0">
        {/* 移动端详情视图下显示返回按钮，桌面端不显示 */}
        {mobileShowDetail && activeId && (
          <button
            onClick={backToList}
            className="md:hidden flex items-center gap-1 text-xs text-muted-foreground mr-2"
          >
            <ArrowLeft className="w-4 h-4" />返回
          </button>
        )}
        <MessageCircle className="w-4 h-4 text-blue-500 mr-2" />
        <span className="text-sm font-medium">话单查询 · AI 对话记录</span>
        <span className="ml-2 text-[11px] text-muted-foreground hidden sm:inline">（最新{LATEST_N}条）</span>
        <button
          onClick={() => setRefresh(r => r + 1)}
          className="ml-auto flex items-center gap-1 text-xs text-muted-foreground hover:text-blue-600 transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />刷新
        </button>
      </div>

      {/* 桌面端：左右分栏 flex-row；移动端：单栏切换显示，用 md: 断点控制 */}
      <div className="flex flex-1 overflow-hidden flex-col md:flex-row">

        {/* 会话列表 —— 移动端：未点开详情时全屏显示；已点开则隐藏（除非是 md 桌面端，桌面端始终显示） */}
        <div
          className={`border-r flex-col shrink-0 md:flex md:w-[272px] w-full
            ${mobileShowDetail ? "hidden md:flex" : "flex"}`}
        >
          <div className="flex-1 overflow-y-auto">
            {listLoading && (
              <p className="text-xs text-muted-foreground text-center py-8">加载中...</p>
            )}
            {!listLoading && sessions.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-8">暂无对话记录</p>
            )}
            {!listLoading && sessions.map(s => {
              const st = STATUS[s.status] ?? STATUS.ended
              return (
                <button
                  key={s._id}
                  onClick={() => openSession(s._id)}
                  className={`w-full text-left px-3 py-3 md:py-2.5 border-b hover:bg-muted active:bg-muted transition-colors ${
                    activeId === s._id ? "bg-blue-50" : ""
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-1.5">
                      <Phone className="w-3 h-3 text-muted-foreground" />
                      <span className="text-xs font-medium">{s.caller}</span>
                      {getSkillType(s.caller) && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded border ${getSkillType(s.caller).cls}`}>
                          {getSkillType(s.caller).label}
                        </span>
                      )}
                    </div>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded border ${st.cls}`}>{st.label}</span>
                  </div>
                  <div className="flex justify-between text-[11px] text-muted-foreground">
                    <span>{fmt(s.start_at)}</span>
                    <span className="font-mono">{s.sn}</span>
                  </div>
                </button>
              )
            })}
          </div>
          <div className="border-t px-3 py-2 bg-card shrink-0">
            <span className="text-[11px] text-muted-foreground">共 {sessions.length} 条 · 按最新时间排序</span>
          </div>
        </div>

        {/* 对话详情 —— 移动端：未点开详情时隐藏；已点开则全屏显示（除非是 md 桌面端，桌面端始终显示） */}
        <div
          className={`flex-1 flex-col overflow-hidden bg-background
            ${mobileShowDetail ? "flex" : "hidden md:flex"}`}
        >
          {!activeId ? (
            <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-2">
              <MessageCircle className="w-8 h-8 opacity-20" />
              <span className="text-sm">选择左侧一条记录查看对话详情</span>
            </div>
          ) : (
            <>
              <div className="border-b bg-card px-4 py-2.5 flex items-center gap-3 shrink-0 flex-wrap">
                <Phone className="w-4 h-4 text-muted-foreground" />
                <span className="text-sm font-medium">{active?.caller}</span>
                <Badge variant="outline" className={`text-xs ${STATUS[active?.status]?.cls}`}>
                  {STATUS[active?.status]?.label}
                </Badge>
                <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
                  <span className="flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    {active?.start_at && fmt(active.start_at)}
                  </span>
                  <span>{active?.turn_count} 轮</span>
                  <span>{dur(active?.duration_s ?? 0)}</span>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 space-y-4">
                {loading && <p className="text-xs text-muted-foreground text-center py-8">加载中...</p>}
                {!loading && messages.map((m, i) => {
                  const isBot = m.role === "bot"
                  return (
                    <div key={i} className={`flex gap-2.5 ${isBot ? "" : "flex-row-reverse"}`}>
                      <div
                        className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
                          isBot ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-600"
                        }`}
                      >
                        {isBot ? <Bot className="w-3.5 h-3.5" /> : <User className="w-3.5 h-3.5" />}
                      </div>
                      <div className="max-w-[85%] md:max-w-[72%]">
                        <div
                          className={`rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                            isBot ? "bg-card border rounded-tl-sm" : "bg-blue-500 text-white rounded-tr-sm"
                          }`}
                        >
                          {m.text}
                        </div>
                        <p className={`text-[10px] text-muted-foreground mt-1 ${isBot ? "" : "text-right"}`}>{m.ts}</p>
                      </div>
                    </div>
                  )
                })}
              </div>

              <div className="border-t px-4 py-2 bg-card shrink-0">
                <p className="text-[11px] text-muted-foreground">
                  客户体验专区 · 只读模式 — 仅展示最新 {LATEST_N} 条 AI 对话记录
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
