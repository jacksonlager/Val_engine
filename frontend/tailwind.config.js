/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui", "-apple-system", '"Segoe UI"', "Helvetica", "Arial", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", '"Liberation Mono"', "monospace"],
      },
      colors: {
        ground: "var(--ground)",
        surface: "var(--surface)",
        raised: "var(--raised)",
        ink: "var(--ink)",
        ink2: "var(--ink-2)",
        muted: "var(--muted)",
        hair: "var(--hairline)",
        line: "var(--border)",
        accent: "var(--accent)",
      },
    },
  },
  plugins: [],
};
