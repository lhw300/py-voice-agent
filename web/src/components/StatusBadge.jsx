import { Badge } from "@/components/ui/badge"
import { CheckCircle, Clock, AlertCircle } from "lucide-react"

export default function StatusBadge({ status }) {
  if (status === "indexed") return (
    <Badge variant="outline" className="border-green-500 text-green-600 bg-green-50 text-xs">
      <CheckCircle className="w-3 h-3 mr-1" />已向量化
    </Badge>
  )
  if (status === "pending") return (
    <Badge variant="outline" className="border-amber-500 text-amber-600 bg-amber-50 text-xs">
      <Clock className="w-3 h-3 mr-1" />待向量化
    </Badge>
  )
  return (
    <Badge variant="outline" className="border-red-500 text-red-600 bg-red-50 text-xs">
      <AlertCircle className="w-3 h-3 mr-1" />失败
    </Badge>
  )
}
