import { useState } from "react";
import { api, downloadErrorReport } from "../api";
import { EmptyState, GhostButton, Notice, PageHeader, Panel, QueryState, StatusPill, Table } from "../components";
import { formatMoney } from "../format";
import { useResource } from "../hooks";

type FileRow = {
  id: string;
  original_filename: string;
  stored_filename: string;
  status: string;
  lifecycle: string;
  reconciliation_status: string | null;
  sha256: string;
  source_system: string;
  file_size: number;
  received_at: string | null;
};

type FileDetail = FileRow & {
  parsed_at: string | null;
  duration_ms: number | null;
  record_counts: { claims?: number; transactions?: number } | null;
  stages: Array<{ stage: string; at: string | null }>;
  payment_amount: string | null;
  trace_numbers: string[];
  claims: Array<{ patient_control_number: string; payer: string | null; total_charge: string; payment_amount: string; denied_amount: string; primary_denial_category: string | null; is_reversal: boolean }>;
  reconciliation: Array<{ scope: string; status: string; expected_amount: string; actual_amount: string; difference: string }>;
  errors: Array<{ stage: string; message: string }>;
};

const stages = ["RECEIVED", "VALIDATING", "PARSING", "NORMALIZING", "ANALYZING", "COMPLETED"];

export function ExplorerPage() {
  const [q, setQ] = useState("");
  const [lifecycle, setLifecycle] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const list = useResource<{ total: number; items: FileRow[] }>(`/api/v1/remittances?page_size=50${q ? `&q=${encodeURIComponent(q)}` : ""}${lifecycle ? `&lifecycle=${lifecycle}` : ""}`);
  const detail = useResource<FileDetail>(selected ? `/api/v1/remittances/${selected}` : null);
  const active = selected ? detail.data : null;

  async function retry(id: string) {
    setMessage("");
    try {
      const result = await api<{ lifecycle: string; message: string }>(`/api/v1/remittances/${id}/retry`, { method: "POST" });
      setMessage(`${result.lifecycle}. ${result.message}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Retry failed.");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader kicker="Remittance explorer" title="Every file, still intact." lede="Original names and SHA-256 checksums stay attached to the normalized claims." />
      <div className="flex flex-col gap-3 md:flex-row">
        <input value={q} onChange={(event) => setQ(event.target.value)} placeholder="Search filename" className="w-full rounded-full border border-line bg-inset px-4 py-2 text-sm outline-none md:max-w-sm" />
        <select value={lifecycle} onChange={(event) => setLifecycle(event.target.value)} className="rounded-full border border-line bg-inset px-4 py-2 text-sm">
          <option value="">All lifecycles</option>
          {["COMPLETED", "QUARANTINED", "REQUIRES_REVIEW", "RECEIVED", "FAILED"].map((item) => <option key={item}>{item}</option>)}
        </select>
      </div>
      <QueryState loading={list.isLoading} error={list.error}>
        {list.data && list.data.total === 0 ? (
          <EmptyState title="The ledger is empty." body="Ingest a downloaded 835, EDI, or ZIP file. Search will light up after the first file is stored." />
        ) : (
          <div className="grid gap-4 lg:grid-cols-[minmax(280px,380px)_1fr]">
            <Panel title={`${list.data?.total ?? 0} files`}>
              <ul className="max-h-[70vh] space-y-2 overflow-auto">
                {(list.data?.items || []).map((item) => (
                  <li key={item.id}>
                    <button className={`w-full rounded-xl border px-3 py-3 text-left transition ${selected === item.id ? "border-foam bg-inset" : "border-line hover:border-foam/30"}`} onClick={() => setSelected(item.id)}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm">{item.original_filename}</span>
                        <StatusPill value={item.lifecycle} />
                      </div>
                      <p className="mt-2 font-mono text-[10px] text-faint">{item.sha256.slice(0, 16)} · {item.source_system}</p>
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>
            <Panel title="Inspection">
              {!selected ? (
                <Notice>Select a remittance. Reconciliation, lineage, and claims open here.</Notice>
              ) : detail.isLoading || !active || active.id !== selected ? (
                <Notice>Loading the file…</Notice>
              ) : (
                <div className="space-y-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-display text-3xl">{active.original_filename}</h2>
                    <StatusPill value={active.lifecycle} />
                  </div>
                  <p className="font-mono text-xs leading-5 text-mist">SHA-256 {active.sha256}<br />Stored as {active.stored_filename}<br />{active.file_size} bytes · {active.duration_ms ?? "—"} ms · source {active.source_system}</p>
                  <ol className="flex gap-2 overflow-x-auto pb-1">
                    {(active.lifecycle === "QUARANTINED" ? ["RECEIVED", "VALIDATING", "PARSING", "QUARANTINED"] : active.lifecycle === "REQUIRES_REVIEW" ? [...stages.slice(0, 5), "REQUIRES_REVIEW"] : stages).map((stage) => {
                      const hit = active.stages.some((item) => item.stage === stage);
                      return <li key={stage} className={`shrink-0 rounded-full border px-3 py-1 font-mono text-[10px] ${hit ? "border-foam text-foam" : "border-line text-faint"}`}>{stage}</li>;
                    })}
                  </ol>
                  <Notice>Payment {formatMoney(active.payment_amount)}. Trace {active.trace_numbers.join(", ") || "—"}. Claims {active.record_counts?.claims ?? active.claims.length}.</Notice>
                  {message ? <Notice>{message}</Notice> : null}
                  <div className="flex flex-wrap gap-2">
                    {active.lifecycle === "QUARANTINED" ? <GhostButton onClick={() => retry(active.id)}>Retry</GhostButton> : null}
                    <GhostButton onClick={() => downloadErrorReport(active.id, active.original_filename).catch((error: Error) => setMessage(error.message))}>Error report</GhostButton>
                  </div>
                  <Table columns={["Scope", "Status", "Expected", "Actual", "Difference"]} rows={active.reconciliation.map((row) => [row.scope, row.status, formatMoney(row.expected_amount), formatMoney(row.actual_amount), formatMoney(row.difference)])} />
                  <Table columns={["Control", "Payer", "Charge", "Paid", "Denied", "Category"]} rows={active.claims.map((row) => [row.patient_control_number, row.payer || "—", formatMoney(row.total_charge), formatMoney(row.payment_amount), formatMoney(row.denied_amount), row.is_reversal ? "Reversal" : row.primary_denial_category || "—"])} />
                  {active.errors.length ? <Notice>{active.errors.map((item) => `${item.stage}: ${item.message}`).join(" ")}</Notice> : null}
                </div>
              )}
            </Panel>
          </div>
        )}
      </QueryState>
    </div>
  );
}
