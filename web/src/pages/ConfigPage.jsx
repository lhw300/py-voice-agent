import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Badge }  from "@/components/ui/badge"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Settings, Filter, Database, Zap, FileText, BookOpen } from "lucide-react"
import ConfigField from "@/components/ConfigField"

const API = "/api/config"

const SECTIONS = [
  { key: "system", label: "系统模式", icon: Settings, fields: [
    { key: "system.run.type",       label: "运行模式",  type: "select", options: ["qwen","hybrid-openai","hybrid-qwen","hybrid2","openai","simple","localOpenai","localOllama"], desc: "决定使用哪种大模型链路" },
    { key: "skill_tools.mode",      label: "技能路由模式", type: "select", options: ["layer","classify"], desc: "layer=分层强制路由，更稳定 / classify=合并分类，省调用但准确率略低" },
    { key: "system.warmup.enabled", label: "启动预热",  type: "bool",   desc: "启动时预热所有模型连接" },
	 { key: "api.base.local_openai",  label: "vLLM 地址",  type: "text", desc: "本地 vLLM OpenAI 兼容接口地址，system.run.type=localOpenai 时使用" },
    { key: "vllm.model.chat",       label: "vLLM 模型(rewrite)", type: "text", desc: "local 模式下用于意图分类/改写的模型" },
    { key: "vllm.model.final",      label: "vLLM 模型(final)",   type: "text", desc: "local 模式下用于生成最终回答的模型，留空则与 rewrite 相同" },
	 { key: "api.base.ollama",       label: "Ollama 地址", type: "text", desc: "本地 Ollama OpenAI 兼容接口地址，如 http://localhost:11434/v1" },
    { key: "ollama.model.chat",     label: "Ollama 模型(rewrite)", type: "text", desc: "本地模式下用于意图分类/改写的模型" },
    { key: "ollama.model.final",    label: "Ollama 模型(final)",   type: "text", desc: "本地模式下用于生成最终回答的模型，留空则与 rewrite 相同" },
  ]},
  { key: "rag", label: "RAG 检索", icon: Filter, fields: [
    { key: "rag.query.mode",                   label: "检索模式",     type: "select", options: ["retrieveRerank","retrieveOnly","fullText","simple"], desc: "粗排+精排 / 仅粗排 / 全量 / 简单" },
    { key: "rag.threshold.trust",              label: "信任快道",     type: "slider", desc: "粗排 < 此值直接返回，跳过精排" },
    { key: "rag.threshold.rerank_trigger_max", label: "精排入池上限", type: "slider", desc: "粗排后结果超过此值不送精排" },
    { key: "rag.threshold.comp_embed",         label: "粗排资格线",   type: "slider", desc: "精排抢救时，当初的粗排值必须低于此值" },
    { key: "rag.threshold.comp_rerank",        label: "精排触发线",   type: "slider", desc: "精排抢救时， 精排值必须大于此值，极差时触发强制拉回" },
    { key: "rag.threshold.rescue_score",       label: "抢救分数",     type: "slider", desc: "精排抢救时，补偿机制触发后赋予的及格距离，得到后最终一起排序后送LLM" },
    { key: "rag.threshold.similarity",         label: "拒答阈值",     type: "slider", desc: "精排距离 > 此值则拦截" },
    { key: "rag.limit.max_rerank",             label: "精排候选数",   type: "number", min:1,  max:20, step:1 },
    { key: "rag.limit.final_limit",            label: "云端上下文数", type: "number", min:1,  max:10, step:1 },
    { key: "rag.timeout.rerank",               label: "精排超时(秒)", type: "number", min:1,  max:30, step:1 },
  ]},
  { key: "db", label: "数据库", icon: Database, fields: [
    { key: "storage.type",             label: "存储类型",   type: "select", options: ["postgres","postgress","lucene"] },

    // ── PostgreSQL 向量知识库 ──────────────────────────────
    { key: "db.postgres.url",          label: "【向量库】数据库 URL", type: "text", desc: "PostgreSQL + pgvector，RAG 知识检索" },
    { key: "db.postgres.user",         label: "用户名",     type: "text" },
    { key: "db.postgres.password",     label: "密码",       type: "password" },
    { key: "db.postgres.pool.max",     label: "最大连接数", type: "number", min:1, max:100, step:1 },
    { key: "db.postgres.pool.keepalive", label: "连接保活(ms)", type: "number", min:1000, max:300000, step:1000 },
    { key: "db.postgres.table.online", label: "知识库表名", type: "text" },

    // ── MySQL 业务库 ──────────────────────────────────────
    { key: "db.mysql.host",     label: "【业务库】MySQL Host",   type: "text", desc: "MySQL 业务数据库（用户、工单、配置等）" },
    { key: "db.mysql.port",     label: "端口",                   type: "number", min:1, max:65535, step:1 },
    { key: "db.mysql.user",     label: "用户名",                 type: "text" },
    { key: "db.mysql.password", label: "密码",                   type: "password" },
    { key: "db.mysql.dbname",   label: "数据库名",               type: "text" },

    // ── MongoDB 对话历史 ──────────────────────────────────
    { key: "db.mongo.host",     label: "【对话库】MongoDB Host", type: "text", desc: "MongoDB 对话历史存储" },
    { key: "db.mongo.port",     label: "端口",                   type: "number", min:1, max:65535, step:1 },
    { key: "db.mongo.user",     label: "用户名",                 type: "text" },
    { key: "db.mongo.password", label: "密码",                   type: "password" },
    { key: "db.mongo.dbname",   label: "数据库名",               type: "text" },
    { key: "db.chathistory.session.timeout.minutes", label: "会话超时(分钟)", type: "number", min:1, max:1440, step:1, desc: "对话 session 超时时间" },
  ]},
  { key: "cache", label: "缓存配置", icon: Zap, fields: [
    { key: "cache.update.k1k2",        label: "更新 K1/K2",      type: "bool" },
    { key: "cache.warmup.on_start",    label: "启动预热缓存",     type: "bool", desc: "知识库更新后改 true 跑一次再改回" },
    { key: "k1.lru.max",               label: "K1 LRU 上限",     type: "number", min:100, max:10000, step:100 },
    { key: "k2.similarity.threshold",  label: "K2 相似度阈值",   type: "slider" },
    { key: "k2.minanswer.length",      label: "K2 最小答案长度", type: "number", min:0, max:200, step:1 },
    { key: "cache.ttl.days",           label: "缓存 TTL（天）",  type: "number", min:1, max:30, step:1 },
    { key: "cache.fallback.keywords",  label: "降级关键词",       type: "text", desc: "用 | 分隔" },
    { key: "redis.faq.file",           label: "FAQ 文件路径",     type: "text" },
    { key: "redis.convert.file",       label: "转换文件路径",     type: "text" },
  ]},
  { key: "log", label: "日志", icon: FileText, fields: [
    { key: "log.messages.chars",      label: "消息打印字数",   type: "number", min:0, max:5000,  step:100, desc: "0=不打印" },
    { key: "log.fullctx.chars",       label: "完整上下文字数", type: "number", min:0, max:10000, step:100 },
    { key: "log.ai.response.chars",   label: "AI 响应字数",    type: "number", min:0, max:5000,  step:100 },
    { key: "log.intent.input.chars",  label: "意图分类输入字数",type: "number", min:0, max:5000,  step:100 },
    { key: "log.prompt.preview.chars",label: "Prompt 预览字数", type: "number", min:0, max:5000,  step:100 },
    { key: "log.candidates.max",      label: "候选列表条数",   type: "number", min:0, max:20,    step:1 },
  ]},
  { key: "response", label: "回复文本", icon: BookOpen, fields: [
    { key: "response.command.unknown",          label: "未知指令",      type: "textarea" },
    { key: "response.command.no_replay",        label: "无重播内容",    type: "text" },
    { key: "response.command.transfer",         label: "转人工",        type: "text" },
    { key: "response.command.vol_up",           label: "音量调大",      type: "text" },
    { key: "response.command.vol_down",         label: "音量调小",      type: "text" },
    { key: "response.command.hangup",           label: "挂断回复",      type: "text" },
    { key: "response.command.unsupported",      label: "不支持指令",    type: "text" },
    { key: "response.chitchat.error",           label: "闲聊服务异常",  type: "text" },
    { key: "response.inform.ack",               label: "确认回复",      type: "textarea", desc: "用 | 分隔，随机选一条" },
    { key: "greeting.farewell.pattern",         label: "告别触发词",    type: "text", desc: "正则，| 分隔" },
    { key: "response.greeting.farewell",        label: "告别语",        type: "text" },
    { key: "response.greeting.pool",            label: "问候语池",      type: "textarea", desc: "用 | 分隔，随机选一条" },
    { key: "response.ack.affirm",               label: "肯定确认",      type: "text" },
    { key: "response.ack.negate",               label: "否定确认",      type: "text" },
    { key: "response.ack.default",              label: "默认确认",      type: "text" },
    { key: "response.feedback.positive",        label: "正面反馈",      type: "text" },
    { key: "response.feedback.negative",        label: "负面反馈",      type: "text" },
    { key: "response.feedback.negative.transfer",label: "负面反馈转人工",type: "text" },
    { key: "response.feedback.neutral",         label: "中性反馈",      type: "text" },
    { key: "response.fallback.empty_input",     label: "空输入回复",    type: "text" },
    { key: "response.fallback.no_knowledge",    label: "无知识库回复",  type: "text" },
    { key: "response.fallback.low_similarity",  label: "低相似度回复",  type: "textarea" },
    { key: "response.fallback.empty_kb",        label: "知识库为空",    type: "text" },
    { key: "response.fallback.no_category_match",label:"无分类匹配",    type: "text" },
    { key: "response.fallback.ai_empty",        label: "AI响应为空",    type: "text" },
    { key: "response.fallback.system_error",    label: "系统故障",      type: "text" },
    { key: "query.category.required",           label: "要求声明身份",  type: "bool", desc: "教育类=true，诊所/通用=false" },
    { key: "response.query.ask_category",       label: "询问身份话术",  type: "text" },
    { key: "prompt.label.user_input",           label: "用户输入标签",  type: "text" },
    { key: "prompt.label.history",              label: "历史标签",      type: "text" },
    { key: "prompt.label.user_latest",          label: "最新输入标签",  type: "text" },
  ]},
]

