"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Radar, RefreshCw, Save } from "lucide-react";
import { api } from "../../../lib/api";
import { Button } from "../../../components/ui/button";

type DiscoverySources = { propublica: boolean; grants_gov: boolean; sam_gov: boolean };
type DiscoveryConfig = {
  id?: string;
  enabled: boolean;
  cron_expression: string;
  states: string[];
  keywords: string[];
  sources: DiscoverySources;
  max_per_source: number;
  updated_at?: string;
};
type DiscoveryRun = {
  id: string; started_at: string; finished_at?: string; status: string;
  trigger: string; urls_discovered: number; urls_new: number;
  scrape_job_id?: string; error_message?: string;
};
type ScheduleMode = "daily" | "weekly" | "monthly" | "custom";

const DOW_NAMES = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];

function parseCronToSchedule(expr: string) {
  const p = expr.trim().split(/\s+/);
  if (p.length !== 5) return { mode: "custom" as ScheduleMode, hour: 2, minute: 0, dow: 1, dom: 1 };
  const [min, hr, dom, , dow] = p;
  const hour = parseInt(hr, 10), minute = parseInt(min, 10);
  const h = isNaN(hour) ? 2 : hour, m = isNaN(minute) ? 0 : minute;
  if (dow !== "*" && dom === "*") return { mode: "weekly" as ScheduleMode, hour: h, minute: m, dow: parseInt(dow,10)||1, dom: 1 };
  if (dom !== "*" && dow === "*") return { mode: "monthly" as ScheduleMode, hour: h, minute: m, dow: 1, dom: parseInt(dom,10)||1 };
  if (dow === "*" && dom === "*") return { mode: "daily" as ScheduleMode, hour: h, minute: m, dow: 1, dom: 1 };
  return { mode: "custom" as ScheduleMode, hour: h, minute: m, dow: 1, dom: 1 };
}

function buildCron(mode: ScheduleMode, h: number, m: number, dow: number, dom: number, custom: string) {
  if (mode === "custom") return custom;
  if (mode === "daily") return `${m} ${h} * * *`;
  if (mode === "weekly") return `${m} ${h} * * ${dow}`;
  return `${m} ${h} ${dom} * *`;
}

function describeSchedule(mode: ScheduleMode, h: number, m: number, dow: number, dom: number) {
  const t = `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")} UTC`;
  if (mode === "daily") return `Every day at ${t}`;
  if (mode === "weekly") return `Every ${DOW_NAMES[dow]} at ${t}`;
  if (mode === "monthly") return `Day ${dom} of every month at ${t}`;
  return "";
}

function StatusBadge({ status }: { status: string }) {
  const s = { running:"bg-brand/10 text-brand", completed:"bg-emerald-50 text-emerald-700", failed:"bg-red-50 text-red-700" }[status] ?? "bg-slate-100 text-slate-600";
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${s}`}>{status}</span>;
}
function TriggerBadge({ trigger }: { trigger: string }) {
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${trigger==="manual"?"bg-indigo-50 text-indigo-700":"bg-slate-100 text-slate-600"}`}>{trigger}</span>;
}

const sel = "rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-sm text-slate-700 focus:border-brand/50 focus:outline-none focus:ring-2 focus:ring-brand/10";

