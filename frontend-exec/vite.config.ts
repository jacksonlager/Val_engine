import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served by the FastAPI app at /exec/ (StaticFiles, html=True) and also inlined into a
// single-file exec_report.html. The base is relative rather than "/exec/" on purpose: the
// shared inliner in export/static_report.py resolves asset refs by stripping the leading
// slash and joining onto static_exec/, so "/exec/assets/x.js" would miss and be left as a
// dangling tag, while "./assets/x.js" resolves both there and under the /exec/ mount.
// Output lands inside the Python package so the site ships with `pip install -e .`.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../src/hc_valuation/api/static_exec",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        // one JS chunk so the single-file inliner picks up the whole app
        manualChunks: undefined,
        inlineDynamicImports: true,
      },
    },
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
