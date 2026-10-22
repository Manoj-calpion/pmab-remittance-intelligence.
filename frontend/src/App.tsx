import { FormEvent, useEffect, useMemo, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  Bell,
  Building2,
  FileText,
  Files,
  LayoutDashboard,
  LogOut,
  Moon,
  Search,
  Settings,
  ShieldAlert,
  Sun,
  Upload,
  Wallet,
  Waypoints,
} from "lucide-react";
import { api, getToken, setToken } from "./api";
import { AlertsPage, InvestigatePage, ProcessingPage, ReportsPage, SettingsPage } from "./pages/AlertsPage";
import { ExplorerPage } from "./pages/ExplorerPage";
import { DenialsPage, OverviewPage } from "./pages/OverviewPage";
import { PayersPage, PaymentsPage, SlicePage } from "./pages/PaymentsPage";
import { useResource } from "./hooks";
import { useTheme } from "./theme";

const links = [
  { to: "/", label: "Command", icon: LayoutDashboard },
  { to: "/remittances", label: "Remittances", icon: Files },
  { to: "/denials", label: "Denials", icon: ShieldAlert },
  { to: "/payments", label: "Payments", icon: Wallet },
  { to: "/payers", label: "Payers", icon: Building2 },
  { to: "/investigate", label: "Agents", icon: Waypoints },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/processing", label: "Ingestion", icon: Upload },
  { to: "/alerts", label: "Alerts", icon: Bell },
  { to: "/settings", label: "Governance", icon: Settings },
];

const paletteLinks = [
  ...links,
  { to: "/authorization", label: "Authorization denials", icon: ShieldAlert },
  { to: "/coding", label: "Coding denials", icon: ShieldAlert },
];

type Meta = {
  demo_mode: boolean;
  demo_email?: string;
  demo_password?: string;
  central_reach_status: string;
  llm_provider: string;
  ingestion_note?: string;
  filename_pattern?: string;
};

export function App() {
  const token = getToken();
  if (!token) return <Login />;
  return <Shell />;
}

function Login() {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const meta = useResource<Meta>("/api/v1/meta");

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

  if (meta.isLoading) return <main className="grid min-h-screen place-items-center text-sm text-mist">Loading sign-in…</main>;
  const demoEmail = meta.data?.demo_email ?? "analyst@pmab.demo";
  const demoPassword = meta.data?.demo_password ?? "";

  return (
    <main className="grid min-h-screen bg-canvas text-foam lg:grid-cols-2">
      <section className="flex flex-col justify-between border-b border-line px-8 py-10 lg:border-b-0 lg:border-r lg:px-14">
        <p className="text-[11px] uppercase tracking-[0.32em] text-faint">PMAB Intelligence</p>
        <div>
          <h1 className="max-w-xl font-display text-5xl leading-[0.95] md:text-7xl">Every remittance tells a story.</h1>
          <p className="mt-6 max-w-md text-sm leading-6 text-mist">Turn payment data into financial intelligence. Downloaded 835 files are enough to begin. Central Reach is not required.</p>
        </div>
        <p className="text-xs uppercase tracking-[0.2em] text-faint">Remittance Intelligence System</p>
      </section>
      <section className="flex items-center px-8 py-12 lg:px-16">
        <form onSubmit={submit} className="w-full max-w-md">
          <h2 className="font-display text-4xl">Sign in</h2>
          <p className="mt-3 text-sm leading-6 text-mist">Calculated ERA/835 analytics. No live payer connection is assumed.</p>
          {meta.data?.demo_mode ? (
            <p className="mt-6 border border-line bg-inset p-4 text-sm leading-6 text-mist">
              Synthetic demo mode. Analyst {demoEmail}. Password {demoPassword}. The same password works for admin@pmab.demo and viewer@pmab.demo.
            </p>
          ) : null}
          <label className="mt-6 block text-xs uppercase tracking-[0.16em] text-faint">
            Email
            <input name="email" type="email" required autoComplete="off" defaultValue={demoEmail} className="mt-2 w-full rounded-xl border border-line bg-inset px-3 py-3 text-sm text-foam" />
          </label>
          <label className="mt-4 block text-xs uppercase tracking-[0.16em] text-faint">
            Password
            <input name="password" type={meta.data?.demo_mode ? "text" : "password"} required autoComplete="off" defaultValue={demoPassword} className="mt-2 w-full rounded-xl border border-line bg-inset px-3 py-3 text-sm text-foam" />
          </label>
          {error ? <p className="mt-3 text-sm text-foam">{error}</p> : null}
          <button className="mt-6 w-full rounded-full bg-foam px-4 py-3 text-sm font-medium text-canvas" type="submit">
            Enter the workspace
          </button>
        </form>
      </section>
    </main>
  );
}

