import { useEffect, useRef, type ReactNode } from "react";
import * as echarts from "echarts";
import { basisLabel } from "./format";

export function Card({ title, children, action }: { title?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-panel p-4 shadow-sm">
      {title ? (
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold tracking-wide text-mist">{title}</h2>
          {action}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border border-line bg-[#0c1a2c] p-4">
      <div className="text-xs uppercase tracking-[0.14em] text-mist">{label}</div>
      <div className="mt-2 font-mono text-2xl text-foam">{value}</div>
      {note ? <div className="mt-2 text-xs text-teal">{note}</div> : null}
    </div>
  );
}

export function Basis({ value }: { value?: string | null }) {
  const synthetic = value === "synthetic_demo" || value === "mixed";
  return (
    <span className={`rounded-full px-2 py-1 text-xs ${synthetic ? "bg-amber-500/15 text-amber-200" : "bg-teal/15 text-teal"}`}>
      {basisLabel(value)}
    </span>
  );
}

export function Chart({ option }: { option: echarts.EChartsOption }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [option]);
  return <div ref={ref} className="h-72 w-full" />;
}

export function Notice({ children }: { children: ReactNode }) {
  return <p className="text-sm leading-6 text-mist">{children}</p>;
}

export function Table({ columns, rows }: { columns: string[]; rows: Array<Array<ReactNode>> }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-mist">
          <tr>{columns.map((column) => <th key={column} className="border-b border-line px-2 py-2 font-medium">{column}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td className="px-2 py-4 text-mist" colSpan={columns.length}>No rows for this filter.</td></tr>
          ) : rows.map((row, index) => (
            <tr key={index} className="border-b border-line/70">
              {row.map((cell, cellIndex) => <td key={cellIndex} className="px-2 py-2 align-top">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
