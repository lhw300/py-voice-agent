import { useState, useEffect } from "react"
import { Input }  from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge }  from "@/components/ui/badge"
import { Trash2, Plus, RefreshCw, RotateCcw, Search } from "lucide-react"

const TABS = [
  { value: "k1", label: "K1 精确缓存" },
  { value: "k2", label: "K2 语义缓存" },
]
const PAGE_SIZE = 20

function CacheWarmupButton({ onSuccess }) {
  const [step, setStep] = useState("idle") // idle | confirming | loading
  const [error, setError] = useState(null)

  async function handleConfirm() {
    setStep("loading")
    try {
      const res  = await fetch("/api/cache/warmup", { method: "POST" })
      const data = await res.json()
      if (data.ok) {
        onSuccess?.(data)
      } else {
        setError("初始化失败，请查看后端日志")
      }
    } catch (e) {
      setError("请求失败：" + e.message)
    } finally {
      setStep("idle")
    }
  }

  return (
    <div className="relative">
      <button onClick={() => { setError(null); setStep("confirming") }}
        disabled={step === "loading"}
        className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50">
        <RotateCcw className={`w-3.5 h-3.5 ${step === "loading" ? "animate-spin" : ""}`} />
        缓存初始化
      </button>

      {step === "confirming" && (
        <div className="absolute top-full right-0 mt-2 w-64 p-3 rounded-md border bg-card shadow-lg z-10">
          <p className="text-xs text-muted-foreground leading-relaxed mb-3">
            此操作会<span className="font-medium text-red-600">清空全部缓存</span>，
            并从 FAQ 文件重新生成 K1 + K2，手动添加的条目也会被清除，确定继续吗？
          </p>
          <div className="flex justify-end gap-2">
            <button onClick={() => setStep("idle")}
              className="px-2 py-0.5 text-xs border rounded hover:bg-muted">取消</button>
            <button onClick={handleConfirm}
              className="px-2 py-0.5 text-xs rounded bg-red-500 text-white hover:bg-red-600">确认</button>
          </div>
        </div>
      )}

      {error && (
        <div className="absolute top-full right-0 mt-2 w-64 p-2 text-xs rounded border bg-red-50 border-red-200 text-red-600 z-10">
          {error}
        </div>
      )}
    </div>
  )
}