function Shell() {
  const location = useLocation();
  const reduce = useReducedMotion();
  const { theme, toggle } = useTheme();
  const meta = useResource<Meta>("/api/v1/meta");
  const me = useResource<{ email: string; role: string }>("/api/v1/auth/me");
  const [palette, setPalette] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((open) => !open);
      }
      if (event.key === "Escape") setPalette(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const matches = useMemo(
    () => paletteLinks.filter((item) => item.label.toLowerCase().includes(query.toLowerCase())),
    [query],
  );

  return (
    <div className="min-h-screen bg-canvas text-foam md:grid md:grid-cols-[240px_1fr]">
      <aside className="border-b border-line bg-inset md:min-h-screen md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-5 py-5 md:block">
          <div>
            <div className="text-[11px] uppercase tracking-[0.28em] text-faint">PMAB</div>
            <div className="mt-1 font-display text-2xl leading-none">Intelligence</div>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:block md:space-y-1 md:px-3">
          {links.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 whitespace-nowrap rounded-xl px-3 py-2 text-sm ${isActive ? "bg-panel text-foam" : "text-mist hover:text-foam"}`
              }
            >
              <item.icon size={16} />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden px-5 pb-6 md:block">
          <p className="text-[11px] uppercase tracking-[0.16em] text-faint">{me.data?.role || "signed in"}</p>
          <p className="mt-1 truncate font-mono text-xs text-mist">{me.data?.email}</p>
        </div>
      </aside>
      <div className="min-w-0">
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3 md:px-8">
          <button className="flex flex-1 items-center gap-2 rounded-full border border-line px-3 py-2 text-left text-sm text-mist md:max-w-md" onClick={() => setPalette(true)}>
            <Search size={14} />
            Search the workspace
            <span className="ml-auto font-mono text-[10px] text-faint">Ctrl K</span>
          </button>
          <div className="flex items-center gap-2">
            <button aria-label="Toggle color theme" className="grid h-9 w-9 place-items-center rounded-full border border-line" onClick={toggle}>
              {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
            </button>
            <button
              className="grid h-9 w-9 place-items-center rounded-full border border-line"
              aria-label="Sign out"
              onClick={() => {
                setToken(null);
                window.location.assign("/");
              }}
            >
              <LogOut size={15} />
            </button>
          </div>
        </header>
        {meta.data?.demo_mode ? (
          <div className="border-b border-line px-4 py-2 text-xs uppercase tracking-[0.16em] text-mist md:px-8">
            Synthetic demo · calculated from labeled fixtures · not an approved payer result
          </div>
        ) : null}
        <AnimatePresence mode="wait">
          <motion.main
            key={location.pathname}
            className="space-y-6 px-4 py-6 md:px-8 md:py-8"
            initial={reduce ? false : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduce ? undefined : { opacity: 0 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          >
            <Routes location={location}>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/remittances" element={<ExplorerPage />} />
              <Route path="/denials" element={<DenialsPage />} />
              <Route path="/payments" element={<PaymentsPage />} />
              <Route path="/payers" element={<PayersPage />} />
              <Route path="/authorization" element={<SlicePage category="authorization" title="Authorization denials" />} />
              <Route path="/coding" element={<SlicePage category="coding" title="Coding denials" />} />
              <Route path="/investigate" element={<InvestigatePage provider={meta.data?.llm_provider} />} />
              <Route path="/alerts" element={<AlertsPage />} />
              <Route path="/processing" element={<ProcessingPage demoMode={meta.data?.demo_mode} />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/settings" element={<SettingsPage status={meta.data?.central_reach_status} note={meta.data?.ingestion_note} pattern={meta.data?.filename_pattern} provider={meta.data?.llm_provider} />} />
              <Route path="/login" element={<Navigate to="/" replace />} />
            </Routes>
          </motion.main>
        </AnimatePresence>
      </div>
      {palette ? (
        <div className="fixed inset-0 z-40 bg-black/60 p-4" onClick={() => setPalette(false)}>
          <div className="mx-auto mt-[12vh] max-w-xl rounded-2xl border border-line bg-panel p-3" onClick={(event) => event.stopPropagation()}>
            <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Jump to a workspace" className="w-full bg-transparent px-3 py-3 text-sm outline-none" />
            <div className="max-h-80 overflow-auto">
              {matches.map((item) => (
                <NavLink key={item.to} to={item.to} onClick={() => setPalette(false)} className="flex items-center gap-3 rounded-xl px-3 py-3 text-sm hover:bg-inset">
                  <item.icon size={15} />
                  {item.label}
                </NavLink>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
