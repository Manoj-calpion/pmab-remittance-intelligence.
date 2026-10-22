import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { EChartsOption } from "echarts";
import { Basis, Chart, CountText, EmptyState, HeroField, Metric, Notice, PageHeader, Panel, QueryState, Table, chartChrome, moveGlow } from "../components";
import { Carousel, Slide } from "../carousel";
import { formatMoney, formatRate } from "../format";
import { useResource } from "../hooks";
import { useTheme } from "../theme";

type Overview = {
  demo_mode: boolean;
  as_of?: string;
  total_remittances: number;
  claims_analyzed: number;
  total_paid: string | null;
  payers_analyzed: number;
  denial_rate: string | null;
  denied_amount: string | null;
  potential_underpayments: string | null;
  underpayment_basis: string;
  underpayment_notice: string;
  delayed_payments: number | null;
  delay_basis: string;
  delay_notice: string;
  high_priority_alerts: number;
  anomaly_count: number;
  payment_trend: Array<{ month: string; paid_amount: string | null; denied_amount: string | null; claims: number }>;
  ai_insights: Array<{ id: string; summary: string; provider_name: string; insufficient_evidence: boolean }>;
};

type Denials = {
  definition?: string;
  claim_level: { claims: number; denied_claims: number; denial_rate: string | null; denied_amount: string | null };
  by_category?: Array<{ label: string; denied_claims: number; denied_amount: string; denial_rate: string | null }>;
  by_carc: Array<{ label: string; denied_claims: number; denied_amount: string }>;
  by_payer: Array<{ label: string; claims: number; denial_rate: string | null; denied_amount: string }>;
  trend: Array<{ month: string; payer: string; denial_rate: string | null; denied_amount: string; claims?: number }>;
  by_procedure: Array<{ procedure_code: string; denied_lines: number; denial_rate: string | null; denied_amount: string }>;
};

const agents = [
  ["Denial", "Patterns, classification, and financial impact from mapped adjustments."],
  ["Payment", "Delays and reimbursement gaps only where dates or contracts exist."],
  ["Payer", "Behavior over time, with low-volume payers kept visible and cautious."],
  ["Root cause", "What the evidence supports, and which reference data is still missing."],
  ["Insight", "Readable summaries of tool output. The model does not invent amounts."],
];

