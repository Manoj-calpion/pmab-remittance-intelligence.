import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { Basis, Chart, Notice, PageHeader, Panel, QueryState, Table, chartChrome } from "../components";
import { Carousel, Slide } from "../carousel";
import { formatMoney, formatRate } from "../format";
import { useResource } from "../hooks";
import { useTheme } from "../theme";

type Delays = {
  metric_basis: string;
  notice: string;
  threshold_days: number;
  delayed_count: number | null;
  insufficient_data_count: number;
  items: Array<{ patient_control_number: string; payer: string | null; delay_days: number | null; delayed: boolean; metric_basis: string; reason: string }>;
};

type Underpayments = {
  metric_basis: string;
  notice: string;
  underpaid_count: number;
  underpaid_amount: string | null;
  insufficient_data_count: number;
  items: Array<{ patient_control_number: string; payer: string | null; procedure_code: string | null; expected_amount: string | null; actual_amount: string | null; variance: string | null; metric_basis: string; status?: string; trace: string[] }>;
};

export function PaymentsPage() {
  const delays = useResource<Delays>("/api/v1/analytics/payment-delays");
  const under = useResource<Underpayments>("/api/v1/analytics/underpayments");
  const ready = delays.data && under.data;
  return (
    <div className="space-y-6">
      <PageHeader kicker="Payment intelligence" title="Late, short, or simply unknown." lede="A service date is never treated as a submission date. A missing contract stays missing." />
      <QueryState loading={delays.isLoading || under.isLoading} error={delays.error || under.error}>
        {ready ? (
          <>
            <div className="flex flex-wrap gap-2">
              <Basis value={delays.data!.metric_basis} />
              <Basis value={under.data!.metric_basis} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title={`Delays · threshold ${delays.data!.threshold_days} days`}>
                <Notice>{delays.data!.notice} Delayed {delays.data!.delayed_count ?? "—"}. Missing submission or acceptance dates: {delays.data!.insufficient_data_count}.</Notice>
                <Table columns={["Control", "Payer", "Days", "Basis", "Evidence"]} rows={delays.data!.items.filter((item) => item.delayed).map((item) => [item.patient_control_number, item.payer, item.delay_days ?? "—", item.metric_basis, item.reason])} />
              </Panel>
              <Panel title="Underpayment">
                <Notice>{under.data!.notice} Confirmed or potential rows {under.data!.underpaid_count}. Exposure {formatMoney(under.data!.underpaid_amount)}. Lines without a rule: {under.data!.insufficient_data_count}.</Notice>
                <Table
                  columns={["Control", "Procedure", "Expected", "Actual", "Variance", "Basis"]}
                  rows={under.data!.items.slice(0, 40).map((item) => [item.patient_control_number, item.procedure_code, formatMoney(item.expected_amount), formatMoney(item.actual_amount), formatMoney(item.variance), item.metric_basis])}
                />
              </Panel>
            </div>
            <Panel title="Calculation evidence">
              <Table columns={["Control", "Trace"]} rows={under.data!.items.filter((item) => item.trace?.length).slice(0, 12).map((item) => [item.patient_control_number, item.trace.join(" · ")])} />
            </Panel>
          </>
        ) : null}
      </QueryState>
    </div>
  );
}

type Payers = {
  payers: Array<{ label: string; claims: number; denial_rate: string | null; denied_amount: string; delayed_payments: number | null; underpayment_amount: string | null; low_volume?: boolean }>;
  delay_basis: string;
  underpayment_basis: string;
  trend: Array<{ month: string; payer: string; denial_rate: string | null; denied_amount: string }>;
  movement?: Array<{ payer: string; month: string; previous_month: string | null; denial_rate: string | null; denial_rate_change: string | null; claims: number; note: string }>;
  low_volume_minimum_claims?: number;
};

type Anomalies = {
  notice: string;
  count: number;
  items: Array<{ entity_label: string; severity: string; method: string; explanation: string; is_financial_error: boolean }>;
};