export default function ConfigPage() {
  const [cfg,       setCfg]       = useState({})
  const [draft,     setDraft]     = useState({})
  const [activeKey, setActiveKey] = useState("system")
  const [status,    setStatus]    = useState("loading")
  const [msg,       setMsg]       = useState("")

  useEffect(() => {
    fetch(API)
      .then(r => r.json())
      .then(({ data }) => { setCfg(data); setDraft(data); setStatus("ok") })
      .catch(() => setStatus("error"))
  }, [])

  const dirty = Object.keys(draft).filter(k => draft[k] !== cfg[k])

  async function handleSave() {
    const updates = Object.fromEntries(dirty.map(k => [k, draft[k]]))
    try {
      const r = await fetch(API, { method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ updates }) })
      if (!r.ok) throw new Error()
      setCfg(c => ({ ...c, ...updates }))
      flash(`已保存 ${dirty.length} 项`)
    } catch { flash("保存失败", true) }
  }

  function flash(text, err = false) {
    setMsg(err ? `❌ ${text}` : `✓ ${text}`)
    setTimeout(() => setMsg(""), 2500)
  }

  const sec = SECTIONS.find(s => s.key === activeKey)

  return (
    <div className="flex flex-col h-full">
      <div className="border-b bg-card px-4 flex items-center h-10 shrink-0 gap-1">
        {SECTIONS.map(s => {
          const Icon = s.icon
          const hasDirty = s.fields.some(f => draft[f.key] !== cfg[f.key])
          const active = s.key === activeKey
          return (
            <button key={s.key} onClick={() => setActiveKey(s.key)}
              className={`relative flex items-center gap-1.5 px-3 h-full text-xs border-b-2 transition-colors
                ${active ? "border-blue-500 text-blue-600 font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
              <Icon className="w-3.5 h-3.5" />
              {s.label}
              {hasDirty && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 absolute top-2 right-0.5" />}
            </button>
          )
        })}
        <div className="ml-auto flex items-center gap-2">
          {msg && <span className={`text-xs px-2 py-0.5 rounded ${msg.startsWith("❌") ? "bg-red-50 text-red-600" : "bg-green-50 text-green-600"}`}>{msg}</span>}
          {dirty.length > 0 && <Badge variant="outline" className="text-amber-600 border-amber-400 text-xs">{dirty.length} 项未保存</Badge>}
          <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setDraft({ ...cfg })}>还原</Button>
          <Button size="sm" className="h-7 text-xs" disabled={dirty.length === 0} onClick={handleSave}>保存更改</Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {status === "loading" && <p className="text-sm text-muted-foreground">加载中...</p>}
        {status === "error"   && <Alert variant="destructive"><AlertDescription>无法连接配置 API（{API}），请确保后端已启动。</AlertDescription></Alert>}
        {status === "ok" && sec && (
          <div className="border rounded-lg bg-card overflow-hidden">
            {sec.fields.map((field, i) => {
              const isDirty = draft[field.key] !== cfg[field.key]
              return (
                <div key={field.key}
                  className={`grid grid-cols-[320px_1fr] gap-4 items-start px-4 py-3 ${i < sec.fields.length - 1 ? "border-b" : ""}`}>
                  <div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm font-medium">{field.label}</span>
                      {isDirty && <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />}
                    </div>
                    <code className="text-[10px] text-muted-foreground/70">{field.key}</code>
                    {field.desc && <p className="text-xs text-muted-foreground mt-0.5 leading-snug">{field.desc}</p>}
                  </div>
                  <div>
                    <ConfigField field={field} value={draft[field.key]}
                      onChange={v => setDraft(d => ({ ...d, [field.key]: v }))} />
                    {isDirty && <p className="text-[11px] text-muted-foreground mt-1">原值：<code className="font-mono">{cfg[field.key] ?? "(未设置)"}</code></p>}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}