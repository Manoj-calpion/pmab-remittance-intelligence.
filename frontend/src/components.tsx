import { useEffect, useRef, useState, type ButtonHTMLAttributes, type MouseEvent, type ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";
import * as echarts from "echarts";
import { basisLabel } from "./format";
import { useTheme } from "./theme";

export function Panel({ title, action, children, className = "" }: { title?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl border border-line bg-panel p-5 ${className}`}>
      {title ? (
        <div className="mb-4 flex items-start justify-between gap-3">
          <h2 className="text-[11px] font-medium uppercase tracking-[0.22em] text-mist">{title}</h2>
          {action}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function Card(props: { title?: string; children: ReactNode; action?: ReactNode }) {
  return <Panel {...props} />;
}

export function PageHeader({ kicker, title, lede }: { kicker: string; title: string; lede?: string }) {
  return (
    <header className="max-w-3xl">
      <p className="text-[11px] uppercase tracking-[0.28em] text-faint">{kicker}</p>
      <h1 className="mt-3 font-display text-4xl leading-none text-foam md:text-6xl">{title}</h1>
      {lede ? <p className="mt-4 max-w-2xl text-sm leading-6 text-mist md:text-base">{lede}</p> : null}
    </header>
  );
}

export function Metric({ label, value, note, hint }: { label: string; value: ReactNode; note?: string; hint?: string }) {
  return (
    <div className="group h-full rounded-2xl border border-line bg-inset p-5 transition duration-300 hover:-translate-y-0.5 hover:border-foam/30" title={hint}>
      <div className="text-[11px] uppercase tracking-[0.18em] text-faint">{label}</div>
      <div className="mt-4 font-mono text-3xl tracking-tight text-foam">{value}</div>
      {note ? <div className="mt-3 text-xs leading-5 text-mist">{note}</div> : null}
    </div>
  );
}

export function Basis({ value }: { value?: string | null }) {
  const synthetic = value === "synthetic_demo" || value === "mixed";
  const missing = !value || value === "insufficient_data";
  const tone = synthetic ? "border-white/30 text-foam" : missing ? "border-line text-mist" : "border-foam/40 text-foam";
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] uppercase tracking-[0.14em] ${tone}`}>{basisLabel(value)}</span>;
}

export function StatusPill({ value }: { value: string }) {
  const attention = value === "QUARANTINED" || value === "FAILED" || value === "REQUIRES_REVIEW";
  return (
    <span className={`rounded-full border px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] ${attention ? "border-foam text-foam" : "border-line text-mist"}`}>
      {value}
    </span>
  );
}

export function Chart({ option, height = "h-72" }: { option: echarts.EChartsOption; height?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [option, theme]);
  return <div ref={ref} className={`${height} w-full`} />;
}

export function chartChrome(theme: "dark" | "light") {
  const text = theme === "dark" ? "#A3A3A3" : "#5c5c5c";
  const line = theme === "dark" ? "#262626" : "#e6e6e6";
  const ink = theme === "dark" ? "#ffffff" : "#101010";
  return {
    base: {
      backgroundColor: "transparent",
      textStyle: { color: text, fontFamily: "Inter, sans-serif" },
      tooltip: { backgroundColor: theme === "dark" ? "#151515" : "#fff", borderColor: line, textStyle: { color: ink } },
      legend: { textStyle: { color: text }, top: 0 },
      grid: { left: 48, right: 16, top: 36, bottom: 28 },
    },
    axis: {
      axisLine: { lineStyle: { color: line } },
      axisLabel: { color: text },
      splitLine: { lineStyle: { color: line } },
    },
  };
}

export function Notice({ children }: { children: ReactNode }) {
  return <p className="text-sm leading-6 text-mist">{children}</p>;
}

export function Table({ columns, rows }: { columns: string[]; rows: Array<Array<ReactNode>> }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-[10px] uppercase tracking-[0.16em] text-faint">
          <tr>
            {columns.map((column) => (
              <th key={column} className="border-b border-line px-2 py-3 font-medium">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className="px-2 py-6 text-mist" colSpan={columns.length}>
                No rows for this filter.
              </td>
            </tr>
          ) : (
            rows.map((row, index) => (
              <tr key={index} className="border-b border-line/80">
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className="px-2 py-3 align-top text-foam">
                    {cell}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-line px-6 py-16 text-center">
      <h2 className="font-display text-3xl text-foam">{title}</h2>
      <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-mist">{body}</p>
      {action ? <div className="mt-6">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return <p className="rounded-xl border border-line bg-inset px-4 py-3 text-sm text-foam">{message}</p>;
}

export function LoadingSkeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-live="polite">
      {Array.from({ length: lines }).map((_, index) => (
        <div key={index} className="h-16 animate-pulse rounded-2xl bg-inset" />
      ))}
    </div>
  );
}

export function QueryState({ loading, error, children }: { loading: boolean; error: unknown; children: ReactNode }) {
  if (loading) return <LoadingSkeleton />;
  if (error) return <ErrorState message={error instanceof Error ? error.message : "The request failed."} />;
  return <>{children}</>;
}

export function Reveal({ children, className = "" }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div className={className} initial={reduce ? false : { opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}>
      {children}
    </motion.div>
  );
}

export function PrimaryButton({ children, className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  const ref = useRef<HTMLButtonElement>(null);
  const reduce = useReducedMotion();
  return (
    <button
      ref={ref}
      {...props}
      className={`rounded-full bg-foam px-4 py-2 text-sm font-medium text-canvas transition hover:opacity-90 disabled:opacity-40 ${className}`}
      onMouseMove={(event) => {
        if (reduce || !ref.current) return;
        const rect = ref.current.getBoundingClientRect();
        const x = (event.clientX - rect.left - rect.width / 2) * 0.12;
        const y = (event.clientY - rect.top - rect.height / 2) * 0.2;
        ref.current.style.transform = `translate(${x}px, ${y}px)`;
      }}
      onMouseLeave={() => {
        if (ref.current) ref.current.style.transform = "";
      }}
    >
      {children}
    </button>
  );
}

export function GhostButton({ children, className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button {...props} className={`rounded-full border border-line px-4 py-2 text-sm text-foam transition hover:border-foam/40 ${className}`}>
      {children}
    </button>
  );
}

export function CountText({ value }: { value: string }) {
  const reduce = useReducedMotion();
  const numeric = Number(value.replace(/[^0-9.-]/g, ""));
  const prefix = value.trim().startsWith("$") ? "$" : "";
  const suffix = value.trim().endsWith("%") ? "%" : "";
  const [shown, setShown] = useState(reduce || Number.isNaN(numeric) ? value : `${prefix}0${suffix}`);
  useEffect(() => {
    if (reduce || Number.isNaN(numeric)) {
      setShown(value);
      return;
    }
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / 700);
      const current = numeric * (1 - Math.pow(1 - progress, 3));
      const formatted = prefix
        ? current.toLocaleString("en-US", { style: "currency", currency: "USD" })
        : suffix
          ? `${current.toFixed(1)}%`
          : Math.round(current).toLocaleString("en-US");
      setShown(formatted);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [numeric, prefix, reduce, suffix, value]);
  return <>{shown}</>;
}

export function moveGlow(event: MouseEvent<HTMLElement>) {
  const node = event.currentTarget.querySelector("[data-glow]") as HTMLElement | null;
  if (!node) return;
  const rect = event.currentTarget.getBoundingClientRect();
  node.style.transform = `translate(${event.clientX - rect.left - 120}px, ${event.clientY - rect.top - 120}px)`;
}

export function HeroField() {
  const reduce = useReducedMotion();
  if (reduce) return null;
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div data-glow className="absolute h-60 w-60 rounded-full bg-white/5 blur-2xl" />
    </div>
  );
}
