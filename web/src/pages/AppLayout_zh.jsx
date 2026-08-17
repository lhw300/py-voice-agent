import { useState, useEffect } from "react"
import { Database, SlidersHorizontal, MessageCircle, ChevronRight, MemoryStick, LogOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import ConfigPage       from "./ConfigPage"
import KnowledgePage    from "./KnowledgePage"
import ConversationPage from "./ConversationPage"
import CachePage        from "./CachePage"
import ChatTestPage     from "./ChatTestPage"
import LoginPage        from "./LoginPage"

// 静态的导航菜单定义。
// 每一项把一个 "key"（内部用来判断当前显示哪个页面的标识符）
// 对应到显示文字 "label" 和一个来自 lucide-react 的图标组件 "icon"。
// 这个数组写在组件函数外面，意味着它只会被创建一次，
// 不会随着组件每次重新渲染而重复创建（性能优化）。
const NAV = [
  { key: "config",       label: "配置管理",  icon: SlidersHorizontal },
  { key: "knowledge",    label: "知识库管理", icon: Database },
  { key: "conversation", label: "对话查询",  icon: MessageCircle },
  { key: "cache",        label: "缓存管理",  icon: MemoryStick },
  { key: "chattest",     label: "聊天测试",  icon: Bot },
]

// 特殊的占位值，当后端返回 "dev_mode"（开发模式）开启时，
// 用这个假 token 让前端跳过真实的登录验证流程。
const DEV_TOKEN = "dev"

// 在 React 里，一个"组件"本质就是一个返回 JSX（类似HTML的语法）的普通 JS 函数。
// "export default" 表示这是本文件对外导出的主要内容，
// 其他文件可以用 `import AppLayout from "./AppLayout"` 来引用它。
export default function AppLayout() {

  // ── React 状态（Hooks）────────────────────────────────────────────
  // useState(初始值) 会返回一对东西：[当前值, 修改这个值的函数]。
  // 调用"修改函数"会更新这个值，同时触发 React 用新值重新渲染这个组件。

  // 记录当前侧边栏选中的是哪个 tab / 页面。
  // 初始值是 "knowledge"（所以页面一打开默认显示知识库管理）。
  const [active,  setActive]  = useState("knowledge")

  // 记录已登录管理员的认证令牌（token）。
  // useState(() => ...) —— 传进去的是一个"函数"而不是普通值，
  // 这表示这个初始化逻辑只会在组件第一次渲染时执行一次（懒初始化），
  // 不会每次重新渲染都重复执行。这里是从浏览器的 localStorage
  // （持久化的键值对本地存储）里读取之前登录时保存的 token，
  // 用来恢复"还记得我"的登录状态。
  const [token,   setToken]   = useState(() => localStorage.getItem("admin_token"))

  // 记录操作员工号字符串，仅用于界面显示（比如 "1000"）。
  // 如果 localStorage 里还没存任何值，就用空字符串 "" 兜底。
  const [idOper,  setIdOper]  = useState(() => localStorage.getItem("admin_id_oper") || "")

  // 标记后端当前是否处于"开发者模式"（这种模式下会跳过真实登录，
  // 直接自动认证通过）。初始值为 false，等检测完成后再更新。
  const [devMode, setDevMode] = useState(false)

  // 用来防止"登录页一闪而过"的标志位。
  // 在下面的 useEffect 里那次异步的登录状态检查完成之前，
  // 这个值一直是 false，组件会直接 return null（什么都不渲染），
  // 避免对已经登录过的用户，短暂闪现一下登录表单再切回主界面。
  const [checked, setChecked] = useState(false)

  // ── useEffect：在渲染之后执行"副作用"逻辑 ──────────────────────────
  // useEffect(回调函数, 依赖数组) 的作用类似浏览器原生的
  // window.onload 事件，但是它的作用范围只限于这一个组件内部。
  // 依赖数组传空数组 [] 的意思是：
  // "这段回调函数只在组件第一次挂载（出现在页面上）时执行一次"，
  // 之后组件再怎么重新渲染，这段逻辑都不会再跑第二遍。
  useEffect(() => {
    // 向后端询问当前是否开启了 dev_mode（开发模式）。
    fetch("/api/auth/config")
      .then(r => r.json())
      .then(data => {
        if (data.dev_mode) {
          // 开发模式的捷径：完全跳过真实登录流程。
          setDevMode(true)
          setToken(DEV_TOKEN)   // 用一个假 token，让后续逻辑以为"已登录"
          setChecked(true)      // 解除阻塞，允许渲染主界面
          return                // 到此为止，不再往下走"正常模式"的逻辑
        }

        // ── 正常模式：校验之前保存下来的 token 是否还有效 ──────────
        const t = localStorage.getItem("admin_token")
        if (!t) {
          // 本地根本没存过 token → 没什么可校验的，
          // 直接解除阻塞，让登录页正常显示出来。
          setChecked(true)
          return
        }

        // 本地存在一个之前会话留下的 token —— 问问后端这个 token
        // 现在是不是还有效（没过期、没被注销）。
        fetch(`/api/auth/check?token=${t}`)
          .then(r => {
            if (!r.ok) handleLogout()   // token 已失效 → 清除它，强制重新登录
            else setChecked(true)        // token 仍然有效 → 放行进入主界面
          })
          .catch(() => {
            // 校验请求本身网络出错了 —— 为安全起见按"已登出"处理。
            handleLogout()
            setChecked(true)
          })
      })
      .catch(() => setChecked(true))  // 就算 /api/auth/config 这一步本身请求失败，也要解除阻塞
  }, [])  // <-- 空依赖数组 = 只在组件挂载时执行一次

  // ── 事件处理函数 ──────────────────────────────────────────────────
  // 这些是定义在组件函数内部的普通 JavaScript 函数。
  // 它们可以通过"闭包"访问组件的状态变量，
  // 也可以作为 "props"（属性）传给子组件
  // （比如 <LoginPage onLogin={handleLogin} /> 这种写法）。

  // 当子组件 LoginPage 登录成功后，会调用这个函数（回调父组件）。
  // newToken 是后端登录接口返回的认证令牌。
  function handleLogin(newToken) {
    setToken(newToken)
    // 重新从 localStorage 读取 id_oper，
    // 因为按设计，LoginPage 在调用这个回调之前应该已经把它存进去了。
    setIdOper(localStorage.getItem("admin_id_oper") || "")
  }

  // 退出登录：（非开发模式下）通知后端把这个 token 作废，
  // 清空 localStorage 里存的登录信息，并重置本地 React 状态，
  // 这样组件重新渲染后就会自动回退到显示 LoginPage 登录页。
  function handleLogout() {
    if (!devMode) {
      const t = localStorage.getItem("admin_token")
      if (t) {
        // 发一个"发后不管"的请求，告诉后端也把这个 token 在服务端
        // 作废掉（比如从 Redis 里删除）。
        fetch("/api/auth/logout", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ token: t })
        })
      }
      localStorage.removeItem("admin_token")
      localStorage.removeItem("admin_id_oper")
    }
    setToken(null)
    setIdOper("")
  }

  // ── 提前 return 的条件判断（守卫语句）────────────────────────────
  // 在 JSX 里，一个组件函数可以根据不同条件 `return` 不同的内容。
  // React 只会渲染最终实际执行到的那一条 `return` 语句返回的内容。

  // 还在等待最初那次 /api/auth/config + /api/auth/check 的异步请求
  // 跑完 → 什么都不渲染（返回 null，页面空白）。
  // 这样可以避免对实际上已经登录过的用户，
  // 短暂闪现一下登录表单，造成视觉上的"跳动"。
  if (!checked) return null

  // 检查流程跑完之后，发现没有有效 token → 显示登录界面。
  // 这里把 `handleLogin` 函数当作名为 `onLogin` 的 prop 传下去，
  // 这样 LoginPage 组件内部登录成功后，就可以"回调"调用这个函数，
  // 通知父组件（也就是这里）登录已经完成。
  if (!token) return <LoginPage onLogin={handleLogin} />

  // ── 已登录状态下的主界面 ──────────────────────────────────────────
  // 如果代码执行到了这里，说明用户已经通过认证
  // （无论是真实登录，还是 dev_mode 自动登录），
  // 于是渲染完整的应用外壳：顶部栏 + 左侧边栏 + 右侧主内容区。
  return (
    <div className="min-h-screen bg-background flex flex-col">

      {/* 顶部栏：左边是 Logo/标题，右边是用户信息 + 退出按钮 */}
      <header className="border-b bg-card px-5 flex items-center justify-between h-12 shrink-0">
        <div className="flex items-center gap-2">
          <Database className="w-5 h-5 text-blue-500" />
          <span className="font-medium text-sm">RAG 知识库管理</span>
        </div>
        <div className="flex items-center gap-3">
          {/* 三元表达式（条件 ? 真时的JSX : 假时的JSX）——
              这是 JSX 里写 if/else 的标准方式之一。
              之所以写成行内表达式，是因为 JSX 花括号 {} 里
              必须是一个"单一表达式"，不能直接写多行的 if/else 语句。 */}
          {devMode
            ? <span className="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-700 border border-amber-300">开发模式</span>
            : <span className="text-xs text-muted-foreground">{idOper}</span>
          }
          {/* `条件 && <JSX>` —— React 里常用的简写写法，
              意思是"只有条件为真时才渲染这段内容"。
              如果 devMode 是 true，那么 `!devMode` 就是 false，
              JS 的短路求值会让后面的内容直接不渲染
              （开发模式下不显示"退出"按钮）。 */}
          {!devMode && (
            <Button variant="ghost" size="sm" className="text-xs gap-1" onClick={handleLogout}>
              <LogOut className="w-3.5 h-3.5" />退出
            </Button>
          )}
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">

        {/* 左侧边栏：纵向的导航菜单 */}
        <aside className="w-44 border-r bg-card flex flex-col shrink-0">
          <nav className="flex-1 p-2 space-y-0.5 pt-3">
            {/* 数组的 .map() 方法把 NAV 数组里的每一项，
                转换成一个 JSX 的 <button> 按钮元素。
                React 接着会把转换出来的这一整组按钮渲染成列表。
                这是 React 里根据数据动态生成"重复型 UI"的标准写法。 */}
            {NAV.map(({ key, label, icon: Icon }) => {
              // 解构赋值时顺便重命名：`icon: Icon` 表示
              // 把这一项的 icon 属性取出来，本地重新命名为 Icon
              // （首字母大写），因为 JSX 规定组件名必须大写开头，
              // 否则会被当成普通 HTML 标签而不是 React 组件来处理。
              const on = active === key   // 判断这一项是不是当前选中的 tab
              return (
                // `key={key}` 是 React 在渲染列表时要求的特殊属性 ——
                // 它帮助 React 在每次重新渲染时，
                // 高效地识别"哪个数组项对应哪个 DOM 元素"，
                // 这个 key 本身不会显示在最终渲染的页面上。
                <button
                  key={key}
                  onClick={() => setActive(key)}   // 点击就切换当前激活的 tab
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors
                    ${on ? "bg-blue-50 text-blue-700 font-medium dark:bg-blue-950" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  {label}
                  {/* 只有当前选中的那一项才显示右边的小箭头 ">" */}
                  {on && <ChevronRight className="w-3.5 h-3.5 ml-auto opacity-50" />}
                </button>
              )
            })}
          </nav>
          <div className="border-t p-3">
            <p className="text-[10px] text-muted-foreground/60">py-ai-agent v1.0</p>
          </div>
        </aside>

        {/* 主内容区：下面这四个页面组件中，
            任意时刻只有一个会被真正渲染出来，
            具体是哪一个由上面的 `active` 状态变量决定。
            这其实是一种"手写的简易路由"——
            没有改变浏览器地址栏的 URL，也没有用 react-router 这类库，
            纯粹靠这个 `active` 状态变量来控制条件渲染。 */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {active === "config"       && <ConfigPage />}
          {active === "knowledge"    && <KnowledgePage />}
          {active === "conversation" && <ConversationPage />}
          {active === "cache"        && <CachePage />}
		  {active === "chattest"     && <ChatTestPage />}
        </main>
      </div>
    </div>
  )
}
