import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 3737,
    proxy: {
      "/api": {
        target: process.env.MEDUSA_API_PROXY || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
