import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  server: {
    port: 5173,
    // the API lives on the backend in dev; same-origin in a build
    proxy: { '/api': { target: 'http://127.0.0.1:8010', changeOrigin: true } },
  },
  build: { outDir: 'dist', sourcemap: true },
})
