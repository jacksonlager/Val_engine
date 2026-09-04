import { useEffect, useState } from "react";

// Recharts writes fills as SVG attributes; resolve the CSS variables once per
// theme change so chart marks follow the same palette as the rest of the page.
export interface ChartTheme {
  up: string;
  down: string;
  neutral: string;
  series1: string;
  series1Soft: string;
  grid: string;
  axis: string;
  ink: string;
  ink2: string;
  muted: string;
  surface: string;
  block: string;
  review: string;
  monitor: string;
  clear: string;
}

function read(): ChartTheme {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return {
    up: v("--up-mark"),
    down: v("--down-mark"),
    neutral: v("--neutral-mark"),
    series1: v("--series-1"),
    series1Soft: v("--series-1-soft"),
    grid: v("--grid"),
    axis: v("--axis"),
    ink: v("--ink"),
    ink2: v("--ink-2"),
    muted: v("--muted"),
    surface: v("--surface"),
    block: v("--block"),
    review: v("--review"),
    monitor: v("--monitor"),
    clear: v("--clear"),
  };
}

export function useChartTheme(): ChartTheme {
  const [t, setT] = useState<ChartTheme>(() => read());
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setT(read());
    mq.addEventListener("change", on);
    const obs = new MutationObserver(on);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      mq.removeEventListener("change", on);
      obs.disconnect();
    };
  }, []);
  return t;
}
