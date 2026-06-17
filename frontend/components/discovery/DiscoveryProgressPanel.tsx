"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Loader2,
  StopCircle,
  Timer,
  X,
  XCircle,
} from "lucide-react";
import { api, type DiscoveryProgress, type JobStatusResponse, type ScrapedFundResult } from "../../lib/api";
import { Button } from "../ui/button";
import { SourceProgressCard } from "./SourceProgressCard";
import { DiscoverySourceBadge } from "../results/DiscoverySourceBadge";

type Props = {
  progress: DiscoveryProgress;
  cancelling?: boolean;
  onCancel?: () => void;
  onDismiss?: () => void;
};

const RUN_STATUS_LABEL: Record<string, string> = {
  running: "Discovering sources",
  running_docs: "Analyzing documents",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

function formatElapsed(seconds: number): string {
  if (!seconds || seconds < 0) return "0s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function useLiveElapsed(progress: DiscoveryProgress): number {
  const [now, setNow] = useState<number>(() => Date.now() / 1000);
  const isLive = ["running", "running_docs"].includes(progress.status);
  useEffect(() => {
    if (!isLive) return;
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, [isLive]);
  if (!progress.started_at) return progress.elapsed_seconds || 0;
  const end = progress.finished_at ?? now;
  return Math.max(0, Math.round(end - progress.started_at));
}

// ── Inline scrape-job progress ────────────────────────────────────────────────

function ScrapeJobProgress({ jobId, onDone }: { jobId: string; onDone?: () => void }) {
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const doneFiredRef = useRef(false);

  useEffect(() => {
    let active = true;

    const fetchJob = async () => {
      try {
        const status = await api.jobStatus(jobId);
        if (!active) return;
        setJob(status);
        if (status.done && !doneFiredRef.current) {
          doneFiredRef.current = true;
          onDone?.();
        }
      } catch { /* swallow */ }
    };

    fetchJob();
    const interval = setInterval(fetchJob, 2500);
    return () => { active = false; clearInterval(interval); };
  }, [jobId, onDone]);

  if (!job) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs text-slate-400">
        <Loader2 size={11} className="animate-spin" />
        Loading scrape progress…
      </div>
    );
  }

  const pending = Math.max(0, job.total_urls - job.completed_urls);
  const pct = job.progress_percent ?? 0;

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
        <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
          Scrape job
        </p>
        <span className="ml-auto font-mono text-[10px] text-slate-400">
          {jobId.slice(0, 8)}…
        </span>
      </div>

      <div className="space-y-2.5 p-3">
        {/* Status + timer */}
        <div className="flex items-center gap-2">
          {job.done
            ? <CheckCircle2 size={13} className="shrink-0 text-emerald-500" />
            : <Loader2 size={13} className="shrink-0 animate-spin text-brand" />}
          <p className="text-xs font-semibold text-slate-800">
            {job.done ? "Scrape complete" : "Scraping queued URLs"}
          </p>
          <span className="ml-auto flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
            <Timer size={10} />
            {formatElapsed(job.total_elapsed_seconds)}
          </span>
        </div>

        {/* Progress bar */}
        <div className="overflow-hidden rounded-full bg-slate-100" style={{ height: 6 }}>
          <div
            className="h-full rounded-full bg-brand transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>

        {/* Current URL */}
        {job.current_url && !job.done && (
          <p className="truncate text-[11px] text-slate-500">
            <span className="font-medium text-slate-700">Scraping: </span>
            {job.current_url}
          </p>
        )}

        {/* Stats row */}
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
          <span>
            <span className="font-semibold text-slate-700">{job.completed_urls}</span>
            /{job.total_urls} scraped
          </span>
          {pending > 0 && (
            <span>
              <span className="font-semibold text-slate-700">{pending}</span> in queue
            </span>
          )}
          {job.errors.length > 0 && (
            <span className="text-red-500">
              {job.errors.length} error{job.errors.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function DiscoveryProgressPanel({ progress, cancelling, onCancel, onDismiss }: Props) {
  const elapsed = useLiveElapsed(progress);
  const isRunning = ["running", "running_docs"].includes(progress.status);
  const isDone = !isRunning;

  const [scrapedFunds, setScrapedFunds] = useState<ScrapedFundResult[] | null>(null);
  const [loadingStats, setLoadingStats] = useState(false);
  const statsFetchedRef = useRef(false);

  const fetchStats = useCallback(() => {
    if (statsFetchedRef.current || !progress.scrape_job_id) return;
    statsFetchedRef.current = true;
    setLoadingStats(true);
    api
      .discoveryRunScrapedFunds(progress.run_id)
      .then(setScrapedFunds)
      .catch(() => setScrapedFunds([]))
      .finally(() => setLoadingStats(false));
  }, [progress.run_id, progress.scrape_job_id]);

  // If panel mounts in a completed state (restored from localStorage), fetch immediately.
  useEffect(() => {
    if (isDone && progress.scrape_job_id) fetchStats();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const sortedSources = Object.values(progress.sources || {}).sort((a, b) => {
    const aActive = a.status === "running" ? 0 : 1;
    const bActive = b.status === "running" ? 0 : 1;
    if (aActive !== bActive) return aActive - bActive;
    return (b.urls_found || 0) - (a.urls_found || 0);
  });

  return (
    <div className="space-y-4 p-5">
      {/* Header row */}
      <div className="flex flex-wrap items-center gap-2.5">
        <RunStatusIcon status={progress.status} />
        <p className="text-sm font-semibold text-slate-800">
          {RUN_STATUS_LABEL[progress.status] ?? progress.status}
        </p>
        <span className="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
          <Timer size={11} />
          {formatElapsed(elapsed)}
        </span>
        <span className="font-mono text-[11px] text-slate-400">{progress.run_id.slice(0, 12)}…</span>

        <div className="ml-auto flex items-center gap-1.5">
          {isRunning && onCancel && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onCancel}
              disabled={cancelling}
              className="flex items-center gap-1.5 text-xs text-red-600 hover:bg-red-50"
            >
              <StopCircle size={12} />
              {cancelling ? "Cancelling…" : "Cancel"}
            </Button>
          )}
          {isDone && onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              className="flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              title="Dismiss"
            >
              <X size={12} /> Dismiss
            </button>
          )}
        </div>
      </div>

      {progress.error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          <AlertCircle size={13} /> {progress.error}
        </div>
      )}

      {/* Per-source grid */}
      {sortedSources.length > 0 && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {sortedSources.map((s) => (
            <SourceProgressCard key={s.name} source={s} />
          ))}
        </div>
      )}

      {/* Aggregate counters */}
      <div className="grid grid-cols-2 gap-3 rounded-lg border border-slate-200 bg-slate-50/60 p-3 sm:grid-cols-4">
        <Counter label="URLs found" value={progress.urls_discovered} />
        <Counter label="New to scrape" value={progress.urls_new} brand />
        <Counter
          label="Docs extracted"
          value={progress.documents_extracted}
          sub={
            progress.documents_submitted > 0
              ? `${progress.documents_submitted} submitted${
                  progress.documents_skipped_dedup > 0
                    ? ` · ${progress.documents_skipped_dedup} deduped`
                    : ""
                }`
              : null
          }
          icon={<FileText size={11} />}
        />
        <Counter
          label="Doc errors"
          value={progress.documents_errors}
          danger={progress.documents_errors > 0}
        />
      </div>

      {/* Live results preview */}
      {progress.latest_results && progress.latest_results.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white">
          <p className="border-b border-slate-100 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Latest discoveries
          </p>
          <ul className="divide-y divide-slate-100">
            {progress.latest_results.slice(0, 5).map((r, i) => (
              <li key={`${r.url}-${i}`} className="flex items-center gap-2 px-3 py-2 text-xs">
                {r.source && <DiscoverySourceBadge source={r.source} />}
                <span className="truncate text-slate-700">{r.funder_name || r.url}</span>
                <a
                  href={r.url}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-auto text-slate-400 hover:text-brand"
                  title={r.url}
                >
                  ↗
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Inline scrape job progress */}
      {progress.scrape_job_id && (
        <ScrapeJobProgress jobId={progress.scrape_job_id} onDone={fetchStats} />
      )}

      {/* Post-scrape category breakdown — shown after scrape job finishes */}
      {(loadingStats || scrapedFunds !== null) && (
        <div className="rounded-lg border border-slate-200 bg-white">
          <p className="border-b border-slate-100 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Scraped results
          </p>
          {loadingStats && (
            <div className="flex items-center gap-2 px-3 py-3 text-xs text-slate-400">
              <Loader2 size={11} className="animate-spin" /> Loading breakdown…
            </div>
          )}
          {!loadingStats && scrapedFunds !== null && scrapedFunds.length === 0 && (
            <p className="px-3 py-3 text-xs text-slate-400">
              No fund records found in the database for this run yet.
            </p>
          )}
          {!loadingStats && scrapedFunds !== null && scrapedFunds.length > 0 && (
            <ScrapedFundsStats funds={scrapedFunds} />
          )}
        </div>
      )}
    </div>
  );
}

// ── Scraped funds stats ───────────────────────────────────────────────────────

function ScrapedFundsStats({ funds }: { funds: ScrapedFundResult[] }) {
  const elig: Record<string, number> = {};
  const types: Record<string, number> = {};
  for (const f of funds) {
    if (f.eligibility) elig[f.eligibility] = (elig[f.eligibility] || 0) + 1;
    if (f.grant_type) types[f.grant_type] = (types[f.grant_type] || 0) + 1;
  }
  const eligEntries = Object.entries(elig).sort(([, a], [, b]) => b - a);
  const typeEntries = Object.entries(types).sort(([, a], [, b]) => b - a);

  return (
    <div className="space-y-3 p-3">
      <p className="text-[11px] text-slate-500">
        <span className="font-semibold text-slate-800">{funds.length}</span>{" "}
        fund{funds.length !== 1 ? "s" : ""} stored ·{" "}
        <a href="/results" className="text-brand hover:underline">
          View all results →
        </a>
      </p>
      {eligEntries.length > 0 && (
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Eligibility
          </p>
          <div className="flex flex-wrap gap-1.5">
            {eligEntries.map(([k, v]) => (
              <span
                key={k}
                className="rounded-full bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600 ring-1 ring-slate-200"
              >
                {k}{" "}
                <span className="font-semibold text-slate-800">{v}</span>
              </span>
            ))}
          </div>
        </div>
      )}
      {typeEntries.length > 0 && (
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Grant type
          </p>
          <div className="flex flex-wrap gap-1.5">
            {typeEntries.map(([k, v]) => (
              <span
                key={k}
                className="rounded-full bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600 ring-1 ring-slate-200"
              >
                {k}{" "}
                <span className="font-semibold text-slate-800">{v}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function RunStatusIcon({ status }: { status: string }) {
  if (status === "running" || status === "running_docs")
    return <Loader2 size={14} className="animate-spin text-brand" />;
  if (status === "completed") return <CheckCircle2 size={14} className="text-emerald-500" />;
  if (status === "failed") return <XCircle size={14} className="text-red-500" />;
  if (status === "cancelled") return <AlertCircle size={14} className="text-amber-500" />;
  return null;
}

function Counter({
  label, value, sub, brand, danger, icon,
}: {
  label: string; value: number; sub?: string | null;
  brand?: boolean; danger?: boolean; icon?: React.ReactNode;
}) {
  const cls = danger ? "text-red-600" : brand ? "text-brand" : "text-slate-900";
  return (
    <div className="text-center">
      <p className={`text-xl font-bold ${cls}`}>{value}</p>
      <p className="flex items-center justify-center gap-1 text-[10px] uppercase tracking-wider text-slate-400">
        {icon} {label}
      </p>
      {sub && <p className="mt-0.5 text-[10px] text-slate-400">{sub}</p>}
    </div>
  );
}
