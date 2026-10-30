import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 前后端分离：前端独立运行，API 指向后端 8033（可通过 VITE_API_BASE 覆盖）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8033',
      '/files': 'http://127.0.0.1:8033',
    },
  },
})
