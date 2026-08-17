import { useState } from "react"
import { Database } from "lucide-react"
import { Input }  from "@/components/ui/input"
import { Button } from "@/components/ui/button"

export default function LoginPage({ onLogin }) {
  const [idOper, setIdOper] = useState("")
  const [passwd, setPasswd] = useState("")
  const [error,  setError]  = useState("")
  const [loading,setLoading]= useState(false)

  async function handleLogin() {
    if (!idOper.trim() || !passwd.trim()) {
      setError("请输入工号和密码"); return
    }
    setLoading(true); setError("")
    try {
      const res  = await fetch("/api/auth/login", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ id_oper: idOper, passwd })
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail || "登录失败")
      } else {
        localStorage.setItem("admin_token",   data.token)
        localStorage.setItem("admin_id_oper", data.id_oper)
        onLogin(data.token)
      }
    } catch {
      setError("网络错误，请重试")
    }
    setLoading(false)
  }

  function onKeyDown(e) {
    if (e.key === "Enter") handleLogin()
  }

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--color-background-tertiary)"
    }}>
      <div style={{
        background: "var(--color-background-primary)",
        border: "0.5px solid var(--color-border-tertiary)",
        borderRadius: "var(--border-radius-lg)",
        padding: "2.5rem",
        width: "360px",
        boxShadow: "0 4px 24px rgba(0,0,0,0.06)"
      }}>
        {/* Logo */}
        <div style={{ display:"flex", alignItems:"center", gap:"10px", marginBottom:"2rem" }}>
          <Database style={{ width:28, height:28, color:"#378ADD" }} />
          <div>
            <p style={{ fontWeight:500, fontSize:16, margin:0, color:"var(--color-text-primary)" }}>RAG 知识库管理</p>
            <p style={{ fontSize:12, color:"var(--color-text-secondary)", margin:0 }}>LCallAI Admin</p>
          </div>
        </div>

        {/* 表单 */}
        <div style={{ display:"flex", flexDirection:"column", gap:"12px" }}>
          <div>
            <label style={{ fontSize:13, color:"var(--color-text-secondary)", display:"block", marginBottom:4 }}>工号</label>
            <Input placeholder="请输入工号" value={idOper}
              onChange={e => setIdOper(e.target.value)} onKeyDown={onKeyDown} />
          </div>
          <div>
            <label style={{ fontSize:13, color:"var(--color-text-secondary)", display:"block", marginBottom:4 }}>密码</label>
            <Input type="password" placeholder="请输入密码" value={passwd}
              onChange={e => setPasswd(e.target.value)} onKeyDown={onKeyDown} />
          </div>

          {error && (
            <p style={{ fontSize:13, color:"var(--color-text-danger)", margin:0 }}>⚠ {error}</p>
          )}

          <Button onClick={handleLogin} disabled={loading} style={{ width:"100%", marginTop:4 }}>
            {loading ? "登录中..." : "登录"}
          </Button>
        </div>
      </div>
    </div>
  )
}
