import { FormEvent, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, downloadReport } from "../api";
import { Card, Notice, Table } from "../components";
import { useResource } from "../hooks";

const questions = [
  "Which payer has the highest denial rate?",
  "Why are authorization denials increasing?",
  "Which procedure codes have recurring denials?",
  "Which underpayment patterns have the highest financial impact?",
];

type Investigation = {
  investigation_id: string;
  status: string;
  provider_name: string;
  model_id: string;
  summary: string;
  recommendations: string[];
  missing_evidence: string[];
  citations: string[];
  disclaimer: string;
  needs_human_review: boolean;
  insufficient_evidence: boolean;
  llm_error: string | null;
  agent_outputs: Array<{ agent: string; summary: string }>;
};

export function InvestigatePage({ provider }: { provider?: string }) {
  const [result, setResult] = useState<Investigation | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function ask(question: string) {
    setPending(true);
    setError("");
    try {
      setResult(await api<Investigation>("/api/v1/ai/ask", { method: "POST", body: JSON.stringify({ question }) }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Investigation failed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">AI investigation</h1>
      <Notice>Provider: {provider || "loading"}. The model narrates tool output. It does not calculate reimbursement. Questions are treated as data, not instructions.</Notice>
      <div className="flex flex-wrap gap-2">
        {questions.map((question) => (
          <button key={question} className="rounded-full border border-line px-3 py-1 text-left text-sm hover:border-teal" onClick={() => ask(question)}>{question}</button>
        ))}
      </div>
      <form className="flex gap-2" onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); ask(String(new FormData(event.currentTarget).get("question") || "")); }}>
        <input name="question" className="flex-1 rounded-lg border border-line bg-ink px-3 py-2" placeholder="Ask about denials, payers, delays, or underpayments" />
        <button className="rounded-lg bg-teal px-4 py-2 font-semibold text-ink" disabled={pending}>{pending ? "Running" : "Ask"}</button>
      </form>
      {error ? <p className="text-sm text-red-300">{error}</p> : null}
      {result ? (
        <Card title={`Result · ${result.provider_name} · ${result.status}`}>
          <p className="text-sm leading-6">{result.summary}</p>
          <div className="mt-3 text-xs text-mist">{result.disclaimer} {result.insufficient_evidence ? "Evidence was marked insufficient." : ""} {result.needs_human_review ? "Human review is required before this is treated as final." : ""}</div>
          {result.llm_error ? <p className="mt-2 text-sm text-red-300">{result.llm_error}</p> : null}
          <h3 className="mt-4 text-sm font-semibold">Agent trace</h3>
          <ul className="mt-2 space-y-2 text-sm text-mist">{result.agent_outputs.map((item) => <li key={item.agent}><span className="text-teal">{item.agent}</span> — {item.summary}</li>)}</ul>
          <h3 className="mt-4 text-sm font-semibold">Next steps</h3>
          <ul className="list-disc pl-5 text-sm">{result.recommendations.map((item) => <li key={item}>{item}</li>)}</ul>
          <h3 className="mt-4 text-sm font-semibold">Missing evidence</h3>
          <ul className="list-disc pl-5 text-sm">{result.missing_evidence.map((item) => <li key={item}>{item}</li>)}</ul>
          {result.citations.length ? <p className="mt-3 text-sm text-mist">Citations: {result.citations.join("; ")}</p> : null}
        </Card>
      ) : null}
    </div>
  );
}

type AlertRow = { id: string; title: string; category: string; severity: string; financial_impact: string | null; status: string };