export default function CachePage() {
  const [tab,       setTab]       = useState("k1")
  const [items,     setItems]     = useState([])
  const [total,     setTotal]     = useState(0)
  const [page,      setPage]      = useState(1)
  const [loading,   setLoading]   = useState(false)
  const [search,    setSearch]    = useState("")
  const [newQ,      setNewQ]      = useState("")
  const [newA,      setNewA]      = useState("")
  const [permanent, setPermanent] = useState(true)
  const [adding,    setAdding]    = useState(false)
  const [addResult, setAddResult] = useState(null)

  function load(t = tab, p = page) {
    setLoading(true)
    fetch(`/api/cache/list?cache_type=${t}&page=${p}&page_size=${PAGE_SIZE}`)
      .then(r => r.json())
      .then(d => { setItems(d.items ?? []); setTotal(d.total ?? 0); setLoading(false) })
      .catch(() => setLoading(false))
  }

  useEffect(() => { load(tab, 1); setPage(1) }, [tab])
  useEffect(() => { load(tab, page) }, [page])

  async function handleAdd() {
    if (!newQ.trim() || !newA.trim()) return
    setAdding(true); setAddResult(null)
    const res  = await fetch("/api/cache/add", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ question: newQ, answer: newA, permanent })
    })
    const data = await res.json()
    setAddResult(data)
    setAdding(false)
    setNewQ(""); setNewA("")
    load(tab, 1); setPage(1)
  }

  async function handleDelete(type, id) {
    if (!confirm("确认删除？")) return
    await fetch(`/api/cache/${type}/${id}`, { method: "DELETE" })
    load(tab, page)
  }

  const filtered = search
    ? items.filter(i => i.question.includes(search) || i.answer.includes(search))
    : items

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="flex flex-col h-full">
      {/* Header tabs */}
      <div className="border-b bg-card px-4 flex items-center h-10 shrink-0 gap-2">
        {TABS.map(t => (
          <button key={t.value} onClick={() => setTab(t.value)}
            className={`px-3 h-full text-xs border-b-2 transition-colors
              ${tab === t.value
                ? "border-blue-500 text-blue-600 font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground"}`}>
            {t.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-3">
          <CacheWarmupButton onSuccess={(data) => {
            alert(`缓存初始化完成：K1 写入 ${data.k1_count} 条，K2 写入 ${data.k2_count} 条`)
            load(tab, 1); setPage(1)
          }} />
          <button onClick={() => load(tab, page)} className="text-muted-foreground hover:text-foreground">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* 左侧列表 */}
        <div className="flex flex-col border-r shrink-0" style={{ width: 680 }}>
          {/* 搜索 */}
          <div className="p-3 border-b bg-card space-y-1.5">
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input placeholder="搜索问题或答案..." className="pl-7 h-8 text-xs"
                value={search} onChange={e => setSearch(e.target.value)} />
            </div>
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">共 {total} 条</p>
              {totalPages > 1 && (
                <div className="flex items-center gap-1">
                  <button onClick={() => setPage(p => p-1)} disabled={page===1}
                    className="px-2 py-0.5 text-xs border rounded disabled:opacity-40 hover:bg-muted">上页</button>
                  <span className="text-xs px-1">{page}/{totalPages}</span>
                  <button onClick={() => setPage(p => p+1)} disabled={page>=totalPages}
                    className="px-2 py-0.5 text-xs border rounded disabled:opacity-40 hover:bg-muted">下页</button>
                </div>
              )}
            </div>
          </div>

          {/* 列表 */}
          <div className="flex-1 overflow-y-auto">
            {filtered.map(item => (
              <div key={item.id} className="px-3 py-2.5 border-b hover:bg-muted group">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      {item.permanent
                        ? <Badge variant="outline" className="text-[10px] px-1 py-0 border-blue-300 text-blue-600">永久</Badge>
                        : <Badge variant="outline" className="text-[10px] px-1 py-0 text-muted-foreground">TTL {item.ttl}s</Badge>
                      }
                      {item.hit_source && (
                        <Badge variant="outline" className="text-[10px] px-1 py-0">{item.hit_source}</Badge>
                      )}
                    </div>
                    <p className="text-xs font-medium truncate">Q: {item.question || "(无问题文本)"}</p>
                    <p className="text-[11px] text-muted-foreground line-clamp-2 mt-0.5">A: {item.answer}</p>
                    <p className="text-[10px] text-muted-foreground font-mono mt-0.5 truncate">ID: {item.id}</p>
                  </div>
                  <button onClick={() => handleDelete(tab, item.id)}
                    className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-600 shrink-0 mt-1">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
            {filtered.length === 0 && !loading && (
              <div className="flex items-center justify-center h-32 text-sm text-muted-foreground">
                暂无缓存数据
              </div>
            )}
          </div>
        </div>

        {/* 右侧添加面板 */}
        <div className="flex-1 p-5 overflow-y-auto">
          <h3 className="text-sm font-medium mb-4">手动添加缓存条目</h3>

          <div className="space-y-3 max-w-lg">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">问题（Q）</label>
              <Input placeholder="输入问题..." className="text-sm"
                value={newQ} onChange={e => setNewQ(e.target.value)} />
            </div>

            <div>
              <label className="text-xs text-muted-foreground mb-1 block">答案（A）</label>
              <textarea
                className="w-full border rounded-md px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-blue-500"
                rows={4} placeholder="输入答案..."
                value={newA} onChange={e => setNewA(e.target.value)} />
            </div>

            <div className="flex items-center gap-2">
              <input type="checkbox" id="permanent" checked={permanent}
                onChange={e => setPermanent(e.target.checked)} />
              <label htmlFor="permanent" className="text-xs text-muted-foreground">
                永久缓存（不过期）
              </label>
            </div>

            <Button onClick={handleAdd} disabled={adding || !newQ.trim() || !newA.trim()}
              className="w-full">
              <Plus className="w-4 h-4 mr-1" />
              {adding ? "写入中..." : "添加到 K1 + K2"}
            </Button>

            {addResult && (
              <div className={`text-xs p-3 rounded border ${addResult.ok
                ? "bg-green-50 border-green-200 text-green-700"
                : "bg-red-50 border-red-200 text-red-700"}`}>
                {addResult.ok ? (
                  <>
                    ✅ 写入成功<br />
                    归一化：{addResult.norm}<br />
                    K1: {addResult.k1_written ? "✅" : "❌"} &nbsp;
                    K2: {addResult.k2_written ? "✅" : "❌"} &nbsp;
                    {addResult.permanent ? "永久" : "有期限"}
                  </>
                ) : "❌ 写入失败"}
              </div>
            )}

            <div className="border-t pt-4 mt-2">
              <p className="text-xs text-muted-foreground leading-relaxed">
                <strong>说明：</strong>添加后同时写入 K1（精确匹配）和 K2（语义匹配）。
                K2 写入需要调用 Embedding 模型生成向量，约需 200-500ms。
                永久缓存不受 TTL 限制，不会自动过期。
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}