export function OverviewPage() {
  const { theme } = useTheme();
  const query = useResource<Overview>("/api/v1/analytics/overview");
  const denials = useResource<Denials>("/api/v1/analytics/denials");
  const payers = useResource<{ payers: Array<{ label: string; claims: number; denial_rate: string | null; denied_amount: string; low_volume?: boolean }> }>("/api/v1/analytics/payers");
  const chrome = useMemo(() => chartChrome(theme), [theme]);

  const paymentOption = useMemo<EChartsOption>(() => {
    const rows = query.data?.payment_trend ?? [];
    return {
      ...chrome.base,
      tooltip: { ...chrome.base.tooltip, trigger: "axis" },
      xAxis: { type: "category", data: rows.map((row) => row.month), ...chrome.axis },
      yAxis: { type: "value", ...chrome.axis },
      series: [
        { name: "Paid", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => Number(row.paid_amount || 0)), lineStyle: { color: theme === "dark" ? "#fff" : "#101010", width: 1.5 } },
        { name: "Denied", type: "bar", data: rows.map((row) => Number(row.denied_amount || 0)), itemStyle: { color: theme === "dark" ? "#3a3a3a" : "#d4d4d4" } },
      ],
    };
  }, [chrome, query.data?.payment_trend, theme]);

  const categoryOption = useMemo<EChartsOption>(() => {
    const rows = denials.data?.by_category ?? [];
    return {
      ...chrome.base,
      tooltip: { ...chrome.base.tooltip, trigger: "item" },
      series: [{
        type: "pie",
        radius: ["58%", "78%"],
        label: { color: theme === "dark" ? "#A3A3A3" : "#5c5c5c" },
        data: rows.map((row, index) => ({
          name: row.label,
          value: Number(row.denied_amount),
          itemStyle: { color: theme === "dark" ? `rgba(255,255,255,${Math.max(0.25, 0.95 - index * 0.12)})` : `rgba(16,16,16,${Math.max(0.25, 0.9 - index * 0.1)})` },
        })),
      }],
    };
  }, [chrome, denials.data?.by_category, theme]);

  if (query.isLoading || query.error || !query.data) return <QueryState loading={query.isLoading} error={query.error}> </QueryState>;
  const data = query.data;
  if (data.total_remittances === 0) {
    return (
      <div className="space-y-8">
        <Hero />
        <EmptyState title="No remittances yet." body="Upload a downloaded 835 file. Metrics stay empty until the parser stores claims." action={<Link className="rounded-full bg-foam px-4 py-2 text-sm text-canvas" to="/processing">Open ingestion</Link>} />
      </div>
    );
  }

  const kpis = [
    { label: "Remittances", value: String(data.total_remittances), note: "Stored files, including quarantined originals.", href: "/remittances", animate: true },
    { label: "Claims", value: String(data.claims_analyzed), note: "Reversals are excluded from the denial rate.", href: "/denials", animate: true },
    { label: "Paid", value: formatMoney(data.total_paid), note: "Sum of claim payment amounts.", href: "/payments", animate: false },
    { label: "Denial rate", value: formatRate(data.denial_rate), note: "Denied claims divided by analyzed claims.", href: "/denials", animate: false },
    { label: "Denied", value: formatMoney(data.denied_amount), note: "Mapped denial adjustments only.", href: "/denials", animate: false },
    { label: "Underpayment", value: data.underpayment_basis === "insufficient_data" ? "Insufficient data" : formatMoney(data.potential_underpayments), note: data.underpayment_notice, href: "/payments", animate: false },
    { label: "Delayed", value: data.delayed_payments === null ? "Insufficient data" : String(data.delayed_payments), note: data.delay_notice, href: "/payments", animate: false },
    { label: "Payers", value: String(data.payers_analyzed), note: `${data.anomaly_count} statistical anomalies · ${data.high_priority_alerts} high alerts.`, href: "/payers", animate: true },
  ];

  const findings = [
    ...data.ai_insights.map((item) => ({
      id: item.id,
      title: item.provider_name,
      body: item.summary,
      note: item.insufficient_evidence ? "Insufficient evidence" : "Completed investigation",
    })),
    ...(denials.data?.by_category || []).slice(0, 3).map((row) => ({
      id: row.label,
      title: "Calculated finding",
      body: `${row.label}: ${row.denied_claims} denied claims, ${formatMoney(row.denied_amount)}.`,
      note: "Denial engine",
    })),
  ];

  return (
    <div className="space-y-8">
      <Hero asOf={data.as_of} />
      <div className="flex flex-wrap items-center gap-3 text-[11px] uppercase tracking-[0.14em] text-faint">
        <span className="inline-flex items-center gap-2">Underpayment <Basis value={data.underpayment_basis} /></span>
        <span className="inline-flex items-center gap-2">Delays <Basis value={data.delay_basis} /></span>
        {data.demo_mode ? <span className="inline-flex items-center gap-2">Corpus <Basis value="synthetic_demo" /></span> : null}
      </div>
      <Carousel label="Executive measures">
        {kpis.map((item) => (
          <Slide key={item.label}>
            <Link to={item.href} className="block h-full" title={item.note}>
              <Metric label={item.label} value={item.animate && item.value !== "—" ? <CountText value={item.value} /> : item.value} note={item.note} hint={item.note} />
            </Link>
          </Slide>
        ))}
      </Carousel>
      <div className="grid gap-4 xl:grid-cols-5">
        <Panel title="Payment and denial trend" className="xl:col-span-3">
          {data.payment_trend.length === 0 ? <Notice>No payment dates are available for a trend.</Notice> : <Chart option={paymentOption} />}
        </Panel>
        <Panel title="Denial categories" className="xl:col-span-2">
          {(denials.data?.by_category?.length ?? 0) === 0 ? <Notice>No denial categories in this period.</Notice> : <Chart option={categoryOption} />}
        </Panel>
      </div>
      <Panel title="Payer comparison">
        <Table columns={["Payer", "Claims", "Denial rate", "Denied", "Volume"]} rows={(payers.data?.payers || []).map((row) => [row.label, row.claims, formatRate(row.denial_rate), formatMoney(row.denied_amount), row.low_volume ? "Low volume" : "Comparable"])} />
      </Panel>
      <Carousel label="Evidence">
        {findings.length === 0 ? (
          <Slide><Panel><Notice>No findings yet.</Notice></Panel></Slide>
        ) : findings.map((item) => (
          <Slide key={item.id}>
            <article className="h-full rounded-2xl border border-line bg-panel p-5">
              <p className="text-[11px] uppercase tracking-[0.18em] text-faint">{item.title}</p>
              <p className="mt-4 text-sm leading-6">{item.body}</p>
              <p className="mt-4 font-mono text-[11px] text-mist">{item.note}</p>
            </article>
          </Slide>
        ))}
      </Carousel>
      <Carousel label="Agents">
        {agents.map(([name, copy]) => (
          <Slide key={name}>
            <Link to="/investigate" className="block h-full rounded-2xl border border-line bg-inset p-5">
              <p className="font-display text-3xl">{name}</p>
              <p className="mt-3 text-sm leading-6 text-mist">{copy}</p>
            </Link>
          </Slide>
        ))}
      </Carousel>
    </div>
  );
}

