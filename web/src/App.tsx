import { useEffect, useState } from "react";
import { api, type Meta } from "./api";
import { defaultDraft, type WorkloadDraft } from "./components/WorkloadForm";
import { CompareView } from "./views/CompareView";
import { ExperimentsView } from "./views/ExperimentsView";
import { SimulationView } from "./views/SimulationView";

type Tab = "simulation" | "compare" | "experiments";
const TABS: [Tab, string][] = [["simulation", "Simulation"], ["compare", "Compare"], ["experiments", "Experiments"]];

function initialTab(): Tab {
  const h = location.hash.slice(1);
  return TABS.some(([t]) => t === h) ? (h as Tab) : "simulation";
}

export function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(initialTab);
  const [present, setPresent] = useState(false);
  const [draft, setDraft] = useState<WorkloadDraft | null>(null);

  useEffect(() => {
    api.meta().then((m) => { setMeta(m); setDraft(defaultDraft(m)); }).catch((e) => setError((e as Error).message));
  }, []);
  useEffect(() => { document.documentElement.classList.toggle("present", present); }, [present]);
  useEffect(() => { history.replaceState(null, "", `#${tab}`); }, [tab]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand"><b>ARBF Simulator</b><span>Adaptive Residual Best Fit · engine v1</span></div>
        <nav className="tabs" role="tablist">
          {TABS.map(([t, label]) => (
            <button key={t} role="tab" className="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{label}</button>
          ))}
        </nav>
        <div className="topbar-right">
          <label className="check" title="Larger text, configuration hidden">
            <input type="checkbox" checked={present} onChange={(e) => setPresent(e.target.checked)} />
            Presentation mode
          </label>
        </div>
      </header>

      {error ? (
        <div className="main"><div className="empty"><b>Cannot reach the simulator backend</b>{error}
          <div className="mono" style={{ marginTop: "0.6rem" }}>python -m simulator</div></div></div>
      ) : !meta || !draft ? (
        <div className="main"><div className="empty"><b>Connecting…</b></div></div>
      ) : (
        <>
          <SimulationView meta={meta} draft={draft} setDraft={setDraft} present={present} active={tab === "simulation"} />
          <CompareView meta={meta} draft={draft} setDraft={setDraft} active={tab === "compare"} />
          <ExperimentsView meta={meta} active={tab === "experiments"} />
        </>
      )}
    </div>
  );
}
