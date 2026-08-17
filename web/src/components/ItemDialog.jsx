import { useState } from "react"
import { Button }   from "@/components/ui/button"
import { Input }    from "@/components/ui/input"
import { Label }    from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"

export default function ItemDialog({ item, categories, onSave, onClose }) {
  const [form, setForm] = useState(item || { category: "", summary: "", content: "" })
  const [saving, setSaving] = useState(false)
  const set = k => e => setForm(f => ({ ...f, [k]: e.target?.value ?? e }))

  async function handleSave() {
    setSaving(true)
    await onSave(form)
    setSaving(false)
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{item?.id ? "编辑知识条目" : "新增知识条目"}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {item?.id && (
            <div className="space-y-1">
              <Label className="text-muted-foreground">ID</Label>
              <Input value={item.id} disabled className="font-mono text-xs bg-muted text-muted-foreground" />
            </div>
          )}

          <div className="space-y-1">
            <Label>分类</Label>
			
            <Select value={form.category} onValueChange={set("category")}>
              <SelectTrigger><SelectValue placeholder="选择分类" /></SelectTrigger>
              <SelectContent>
                {categories.map(c => (
                  <SelectItem key={c.category} value={c.category}>{c.category}</SelectItem>
                ))}
                <SelectItem value="__new__">+ 新建分类...</SelectItem>
              </SelectContent>
            </Select>
            {form.category === "__new__" && (
              <Input className="mt-2" placeholder="输入新分类名称" onChange={set("category")} />
            )}
          </div>

          <div className="space-y-1">
            <Label>摘要</Label>
            <Input value={form.summary} onChange={set("summary")} />
          </div>

          <div className="space-y-1">
            <Label>内容</Label>
            <Textarea value={form.content} rows={5} onChange={set("content")} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={handleSave} disabled={saving}>{saving ? "保存中..." : "保存"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
