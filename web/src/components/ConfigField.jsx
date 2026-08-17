import { Input }    from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

export default function ConfigField({ field, value, onChange }) {
  const val = value ?? ""
  const chg = e => onChange(e.target.value)

  if (field.type === "bool") {
    const on = val === "true"
    return (
      <div className="flex items-center gap-2">
        <button onClick={() => onChange(on ? "false" : "true")}
          style={{ width:40, height:22, borderRadius:11, border:"none", cursor:"pointer",
            background: on ? "#22c55e" : "#d1d5db", position:"relative", padding:0, flexShrink:0 }}>
          <span style={{ position:"absolute", top:3, left: on ? 20 : 3,
            width:16, height:16, borderRadius:"50%", background:"#fff", display:"block", transition:"left 0.15s" }} />
        </button>
        <span className={`text-xs ${on ? "text-green-600" : "text-muted-foreground"}`}>{on ? "开启" : "关闭"}</span>
      </div>
    )
  }
  if (field.type === "select") return (
    <Select value={val} onValueChange={onChange}>
      <SelectTrigger className="h-8 text-xs w-48"><SelectValue /></SelectTrigger>
      <SelectContent>{field.options.map(o => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
    </Select>
  )
  if (field.type === "slider") return (
    <div className="flex items-center gap-2">
      <input type="range" min={0} max={1} step={0.01} value={val || 0}
        onChange={chg} className="w-32 accent-blue-500" />
      <span className="text-xs font-medium w-10 tabular-nums">{parseFloat(val || 0).toFixed(2)}</span>
    </div>
  )
  if (field.type === "number")   return <Input type="number" min={field.min} max={field.max} step={field.step} value={val} onChange={chg} className="h-8 text-xs w-28" />
  if (field.type === "password") return <Input type="password" value={val} onChange={chg} className="h-8 text-xs w-64" />
  if (field.type === "textarea") return <Textarea value={val} onChange={chg} rows={3} className="text-xs resize-y" />
  return <Input type="text" value={val} onChange={chg} className="h-8 text-xs w-full max-w-sm" />
}