export function PayersPage() {
  const query = useResource<Payers>("/api/v1/analytics/payers");
  const anomalies = useResource<Anomalies>("/api/v1/analytics/anomalies");
  const { theme } = useTheme();
  const chrome = useMemo(() => chartChrome(theme), [theme]);
  const option = useMemo<EChartsOption>(() => {
    const months = [...new Set((query.data?.trend || []).map((row) => row.month))];
    const names = [...new Set((query.data?.trend || []).map((row) => row.payer))];
    return {
      ...chrome.base,
      tooltip: { ...chrome.base.tooltip, trigger: "axis" },
      xAxis: { type: "category", data: months, ...chrome.axis },
      yAxis: { type: "value", ...chrome.axis },
      series: names.map((payer) => ({
        name: payer,
        type: "line",
        smooth: true,
        showSymbol: false,
        data: months.map((month) => {
          const row = query.data?.trend.find((item) => item.month === month && item.payer === payer);
          return row?.denied_amount ? Number(row.denied_amount) : 0;
        }),
      })),
    };
  }, [chrome, query.data?.trend]);

  return (
    <div className="space-y-6">
      <PageHeader kicker="Payer intelligence" title="Behavior, not a verdict." lede="Low-volume payers stay on the page. Their rates are not treated as a stable pattern." />
      <QueryState loading={query.isLoading} error={query.error}>
        {query.data ? (
          <>
            <div className="flex flex-wrap gap-2">
              <Basis value={query.data.delay_basis} />
              <Basis value={query.data.underpayment_basis} />
            </div>
            <Carousel label="Payer scorecards">
              {query.data.payers.length === 0 ? (
                <Slide><Panel><Notice>No payers have been analyzed.</Notice></Panel></Slide>
              ) : query.data.payers.map((row) => (
                <Slide key={row.label}>
                  <article className="h-full rounded-2xl border border-line bg-panel p-5">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-faint">{row.low_volume ? "Low volume" : "Scorecard"}</p>
                    <h2 className="mt-3 font-display text-3xl">{row.label}</h2>
                    <p className="mt-4 font-mono text-2xl">{formatRate(row.denial_rate)}</p>
                    <p className="mt-2 text-sm text-mist">{row.claims} claims · denied {formatMoney(row.denied_amount)}</p>
                    <p className="mt-2 text-xs text-faint">Delays {row.delayed_payments ?? "Insufficient data"} · Underpayment {formatMoney(row.underpayment_amount)}</p>
                  </article>
                </Slide>
              ))}
            </Carousel>
            <Panel title="Denied amount by month">
              {query.data.trend.length === 0 ? <Notice>Not enough payment dates to draw a trend.</Notice> : <Chart option={option} />}
            </Panel>
            <Panel title="Month-over-month">
              <Table
                columns={["Payer", "Month", "Prior", "Rate", "Change", "Note"]}
                rows={(query.data.movement || []).map((row) => [row.payer, row.month, row.previous_month || "—", formatRate(row.denial_rate), row.denial_rate_change ? formatRate(row.denial_rate_change) : "—", row.note])}
              />
            </Panel>
            <Panel title="Statistical anomalies">
              <Notice>{anomalies.data?.notice || "Loading anomaly status…"} These are leads. They are not confirmed payment errors.</Notice>
              <Table columns={["Entity", "Severity", "Method", "Finding", "Financial error"]} rows={(anomalies.data?.items || []).map((item) => [item.entity_label, item.severity, item.method, item.explanation, item.is_financial_error ? "Yes" : "No — statistical only"])} />
            </Panel>
          </>
        ) : null}
      </QueryState>
    </div>
  );
}

export function SlicePage({ category, title }: { category: string; title: string }) {
  const query = useResource<{
    claim_level: { denied_claims: number; denied_amount: string | null; denial_rate: string | null; claims: number };
    by_payer: Array<{ label: string; denied_claims: number; denied_amount: string }>;
    by_procedure: Array<{ procedure_code: string; denied_lines: number; denied_amount: string }>;
    by_carc: Array<{ label: string; denied_claims: number }>;
  }>(`/api/v1/analytics/${category}`);
  return (
    <div className="space-y-6">
      <PageHeader kicker={category} title={title} lede="Mapped from approved CARC categories. A code correlation is not a confirmed root cause." />
      <QueryState loading={query.isLoading} error={query.error}>
        {query.data ? (
          <>
            <Notice>{query.data.claim_level.denied_claims} denied claims of {query.data.claim_level.claims}. Amount {formatMoney(query.data.claim_level.denied_amount)}. Rate {formatRate(query.data.claim_level.denial_rate)}.</Notice>
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Payers"><Table columns={["Payer", "Claims", "Amount"]} rows={query.data.by_payer.map((row) => [row.label, row.denied_claims, formatMoney(row.denied_amount)])} /></Panel>
              <Panel title="Procedures"><Table columns={["Procedure", "Lines", "Amount"]} rows={query.data.by_procedure.map((row) => [row.procedure_code, row.denied_lines, formatMoney(row.denied_amount)])} /></Panel>
            </div>
          </>
        ) : null}
      </QueryState>
    </div>
  );
}
