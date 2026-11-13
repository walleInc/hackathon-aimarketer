import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';

// В разработке запросы к API и медиа проксируются на бэкенд
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': new URL('./src', import.meta.url).pathname } },
  server: {
    port: 5173,
    proxy: {
      '/api': process.env.BACKEND_URL ?? 'http://localhost:8000',
      '/media': process.env.BACKEND_URL ?? 'http://localhost:8000',
    },
  },
});
