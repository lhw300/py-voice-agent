import { useState, useEffect } from "react"
import { Input }  from "@/components/ui/input"
import { Badge }  from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { BarChart2, Inbox, Search, Phone, MessageCircle, Bot, User, Calendar } from "lucide-react"

const STATUS = {
  active:      { label: "进行中",  cls: "border-green-400 text-green-700 bg-green-50" },
  ended:       { label: "已结束",  cls: "border-gray-300  text-gray-500  bg-gray-50"  },
  transferred: { label: "已转人工",cls: "border-amber-400 text-amber-700 bg-amber-50" },
}

function fmt(iso) {
  return new Date(iso).toLocaleString("zh-CN", { month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit" })
}
function dur(s) { return s < 60 ? `${s}s` : `${Math.floor(s/60)}m${s%60}s` }

const today = new Date().toISOString().slice(0, 10)

const TABS = [
  { value: "list",  label: "会话列表", icon: Inbox },
  { value: "stats", label: "统计",    icon: BarChart2 },
]

export default function ConversationPage() {
  const [tab,      setTab]      = useState("list")
  const [activeId, setActiveId] = useState(null)
  const [active,   setActive]   = useState(null)
  const [sessions, setSessions] = useState([])
  const [messages, setMessages] = useState([])
  const [loading,  setLoading]  = useState(false)
  const [fStatus,  setFStatus]  = useState("all")
  const [search,   setSearch]   = useState("")

  const [searchSn, setSearchSn] = useState("")
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo,   setDateTo]   = useState("")
  const [refresh,  setRefresh]  = useState(0)
  const [keyword,  setKeyword]  = useState("")
  const [page,     setPage]     = useState(1)
  const [total,    setTotal]    = useState(0)
  const PAGE_SIZE = 20

  useEffect(() => {
    const params = new URLSearchParams()
    if (fStatus  !== "all") params.set("status",    fStatus)
    if (search)             params.set("phone",      search)
    if (searchSn)           params.set("sn",         searchSn)
    if (dateFrom)           params.set("date_from",  dateFrom)
    if (dateTo)             params.set("date_to",    dateTo)
    if (keyword)            params.set("keyword",     keyword)
    params.set("page",      page)
    params.set("page_size", PAGE_SIZE)

    fetch(`/api/conversations?${params}`)
      .then(r => r.json())
      .then(data => { setSessions(data.data ?? []); setTotal(data.total ?? 0) })
      .catch(() => setSessions([]))
  }, [fStatus, search, searchSn, dateFrom, dateTo, keyword, refresh, page])

  function openSession(id) {
    setActiveId(id)
    setLoading(true)
    fetch(`/api/conversations/${id}`)
      .then(r => r.json())
      .then(data => {
        setActive(data)
        setMessages(data.messages ?? [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }

  return (
    <div className="flex flex-col h-full">
      <div className="border-b bg-card px-4 flex items-center h-10 shrink-0">
        {TABS.map(t => {
          const Icon = t.icon; const act = t.value === tab
          return (
            <button key={t.value} onClick={() => setTab(t.value)}
              className={`flex items-center gap-1.5 px-3 h-full text-xs border-b-2 transition-colors
                ${act ? "border-blue-500 text-blue-600 font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
              <Icon className="w-3.5 h-3.5" />{t.label}
            </button>
          )
        })}
        <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400" />数据源：MongoDB
        </span>
      </div>

      {tab === "stats" && (
        <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
          统计图表开发中 — 将展示会话量趋势、平均时长、转人工率等
        </div>
      )}

      {tab === "list" && (
        <div className="flex flex-1 overflow-hidden">
          <div className="border-r flex flex-col shrink-0" style={{width:272}}>
            <div className="p-3 border-b bg-card space-y-2">
              <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <Input placeholder="搜索手机号..." className="pl-7 h-8 text-xs" value={search} onChange={e => { setSearch(e.target.value); setPage(1) }} />
              </div>
              <Input placeholder="流水号 SN..." className="h-7 text-xs" value={searchSn} onChange={e => { setSearchSn(e.target.value); setPage(1) }} />
              <Input placeholder="聊天内容关键字..." className="h-7 text-xs" value={keyword} onChange={e => { setKeyword(e.target.value); setPage(1) }} />
              <Select value={fStatus} onValueChange={v => { setFStatus(v); setPage(1) }}>
                <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部状态</SelectItem>
                  <SelectItem value="active">进行中</SelectItem>
                  <SelectItem value="ended">已结束</SelectItem>
                  <SelectItem value="transferred">已转人工</SelectItem>
                </SelectContent>
              </Select>
              <div className="grid grid-cols-2 gap-2">
                <Input type="date" className="h-7 text-xs" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
                <Input type="date" className="h-7 text-xs" value={dateTo}   onChange={e => setDateTo(e.target.value)} />
              </div>
 
			  <p className="text-xs text-muted-foreground flex items-center justify-between">
  <span>共 {total} 条</span>
  <div className="flex items-center gap-1">
    {total > PAGE_SIZE && (
      <>
<button onClick={() => setPage(p=>p-1)} disabled={page===1}
  className="px-2 py-1 text-sm border rounded disabled:opacity-40 hover:bg-muted bg-card">上页</button>
<span className="text-xs px-1">{page}/{Math.ceil(total/PAGE_SIZE)}</span>
<button onClick={() => setPage(p=>p+1)} disabled={page*PAGE_SIZE>=total}
  className="px-2 py-1 text-sm border rounded disabled:opacity-40 hover:bg-muted bg-card">下页</button>
      </>
    )}
    <button onClick={() => setRefresh(r => r+1)} className="ml-1 text-blue-500 hover:text-blue-700">↻</button>
  </div>
</p>
            </div>

            <div className="flex-1 overflow-y-auto">
              {sessions.map(s => {
                const st = STATUS[s.status] ?? STATUS.ended
                return (
                  <button key={s._id} onClick={() => openSession(s._id)}
                    className={`w-full text-left px-3 py-2.5 border-b hover:bg-muted transition-colors ${activeId === s._id ? "bg-blue-50" : ""}`}>
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-1.5">
                        <Phone className="w-3 h-3 text-muted-foreground" />
                        <span className="text-xs font-medium">{s.caller}</span>
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
            {/* 分页 */}
            {total > PAGE_SIZE && (
              <div className="border-t px-3 py-2 flex items-center justify-between bg-card shrink-0">
                <span className="text-[11px] text-muted-foreground">{(page-1)*PAGE_SIZE+1}–{Math.min(page*PAGE_SIZE,total)} / {total}</span>
                <div className="flex gap-1">
                  <button onClick={() => setPage(p=>p-1)} disabled={page===1}
                    className="px-2 py-0.5 text-xs border rounded disabled:opacity-40 hover:bg-muted">‹</button>
                  <span className="px-2 py-0.5 text-xs">{page}/{Math.ceil(total/PAGE_SIZE)}</span>
                  <button onClick={() => setPage(p=>p+1)} disabled={page*PAGE_SIZE>=total}
                    className="px-2 py-0.5 text-xs border rounded disabled:opacity-40 hover:bg-muted">›</button>
                </div>
              </div>
            )}
          </div>

          <div className="flex-1 flex flex-col overflow-hidden bg-background">
            {!activeId ? (
              <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-2">
                <MessageCircle className="w-8 h-8 opacity-20" />
                <span className="text-sm">选择一条会话查看对话记录</span>
              </div>
            ) : (
              <>
                <div className="border-b bg-card px-4 py-2.5 flex items-center gap-3 shrink-0">
                  <Phone className="w-4 h-4 text-muted-foreground" />
                  <span className="text-sm font-medium">{active?.caller}</span>
                  <Badge variant="outline" className={`text-xs ${STATUS[active?.status]?.cls}`}>{STATUS[active?.status]?.label}</Badge>
                  <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1"><Calendar className="w-3 h-3" />{active?.start_at && fmt(active.start_at)}</span>
                    <span>{active?.turn_count} 轮</span>
                    <span>{dur(active?.duration_s ?? 0)}</span>
                    <code className="text-[10px] bg-muted px-1.5 py-0.5 rounded font-mono">{active?._id}</code>
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                  {loading && <p className="text-xs text-muted-foreground text-center py-8">加载中...</p>}
                  {!loading && messages.map((m, i) => {
                    const isBot = m.role === "bot"
                    return (
                      <div key={i} className={`flex gap-2.5 ${isBot ? "" : "flex-row-reverse"}`}>
                        <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${isBot ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-600"}`}>
                          {isBot ? <Bot className="w-3.5 h-3.5" /> : <User className="w-3.5 h-3.5" />}
                        </div>
                        <div className="max-w-[72%]">
                          <div className={`rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed
                            ${isBot ? "bg-card border rounded-tl-sm" : "bg-blue-500 text-white rounded-tr-sm"}`}>
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
                    只读模式 — 历史记录存储于 MongoDB <code className="bg-muted px-1 rounded font-mono">call_histories</code> 集合
                  </p>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}