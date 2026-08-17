import { useState, useEffect, useRef } from "react"
import {
  getStats, listKnowledge, listCategories,
  createKnowledge, updateKnowledge,
  deleteMany, vectorize, searchKnowledge, bulkImport,
} from "@/api/knowledge"
import { Button }   from "@/components/ui/button"
import { Input }    from "@/components/ui/input"
import { Badge }    from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Checkbox } from "@/components/ui/checkbox"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Database, Search, BarChart2, Plus, Upload, Download, Zap, Trash2, RefreshCw, RotateCcw, Edit, FileText, Filter, X } from "lucide-react"
import StatusBadge from "@/components/StatusBadge"
import ItemDialog  from "@/components/ItemDialog"

const PAGE_SIZE = 20

function SearchPanel({ categories }) {
  const [query,   setQuery]   = useState("")
  const [cat,     setCat]     = useState("all")
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)

  async function run() {
    if (!query.trim()) return
    setLoading(true)
    setResults(await searchKnowledge({ q: query, category: cat === "all" ? undefined : cat }))
    setLoading(false)
  }

  return (
    <div className="p-5 space-y-4">
      <div className="p-4 border rounded-lg bg-card space-y-3">
        <p className="text-sm text-muted-foreground">输入查询语句，测试 pgvector cosine distance 检索效果</p>
        <div className="flex gap-2">
          <Input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === "Enter" && run()}
            placeholder="例如：老师忘记密码怎么办..." className="flex-1" />
          <Select value={cat} onValueChange={setCat}>
            <SelectTrigger className="w-32"><SelectValue placeholder="全部分类" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部分类</SelectItem>
              {categories.map(c => <SelectItem key={c.category} value={c.category}>{c.category}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button onClick={run} disabled={loading}><Search className="w-4 h-4 mr-2" />{loading ? "检索中..." : "检索"}</Button>
        </div>
      </div>
      {results.map((r, i) => (
        <div key={i} className={`p-4 border rounded-lg ${i === 0 ? "border-blue-400" : "border-border"}`}>
          <div className="flex items-center gap-2 mb-2">
            <span className={`w-5 h-5 rounded text-xs font-bold flex items-center justify-center ${i === 0 ? "bg-blue-500 text-white" : "bg-muted text-muted-foreground"}`}>{i + 1}</span>
            <Badge variant="outline">{r.category}</Badge>
            <span className="font-medium text-sm">{r.summary}</span>
            <span className="ml-auto text-xs">distance: <span className={`font-bold ${r.distance < 0.35 ? "text-green-600" : r.distance < 0.55 ? "text-amber-600" : "text-red-600"}`}>{r.distance}</span></span>
          </div>
          <p className="text-sm text-muted-foreground">{r.content}</p>
        </div>
      ))}
    </div>
  )
}

const TABS = [
  { value: "knowledge", icon: Database,  label: "知识库" },
  { value: "search",    icon: Search,    label: "检索测试" },
  { value: "stats",     icon: BarChart2, label: "统计" },
]

