// frontend/src/api/knowledge.js
const BASE = "/api"

export async function getStats() {
  const r = await fetch(`${BASE}/stats`)
  return r.json()
}

export async function listKnowledge({ category, status, search, page = 1, pageSize = 20 } = {}) {
  const params = new URLSearchParams()
  if (category)  params.set("category", category)
  if (status)    params.set("status", status)
  if (search)    params.set("search", search)
  params.set("page", page)
  params.set("page_size", pageSize)
  const r = await fetch(`${BASE}/knowledge?${params}`)
  return r.json()
}

export async function listCategories() {
  const r = await fetch(`${BASE}/categories`)
  return r.json()
}

export async function createKnowledge(item) {
  const r = await fetch(`${BASE}/knowledge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(item),
  })
  return r.json()
}

export async function updateKnowledge(id, item) {
  const r = await fetch(`${BASE}/knowledge/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(item),
  })
  return r.json()
}

export async function deleteKnowledge(id) {
  const r = await fetch(`${BASE}/knowledge/${id}`, { method: "DELETE" })
  return r.json()
}

export async function deleteMany(ids) {
  const r = await fetch(`${BASE}/knowledge`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ids),
  })
  return r.json()
}

export async function vectorize(ids) {
  const r = await fetch(`${BASE}/knowledge/vectorize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ids),
  })
  return r.json()
}

export async function searchKnowledge({ q, category, limit = 5 } = {}) {
  const params = new URLSearchParams({ q })
  if (category) params.set("category", category)
  if (limit)    params.set("limit", limit)
  const r = await fetch(`${BASE}/search?${params}`)
  return r.json()
}

export async function bulkImport(items) {
  const r = await fetch(`${BASE}/knowledge/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(items),
  })
  return r.json()
}
