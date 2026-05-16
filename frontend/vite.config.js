import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/auth": "http://127.0.0.1:8000",
      "/dialogs": "http://127.0.0.1:8000",
      "/messages": "http://127.0.0.1:8000",
      "/jobs": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000",
      "/assets": "http://127.0.0.1:8000",
    },
  },
});
