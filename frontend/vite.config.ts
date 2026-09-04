import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base './' so the bundle works served at '/' by the API and when inlined into a
// single static report file. Output lands inside the Python package so
// `pip install -e .` ships the dashboard with no Node on the reviewer's machine.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../src/hc_valuation/api/static",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 800, // recharts + react in one file, by design (inlined into the static report)
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
