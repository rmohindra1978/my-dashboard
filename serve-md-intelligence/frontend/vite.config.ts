/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: { manualChunks: { maplibre: ["maplibre-gl"], recharts: ["recharts"], react: ["react", "react-dom", "react-router-dom"] } },
    },
  },
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.VITE_API_URL ?? "http://localhost:8000", changeOrigin: true } },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
