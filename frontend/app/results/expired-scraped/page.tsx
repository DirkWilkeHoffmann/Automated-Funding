"use client";

import type { ChangeEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Inbox,
  Link2,
  Play,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../../../lib/api";
import { writeCache } from "../../../lib/storage";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Progress } from "../../../components/ui/progress";

const RESULTS_FORCE_REFRESH_KEY = "results_force_refresh_v1";

type ResultRecord = Record<string, any>;

type JobStatus = {
  job_id: string;
  done: boolean;
  progress_percent: number;
  results: any[];
  errors: { url: string; message: string }[];
  current_url?: string | null;
  current_elapsed_seconds?: number;
  total_elapsed_seconds?: number;
  started_at?: number | null;
  finished_at?: number | null;
  url_timings?: {
    url: string;
    duration_seconds: number;
    started_at?: number | null;
    finished_at?: number | null;
    error?: string | null;
  }[];
  total_urls?: number;
  completed_urls?: number;
};

function normalizeUrlClient(url?: string): string {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    const path = parsed.pathname.replace(/\/$/, "");
    return `${parsed.protocol}//${parsed.host}${path}${parsed.search}`;
  } catch {
    return url;
  }
}

function parseTimestampMs(value: any): number | null {
  if (!value) return null;
  const direct = new Date(value);
  if (!Number.isNaN(direct.getTime())) return direct.getTime();
  if (typeof value === "string") {
    const normalized = value.trim().replace(" ", "T");
    const fallback = new Date(normalized);
    if (!Number.isNaN(fallback.getTime())) return fallback.getTime();
  }
  return null;
}

function compareTimestampValues(a: any, b: any): number {
  const aMs = parseTimestampMs(a);
  const bMs = parseTimestampMs(b);
  if (aMs === null && bMs === null) return 0;
  if (aMs === null) return -1;
  if (bMs === null) return 1;
  return aMs - bMs;
}

