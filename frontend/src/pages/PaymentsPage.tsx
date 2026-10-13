import { Basis, Card, Notice, Table } from "../components";
import { formatMoney } from "../format";
import { useResource } from "../hooks";

type Delays = {
  metric_basis: string;
  notice: string;
  threshold_days: number;
  delayed_count: number | null;
  insufficient_data_count: number;
  items: Array<{ patient_control_number: string; payer: string | null; delay_days: number; delayed: boolean; metric_basis: string; reason: string }>;
};

type Underpayments = {
  metric_basis: string;
  notice: string;
  underpaid_count: number;
  underpaid_amount: string | null;
  insufficient_data_count: number;
  items: Array<{ patient_control_number: string; payer: string | null; procedure_code: string | null; expected_amount: string | null; actual_amount: string | null; variance: string | null; metric_basis: string; trace: string[] }>;
};

export function PaymentsPage() {
  const delays = useResource<Delays>("/api/v1/analytics/payment-delays");
  const under = useResource<Underpayments>("/api/v1/analytics/underpayments");
  if (!delays.data || !under.data) return <p>Loading payment intelligence…</p>;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Payment intelligence</h1>
      <div className="flex flex-wrap gap-2">
        <Basis value={delays.data.metric_basis} />
        <Basis value={under.data.metric_basis} />
      </div>
      <Card title={`Payment delays over ${delays.data.threshold_days} days`}>
        <Notice>{delays.data.notice} Delayed count: {delays.data.delayed_count ?? "—"}. Claims without a usable submission date: {delays.data.insufficient_data_count}.</Notice>
        <Table columns={["Claim control", "Payer", "Days", "Basis", "Trace"]} rows={delays.data.items.filter((item) => item.delayed).map((item) => [item.patient_control_number, item.payer, item.delay_days, item.metric_basis, item.reason])} />
      </Card>
      <Card title="Underpayments">
        <Notice>{under.data.notice} Count {under.data.underpaid_count}. Exposure {formatMoney(under.data.underpaid_amount)}. Lines without a usable rule: {under.data.insufficient_data_count}.</Notice>
        <Table
          columns={["Claim control", "Payer", "Procedure", "Expected", "Actual", "Variance", "Basis"]}
          rows={under.data.items.map((item) => [item.patient_control_number, item.payer, item.procedure_code, formatMoney(item.expected_amount), formatMoney(item.actual_amount), formatMoney(item.variance), item.metric_basis])}
        />
      </Card>
    </div>
  );
}

type Payers = {
  payers: Array<{ label: string; claims: number; denial_rate: string | null; denied_amount: string; delayed_payments: number | null; underpayment_amount: string | null }>;
  delay_basis: string;
  underpayment_basis: string;
};

export function PayersPage() {
  const query = useResource<Payers>("/api/v1/analytics/payers");
  if (!query.data) return <p>Loading payer intelligence…</p>;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Payer intelligence</h1>
      <div className="flex gap-2"><Basis value={query.data.delay_basis} /><Basis value={query.data.underpayment_basis} /></div>
      <Card title="Payer performance">
        <Table
          columns={["Payer", "Claims", "Denial rate", "Denied amount", "Delayed payments", "Underpayment"]}
          rows={query.data.payers.map((row) => [row.label, row.claims, row.denial_rate ? `${(Number(row.denial_rate) * 100).toFixed(1)}%` : "—", formatMoney(row.denied_amount), row.delayed_payments ?? "—", formatMoney(row.underpayment_amount)])}
        />
      </Card>
    </div>
  );
}

export function SlicePage({ category, title }: { category: string; title: string }) {
  const query = useResource<{
    claim_level: { denied_claims: number; denied_amount: string | null; denial_rate: string | null };
    by_payer: Array<{ label: string; denied_claims: number; denied_amount: string }>;
    by_procedure: Array<{ procedure_code: string; denied_lines: number; denied_amount: string }>;
    by_carc: Array<{ label: string; denied_claims: number }>;
  }>(`/api/v1/analytics/${category}`);
  if (!query.data) return <p>Loading {title.toLowerCase()}…</p>;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <Notice>Denied claims {query.data.claim_level.denied_claims}. Amount {formatMoney(query.data.claim_level.denied_amount)}.</Notice>
      <Card title="Payers">
        <Table columns={["Payer", "Denied claims", "Amount"]} rows={query.data.by_payer.map((row) => [row.label, row.denied_claims, formatMoney(row.denied_amount)])} />
      </Card>
      <Card title="Procedures and CARC">
        <Table columns={["Procedure", "Denied lines", "Amount"]} rows={query.data.by_procedure.map((row) => [row.procedure_code, row.denied_lines, formatMoney(row.denied_amount)])} />
        <Table columns={["CARC", "Denied claims"]} rows={query.data.by_carc.map((row) => [row.label, row.denied_claims])} />
      </Card>
    </div>
  );
}
