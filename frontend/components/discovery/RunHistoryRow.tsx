"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Loader2, Timer } from "lucide-react";
import { api, type ScrapedFundResult } from "../../lib/api";
import { DiscoverySourceBadge } from "../results/DiscoverySourceBadge";

// ── Types ─────────────────────────────────────────────────────────────────────

export type DiscoveryRun = {
  id: string;
  started_at: string;
  finished_at?: string;
  status: string;
  trigger: string;
  urls_discovered: number;
  urls_new: number;
  scrape_job_id?: string;
  error_message?: string;
  progress_snapshot?: {
    sources?: Record<string, { name: string; urls_found: number; urls_new: number; status?: string }>;
    latest_results?: Array<{ url: string; funder_name?: string; source?: string }>;
    documents_extracted?: number;
    documents_submitted?: number;
    started_at?: number | null;
    finished_at?: number | null;
    urls_discovered?: number;
    urls_new?: number;
  } | null;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatElapsed(seconds: number): string {
  if (!seconds || seconds < 0) return "0s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

export function StatusBadge({ status }: { status: string }) {
  const cls = (
    {
      running: "bg-brand/10 text-brand",
      running_docs: "bg-brand/10 text-brand",
      completed: "bg-emerald-50 text-emerald-700",
      failed: "bg-red-50 text-red-700",
      cancelled: "bg-amber-50 text-amber-700",
    } as Record<string, string>
  )[status] ?? "bg-slate-100 text-slate-600";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${cls}`}>
      {status}
    </span>
  );
}

export function TriggerBadge({ trigger }: { trigger: string }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
        trigger === "manual"
          ? "bg-indigo-50 text-indigo-700"
          : "bg-slate-100 text-slate-600"
      }`}
    >
      {trigger}
    </span>
  );
}

function PerSourceChips({
  snapshot,
}: {
  snapshot: DiscoveryRun["progress_snapshot"];
}) {
  const sources = snapshot?.sources;
  if (!sources) return null;
  const useful = Object.values(sources).filter(
    (s) => (s.urls_found || 0) > 0 || (s.urls_new || 0) > 0
  );
  if (useful.length === 0) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      {useful.map((s) => (
        <span
          key={s.name}
          className="flex items-center gap-1 rounded-full bg-slate-50 px-2 py-0.5 text-[10px] text-slate-600 ring-1 ring-slate-200"
        >
          <DiscoverySourceBadge source={s.name} />
          <span className="font-mono">
            {s.urls_new || 0}/{s.urls_found || 0}
          </span>
        </span>
      ))}
    </div>
  );
}

