import { Basis, Card, Chart, Metric, Notice, Table } from "../components";
import { formatMoney, formatRate } from "../format";
import { useResource } from "../hooks";

type Overview = {
  demo_mode: boolean;
  total_remittances: number;
  claims_analyzed: number;
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
  ai_insights: Array<{ id: string; summary: string; provider_name: string; insufficient_evidence: boolean }>;
};

export function OverviewPage() {
  const query = useResource<Overview>("/api/v1/analytics/overview");
  if (query.isLoading) return <p>Loading calculated metrics…</p>;
  if (query.error) return <p>{(query.error as Error).message}</p>;
  const data = query.data!;
  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold">Executive overview</h1>
        <p className="text-sm text-mist">Figures come from the remittance database. Empty values mean the calculation was not available.</p>
      </header>
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Remittance files" value={String(data.total_remittances)} />
        <Metric label="Claims analyzed" value={String(data.claims_analyzed)} />
        <Metric label="Denial rate" value={formatRate(data.denial_rate)} />
        <Metric label="Denied amount" value={formatMoney(data.denied_amount)} />
        <Metric label="Potential underpayments" value={formatMoney(data.potential_underpayments)} note={data.underpayment_basis === "insufficient_data" ? "Insufficient contract data" : undefined} />
        <Metric label="Delayed payments" value={data.delayed_payments === null ? "—" : String(data.delayed_payments)} />
        <Metric label="High-priority alerts" value={String(data.high_priority_alerts)} />
        <Metric label="Statistical anomalies" value={String(data.anomaly_count)} note="Not confirmed payment errors" />
      </div>
      <div className="flex flex-wrap gap-2">
        <Basis value={data.underpayment_basis} />
        <Basis value={data.delay_basis} />
      </div>
      <Card title="How these amounts were qualified">
        <Notice>{data.underpayment_notice} {data.delay_notice}</Notice>
      </Card>
      <Card title="Latest AI insight">
        {data.ai_insights.length === 0 ? <Notice>No investigation has been run yet.</Notice> : data.ai_insights.map((item) => (
          <p key={item.id} className="text-sm leading-6">{item.summary} <span className="text-mist">({item.provider_name}{item.insufficient_evidence ? ", insufficient evidence" : ""})</span></p>
        ))}
      </Card>
    </div>
  );
}

type Denials = {
  definition: string;
  claim_level: { claims: number; denied_claims: number; denial_rate: string | null; denied_amount: string | null };
  by_category: Array<{ label: string; denied_claims: number; denied_amount: string; denial_rate: string | null }>;
  by_carc: Array<{ label: string; denied_claims: number; denied_amount: string }>;
  by_payer: Array<{ label: string; claims: number; denial_rate: string | null; denied_amount: string }>;
  trend: Array<{ month: string; payer: string; denial_rate: string | null; denied_amount: string }>;
  by_procedure: Array<{ procedure_code: string; denied_lines: number; denial_rate: string | null; denied_amount: string }>;
};

export function DenialsPage() {
  const query = useResource<Denials>("/api/v1/analytics/denials");
  if (!query.data) return <p>{query.isLoading ? "Loading denials…" : (query.error as Error)?.message}</p>;
  const data = query.data;
  const months = [...new Set(data.trend.map((row) => row.month))];
  const payers = [...new Set(data.trend.map((row) => row.payer))];
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Denial intelligence</h1>
      <Notice>{data.definition} Claim denial rate {formatRate(data.claim_level.denial_rate)} on {data.claim_level.claims} claims. Denied amount {formatMoney(data.claim_level.denied_amount)}.</Notice>
      <Card title="Monthly denial rate">
        <Chart option={{
          backgroundColor: "transparent",
          textStyle: { color: "#93a7c2" },
          tooltip: { trigger: "axis" },
          legend: { textStyle: { color: "#e7eef8" } },
          xAxis: { type: "category", data: months },
          yAxis: { type: "value", axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(0)}%` } },
          series: payers.map((payer) => ({
            name: payer,
            type: "line",
            smooth: true,
            data: months.map((month) => {
              const row = data.trend.find((item) => item.month === month && item.payer === payer);
              return row?.denial_rate ? Number(row.denial_rate) : 0;
            }),
          })),
        }} />
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Top denial categories">
          <Table columns={["Category", "Denied claims", "Amount"]} rows={data.by_category.map((row) => [row.label, row.denied_claims, formatMoney(row.denied_amount)])} />
        </Card>
        <Card title="CARC codes">
          <Table columns={["CARC", "Denied claims", "Amount"]} rows={data.by_carc.map((row) => [row.label, row.denied_claims, formatMoney(row.denied_amount)])} />
        </Card>
      </div>
      <Card title="Procedure codes">
        <Table columns={["Procedure", "Denied lines", "Rate", "Amount"]} rows={data.by_procedure.map((row) => [row.procedure_code, row.denied_lines, formatRate(row.denial_rate), formatMoney(row.denied_amount)])} />
      </Card>
    </div>
  );
}
