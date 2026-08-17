import { useState, useEffect } from "react"
import { Database, SlidersHorizontal, MessageCircle, ChevronRight, MemoryStick, LogOut, Bot, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import ConfigPage       from "./ConfigPage"
import KnowledgePage    from "./KnowledgePage"
import ConversationPage from "./ConversationPage"
import CachePage        from "./CachePage"
import ChatTestPage     from "./ChatTestPage"
import CopilotPage      from "./CopilotPage"
import LoginPage        from "./LoginPage"

// Static navigation menu definition.
// Each item maps a "key" (used internally to track which page is active)
// to a display "label" and an "icon" component from lucide-react.
// This array is defined OUTSIDE the component so it is created only once,
// not re-created on every render.
const NAV = [
  { key: "config",       label: "配置管理",  icon: SlidersHorizontal },
  { key: "knowledge",    label: "知识库管理", icon: Database },
  { key: "conversation", label: "对话查询",  icon: MessageCircle },
  { key: "cache",        label: "缓存管理",  icon: MemoryStick },
    { key: "chattest",     label: "聊天测试",  icon: Bot },
	{ key: "copilot",      label: "AI副驾驶",  icon: Sparkles },
]

// Special sentinel value used as a fake/placeholder token when the backend
// reports "dev_mode" is enabled, so the UI can skip real authentication.
const DEV_TOKEN = "dev"

// In React, a component is just a JavaScript function that returns JSX
// (HTML-like syntax). "export default" means this is the main thing
// this file exports, so other files can `import AppLayout from "./AppLayout"`.
export default function AppLayout() {

  // ── React State (Hooks) ──────────────────────────────────────────────
  // useState(initialValue) returns a pair: [currentValue, setterFunction].
  // Calling the setter function updates the value AND triggers React to
  // re-render the component with the new value.

  // Tracks which sidebar tab/page is currently selected.
  // Initial value: "knowledge" (so Knowledge page shows first on load).
  const [active,  setActive]  = useState("knowledge")

  // Tracks the auth token for the logged-in admin.
  // useState(() => ...) — passing a FUNCTION instead of a plain value means
  // this initializer only runs ONCE on first render (lazy initialization),
  // not on every re-render. Here it reads from the browser's localStorage
  // (persistent key-value storage) to restore a previous login session.
  const [token,   setToken]   = useState(() => localStorage.getItem("admin_token"))

  // Tracks the operator/employee ID string for display purposes (e.g. "1000").
  // Falls back to empty string "" if nothing is stored yet.
  const [idOper,  setIdOper]  = useState(() => localStorage.getItem("admin_id_oper") || "")

  // Whether the backend is running in "developer mode" (which bypasses
  // real login and auto-authenticates). Starts as false until checked.
  const [devMode, setDevMode] = useState(false)

  // Guards against a "flash of login page" while we're still waiting
  // for the initial auth check (the useEffect below) to finish.
  // Until checked === true, we render nothing (return null) to avoid
  // briefly showing the login form before we know if the user is
  // actually already authenticated.
  const [checked, setChecked] = useState(false)

  // ── useEffect: runs side effects after render ──────────────────────
  // useEffect(callback, dependencyArray) is similar to a browser's
  // window.onload event, BUT scoped to this component.
  // An empty dependency array [] means: "run this callback exactly once,
  // right after this component first mounts (appears on screen)."
  // It will NOT run again on subsequent re-renders.
  useEffect(() => {
    // Ask the backend whether dev_mode is currently enabled.
    fetch("/api/auth/config")
      .then(r => r.json())
      .then(data => {
        if (data.dev_mode) {
          // Dev mode shortcut: skip real login entirely.
          setDevMode(true)
          setToken(DEV_TOKEN)   // fake token so the rest of the UI thinks we're logged in
          setChecked(true)      // unblock rendering
          return                // stop here, don't fall through to normal-mode logic
        }

        // ── Normal mode: validate any previously-saved token ──────────
        const t = localStorage.getItem("admin_token")
        if (!t) {
          // No saved token at all → nothing to validate, just unblock
          // rendering so the login page can show.
          setChecked(true)
          return
        }

        // We have a saved token from a previous session — ask the backend
        // if it's still valid (not expired / not revoked).
        fetch(`/api/auth/check?token=${t}`)
          .then(r => {
            if (!r.ok) handleLogout()   // token rejected → clear it and force login
            else setChecked(true)        // token still valid → proceed to main UI
          })
          .catch(() => {
            // Network error while checking — treat as logged out, fail safe.
            handleLogout()
            setChecked(true)
          })
      })
      .catch(() => setChecked(true))  // even if /api/auth/config itself fails, unblock UI
  }, [])  // <-- empty array = run once on mount only

  // ── Event handler functions ──────────────────────────────────────────
  // Plain JavaScript functions defined inside the component. They have
  // access to the component's state via closures, and can be passed down
  // to child components as "props" (e.g. <LoginPage onLogin={handleLogin} />).

  // Called by the LoginPage child component after a successful login.
  // newToken is the auth token returned by the backend.
  function handleLogin(newToken) {
    setToken(newToken)
    // Re-read id_oper from localStorage, since LoginPage is expected to
    // have already saved it there before calling this callback.
    setIdOper(localStorage.getItem("admin_id_oper") || "")
  }

  // Logs the user out: invalidates the token on the server (if not in
  // dev mode), clears localStorage, and resets local React state so the
  // component re-renders and falls back to showing the LoginPage.
  function handleLogout() {
    if (!devMode) {
      const t = localStorage.getItem("admin_token")
      if (t) {
        // Fire-and-forget request to tell the backend to invalidate
        // this token server-side too (e.g. delete it from Redis).
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

  // ── Conditional early returns (guard clauses) ─────────────────────────
  // In JSX, a component function can `return` different things based on
  // conditions. React will render whatever the LAST executed `return`
  // statement produces.

  // Still waiting for the initial /api/auth/config + /api/auth/check
  // round-trip to finish → render nothing at all (null = blank).
  // This avoids a brief "flash" of the login form for users who are
  // actually already logged in.
  if (!checked) return null

  // No valid token after the check completed → show the login screen.
  // We pass `handleLogin` down as a prop named `onLogin`, so LoginPage
  // can call it (like calling back up to the parent) once login succeeds.
  if (!token) return <LoginPage onLogin={handleLogin} />

  // ── Main authenticated UI ──────────────────────────────────────────
  // If we reach this point, the user is authenticated (either via real
  // login or dev_mode auto-login), so we render the full app shell:
  // a top header bar + a left sidebar + a main content area.
  return (
    <div className="min-h-screen bg-background flex flex-col">

      {/* Top bar: logo/title on the left, user info + logout button on the right */}
      <header className="border-b bg-card px-5 flex items-center justify-between h-12 shrink-0">
        <div className="flex items-center gap-2">
          <Database className="w-5 h-5 text-blue-500" />
          <span className="font-medium text-sm">RAG 知识库管理</span>
        </div>
        <div className="flex items-center gap-3">
          {/* Ternary (condition ? thenJSX : elseJSX) — JSX's version of if/else.
              Shown inline because JSX expressions must be a single value,
              not a multi-line if/else statement. */}
          {devMode
            ? <span className="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-700 border border-amber-300">开发模式</span>
            : <span className="text-xs text-muted-foreground">{idOper}</span>
          }
          {/* `condition && <JSX>` — React-specific shorthand for "render
              this only if condition is true". If devMode is true,
              `!devMode` is false, so JavaScript short-circuits and
              nothing is rendered (no logout button shown in dev mode). */}
          {!devMode && (
            <Button variant="ghost" size="sm" className="text-xs gap-1" onClick={handleLogout}>
              <LogOut className="w-3.5 h-3.5" />退出
            </Button>
          )}
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">

        {/* Left sidebar: vertical navigation menu */}
        <aside className="w-44 border-r bg-card flex flex-col shrink-0">
          <nav className="flex-1 p-2 space-y-0.5 pt-3">
            {/* Array.prototype.map() transforms each item in NAV into a
                JSX <button> element. React then renders the resulting
                array of buttons as a list. This is the standard way to
                render dynamic/repeated UI from data in React. */}
            {NAV.map(({ key, label, icon: Icon }) => {
              // Destructuring with renaming: `icon: Icon` takes the
              // `icon` property from this NAV item and binds it locally
              // as `Icon` (capitalized, because JSX requires component
              // names to start with a capital letter to be treated as
              // a component rather than a plain HTML tag).
              const on = active === key   // is this the currently selected tab?
              return (
                // `key={key}` is a special React prop required when
                // rendering lists — it helps React efficiently track
                // which DOM elements correspond to which array items
                // across re-renders. It is NOT visible in the rendered output.
                <button
                  key={key}
                  onClick={() => setActive(key)}   // clicking switches the active tab
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors
                    ${on ? "bg-blue-50 text-blue-700 font-medium dark:bg-blue-950" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  {label}
                  {/* Show a little ">" arrow only next to the active tab */}
                  {on && <ChevronRight className="w-3.5 h-3.5 ml-auto opacity-50" />}
                </button>
              )
            })}
          </nav>
          <div className="border-t p-3">
            <p className="text-[10px] text-muted-foreground/60">py-ai-agent v1.0</p>
          </div>
        </aside>

        {/* Main content area: only ONE of these four pages is actually
            rendered at any given time, based on which tab is `active`.
            This is a simple in-memory "router" — no URL changes, no
            react-router library, just conditional rendering controlled
            by the `active` state variable defined above. */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {active === "config"       && <ConfigPage />}
          {active === "knowledge"    && <KnowledgePage />}
          {active === "conversation" && <ConversationPage />}
          {active === "cache"        && <CachePage />}
		  {active === "chattest"     && <ChatTestPage />}
		  {active === "copilot"      && <CopilotPage />}
        </main>
      </div>
    </div>
  )
}
