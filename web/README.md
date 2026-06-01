# RAG Knowledge Manager

## 项目结构

```
rag-manager/
├── backend/
│   └── main.py          # FastAPI 后端
└── frontend/
    ├── src/
    │   ├── api/
    │   │   └── knowledge.js    # API 调用封装
    │   └── pages/
    │       └── KnowledgePage.jsx  # 主页面
    ├── package.json
    └── vite.config.js
```

---

## 后端启动

```bash
cd backend
pip install fastapi uvicorn psycopg2-binary

# 启动（开发模式）
uvicorn main:app --reload --port 8000
```

API 文档自动生成：http://localhost:8000/docs

---

## 前端启动

```bash
# 1. 创建 Vite + React 项目
npm create vite@latest frontend -- --template react
cd frontend

# 2. 安装依赖
npm install

# 3. 安装 Tailwind CSS
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p

# 4. 安装 shadcn/ui
npm install -D @types/node
npx shadcn-ui@latest init
# 选择: Default style, Zinc color, CSS variables: yes

# 5. 安装需要的组件
npx shadcn-ui@latest add button input badge select dialog table checkbox textarea label tabs progress alert

# 6. 安装图标库
npm install lucide-react

# 7. 复制页面文件到 src/
# - api/knowledge.js → src/api/knowledge.js
# - pages/KnowledgePage.jsx → src/pages/KnowledgePage.jsx

# 8. 修改 src/App.jsx
# import KnowledgePage from "@/pages/KnowledgePage"
# export default function App() { return <KnowledgePage /> }

# 9. 启动
npm run dev
```

---

## vite.config.js（配置代理，解决跨域）

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      }
    }
  }
})
```

---

## tailwind.config.js

```js
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: { extend: {} },
  plugins: [],
}
```

---

## 数据库表结构（enterprise_knowledge_1024）

```sql
ALTER TABLE enterprise_knowledge_1024
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

-- 确保 is_active 列存在
ALTER TABLE enterprise_knowledge_1024
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true;
```

---

## 生产部署

```bash
# 前端构建
cd frontend && npm run build
# 产物在 frontend/dist/

# FastAPI 托管前端
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")

# 启动
uvicorn main:app --host 0.0.0.0 --port 8000
```