export default function DiscoveryAdminPage() {
  const [config, setConfig] = useState<DiscoveryConfig>({
    enabled: false, cron_expression: "0 2 * * 1",
    states: [], keywords: [],
    sources: { propublica: true, grants_gov: true, sam_gov: false },
    max_per_source: 100,
  });
  const [schedMode, setSchedMode] = useState<ScheduleMode>("weekly");
  const [schedHour, setSchedHour] = useState(2);
  const [schedMin, setSchedMin] = useState(0);
  const [schedDow, setSchedDow] = useState(1);
  const [schedDom, setSchedDom] = useState(1);
  const [customCron, setCustomCron] = useState("0 2 * * 1");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [runs, setRuns] = useState<DiscoveryRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  useEffect(() => {
    api.discoveryConfig().then((c: DiscoveryConfig) => {
      setConfig(c);
      const s = parseCronToSchedule(c.cron_expression);
      setSchedMode(s.mode); setSchedHour(s.hour); setSchedMin(s.minute);
      setSchedDow(s.dow); setSchedDom(s.dom); setCustomCron(c.cron_expression);
    }).catch((e: any) => setLoadError(e.message || "Failed to load config"));
    loadRuns();
  }, []);

  useEffect(() => {
    const cron = buildCron(schedMode, schedHour, schedMin, schedDow, schedDom, customCron);
    setConfig((c) => ({ ...c, cron_expression: cron }));
  }, [schedMode, schedHour, schedMin, schedDow, schedDom, customCron]);

  const loadRuns = async () => {
    setRunsLoading(true);
    try { setRuns(await api.discoveryRuns(20)); } catch {} finally { setRunsLoading(false); }
  };

  const handleSave = async () => {
    setSaving(true); setSaveStatus(null);
    try {
      const saved = await api.updateDiscoveryConfig(config);
      setConfig(saved); setSaveStatus("Configuration saved.");
    } catch (e: any) { setSaveStatus(`Error: ${e.message}`); }
    finally { setSaving(false); }
  };

  const cron = buildCron(schedMode, schedHour, schedMin, schedDow, schedDom, customCron);
  const schedDesc = schedMode !== "custom" ? describeSchedule(schedMode, schedHour, schedMin, schedDow, schedDom) : "";

  if (loadError) return (
    <div className="page-content"><div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><AlertCircle size={14}/>{loadError}</div></div>
  );

  return (
    <div className="page-content space-y-6">
      <header>
        <p className="text-xs font-medium uppercase tracking-widest text-slate-400">Admin</p>
        <h1 className="mt-0.5 text-2xl font-bold text-slate-900">Auto-Discovery</h1>
        <p className="mt-1 text-sm text-slate-500">Automatically discover new funding opportunities on a schedule. To trigger a run manually, use the main Scrape &amp; Analyse page.</p>
      </header>

      {/* Schedule */}
      <div className="card-base overflow-hidden">
        <div className="border-b border-slate-100 px-5 py-4"><p className="text-xs font-bold uppercase tracking-wider text-slate-400">Schedule</p></div>
        <div className="space-y-5 p-5">
          {/* Enable toggle */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-800">Enable auto-discovery</p>
              <p className="text-xs text-slate-500">Runs automatically on the configured schedule below.</p>
            </div>
            <button type="button" onClick={()=>setConfig((c)=>({...c,enabled:!c.enabled}))}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${config.enabled?"bg-brand":"bg-slate-200"}`}>
              <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${config.enabled?"translate-x-6":"translate-x-1"}`}/>
            </button>
          </div>

          {/* Frequency tabs */}
          <div className="space-y-3">
            <p className="text-xs font-semibold text-slate-600">Frequency</p>
            <div className="flex gap-1.5 flex-wrap">
              {(["daily","weekly","monthly","custom"] as ScheduleMode[]).map((m)=>(
                <button key={m} type="button" onClick={()=>setSchedMode(m)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium capitalize transition ${schedMode===m?"bg-brand text-white shadow-sm":"border border-slate-200 text-slate-600 hover:bg-slate-50"}`}>
                  {m}
                </button>
              ))}
            </div>

            {/* Time controls */}
            {schedMode !== "custom" && (
              <div className="flex flex-wrap items-center gap-3">
                {schedMode === "weekly" && (
                  <div className="space-y-1">
                    <p className="text-xs text-slate-500">Day</p>
                    <select value={schedDow} onChange={(e)=>setSchedDow(Number(e.target.value))} className={sel}>
                      {DOW_NAMES.map((d,i)=><option key={d} value={i}>{d}</option>)}
                    </select>
                  </div>
                )}
                {schedMode === "monthly" && (
                  <div className="space-y-1">
                    <p className="text-xs text-slate-500">Day of month</p>
                    <select value={schedDom} onChange={(e)=>setSchedDom(Number(e.target.value))} className={sel}>
                      {Array.from({length:28},(_,i)=>i+1).map((d)=><option key={d} value={d}>{d}</option>)}
                    </select>
                  </div>
                )}
                <div className="space-y-1">
                  <p className="text-xs text-slate-500">Hour (UTC)</p>
                  <select value={schedHour} onChange={(e)=>setSchedHour(Number(e.target.value))} className={sel}>
                    {Array.from({length:24},(_,i)=>i).map((h)=><option key={h} value={h}>{String(h).padStart(2,"0")}:00</option>)}
                  </select>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-slate-500">Minute</p>
                  <select value={schedMin} onChange={(e)=>setSchedMin(Number(e.target.value))} className={sel}>
                    {[0,15,30,45].map((m)=><option key={m} value={m}>{String(m).padStart(2,"0")}</option>)}
                  </select>
                </div>
              </div>
            )}

            {schedMode === "custom" && (
              <div className="space-y-1">
                <p className="text-xs text-slate-500">Cron expression (minute hour day month weekday)</p>
                <input type="text" value={customCron} onChange={(e)=>setCustomCron(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-sm text-slate-700 focus:border-brand/50 focus:outline-none focus:ring-2 focus:ring-brand/10"/>
              </div>
            )}

            <div className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Preview</span>
              <span className="text-xs text-slate-700">{schedDesc || cron}</span>
              {schedMode !== "custom" && <span className="ml-auto font-mono text-[10px] text-slate-400">{cron}</span>}
            </div>
          </div>
        </div>
      </div>

      {/* Sources */}
      <div className="card-base overflow-hidden">
        <div className="border-b border-slate-100 px-5 py-4"><p className="text-xs font-bold uppercase tracking-wider text-slate-400">Sources</p></div>
        <div className="divide-y divide-slate-100">
          {[
            { key:"propublica" as const, label:"ProPublica Nonprofit Explorer", desc:"Discovers grant-making foundations across the US.", badge:"Free", badgeCls:"bg-emerald-50 text-emerald-700" },
            { key:"grants_gov" as const, label:"Grants.gov", desc:"Open federal grant opportunities.", badge:"Free", badgeCls:"bg-emerald-50 text-emerald-700" },
          ].map(({key,label,desc,badge,badgeCls})=>(
            <label key={key} className="flex cursor-pointer items-center gap-3 px-5 py-4">
              <input type="checkbox" checked={config.sources[key]} onChange={(e)=>setConfig((c)=>({...c,sources:{...c.sources,[key]:e.target.checked}}))} className="h-4 w-4 rounded border-slate-300 accent-brand"/>
              <div className="min-w-0 flex-1"><p className="text-sm font-semibold text-slate-800">{label}</p><p className="text-xs text-slate-500">{desc} No API key required.</p></div>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${badgeCls}`}>{badge}</span>
            </label>
          ))}
          <label className="flex cursor-pointer items-center gap-3 px-5 py-4">
            <input type="checkbox" checked={config.sources.sam_gov} onChange={(e)=>setConfig((c)=>({...c,sources:{...c.sources,sam_gov:e.target.checked}}))} className="h-4 w-4 rounded border-slate-300 accent-brand"/>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-slate-800">SAM.gov</p>
              <p className="text-xs text-slate-500">Federal contract &amp; grant opportunities. API key managed in <a href="/admin/keys" className="text-brand hover:underline">API Keys</a>.</p>
            </div>
            <span className="shrink-0 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">Key needed</span>
          </label>
        </div>
      </div>

      {/* Save */}
      <div className="flex items-center gap-3">
        <Button onClick={handleSave} disabled={saving} className="flex items-center gap-2"><Save size={14}/>{saving?"Saving…":"Save configuration"}</Button>
        {saveStatus && <p className={`text-sm ${saveStatus.startsWith("Error")?"text-red-600":"text-emerald-600"}`}>{saveStatus}</p>}
      </div>

      {/* Run history */}
      <div className="card-base overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Run history</p>
          <Button variant="ghost" size="sm" onClick={loadRuns} disabled={runsLoading} className="flex items-center gap-1.5 text-xs">
            <RefreshCw size={11} className={runsLoading?"animate-spin":""}/>Refresh
          </Button>
        </div>
        {runs.length===0?(
          <div className="flex flex-col items-center gap-2 py-10 text-center"><Radar size={28} className="text-slate-200"/><p className="text-sm text-slate-400">No discovery runs yet.</p></div>
        ):(
          <div className="divide-y divide-slate-100">
            {runs.map((run)=>(
              <div key={run.id} className="flex items-center gap-4 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2"><StatusBadge status={run.status}/><TriggerBadge trigger={run.trigger}/><span className="text-xs text-slate-400">{run.started_at?new Date(run.started_at).toLocaleString():"—"}</span></div>
                  {run.error_message&&<p className="mt-0.5 truncate text-xs text-red-500">{run.error_message}</p>}
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-sm font-semibold">{run.urls_new>0?<span className="text-brand">{run.urls_new} new</span>:<span className="text-slate-400">0 new</span>}</p>
                  <p className="text-xs text-slate-400">{run.urls_discovered} found</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
