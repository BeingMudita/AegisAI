import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// In development the API is proxied, so the browser talks to one origin and
// no CORS setup is needed. Production builds call VITE_API_URL directly.
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": loadEnv(mode, ".", "AEGIS_").AEGIS_API_TARGET || "http://localhost:8000",
      "/health": loadEnv(mode, ".", "AEGIS_").AEGIS_API_TARGET || "http://localhost:8000",
    },
  },
}));
