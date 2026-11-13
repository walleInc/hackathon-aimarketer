import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В разработке запросы к API и медиа проксируются на бэкенд
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.BACKEND_URL ?? "http://localhost:8000",
      "/media": process.env.BACKEND_URL ?? "http://localhost:8000",
    },
  },
});