function Hero({ asOf }: { asOf?: string }) {
  return (
    <section className="relative overflow-hidden" onMouseMove={moveGlow}>
      <HeroField />
      <PageHeader kicker="PMAB Intelligence · Remittance Intelligence System" title="Every remittance tells a story." lede="Turn payment data into financial intelligence." />
      {asOf ? <p className="relative mt-4 font-mono text-[11px] text-faint">As of {asOf}</p> : null}
    </section>
  );
}

export function DenialsPage() {
  const [tab, setTab] = useState<"all" | "authorization" | "coding">("all");
  const path = tab === "all" ? "/api/v1/analytics/denials" : `/api/v1/analytics/${tab}`;
  const query = useResource<Denials>(path);
  const claims = useResource<{ items: Array<{ id: string; patient_control_number: string; payer: string | null; primary_denial_category: string | null; primary_carc: string | null; denied_amount: string; denial_scope: string | null }> }>(
    `/api/v1/claims?page_size=25${tab === "all" ? "" : `&denial_category=${tab}`}`,
  );
  const { theme } = useTheme();
  const chrome = useMemo(() => chartChrome(theme), [theme]);
  const option = useMemo<EChartsOption>(() => {
    const months = [...new Set((query.data?.trend || []).map((row) => row.month))];
    const names = [...new Set((query.data?.trend || []).map((row) => row.payer))];
    return {
      ...chrome.base,
      tooltip: { ...chrome.base.tooltip, trigger: "axis" },
      xAxis: { type: "category", data: months, ...chrome.axis },
      yAxis: { type: "value", ...chrome.axis, axisLabel: { ...chrome.axis.axisLabel, formatter: (value: number) => `${(value * 100).toFixed(0)}%` } },
      series: names.map((payer, index) => ({
        name: payer,
        type: "line",
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, color: theme === "dark" ? `rgba(255,255,255,${Math.max(0.35, 1 - index * 0.18)})` : `rgba(16,16,16,${Math.max(0.35, 1 - index * 0.18)})` },
        data: months.map((month) => {
          const row = query.data?.trend.find((item) => item.month === month && item.payer === payer);
          return row?.denial_rate ? Number(row.denial_rate) : null;
        }),
      })),
    };
  }, [chrome, query.data?.trend, theme]);

  return (
    <div className="space-y-6">
      <PageHeader kicker="Denial intelligence" title="What was refused, and why." lede="Contractual adjustments and patient responsibility stay out of the denial rate." />
      <div className="flex flex-wrap gap-2">
        {(["all", "authorization", "coding"] as const).map((item) => (
          <button key={item} className={`rounded-full border px-4 py-2 text-sm capitalize ${tab === item ? "border-foam bg-foam text-canvas" : "border-line text-mist"}`} onClick={() => setTab(item)}>
            {item}
          </button>
        ))}
      </div>
      <QueryState loading={query.isLoading} error={query.error}>
        {query.data ? (
          <>
            <Notice>
              {query.data.definition || "Filtered to the selected denial category."} Rate {formatRate(query.data.claim_level.denial_rate)} across {query.data.claim_level.claims} claims. Denied {formatMoney(query.data.claim_level.denied_amount)}.
            </Notice>
            <Panel title="Denial rate by payer">
              {query.data.trend.length === 0 ? <Notice>No payment-dated trend is available.</Notice> : <Chart option={option} />}
            </Panel>
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Categories">
                <Table columns={["Category", "Claims", "Rate", "Amount"]} rows={(query.data.by_category || query.data.by_payer).map((row) => [row.label, "denied_claims" in row ? row.denied_claims : row.claims, formatRate(row.denial_rate), formatMoney(row.denied_amount)])} />
              </Panel>
              <Panel title="CARC">
                <Table columns={["Code", "Claims", "Amount"]} rows={query.data.by_carc.map((row) => [row.label, row.denied_claims, formatMoney(row.denied_amount)])} />
              </Panel>
            </div>
            <Panel title="Procedure codes">
              <Table columns={["Procedure", "Denied lines", "Rate", "Amount"]} rows={query.data.by_procedure.map((row) => [row.procedure_code, row.denied_lines, formatRate(row.denial_rate), formatMoney(row.denied_amount)])} />
            </Panel>
            <Panel title="Claim evidence">
              <Table
                columns={["Control", "Payer", "Category", "CARC", "Scope", "Denied"]}
                rows={(claims.data?.items || []).map((item) => [item.patient_control_number, item.payer || "—", item.primary_denial_category || "—", item.primary_carc || "—", item.denial_scope || "—", formatMoney(item.denied_amount)])}
              />
            </Panel>
          </>
        ) : null}
      </QueryState>
    </div>
  );
}