function formatAgeLabel(timestamp: any): string | null {
  const parsedMs = parseTimestampMs(timestamp);
  if (parsedMs === null) return null;
  const diffMs = Date.now() - parsedMs;
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (days < 1) return "today";
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

function formatTimestamp(value: any) {
  const parsedMs = parseTimestampMs(value);
  if (parsedMs === null) return value ? String(value) : "-";
  return new Date(parsedMs).toLocaleString();
}

function formatSeconds(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  return [
    hours > 0 ? `${hours}h` : null,
    minutes > 0 ? `${minutes}m` : null,
    `${seconds}s`,
  ]
    .filter(Boolean)
    .join(" ");
}

function getDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function FaviconImg({ url }: { url: string }) {
  const [errored, setErrored] = useState(false);
  const domain = getDomain(url);
  if (errored || !url) {
    return (
      <div className="flex h-5 w-5 items-center justify-center rounded bg-slate-100">
        <Link2 size={10} className="text-slate-400" />
      </div>
    );
  }
  return (
    <img
      src={`https://www.google.com/s2/favicons?domain=${domain}&sz=16`}
      alt=""
      width={16}
      height={16}
      className="h-4 w-4 rounded"
      onError={() => setErrored(true)}
    />
  );
}

const eligibilityVariantMap: Record<string, any> = {
  "Highly Eligible": "highly-eligible",
  Eligible: "eligible",
  "Possibly Eligible": "possibly-eligible",
  "Low Match": "low-match",
  "Not Eligible": "not-eligible",
};

export default function ExpiredScrapedPage() {
  const [staleFunds, setStaleFunds] = useState<ResultRecord[]>([]);
  const [staleChecked, setStaleChecked] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [queuedUrls, setQueuedUrls] = useState<string[]>([]);
  const [staleLoading, setStaleLoading] = useState(false);
  const [staleError, setStaleError] = useState<string | null>(null);
  const [cutoffTimestamp, setCutoffTimestamp] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [isScraping, setIsScraping] = useState(false);
  const [errorsOpen, setErrorsOpen] = useState(false);
  const [timingsOpen, setTimingsOpen] = useState(false);
  const lastCompletedJobId = useRef<string | null>(null);

  const latestStaleFunds = useMemo(() => {
    const latestByKey = new Map<string, ResultRecord>();
    staleFunds.forEach((row) => {
      const key = normalizeUrlClient(row?.fund_url) || row?.fund_url || row?.fund_name || "";
      if (!key) return;
      const current = latestByKey.get(key);
      if (
        !current ||
        compareTimestampValues(row?.extraction_timestamp, current?.extraction_timestamp) > 0
      ) {
        latestByKey.set(key, row);
      }
    });
    return Array.from(latestByKey.values());
  }, [staleFunds]);

  const staleOptions = useMemo(() => {
    const seen = new Set<string>();
    const queuedSet = new Set(queuedUrls);
    const options: {
      value: string;
      name: string;
      url: string;
      age: string | null;
      disabled: boolean;
    }[] = [];

    latestStaleFunds.forEach((row) => {
      const normalized = normalizeUrlClient(row?.fund_url);
      const value = normalized || row?.fund_url || row?.fund_name || "";
      if (!value || seen.has(value)) return;
      seen.add(value);
      options.push({
        value,
        name: row?.fund_name || getDomain(row?.fund_url || value),
        url: row?.fund_url || value,
        age: formatAgeLabel(row?.extraction_timestamp),
        disabled: queuedSet.has(value),
      });
    });

    return options;
  }, [latestStaleFunds, queuedUrls]);

  const filteredOptions = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return staleOptions;
    return staleOptions.filter(
      (o) => o.name.toLowerCase().includes(q) || o.url.toLowerCase().includes(q)
    );
  }, [staleOptions, search]);

  const queueLookup = useMemo(() => {
    const map = new Map<string, ResultRecord>();
    latestStaleFunds.forEach((row) => {
      const key = normalizeUrlClient(row?.fund_url) || row?.fund_url || row?.fund_name;
      if (key && !map.has(key)) map.set(key, row);
    });
    return map;
  }, [latestStaleFunds]);

  const loadStaleFunds = async (forceRefresh = false) => {
    setStaleLoading(true);
    setStaleError(null);
    try {
      const res = await api.staleResults(3, { forceRefresh });
      setStaleFunds(res.results || []);
      setCutoffTimestamp(res.cutoff_timestamp || null);
    } catch (err: any) {
      setStaleError(err.message || "Failed to load stale funds.");
    } finally {
      setStaleLoading(false);
    }
  };

  useEffect(() => {
    loadStaleFunds();
  }, []);

  useEffect(() => {
    if (!job || !job.done) return;
    if (lastCompletedJobId.current === job.job_id) return;
    lastCompletedJobId.current = job.job_id;
    writeCache(RESULTS_FORCE_REFRESH_KEY, { jobId: job.job_id, completedAt: Date.now() });
  }, [job]);

  useEffect(() => {
    if (!job || job.done) return;
    const interval = setInterval(async () => {
      try {
        const status = await api.jobStatus(job.job_id);
        setJob(status);
      } catch (err) {
        console.error(err);
      }
    }, 4000);
    return () => clearInterval(interval);
  }, [job]);

  const toggleCheck = (value: string) => {
    setStaleChecked((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  };

  const toggleAll = () => {
    const eligible = filteredOptions.filter((o) => !o.disabled).map((o) => o.value);
    const allChecked = eligible.every((v) => staleChecked.has(v));
    setStaleChecked((prev) => {
      const next = new Set(prev);
      if (allChecked) eligible.forEach((v) => next.delete(v));
      else eligible.forEach((v) => next.add(v));
      return next;
    });
  };

  const queueSelection = () => {
    const toAdd = Array.from(staleChecked);
    if (toAdd.length === 0) return;
    setQueuedUrls((prev) => {
      const next = [...prev];
      toAdd.forEach((url) => {
        if (!next.includes(url)) next.push(url);
      });
      return next;
    });
    setStaleChecked(new Set());
  };

  const removeFromQueue = (url: string) => {
    setQueuedUrls((prev) => prev.filter((u) => u !== url));
  };

  const clearQueue = () => setQueuedUrls([]);

  const startRescrape = async () => {
    if (queuedUrls.length === 0) return;
    setIsScraping(true);
    setJobError(null);
    try {
      const payload = await api.scrapeBatch([], queuedUrls, { rescrapeScope: "any" });
      const status = await api.jobStatus(payload.job_id);
      setJob(status);
      setQueuedUrls([]);
      setStaleChecked(new Set());
    } catch (err: any) {
      setJobError(err.message || "Failed to start rescrape job.");
    } finally {
      setIsScraping(false);
    }
  };

  const clearCompletedJob = () => {
    setJob(null);
    setJobError(null);
    lastCompletedJobId.current = null;
  };

  const eligibleToCheck = filteredOptions.filter((o) => !o.disabled);
  const allFilteredChecked =
    eligibleToCheck.length > 0 && eligibleToCheck.every((o) => staleChecked.has(o.value));

  const progressValue = job ? Math.max(0, Math.min(100, Number(job.progress_percent) || 0)) : 0;

  return (
    <div className="page-content space-y-6">
      <header>
        <p className="text-xs font-medium uppercase tracking-widest text-slate-400">Results</p>
        <h1 className="mt-0.5 text-2xl font-bold text-slate-900">Stale Funds</h1>
        <p className="mt-1 text-sm text-slate-500">
          Queue funds that haven&apos;t been scraped recently and monitor the rescrape in real time.
        </p>
      </header>

      {/* Stale fund selector */}
      <div className="card-base overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Available stale funds</p>
            {cutoffTimestamp && (
              <p className="mt-0.5 text-xs text-slate-500">
                Cutoff: {formatTimestamp(cutoffTimestamp)}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {latestStaleFunds.length > 0 && (
              <span className="stat-pill">{latestStaleFunds.length} stale</span>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => loadStaleFunds(true)}
              disabled={staleLoading}
              className="flex items-center gap-1.5"
            >
              <RefreshCw size={13} className={staleLoading ? "animate-spin" : ""} />
              {staleLoading ? "Refreshing…" : "Refresh"}
            </Button>
          </div>
        </div>

        <div className="p-5 space-y-3">
          {staleError && (
            <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              <AlertCircle size={14} className="shrink-0" />
              {staleError}
            </div>
          )}

          {staleLoading && (
            <div className="space-y-2 py-2">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="flex items-center gap-3">
                  <div className="h-4 w-4 animate-pulse rounded bg-slate-100" />
                  <div className="h-4 flex-1 animate-pulse rounded bg-slate-100" />
                  <div className="h-4 w-16 animate-pulse rounded bg-slate-100" />
                </div>
              ))}
            </div>
          )}

          {!staleLoading && staleOptions.length === 0 && (
            <div className="flex flex-col items-center gap-2 py-8 text-center">
              <Inbox size={28} className="text-slate-300" />
              <p className="text-sm text-slate-500">No stale funds found.</p>
            </div>
          )}

          {!staleLoading && staleOptions.length > 0 && (
            <>
              {/* Search */}
              <div className="relative">
                <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search funds…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2 pl-8 pr-8 text-sm text-slate-700 placeholder:text-slate-400 focus:border-brand/50 focus:outline-none focus:ring-2 focus:ring-brand/10"
                />
                {search && (
                  <button
                    type="button"
                    onClick={() => setSearch("")}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>

              {/* Select all */}
              <div className="flex items-center justify-between">
                <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-slate-600">
                  <input
                    type="checkbox"
                    checked={allFilteredChecked}
                    onChange={toggleAll}
                    disabled={eligibleToCheck.length === 0}
                    className="h-3.5 w-3.5 cursor-pointer rounded border-slate-300 accent-brand"
                  />
                  Select all ({eligibleToCheck.length})
                </label>
                {staleChecked.size > 0 && (
                  <span className="text-xs text-brand font-medium">{staleChecked.size} selected</span>
                )}
              </div>

              {/* Checkbox list */}
              <div className="max-h-72 overflow-y-auto rounded-lg border border-slate-200 divide-y divide-slate-100">
                {filteredOptions.length === 0 ? (
                  <p className="py-4 text-center text-sm text-slate-400">No matches</p>
                ) : (
                  filteredOptions.map((opt) => (
                    <label
                      key={opt.value}
                      className={[
                        "flex cursor-pointer items-center gap-3 px-3 py-2.5 transition-colors",
                        opt.disabled
                          ? "bg-slate-50 opacity-50 cursor-not-allowed"
                          : "hover:bg-slate-50",
                        staleChecked.has(opt.value) ? "bg-brand/5" : "",
                      ].join(" ")}
                    >
                      <input
                        type="checkbox"
                        checked={staleChecked.has(opt.value)}
                        disabled={opt.disabled}
                        onChange={() => !opt.disabled && toggleCheck(opt.value)}
                        className="h-3.5 w-3.5 shrink-0 rounded border-slate-300 accent-brand"
                      />
                      <FaviconImg url={opt.url} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-slate-800">{opt.name}</p>
                        <p className="truncate text-xs text-slate-400">{getDomain(opt.url)}</p>
                      </div>
                      {opt.age && (
                        <span className="shrink-0 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                          {opt.age}
                        </span>
                      )}
                      {opt.disabled && (
                        <span className="shrink-0 text-[10px] text-slate-400">queued</span>
                      )}
                    </label>
                  ))
                )}
              </div>

              <Button
                onClick={queueSelection}
                disabled={staleChecked.size === 0}
                className="w-full"
                size="sm"
              >
                Add {staleChecked.size > 0 ? `${staleChecked.size} ` : ""}to queue
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Rescrape queue */}
      <div className="card-base overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Rescrape queue</p>
            <p className="mt-0.5 text-xs text-slate-500">
              Queued funds will be re-scraped and appended as new rows.
            </p>
          </div>
          {queuedUrls.length > 0 && (
            <span className="stat-pill">{queuedUrls.length} queued</span>
          )}
        </div>

        <div className="p-5 space-y-4">
          {queuedUrls.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-6 text-center">
              <Inbox size={24} className="text-slate-300" />
              <p className="text-sm text-slate-400">
                Nothing queued yet. Select funds above to add them.
              </p>
            </div>
          ) : (
            <ul className="space-y-2">
              {queuedUrls.map((url, idx) => {
                const row = queueLookup.get(url);
                const name = row?.fund_name || getDomain(url);
                const age = formatAgeLabel(row?.extraction_timestamp);
                return (
                  <li
                    key={url}
                    className="flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50/60 px-3 py-2.5"
                  >
                    <span className="w-5 shrink-0 text-center text-[10px] font-medium text-slate-400">
                      {idx + 1}
                    </span>
                    <FaviconImg url={url} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-slate-900">{name}</p>
                      <p className="truncate text-xs text-slate-400">{getDomain(url)}</p>
                    </div>
                    {age && (
                      <span className="shrink-0 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                        {age}
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => removeFromQueue(url)}
                      className="shrink-0 rounded-lg p-1 text-slate-400 transition hover:bg-red-50 hover:text-red-500"
                      aria-label="Remove from queue"
                    >
                      <X size={13} />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          {jobError && (
            <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              <AlertCircle size={14} className="shrink-0" />
              {jobError}
            </div>
          )}

          {/* Summary + actions */}
          {queuedUrls.length > 0 && (
            <div className="rounded-xl border border-brand/20 bg-brand/5 px-4 py-3">
              <p className="text-sm font-semibold text-slate-800">
                {queuedUrls.length} {queuedUrls.length === 1 ? "fund" : "funds"} ready to rescrape
              </p>
              <p className="mt-0.5 text-xs text-slate-500">
                Results will appear on the main Results page when complete.
              </p>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={clearQueue}
              disabled={queuedUrls.length === 0 || isScraping}
              className="flex items-center gap-1.5 text-slate-500"
            >
              <Trash2 size={13} />
              Clear queue
            </Button>
            <Button
              onClick={startRescrape}
              disabled={queuedUrls.length === 0 || isScraping}
              className="flex items-center gap-2"
            >
              <Play size={14} />
              {isScraping
                ? "Starting…"
                : `Rescrape ${queuedUrls.length > 0 ? queuedUrls.length : ""} fund${queuedUrls.length !== 1 ? "s" : ""}`}
            </Button>
          </div>
        </div>
      </div>

      {/* Job monitor */}
      {job && (
        <div className="card-base overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div className="flex items-center gap-2.5">
              {job.done ? (
                <CheckCircle2 size={16} className="text-emerald-500" />
              ) : (
                <RefreshCw size={16} className="animate-spin text-brand" />
              )}
              <div>
                <p className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Job monitor
                </p>
                <p className="text-xs text-slate-500 font-mono">{job.job_id.slice(0, 12)}…</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span
                className={[
                  "rounded-full px-2 py-0.5 text-[10px] font-semibold",
                  job.done
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-brand/10 text-brand",
                ].join(" ")}
              >
                {job.done ? "Done" : "Running"}
              </span>
              {job.done && (
                <Button variant="ghost" size="sm" onClick={clearCompletedJob}>
                  <X size={13} />
                </Button>
              )}
            </div>
          </div>

          <div className="p-5 space-y-4">
            {/* Progress */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>
                  {job.completed_urls || job.results.length}/{job.total_urls || "?"} funds
                </span>
                <span>{progressValue}%</span>
              </div>
              <Progress value={progressValue} />
              <div className="flex items-center gap-1.5 text-xs text-slate-400">
                <Clock size={11} />
                Total elapsed: {formatSeconds(job.total_elapsed_seconds || 0)}
              </div>
            </div>

            {/* Current URL */}
            {job.current_url && !job.done && (
              <div className="card-section">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Currently scraping
                </p>
                <p className="truncate font-mono text-xs text-slate-700">{job.current_url}</p>
                <p className="mt-1 text-[11px] text-slate-400">
                  Elapsed: {formatSeconds(job.current_elapsed_seconds || 0)}
                </p>
              </div>
            )}

            {/* Latest results */}
            {job.results.length > 0 && (
              <div className="space-y-2">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Latest results
                </p>
                <ul className="space-y-2">
                  {job.results
                    .slice(-5)
                    .reverse()
                    .map((res) => (
                      <li
                        key={`${res.fund_url}-${res.fund_name}`}
                        className="flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2"
                      >
                        <FaviconImg url={res.fund_url || ""} />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold text-slate-900">
                            {res.fund_name || res.fund_url}
                          </p>
                          {res.fund_url && (
                            <p className="truncate text-xs text-slate-400">
                              {getDomain(res.fund_url)}
                            </p>
                          )}
                        </div>
                        {res.eligibility && (
                          <Badge
                            variant={
                              eligibilityVariantMap[res.eligibility] || "outline"
                            }
                            className="shrink-0 whitespace-nowrap"
                          >
                            {res.eligibility}
                          </Badge>
                        )}
                      </li>
                    ))}
                </ul>
              </div>
            )}

            {/* Errors collapsible */}
            {job.errors.length > 0 && (
              <div className="rounded-lg border border-red-100 overflow-hidden">
                <button
                  type="button"
                  onClick={() => setErrorsOpen((v) => !v)}
                  className="flex w-full items-center justify-between px-4 py-2.5 bg-red-50 text-left"
                >
                  <span className="text-xs font-semibold text-red-700">
                    {job.errors.length} error{job.errors.length !== 1 ? "s" : ""}
                  </span>
                  {errorsOpen ? (
                    <ChevronDown size={13} className="text-red-500" />
                  ) : (
                    <ChevronRight size={13} className="text-red-500" />
                  )}
                </button>
                {errorsOpen && (
                  <ul className="divide-y divide-red-50">
                    {job.errors.map((err) => (
                      <li key={err.url} className="px-4 py-2.5">
                        <p className="truncate text-xs font-medium text-red-700">{err.url}</p>
                        <p className="text-xs text-red-500">{err.message}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {/* Timings collapsible */}
            {job.url_timings && job.url_timings.length > 0 && (
              <div className="rounded-lg border border-slate-200 overflow-hidden">
                <button
                  type="button"
                  onClick={() => setTimingsOpen((v) => !v)}
                  className="flex w-full items-center justify-between px-4 py-2.5 bg-slate-50 text-left"
                >
                  <span className="text-xs font-semibold text-slate-600">
                    Per-fund timing ({job.url_timings.length})
                  </span>
                  {timingsOpen ? (
                    <ChevronDown size={13} className="text-slate-400" />
                  ) : (
                    <ChevronRight size={13} className="text-slate-400" />
                  )}
                </button>
                {timingsOpen && (
                  <ul className="divide-y divide-slate-100">
                    {job.url_timings
                      .slice()
                      .reverse()
                      .map((t) => (
                        <li
                          key={`${t.url}-${t.finished_at || t.started_at}`}
                          className="flex items-center gap-3 px-4 py-2.5"
                        >
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-xs font-medium text-slate-700">{t.url}</p>
                            {t.error && (
                              <p className="text-[11px] text-red-500">{t.error}</p>
                            )}
                          </div>
                          <span className="shrink-0 text-xs text-slate-400">
                            {formatSeconds(t.duration_seconds || 0)}
                          </span>
                        </li>
                      ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