export default function KnowledgePage() {
  const [tab,      setTab]      = useState("knowledge")
  const [mode,     setMode]     = useState("structured")
  const [stats,    setStats]    = useState({})
  const [items,    setItems]    = useState([])
  const [cats,     setCats]     = useState([])
  const [total,    setTotal]    = useState(0)
  const [page,     setPage]     = useState(1)
  const [search,   setSearch]   = useState("")
  const [fCat,     setFCat]     = useState("all")
  const [fStatus,  setFStatus]  = useState("")
  const [selected, setSelected] = useState([])
  const [editItem, setEditItem] = useState(null)
  const [viewItem, setViewItem] = useState(null)
  const [showAdd,  setShowAdd]  = useState(false)
  const [loading,  setLoading]  = useState(false)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [confirmAction, setConfirmAction] = useState(null)  // { message, onConfirm }
  const [toast, setToast] = useState(null)
  const fileRef = useRef()

  useEffect(() => { loadStats(); loadCats() }, [])
  useEffect(() => { loadItems() }, [page, search, fCat, fStatus])

  async function loadStats()  { setStats(await getStats()) }
  async function loadCats()   { setCats(await listCategories()) }
  async function loadItems() {
    setLoading(true)
    const d = await listKnowledge({
      category: fCat === "all" ? undefined : fCat,
      status: fStatus || undefined,
      search: search || undefined,
      page, pageSize: PAGE_SIZE,
    })
    setItems(d.items||[]); setTotal(d.total||0); setSelected([]); setLoading(false)
  }

  function toggleFStatus(s)  { setFStatus(p => p === s ? "" : s); setPage(1) }
  function toggleSel(id)     { setSelected(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id]) }
  function toggleAll()       { setSelected(s => s.length === items.length ? [] : items.map(i => i.id)) }

  async function handleSave(form) {
    form.id ? await updateKnowledge(form.id, form) : await createKnowledge(form)
    setEditItem(null); setShowAdd(false)
    loadItems(); loadStats(); loadCats()
  }
  async function handleDelete(ids)    { await deleteMany(ids);  setSelected([]); loadItems(); loadStats() }
  async function handleVectorize(ids) { await vectorize(ids);   setSelected([]); loadItems(); loadStats() }
  async function runVectorizeByStatus(statusFilter, label) {
      // 跨分页取全量列表，只处理匹配该状态的记录
      const d = await listKnowledge({ status: statusFilter, pageSize: 9999 })
      const ids = (d.items || []).map(i => i.id)
      if (ids.length === 0) { setToast(`没有${label}的记录`); return }
      setLoading(true)
      const result = await vectorize(ids)
      setLoading(false)
      setToast(`完成：成功 ${result.success} 条，失败 ${result.failed} 条`)
      loadItems(); loadStats()
    }
  async function runReinitAll() {
      setLoading(true)
      // 拿全量 id，不受分页/状态筛选影响（做法跟 handleExport 一致）
      const d = await listKnowledge({ pageSize: 9999 })
      const allIds = (d.items || []).map(i => i.id)
      const result = await vectorize(allIds)
      setLoading(false)
      setToast(`初始化完成：成功 ${result.success} 条，失败 ${result.failed} 条`)
      loadItems(); loadStats()
    }

  async function handleImport(e) {
    const f = e.target.files[0]; if (!f) return
    setImporting(true); setImportResult(null)
    const formData = new FormData()
    formData.append("file", f)
    const res  = await fetch("/api/knowledge/import/txt", { method: "POST", body: formData })
    const data = await res.json()
    setImportResult(data)
    setImporting(false)
    loadItems(); loadStats(); loadCats()
    fileRef.current.value = ""
  }
  async function handleExport() {
    const d = await listKnowledge({ pageSize: 9999 })
    const a = Object.assign(document.createElement("a"), {
      href: URL.createObjectURL(new Blob([JSON.stringify(d.items, null, 2)], { type: "application/json" })),
      download: "knowledge_export.json",
    })
    a.click()
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="flex flex-col h-full">
      <div className="border-b bg-card px-4 flex items-center h-10 shrink-0">
        {TABS.map(t => {
          const Icon = t.icon; const active = t.value === tab
          return (
            <button key={t.value} onClick={() => setTab(t.value)}
              className={`flex items-center gap-1.5 px-3 h-full text-xs border-b-2 transition-colors
                ${active ? "border-blue-500 text-blue-600 font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
              <Icon className="w-3.5 h-3.5" />{t.label}
            </button>
          )
        })}
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "search" && <SearchPanel categories={cats} />}
        {tab === "stats"  && <p className="p-8 text-center text-sm text-muted-foreground">统计图表开发中...</p>}

        {tab === "knowledge" && (
          <div className="p-5 space-y-4">
            {/* Toolbar */}
            <div className="flex items-center justify-between">
              <div className="flex border rounded-lg p-1 gap-1 bg-card">
                {[{v:"structured",i:Filter,l:"结构化条目"},{v:"chunk",i:FileText,l:"文档 Chunk"}].map(m => (
                  <button key={m.v} onClick={() => setMode(m.v)}
                    className={`px-3 py-1.5 rounded text-xs font-medium flex items-center gap-1.5 transition-all
                      ${mode === m.v ? "bg-blue-500 text-white" : "text-muted-foreground hover:bg-muted"}`}>
                    <m.i className="w-3.5 h-3.5" />{m.l}
                  </button>
                ))}
              </div>
              {mode === "structured" && (
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={handleExport}><Download className="w-4 h-4 mr-1" />导出</Button>
                  <Button variant="outline" size="sm" onClick={() => fileRef.current.click()} disabled={importing}><Upload className="w-4 h-4 mr-1" />{importing ? "导入中..." : "批量导入"}</Button>
                  <input ref={fileRef} type="file" accept=".txt" className="hidden" onChange={handleImport} />
                  <Button size="sm" onClick={() => setShowAdd(true)}><Plus className="w-4 h-4 mr-1" />新增条目</Button>
                </div>
              )}
              {mode === "chunk" && (
                <div className="flex gap-2">
                  <Select defaultValue="500">
                    <SelectTrigger className="w-40 h-8 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="500">chunk 策略：500字</SelectItem>
                      <SelectItem value="200">chunk 策略：200字</SelectItem>
                      <SelectItem value="para">chunk 策略：按段落</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button size="sm"><Upload className="w-4 h-4 mr-1" />上传文档</Button>
                </div>
              )}
            </div>

            {importResult && (
              <Alert className="py-2">
                <AlertDescription className="flex items-center justify-between">
                  <span>✅ 导入完成：成功 <strong>{importResult.inserted}</strong> / 共 <strong>{importResult.total}</strong> 条</span>
                  <Button variant="ghost" size="sm" className="h-6 px-2" onClick={() => setImportResult(null)}>×</Button>
                </AlertDescription>
              </Alert>
            )}

            {/* Stat cards */}
            <div className="grid grid-cols-5 gap-2">
              {[
                { label:"总条目",    val:stats.total,   color:"text-foreground", st:"",        sub:"结构化 + Chunk" },
                { label:"已向量化",  val:stats.indexed, color:"text-green-600",  st:"indexed", prog:stats.total ? Math.round((stats.indexed/stats.total)*100) : 0 },
                { label:"待向量化",  val:stats.pending, color:"text-amber-600",  st:"pending", sub:"点击筛选" },
                { label:"向量化失败",val:stats.failed,  color:"text-red-600",    st:"failed",  sub:"点击筛选" },
                { label:"文档数",    val:"8",           color:"text-blue-600",   st:null,      sub:"234 个 chunk" },
              ].map(c => (
                <button key={c.label} onClick={() => c.st !== null ? toggleFStatus(c.st) : setMode("chunk")}
                  className={`text-left p-3 rounded-lg border transition-all w-full
                    ${fStatus === c.st && c.st !== null ? "border-blue-400 bg-blue-50" : "border-border bg-muted hover:border-muted-foreground/40"}`}>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">{c.label}</p>
                  <p className={`text-2xl font-medium ${c.color}`}>{c.val ?? "—"}</p>
                  {c.prog != null && <Progress value={c.prog} className="h-1 mt-2" />}
                  {c.sub && <p className="text-xs text-muted-foreground mt-1">{c.sub}</p>}
                </button>
              ))}
            </div>

            {fStatus && (
              <Alert className="py-2">
                <Filter className="w-4 h-4" />
                <AlertDescription className="flex items-center justify-between">
                  <span>筛选中：<strong>{{indexed:"已向量化",pending:"待向量化",failed:"失败"}[fStatus]}</strong>（共 {total} 条）</span>
                  <Button variant="ghost" size="sm" onClick={() => { setFStatus(""); setPage(1) }}><X className="w-3 h-3 mr-1" />清除</Button>
                </AlertDescription>
              </Alert>
            )}

            <div className="grid grid-cols-[180px_1fr] gap-3">
              <div className="space-y-3">
                <div className="border rounded-lg p-3 bg-card space-y-2">
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">搜索</p>
                  <div className="relative">
                    <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                    <Input placeholder="关键词..." className="pl-7 h-8 text-xs" value={search}
                      onChange={e => { setSearch(e.target.value); setPage(1) }} />
                  </div>
                </div>

                {mode === "structured" && (
                  <div className="border rounded-lg p-3 bg-card space-y-3">
                    <div className="space-y-1.5">
                      <p className="text-xs text-muted-foreground uppercase tracking-wide">分类</p>
                      <Select value={fCat} onValueChange={v => { setFCat(v); setPage(1) }}>
                        <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="全部分类" /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">全部分类</SelectItem>
                          {cats.map(c => <SelectItem key={c.category} value={c.category}>{c.category} ({c.count})</SelectItem>)}
                        </SelectContent>
                      </Select>
                      <p className="text-xs text-muted-foreground">共 {cats.length} 个分类</p>
                    </div>
                    <div className="space-y-1.5">
                      <p className="text-xs text-muted-foreground uppercase tracking-wide">批量操作</p>
                      <Button variant="outline" size="sm" className="w-full text-xs text-green-600 border-green-400"
                        onClick={() => setConfirmAction({
                          message: "即将重新计算所有【未向量化】记录的向量，确定继续吗？",
                          onConfirm: () => runVectorizeByStatus("pending", "未向量化"),
                        })}><Zap className="w-3 h-3 mr-1" />更新向量</Button>
                      <Button variant="outline" size="sm" className="w-full text-xs text-amber-600 border-amber-400"
                        onClick={() => setConfirmAction({
                          message: "即将重试所有【向量化失败】的记录，确定继续吗？",
                          onConfirm: () => runVectorizeByStatus("failed", "向量化失败"),
                        })}><RefreshCw className="w-3 h-3 mr-1" />重试失败项</Button>

                      <Button variant="outline" size="sm" className="w-full text-xs text-orange-600 border-orange-400"
                        onClick={() => setConfirmAction({
                          message: `此操作会用当前配置的 Embedding 模型，重新计算全部 ${total} 条记录的向量（包括已向量化的），确定继续吗？`,
                          onConfirm: runReinitAll,
                        })}><RotateCcw className="w-3 h-3 mr-1" />初始化向量（全重建）</Button>
						
                      {selected.length > 0 && (
                        <Button variant="outline" size="sm" className="w-full text-xs text-red-600 border-red-400"
                          onClick={() => handleDelete(selected)}><Trash2 className="w-3 h-3 mr-1" />删除所选({selected.length})</Button>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {mode === "structured" && (
                <div className="border rounded-lg bg-card overflow-hidden">
                  <div className="px-4 py-2 border-b flex items-center gap-2">
                    <Checkbox checked={selected.length === items.length && items.length > 0} onCheckedChange={toggleAll} />
                    <span className="text-sm font-medium">结构化条目</span>
                    <Badge variant="secondary">{total} 条</Badge>
                    {selected.length > 0 && (
                      <Button variant="outline" size="sm" className="ml-auto text-green-600 border-green-400"
                        onClick={() => handleVectorize(selected)}><Zap className="w-3 h-3 mr-1" />向量化({selected.length})</Button>
                    )}
                  </div>
				  
				  
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-8" />
                        <TableHead className="w-14 font-mono text-[10px]">ID</TableHead>
                        <TableHead className="w-20">分类</TableHead>
                        <TableHead className="w-32">摘要</TableHead>
                        <TableHead>内容预览</TableHead>
                        <TableHead className="w-28">状态</TableHead>
                        <TableHead className="w-24">操作</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {loading && <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">加载中...</TableCell></TableRow>}
                      {!loading && items.length === 0 && <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">没有匹配的条目</TableCell></TableRow>}
                      {!loading && items.map(item => (
                        <TableRow key={item.id}
                          className={`cursor-pointer ${selected.includes(item.id) ? "bg-blue-50/50" : "hover:bg-muted/50"}`}
                          onClick={() => setViewItem(item)}>
                          <TableCell onClick={e => e.stopPropagation()}><Checkbox checked={selected.includes(item.id)} onCheckedChange={() => toggleSel(item.id)} /></TableCell>
                           <TableCell className="font-mono text-[10px] text-muted-foreground" title={item.id}>{item.id.slice(0, 6)}{item.id.length > 6 ? "..." : ""}</TableCell>
                          <TableCell><Badge variant="outline" className="text-xs">{item.category}</Badge></TableCell>
                          <TableCell className="font-medium text-sm">{item.summary}</TableCell>
                          <TableCell className="text-xs text-muted-foreground max-w-xs truncate">{item.content}</TableCell>
                          <TableCell><StatusBadge status={item.status} /></TableCell>
                          <TableCell onClick={e => e.stopPropagation()}>
                            <div className="flex gap-1">
                              {item.status !== "indexed" && (
                                <Button variant="ghost" size="icon" className="h-7 w-7 text-green-600" onClick={() => handleVectorize([item.id])}><Zap className="w-3.5 h-3.5" /></Button>
                              )}
                              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setEditItem(item)}><Edit className="w-3.5 h-3.5" /></Button>
                              <Button variant="ghost" size="icon" className="h-7 w-7 text-red-500" onClick={() => handleDelete([item.id])}><Trash2 className="w-3.5 h-3.5" /></Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  <div className="px-4 py-2 border-t flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">{(page-1)*PAGE_SIZE+1}–{Math.min(page*PAGE_SIZE,total)} / {total} 条</span>
                    <div className="flex gap-1">
                      <Button variant="outline" size="sm" className="h-7 w-7 p-0" disabled={page===1} onClick={() => setPage(p=>p-1)}>‹</Button>
                      {Array.from({length:Math.min(totalPages,5)},(_,i)=>i+1).map(p => (
                        <Button key={p} variant={p===page?"default":"outline"} size="sm" className="h-7 w-7 p-0" onClick={() => setPage(p)}>{p}</Button>
                      ))}
                      <Button variant="outline" size="sm" className="h-7 w-7 p-0" disabled={page===totalPages} onClick={() => setPage(p=>p+1)}>›</Button>
                    </div>
                  </div>
                </div>
              )}
              {mode === "chunk" && (
                <div className="border rounded-lg bg-card p-4 text-sm text-muted-foreground text-center py-12">
                  文档 Chunk 管理功能开发中...
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {(editItem || showAdd) && (
        <ItemDialog item={editItem} categories={cats} onSave={handleSave}
          onClose={() => { setEditItem(null); setShowAdd(false) }} />
      )}

      {confirmAction && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center"
          onClick={() => setConfirmAction(null)}>
          <div className="bg-card rounded-xl shadow-xl w-96 p-5 space-y-4" onClick={e => e.stopPropagation()}>
            <p className="text-sm leading-relaxed">{confirmAction.message}</p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setConfirmAction(null)}>取消</Button>
              <Button size="sm" onClick={() => { confirmAction.onConfirm(); setConfirmAction(null) }}>确定</Button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 bg-card border rounded-lg shadow-lg px-4 py-3 text-sm max-w-sm">
          <div className="flex items-start justify-between gap-3">
            <span>{toast}</span>
            <button onClick={() => setToast(null)} className="text-muted-foreground hover:text-foreground shrink-0">×</button>
          </div>
        </div>
      )}

      {viewItem && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center"
          onClick={() => setViewItem(null)}>
          <div className="bg-card rounded-xl shadow-xl w-[620px] max-h-[80vh] overflow-y-auto p-6 space-y-4"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Badge variant="outline">{viewItem.category}</Badge>
                <StatusBadge status={viewItem.status} />
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={() => { setEditItem(viewItem); setViewItem(null) }}>
                  <Edit className="w-3.5 h-3.5 mr-1" />编辑
                </Button>
                <button onClick={() => setViewItem(null)} className="text-muted-foreground hover:text-foreground">
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1">摘要</p>
              <p className="text-sm font-medium">{viewItem.summary}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1">内容</p>
              <p className="text-sm leading-relaxed whitespace-pre-wrap bg-muted/40 rounded-lg p-3">{viewItem.content}</p>
            </div>
            <div className="text-xs text-muted-foreground border-t pt-3">
              ID: {viewItem.id} · 更新时间: {viewItem.updated_at}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}