function CategoryChips({
  label,
  counts,
}: {
  label: string;
  counts: Record<string, number>;
}) {
  const entries = Object.entries(counts).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) return null;
  return (
    <div>
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {entries.map(([k, v]) => (
          <span
            key={k}
            className="rounded-full bg-white px-2 py-0.5 text-[11px] text-slate-600 ring-1 ring-slate-200"
          >
            {k} <span className="font-semibold text-slate-800">{v}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function RunHistoryRow({ run }: { run: DiscoveryRun }) {
  const [expanded, setExpanded] = useState(false);
  const [funds, setFunds] = useState<ScrapedFundResult[] | null>(null);
  const [loadingFunds, setLoadingFunds] = useState(false);
  const fetchedRef = useRef(false);

  const snap = run.progress_snapshot;
  const isDone = !["running", "running_docs"].includes(run.status);

  const durationSec = useMemo(() => {
    const s =
      snap?.started_at ??
      (run.started_at ? new Date(run.started_at).getTime() / 1000 : null);
    const e =
      snap?.finished_at ??
      (run.finished_at ? new Date(run.finished_at).getTime() / 1000 : null);
    if (!s || !e) return null;
    return Math.max(0, Math.round(e - s));
  }, [snap, run.started_at, run.finished_at]);

  useEffect(() => {
    if (!expanded || fetchedRef.current || !run.scrape_job_id || !isDone) return;
    fetchedRef.current = true;
    setLoadingFunds(true);
    api
      .discoveryRunScrapedFunds(run.id)
      .then(setFunds)
      .catch(() => setFunds([]))
      .finally(() => setLoadingFunds(false));
  }, [expanded, run.id, run.scrape_job_id, isDone]);

  const categoryCounts = useMemo(() => {
    if (!funds || funds.length === 0) return null;
    const elig: Record<string, number> = {};
    const types: Record<string, number> = {};
    for (const f of funds) {
      if (f.eligibility) elig[f.eligibility] = (elig[f.eligibility] || 0) + 1;
      if (f.grant_type) types[f.grant_type] = (types[f.grant_type] || 0) + 1;
    }
    return { elig, types };
  }, [funds]);

  const latestResults = snap?.latest_results ?? [];

  return (
    <div className="border-b border-slate-100 last:border-b-0">
      {/* Header row */}
      <button
        type="button"
        className="flex w-full cursor-pointer items-start gap-4 px-5 py-3 text-left hover:bg-slate-50"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={run.status} />
            <TriggerBadge trigger={run.trigger} />
            <span className="text-xs text-slate-400">
              {run.started_at
                ? new Date(run.started_at).toLocaleString()
                : "—"}
            </span>
            {durationSec !== null && (
              <span className="flex items-center gap-1 text-[11px] text-slate-400">
                <Timer size={10} />
                {formatElapsed(durationSec)}
              </span>
            )}
          </div>
          <PerSourceChips snapshot={snap} />
          {run.error_message && (
            <p className="mt-0.5 truncate text-xs text-red-500">
              {run.error_message}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <div className="text-right">
            <p className="text-sm font-semibold">
              {run.urls_new > 0 ? (
                <span className="text-brand">{run.urls_new} new</span>
              ) : (
                <span className="text-slate-400">0 new</span>
              )}
            </p>
            <p className="text-xs text-slate-400">{run.urls_discovered} found</p>
            {snap?.documents_extracted ? (
              <p className="mt-0.5 text-[10px] text-emerald-600">
                {snap.documents_extracted} docs
              </p>
            ) : null}
          </div>
          <ChevronDown
            size={14}
            className={`shrink-0 text-slate-400 transition-transform duration-200 ${
              expanded ? "rotate-180" : ""
            }`}
          />
        </div>
      </button>

      {/* Expanded panel */}
      {expanded && (
        <div className="space-y-4 border-t border-slate-100 bg-slate-50/60 px-5 py-4">
          {/* Discovered URLs from snapshot */}
          {latestResults.length > 0 && (
            <div>
              <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                Discovered URLs
                {latestResults.length < (run.urls_new || 0) && (
                  <span className="ml-1 font-normal normal-case text-slate-400">
                    (showing {latestResults.length} of {run.urls_new})
                  </span>
                )}
              </p>
              <div className="space-y-1">
                {latestResults.map((r, i) => (
                  <div
                    key={`${r.url}-${i}`}
                    className="flex items-center gap-2 rounded-lg bg-white px-3 py-1.5 text-xs ring-1 ring-slate-100"
                  >
                    {r.source && (
                      <DiscoverySourceBadge source={r.source} />
                    )}
                    <span className="min-w-0 flex-1 truncate text-slate-700">
                      {r.funder_name || r.url}
                    </span>
                    <a
                      href={r.url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="ml-auto shrink-0 text-slate-400 hover:text-brand"
                      title={r.url}
                    >
                      ↗
                    </a>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Scraped-fund category breakdown */}
          {isDone && run.scrape_job_id && (
            <div>
              <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                Scraped results
              </p>
              {loadingFunds && (
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <Loader2 size={11} className="animate-spin" /> Loading…
                </div>
              )}
              {!loadingFunds && funds !== null && funds.length === 0 && (
                <p className="text-xs text-slate-400">
                  No fund records found for this scrape job yet.
                </p>
              )}
              {!loadingFunds && categoryCounts && (
                <div className="space-y-3">
                  <CategoryChips
                    label="Eligibility"
                    counts={categoryCounts.elig}
                  />
                  <CategoryChips
                    label="Grant type"
                    counts={categoryCounts.types}
                  />
                  <p className="text-[11px] text-slate-500">
                    <span className="font-semibold text-slate-700">
                      {funds!.length}
                    </span>{" "}
                    fund{funds!.length !== 1 ? "s" : ""} in database from this
                    run ·{" "}
                    <a
                      href="/results"
                      onClick={(e) => e.stopPropagation()}
                      className="text-brand hover:underline"
                    >
                      View all results →
                    </a>
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Empty state */}
          {latestResults.length === 0 && !run.scrape_job_id && (
            <p className="text-xs text-slate-400">No details available for this run.</p>
          )}
        </div>
      )}
    </div>
  );
}