export function AlertsPage() {
  const query = useResource<{ items: AlertRow[] }>("/api/v1/alerts");
  const client = useQueryClient();
  async function update(id: string, status: string) {
    await api(`/api/v1/alerts/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
    await client.invalidateQueries({ queryKey: ["/api/v1/alerts"] });
  }
  if (!query.data) return <p>Loading alerts…</p>;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Alerts</h1>
      <Card title="Active and reviewed alerts">
        <Table
          columns={["Alert", "Category", "Severity", "Impact", "Status", "Review"]}
          rows={query.data.items.map((item) => [item.title, item.category, item.severity, item.financial_impact ? `$${item.financial_impact}` : "—", item.status, item.status === "open" ? <button className="text-teal" onClick={() => update(item.id, "acknowledged")}>Acknowledge</button> : item.status])}
        />
      </Card>
    </div>
  );
}

export function ProcessingPage() {
  const jobs = useResource<{ items: Array<{ id: string; job_type: string; status: string; stats: Record<string, number> }> }>("/api/v1/processing/jobs");
  const files = useResource<{ total: number; items: Array<{ original_filename: string; status: string; reconciliation_status: string | null }> }>("/api/v1/remittances?page_size=100");
  const client = useQueryClient();
  const [message, setMessage] = useState("");
  async function runDemo() {
    setMessage("Running the synthetic ingestion pipeline…");
    const result = await api<{ stats: Record<string, number> }>("/api/v1/processing/run", { method: "POST", body: JSON.stringify({ source: "synthetic_demo" }) });
    setMessage(`Parsed ${result.stats.parsed ?? 0}, quarantined ${result.stats.quarantined ?? 0}, duplicates ${result.stats.duplicates ?? 0}, already ingested ${result.stats.skipped_known ?? 0}.`);
    await client.invalidateQueries();
  }
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Processing monitor</h1>
      <button className="rounded-lg bg-teal px-4 py-2 font-semibold text-ink" onClick={runDemo}>Run synthetic ingestion</button>
      {message ? <Notice>{message}</Notice> : null}
      <Card title="Files">
        <Notice>{files.data ? `${files.data.total} stored files` : "Loading files…"}</Notice>
        <Table columns={["File", "Status", "Reconciliation"]} rows={(files.data?.items || []).map((item) => [item.original_filename, item.status, item.reconciliation_status || "—"])} />
      </Card>
      <Card title="Jobs">
        <Table columns={["Type", "Status", "Parsed", "Quarantined", "Duplicates", "Already ingested"]} rows={(jobs.data?.items || []).map((item) => [item.job_type, item.status, item.stats?.parsed ?? "—", item.stats?.quarantined ?? "—", item.stats?.duplicates ?? "—", item.stats?.skipped_known ?? "—"])} />
      </Card>
    </div>
  );
}

const reports = ["daily_remittance", "weekly_denial", "monthly_payer", "underpayment_exception", "authorization_denial", "coding_denial", "reconciliation"];

export function ReportsPage() {
  const [message, setMessage] = useState("");
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Reports</h1>
      <Notice>Exports contain aggregate metrics. Viewer role cannot export. Demo exports are labeled synthetic.</Notice>
      {message ? <p className="text-sm text-red-300">{message}</p> : null}
      <Card title="Available reports">
        <div className="space-y-3">
          {reports.map((report) => (
            <div key={report} className="flex flex-wrap items-center justify-between gap-2 border-b border-line py-2">
              <span className="text-sm">{report.replaceAll("_", " ")}</span>
              <span className="space-x-2">
                {(["csv", "xlsx", "pdf"] as const).map((format) => (
                  <button key={format} className="rounded border border-line px-2 py-1 text-xs uppercase" onClick={() => downloadReport(report, format).catch((error: Error) => setMessage(error.message))}>{format}</button>
                ))}
              </span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

export function SettingsPage({ status }: { status?: string }) {
  const mappings = useResource<{ items: Array<{ code: string; code_type: string; category: string; is_denial: boolean; version: number }> }>("/api/v1/settings/denial-mappings");
  const thresholds = useResource<Record<string, string | number>>("/api/v1/settings/thresholds");
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <Card title="Central Reach">
        <Notice>{status || "Checking integration status…"}</Notice>
      </Card>
      <Card title="Thresholds">
        <Table columns={["Setting", "Value"]} rows={Object.entries(thresholds.data || {}).map(([key, value]) => [key.replaceAll("_", " "), String(value)])} />
      </Card>
      <Card title="Denial mappings">
        <Table columns={["Code", "Type", "Category", "Denial", "Version"]} rows={(mappings.data?.items || []).map((item) => [item.code, item.code_type, item.category, item.is_denial ? "yes" : "no", item.version])} />
      </Card>
    </div>
  );
}
