import AppLayout from "./pages/AppLayout"
import ConversationPageForCust from "./pages/ConversationPageForCust"
import CopilotPage from "./pages/CopilotPage"

export default function App() {
  const path = window.location.pathname

  if (path === "/aiweb/conversation-cust" || path === "/aiweb/conversation-cust/") {
    return (
      <div className="min-h-screen bg-background">
        <ConversationPageForCust />
      </div>
    )
  }

  // Standalone route (no login / no sidebar shell) so this can be
  // embedded directly as an <iframe> from the legacy JSP call panel
  // (popCustAck2_v2.jsp -> "AI副驾驶" tab).
  // Uses a query param (?view=copilot) rather than a path segment,
  // because the backend serves this app via a plain
  // StaticFiles(html=True) mount at /aiweb — that only auto-falls-back
  // to index.html for the bare "/aiweb/" root, and 404s on unknown
  // path segments like "/aiweb/copilot". A query string on "/aiweb/"
  // itself doesn't hit that problem since StaticFiles only looks at
  // the path, not the query string.
  const params = new URLSearchParams(window.location.search)
  if (params.get("view") === "copilot") {
    return (
      <div className="min-h-screen bg-background">
        <CopilotPage />
      </div>
    )
  }

  return <AppLayout />
}
