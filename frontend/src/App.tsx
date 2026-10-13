import { FormEvent, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, getToken, setToken } from "./api";
import { AlertsPage, InvestigatePage, ProcessingPage, ReportsPage, SettingsPage } from "./pages/AlertsPage";
import { DenialsPage, OverviewPage } from "./pages/OverviewPage";
import { PayersPage, PaymentsPage, SlicePage } from "./pages/PaymentsPage";
import { useResource } from "./hooks";

const links = [
  ["/", "Overview"],
  ["/denials", "Denials"],
  ["/payments", "Payments"],
  ["/payers", "Payers"],
  ["/authorization", "Authorization"],
  ["/coding", "Coding"],
  ["/investigate", "Investigation"],
  ["/alerts", "Alerts"],
  ["/processing", "Processing"],
  ["/reports", "Reports"],
  ["/settings", "Settings"],
];

export function App() {
  const token = getToken();
  if (!token) return <Login />;
  return <Shell />;
}

function Login() {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const meta = useResource<{ demo_mode: boolean; demo_email?: string; demo_password?: string; central_reach_status: string }>("/api/v1/meta");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const result = await api<{ access_token: string }>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      });
      setToken(result.access_token);
      navigate("/");
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    }
  }

  if (meta.isLoading) {
    return <main className="grid min-h-screen place-items-center px-4 text-sm text-mist">Loading sign-in…</main>;
  }
  const demoEmail = meta.data?.demo_email ?? "analyst@pmab.demo";
  const demoPassword = meta.data?.demo_password ?? "";

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-md rounded-2xl border border-line bg-panel p-6">
        <p className="text-xs uppercase tracking-[0.18em] text-teal">PMAB</p>
        <h1 className="mt-2 text-2xl font-semibold">Remittance intelligence</h1>
        <p className="mt-2 text-sm text-mist">Sign in to view calculated ERA/835 analytics. Central Reach stays read-only.</p>
        {meta.data?.demo_mode ? (
          <p className="mt-4 rounded-lg bg-amber-500/10 p-3 text-sm text-amber-100">
            Synthetic demo mode. Email {demoEmail}. Password {demoPassword}. The same password works for admin@pmab.demo and viewer@pmab.demo.
          </p>
        ) : null}
        <label className="mt-4 block text-sm">Email
          <input name="email" type="email" required autoComplete="off" className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2" defaultValue={demoEmail} />
        </label>
        <label className="mt-3 block text-sm">Password
          <input name="password" type={meta.data?.demo_mode ? "text" : "password"} required autoComplete="off" className="mt-1 w-full rounded-lg border border-line bg-ink px-3 py-2" defaultValue={demoPassword} />
        </label>
        {error ? <p className="mt-3 text-sm text-red-300">{error}</p> : null}
        <button className="mt-5 w-full rounded-lg bg-teal px-3 py-2 font-semibold text-ink" type="submit">Sign in</button>
      </form>
    </main>
  );
}

function Shell() {
  const meta = useResource<{ demo_mode: boolean; llm_provider: string; central_reach_status: string }>("/api/v1/meta");
  return (
    <div className="min-h-screen md:grid md:grid-cols-[240px_1fr]">
      <aside className="border-b border-line bg-[#0b1828] p-4 md:min-h-screen md:border-b-0 md:border-r">
        <div className="text-xs uppercase tracking-[0.18em] text-teal">PMAB</div>
        <div className="mt-1 text-lg font-semibold">Remittance intelligence</div>
        <nav className="mt-6 flex gap-2 overflow-x-auto md:block md:space-y-1">
          {links.map(([path, label]) => (
            <NavLink key={path} to={path} end={path === "/"} className={({ isActive }) => `block whitespace-nowrap rounded-lg px-3 py-2 text-sm ${isActive ? "bg-teal text-ink" : "text-mist hover:bg-white/5"}`}>
              {label}
            </NavLink>
          ))}
        </nav>
        <button className="mt-6 text-sm text-mist underline" onClick={() => { setToken(null); window.location.assign("/login"); }}>Sign out</button>
      </aside>
      <div>
        {meta.data?.demo_mode ? (
          <div className="border-b border-amber-500/30 bg-amber-500/10 px-6 py-2 text-sm text-amber-100">
            Synthetic demo mode. Metrics are calculated from labeled fake 835 files. Underpayments and delays that use demo contracts or demo submission dates are badged. They are not approved payer results. Central Reach is not connected.
          </div>
        ) : null}
        <main className="space-y-4 p-4 md:p-6">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/denials" element={<DenialsPage />} />
            <Route path="/payments" element={<PaymentsPage />} />
            <Route path="/payers" element={<PayersPage />} />
            <Route path="/authorization" element={<SlicePage category="authorization" title="Authorization denials" />} />
            <Route path="/coding" element={<SlicePage category="coding" title="Coding denials" />} />
            <Route path="/investigate" element={<InvestigatePage provider={meta.data?.llm_provider} />} />
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="/processing" element={<ProcessingPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/settings" element={<SettingsPage status={meta.data?.central_reach_status} />} />
            <Route path="/login" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
