import { FormEvent, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, downloadReport, uploadBatch, type BatchFileResult } from "../api";
import { Carousel, Slide } from "../carousel";
import { EmptyState, GhostButton, Notice, PageHeader, Panel, PrimaryButton, QueryState, StatusPill, Table } from "../components";
import { useResource } from "../hooks";

const questions = [
  "Which payer has the highest denial rate?",
  "Why are authorization denials increasing?",
  "Which procedure codes have recurring denials?",
  "Which underpayment patterns have the highest financial impact?",
];

const capabilities = [
  ["Supervisor", "Routes the question, bounds the run, and stops."],
  ["Denial", "Reads classified adjustments and payer mix."],
  ["Payment", "Reads delay and underpayment tool output."],
  ["Payer", "Compares longitudinal payer behavior."],
  ["Root cause", "States the hypothesis and the missing evidence."],
  ["Insight", "Narrates only what the tools already calculated."],
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
  plan: string[];
  agent_outputs: Array<{ agent: string; summary: string }>;
};

export function InvestigatePage({ provider }: { provider?: string }) {
  const [result, setResult] = useState<Investigation | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const history = useResource<{ items: Array<{ id: string; question: string; status: string; summary: string | null; needs_human_review: boolean; created_at: string | null }> }>("/api/v1/ai/investigations");

  async function ask(question: string) {
    setPending(true);
    setError("");
    setResult(null);
    try {
      setResult(await api<Investigation>("/api/v1/ai/ask", { method: "POST", body: JSON.stringify({ question }) }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Investigation failed.");
    } finally {
      setPending(false);
    }
  }

  async function review(id: string) {
    await api(`/api/v1/ai/investigations/${id}/review`, { method: "POST" });
    setResult((current) => current ? { ...current, status: "reviewed", needs_human_review: false } : current);
  }

  const route = new Set(result?.plan || []);

  return (
    <div className="space-y-6">
      <PageHeader kicker="Agent workspace" title="Five specialists. One route." lede={`Provider ${provider || "loading"}. Activity on this page appears only after a question is run.`} />
      <Carousel label="Capabilities">
        {capabilities.map(([name, copy]) => (
          <Slide key={name}>
            <article className="h-full rounded-2xl border border-line p-5">
              <h2 className="font-display text-3xl">{name}</h2>
              <p className="mt-3 text-sm leading-6 text-mist">{copy}</p>
            </article>
          </Slide>
        ))}
      </Carousel>
      <div className="grid gap-3 md:grid-cols-3">
        {["Supervisor", "Denial", "Payment", "Payer", "Root cause", "Insight"].map((name) => {
          const key = name === "Root cause" ? "root_cause" : name.toLowerCase();
          const active = result ? route.has(key) || (name === "Supervisor" && Boolean(result)) : false;
          return (
            <div key={name} className={`rounded-2xl border p-4 ${active ? "border-foam" : "border-line opacity-60"}`}>
              <p className="text-[11px] uppercase tracking-[0.16em] text-faint">{active ? "On this route" : "Idle"}</p>
              <p className="mt-2 font-display text-2xl">{name}</p>
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap gap-2">
        {questions.map((question) => (
          <GhostButton key={question} onClick={() => ask(question)}>{question}</GhostButton>
        ))}
      </div>
      <form className="flex flex-col gap-2 md:flex-row" onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); ask(String(new FormData(event.currentTarget).get("question") || "")); }}>
        <input name="question" minLength={8} className="flex-1 rounded-full border border-line bg-inset px-4 py-3 text-sm outline-none" placeholder="Ask about denials, payers, delays, or underpayments" />
        <PrimaryButton disabled={pending} type="submit">{pending ? "Running" : "Run"}</PrimaryButton>
      </form>
      {error ? <p className="text-sm">{error}</p> : null}
      {pending ? <Notice>The supervisor is calling read-only tools. This is a live request, not a playback.</Notice> : null}
      {result ? (
        <Panel title={`${result.provider_name} · ${result.status}`}>
          <p className="text-sm leading-7">{result.summary}</p>
          <p className="mt-3 text-xs leading-5 text-mist">{result.disclaimer} {result.insufficient_evidence ? "Evidence was marked insufficient." : ""} {result.needs_human_review ? "Human review is required." : ""}</p>
          {result.llm_error ? <p className="mt-2 text-sm">{result.llm_error}</p> : null}
          <ol className="mt-5 space-y-3">
            {result.agent_outputs.map((item, index) => (
              <li key={`${item.agent}-${index}`} className="border-t border-line pt-3 text-sm">
                <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-faint">{String(index + 1).padStart(2, "0")} {item.agent}</span>
                <p className="mt-1 leading-6 text-mist">{item.summary}</p>
              </li>
            ))}
          </ol>
          <h3 className="mt-5 text-[11px] uppercase tracking-[0.16em] text-faint">Missing evidence</h3>
          <ul className="mt-2 list-disc pl-5 text-sm text-mist">{result.missing_evidence.map((item) => <li key={item}>{item}</li>)}</ul>
          {result.needs_human_review ? <PrimaryButton className="mt-4" onClick={() => review(result.investigation_id)}>Mark reviewed</PrimaryButton> : null}
        </Panel>
      ) : null}
      <Carousel label="Investigations">
        {history.error ? (
          <Slide><Panel><Notice>{history.error instanceof Error ? history.error.message : "Investigations could not be loaded."}</Notice></Panel></Slide>
        ) : (history.data?.items.length ?? 0) === 0 ? (
          <Slide><Panel><Notice>No investigations have been stored.</Notice></Panel></Slide>
        ) : history.data?.items.map((item) => (
          <Slide key={item.id}>
            <article className="h-full rounded-2xl border border-line p-5">
              <StatusPill value={item.needs_human_review ? "REVIEW" : item.status} />
              <p className="mt-4 text-sm leading-6">{item.question}</p>
              <p className="mt-3 text-xs leading-5 text-mist">{item.summary || "No summary stored."}</p>
            </article>
          </Slide>
        ))}
      </Carousel>
    </div>
  );
}

type AlertRow = {
  id: string;
  title: string;
  category: string;
  severity: string;
  financial_impact: string | null;
  status: string;
  assigned_to: string | null;
  detail: Record<string, unknown> | null;
};

export function AlertsPage() {
  const query = useResource<{ items: AlertRow[] }>("/api/v1/alerts");
  const client = useQueryClient();
  async function update(id: string, status: string) {
    await api(`/api/v1/alerts/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
    await client.invalidateQueries({ queryKey: ["/api/v1/alerts"] });
  }
  return (
    <div className="space-y-6">
      <PageHeader kicker="Alerts" title="Exceptions with an owner." lede="Delivery to email or chat is not claimed unless a channel confirms it. This screen records review status only." />
      <QueryState loading={query.isLoading} error={query.error}>
        {(query.data?.items.length ?? 0) === 0 ? <EmptyState title="No open exceptions." body="Alerts appear when calculated thresholds are crossed. An empty list is a real status." /> : (
          <div className="space-y-3">
            {query.data?.items.map((item) => (
              <article key={item.id} className="rounded-2xl border border-line p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill value={item.severity} />
                  <StatusPill value={item.status} />
                  <span className="text-xs uppercase tracking-[0.14em] text-faint">{item.category}</span>
                </div>
                <h2 className="mt-3 font-display text-3xl">{item.title}</h2>
                <p className="mt-2 font-mono text-sm">Exposure {item.financial_impact ? `$${item.financial_impact}` : "—"} · Assignee {item.assigned_to || "Unassigned"}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {item.status === "open" ? <GhostButton onClick={() => update(item.id, "acknowledged")}>Acknowledge</GhostButton> : null}
                  {item.status !== "resolved" ? <GhostButton onClick={() => update(item.id, "resolved")}>Resolve</GhostButton> : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </QueryState>
    </div>
  );
}

export function ProcessingPage({ demoMode }: { demoMode?: boolean }) {
  const jobs = useResource<{ items: Array<{ id: string; job_type: string; status: string; stats: Record<string, number> }> }>("/api/v1/processing/jobs");
  const files = useResource<{ total: number; items: Array<{ id: string; original_filename: string; lifecycle: string; reconciliation_status: string | null }> }>("/api/v1/remittances?page_size=20");
  const client = useQueryClient();
  const [progress, setProgress] = useState<number | null>(null);
  const [results, setResults] = useState<BatchFileResult[]>([]);
  const [message, setMessage] = useState("");
  const [over, setOver] = useState(false);

  async function send(list: File[]) {
    setMessage("");
    setProgress(0);
    try {
      const batch = await uploadBatch(list, setProgress);
      setResults(batch.results);
      setMessage(`Parsed ${batch.stats.parsed ?? 0}, quarantined ${batch.stats.quarantined ?? 0}, duplicates ${batch.stats.duplicates ?? 0}, rejected ${batch.stats.rejected ?? 0}.`);
      await client.invalidateQueries();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setProgress(null);
    }
  }

  async function scan() {
    setMessage("Scanning the configured ingestion folder…");
    const result = await api<{ stats: Record<string, number> }>("/api/v1/processing/run", { method: "POST", body: JSON.stringify({ source: "local_directory" }) });
    setMessage(`Discovered ${result.stats.discovered ?? 0}, parsed ${result.stats.parsed ?? 0}, skipped known ${result.stats.skipped_known ?? 0}.`);
    await client.invalidateQueries();
  }

  return (
    <div className="space-y-6">
      <PageHeader kicker="File ingestion" title="Drop the 835. Keep the original." lede="Individual files, batches, and ZIP archives. Live Central Reach retrieval is a separate client-managed connector." />
      <label
        className={`block cursor-pointer rounded-3xl border border-dashed px-6 py-16 text-center ${over ? "border-foam bg-inset" : "border-line"}`}
        onDragOver={(event) => { event.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => { event.preventDefault(); setOver(false); void send([...event.dataTransfer.files]); }}
      >
        <p className="font-display text-4xl">Drop remittance files</p>
        <p className="mt-3 text-sm text-mist">.835, .edi, .txt, .x12, or a .zip of those files</p>
        <input className="sr-only" type="file" multiple accept=".835,.edi,.txt,.x12,.zip" onChange={(event) => { if (event.target.files) void send([...event.target.files]); }} />
        {progress !== null ? <div className="mx-auto mt-6 h-1 max-w-md overflow-hidden rounded-full bg-line"><div className="h-full bg-foam transition-all" style={{ width: `${Math.round(progress * 100)}%` }} /></div> : null}
      </label>
      {message ? <Notice>{message}</Notice> : null}
      <div className="flex flex-wrap gap-2">
        <GhostButton onClick={() => scan()}>Scan ingestion folder</GhostButton>
        {demoMode ? <GhostButton onClick={async () => {
          const result = await api<{ stats: Record<string, number> }>("/api/v1/processing/run", { method: "POST", body: JSON.stringify({ source: "synthetic_demo" }) });
          setMessage(`Synthetic run. Parsed ${result.stats.parsed ?? 0}, quarantined ${result.stats.quarantined ?? 0}, duplicates ${result.stats.duplicates ?? 0}.`);
          await client.invalidateQueries();
        }}>Load synthetic corpus</GhostButton> : null}
      </div>
      <ol className="flex gap-2 overflow-x-auto">
        {["RECEIVED", "VALIDATING", "PARSING", "NORMALIZING", "ANALYZING", "COMPLETED"].map((stage) => (
          <li key={stage} className="rounded-full border border-line px-3 py-1 font-mono text-[10px] text-mist">{stage}</li>
        ))}
      </ol>
      {results.length ? (
        <Panel title="This batch">
          <Table columns={["File", "Lifecycle", "Reconciliation", "Message"]} rows={results.map((item) => [item.filename, item.lifecycle, item.reconciliation_status || "—", item.message])} />
          <div className="mt-3 flex flex-wrap gap-2">
            {results.filter((item) => item.lifecycle === "QUARANTINED" && item.file_id).map((item) => (
              <GhostButton key={item.file_id} onClick={async () => {
                const retry = await api<{ message: string }>(`/api/v1/remittances/${item.file_id}/retry`, { method: "POST" });
                setMessage(retry.message);
              }}>Retry {item.filename}</GhostButton>
            ))}
          </div>
        </Panel>
      ) : null}
      <Panel title="Recent files">
        <Notice>{files.data ? `${files.data.total} stored` : "Loading files…"}</Notice>
        <Table columns={["File", "Lifecycle", "Reconciliation"]} rows={(files.data?.items || []).map((item) => [item.original_filename, item.lifecycle, item.reconciliation_status || "—"])} />
      </Panel>
      <Panel title="Jobs">
        <Table columns={["Type", "Status", "Parsed", "Quarantined", "Duplicates"]} rows={(jobs.data?.items || []).map((item) => [item.job_type, item.status, item.stats?.parsed ?? "—", item.stats?.quarantined ?? "—", item.stats?.duplicates ?? "—"])} />
      </Panel>
    </div>
  );
}

const reports = [
  ["daily_remittance", "Remittances"],
  ["weekly_denial", "Denials"],
  ["monthly_payer", "Payers"],
  ["underpayment_exception", "Underpayments"],
  ["authorization_denial", "Authorization"],
  ["coding_denial", "Coding"],
  ["reconciliation", "Reconciliation"],
];

export function ReportsPage() {
  const [message, setMessage] = useState("");
  return (
    <div className="space-y-6">
      <PageHeader kicker="Insights and reports" title="Export what was calculated." lede="CSV, Excel, and PDF contain aggregate metrics, the generation context, and a synthetic label when demo mode is on." />
      {message ? <Notice>{message}</Notice> : null}
      <div className="grid gap-3 md:grid-cols-2">
        {reports.map(([report, label]) => (
          <article key={report} className="rounded-2xl border border-line p-5">
            <h2 className="font-display text-3xl">{label}</h2>
            <p className="mt-2 font-mono text-[11px] text-faint">{report}</p>
            <div className="mt-4 flex gap-2">
              {(["csv", "xlsx", "pdf"] as const).map((format) => (
                <GhostButton key={format} onClick={() => downloadReport(report, format).catch((error: Error) => setMessage(error.message))}>{format}</GhostButton>
              ))}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

export function SettingsPage({ status, note, pattern, provider }: { status?: string; note?: string; pattern?: string; provider?: string }) {
  const mappings = useResource<{ items: Array<{ code: string; code_type: string; category: string; is_denial: boolean; version: number }> }>("/api/v1/settings/denial-mappings");
  const thresholds = useResource<Record<string, string | number>>("/api/v1/settings/thresholds");
  const audit = useResource<{ items: Array<{ id: string; action: string; resource_type: string; created_at: string | null }> }>("/api/v1/audit");
  const meta = useResource<{ bedrock_phi_approved: boolean; storage_backend: string; demo_mode: boolean }>("/api/v1/meta");
  return (
    <div className="space-y-6">
      <PageHeader kicker="Governance" title="What the platform will not invent." lede="File upload stays available. Central Reach waits for a client-managed connection." />
      <Panel title="Central Reach">
        <p className="font-display text-3xl">Client-managed integration — not connected</p>
        <Notice>{status}</Notice>
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Ingestion">
          <Notice>{note}</Notice>
          <p className="mt-3 font-mono text-xs text-mist">Naming pattern {pattern}. This is a platform default until the business confirms PLUTUS_DATE. Original filenames and checksums are kept either way.</p>
          <p className="mt-3 text-sm text-mist">Storage {meta.data?.storage_backend || "—"}. Model {provider || "—"}. PHI to Bedrock {meta.data?.bedrock_phi_approved ? "approved" : "not approved"}.</p>
        </Panel>
        <Panel title="Thresholds">
          <Table columns={["Setting", "Value"]} rows={Object.entries(thresholds.data || {}).map(([key, value]) => [key.replaceAll("_", " "), String(value)])} />
        </Panel>
      </div>
      <Panel title="Denial mappings">
        <Table columns={["Code", "Type", "Category", "Denial", "Version"]} rows={(mappings.data?.items || []).map((item) => [item.code, item.code_type, item.category, item.is_denial ? "yes" : "no", item.version])} />
      </Panel>
      <Panel title="Audit">
        {audit.error ? <Notice>Audit history requires the audit permission.</Notice> : (
          <Table columns={["When", "Action", "Resource"]} rows={(audit.data?.items || []).slice(0, 30).map((item) => [item.created_at || "—", item.action, item.resource_type])} />
        )}
      </Panel>
      <Panel title="Roles">
        <Notice>Admin, analyst, reviewer, and viewer. Exports require reports access. Patient names and member IDs require phi access. Demo passwords are refused when production startup checks run.</Notice>
      </Panel>
    </div>
  );
}
