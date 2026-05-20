"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, ExternalLink, Play, Radar, RefreshCw } from "lucide-react";
import ScrapeForm from "../components/ScrapeForm";
import { api } from "../lib/api";
import { Button } from "../components/ui/button";

type DiscoveryRun = {
  id: string; status: string; urls_discovered: number; urls_new: number;
  started_at?: string; finished_at?: string; error_message?: string; scrape_job_id?: string;
};

export default function HomePage() {
  const [isSuperuser, setIsSuperuser] = useState(false);
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [activeRun, setActiveRun] = useState<DiscoveryRun | null>(null);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api.adminUsers()
      .then(() => {
        setIsSuperuser(true);
        return api.discoveryConfig();
      })
      .then((c: any) => setAutoEnabled(c?.enabled ?? false))
      .catch(() => {});
  }, []);

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const startPolling = (runId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const run = await api.discoveryRunStatus(runId);
        setActiveRun(run);
        if (run.status !== "running") {
          clearInterval(pollRef.current!); pollRef.current = null;
          setTriggerLoading(false);
        }
      } catch {
        clearInterval(pollRef.current!); pollRef.current = null;
        setTriggerLoading(false);
      }
    }, 3000);
  };

  const handleTrigger = async () => {
    setTriggerLoading(true); setTriggerError(null); setActiveRun(null);
    try {
      const { id } = await api.triggerDiscoveryRun();
      setActiveRun({ id, status: "running", urls_discovered: 0, urls_new: 0, started_at: new Date().toISOString() });
      startPolling(id);
    } catch (e: any) {
      setTriggerError(e.message || "Failed to start discovery run");
      setTriggerLoading(false);
    }
  };

  return (
    <div className="page-content space-y-6">
      <header>
        <p className="text-xs font-medium uppercase tracking-widest text-slate-400">Dashboard</p>
        <h1 className="mt-0.5 text-2xl font-bold text-slate-900">Discover Funding Opportunities</h1>
        <p className="mt-1 text-sm text-slate-500">
          Paste URLs or upload a CSV to scrape and analyze funding sources.
        </p>
      </header>

      {/* Auto-discovery trigger — superusers only */}
      {isSuperuser && (
        <div className="card-base overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand/10 text-brand">
                <Radar size={15} />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-800">Auto-Discovery</p>
                <p className="text-xs text-slate-500">
                  {autoEnabled ? "Scheduled — runs automatically." : "Manual trigger only."}
                  {" "}<a href="/admin/discovery" className="text-brand hover:underline">Configure schedule</a>
                </p>
              </div>
            </div>
            <Button onClick={handleTrigger} disabled={triggerLoading} className="flex items-center gap-2">
              {triggerLoading ? <RefreshCw size={13} className="animate-spin" /> : <Play size={13} />}
              {triggerLoading ? "Running…" : "Run now"}
            </Button>
          </div>

          {(activeRun || triggerError) && (
            <div className="p-5 space-y-3">
              {triggerError && (
                <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                  <AlertCircle size={13} /> {triggerError}
                </div>
              )}
              {activeRun && (
                <>
                  <div className="flex items-center gap-2">
                    {activeRun.status === "running" && <RefreshCw size={13} className="animate-spin text-brand" />}
                    {activeRun.status === "completed" && <CheckCircle2 size={13} className="text-emerald-500" />}
                    {activeRun.status === "failed" && <AlertCircle size={13} className="text-red-500" />}
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${{ running:"bg-brand/10 text-brand", completed:"bg-emerald-50 text-emerald-700", failed:"bg-red-50 text-red-700" }[activeRun.status] ?? "bg-slate-100 text-slate-600"}`}>
                      {activeRun.status}
                    </span>
                    <span className="font-mono text-xs text-slate-400">{activeRun.id.slice(0, 12)}…</span>
                  </div>
                  {activeRun.status === "completed" && (
                    <div className="grid grid-cols-3 gap-4 rounded-lg border border-slate-200 bg-slate-50/60 p-3 text-center">
                      <div><p className="text-lg font-bold text-slate-900">{activeRun.urls_discovered}</p><p className="text-xs text-slate-500">URLs found</p></div>
                      <div><p className="text-lg font-bold text-brand">{activeRun.urls_new}</p><p className="text-xs text-slate-500">New to scrape</p></div>
                      <div>
                        {activeRun.scrape_job_id ? (
                          <>
                            <p className="text-lg font-bold text-emerald-600">✓</p>
                            <p className="text-xs text-slate-500">Scrape queued</p>
                          </>
                        ) : (
                          <>
                            <p className="text-lg font-bold text-slate-400">—</p>
                            <p className="text-xs text-slate-500">No new URLs</p>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                  {activeRun.status === "completed" && activeRun.urls_new > 0 && (
                    <a href="/results" className="inline-flex items-center gap-1.5 text-xs font-medium text-brand hover:underline">
                      <ExternalLink size={12} />View results when ready
                    </a>
                  )}
                  {activeRun.status === "failed" && activeRun.error_message && (
                    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                      {activeRun.error_message}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}

      <ScrapeForm />
    </div>
  );
}
