"use client";

import type { ChangeEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle,
  Clock,
  FileText,
  Link2,
  Play,
  RefreshCw,
  RotateCcw,
  StopCircle,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import { eligibilityVariantMap } from "../lib/eligibility";
import { clearCache, readCache, writeCache } from "../lib/storage";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Progress } from "./ui/progress";
import { cn } from "../lib/utils";
import { ListingExpandPanel, type ListingItem } from "./ListingExpandPanel";

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

type PrepSummary = {
  added: string[];
  alreadyProcessed: string[];
  duplicatesInPayload: string[];
  normalizedMap: Record<string, string>;
};

type QueueStats = { uniqueDomains: number; totalQueued: number };

type ScrapeCache = {
  manualInput: string;
  stagedUrls: string[];
  prepSummary: PrepSummary | null;
  queueStats: QueueStats;
  job: JobStatus | null;
};

const extractUrls = (text: string) =>
  (text.match(/https?:\/\/[^\s,"'>)]+/gi) || []).map((u) => u.trim());

const SCRAPE_CACHE_KEY = "scrape_form_cache_v1";
const RESULTS_FORCE_REFRESH_KEY = "results_force_refresh_v1";


export default function ScrapeForm() {
  const [manualInput, setManualInput] = useState("");
  const [stagedUrls, setStagedUrls] = useState<string[]>([]);
  const [prepSummary, setPrepSummary] = useState<PrepSummary | null>(null);
  const [prepError, setPrepError] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const [isScraping, setIsScraping] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isRefreshingSheet, setIsRefreshingSheet] = useState(false);
  const [sheetRefreshMessage, setSheetRefreshMessage] = useState<string | null>(null);
  const [sheetRefreshError, setSheetRefreshError] = useState<string | null>(null);
  const [queueStats, setQueueStats] = useState<QueueStats>({ uniqueDomains: 0, totalQueued: 0 });
  const [hydratedCache, setHydratedCache] = useState(false);
  const lastCompletedJobId = useRef<string | null>(null);
  const [listingPreview, setListingPreview] = useState<{ sourceUrl: string; items: ListingItem[] } | null>(null);

  const resetAll = () => {
    setManualInput("");
    setStagedUrls([]);
    setPrepSummary(null);
    setPrepError(null);
    setJobError(null);
    setJob(null);
    setSheetRefreshMessage(null);
    setSheetRefreshError(null);
    setQueueStats({ uniqueDomains: 0, totalQueued: 0 });
    lastCompletedJobId.current = null;
    clearCache(SCRAPE_CACHE_KEY);
    clearCache(RESULTS_FORCE_REFRESH_KEY);
  };

  const detectedManualUrls = useMemo(() => extractUrls(manualInput), [manualInput]);

  useEffect(() => {
    const cached = readCache<ScrapeCache>(SCRAPE_CACHE_KEY)?.value;
    if (!cached) { setHydratedCache(true); return; }
    setManualInput(cached.manualInput || "");
    setStagedUrls(cached.stagedUrls || []);
    setPrepSummary(cached.prepSummary ? { ...cached.prepSummary, normalizedMap: cached.prepSummary.normalizedMap || {} } : null);
    setQueueStats(cached.queueStats || calcQueueStats(cached.stagedUrls || []));
    setJob(cached.job || null);
    setHydratedCache(true);
  }, []);

  useEffect(() => {
    if (!hydratedCache) return;
    writeCache(SCRAPE_CACHE_KEY, { manualInput, stagedUrls, prepSummary, queueStats, job });
  }, [hydratedCache, manualInput, stagedUrls, prepSummary, queueStats, job]);

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
      } catch (err: any) {
        const msg = (err?.message || "").toLowerCase();
        if (msg.includes("not found") || msg.includes("404")) {
          // Server restarted — stop polling and mark done so results stay visible.
          setJob((prev) => prev ? { ...prev, done: true, progress_percent: 100 } : null);
        }
        console.error(err);
      }
    }, 4000);
    return () => clearInterval(interval);
  }, [job]);

  const prepareAndStage = async (urls: string[]) => {
    const candidates = Array.from(new Set(urls.map((u) => u.trim()))).filter(Boolean);
    if (candidates.length === 0) { setPrepError("No URLs detected to stage."); return; }
    setPrepError(null);
    setIsPreparing(true);
    try {
      const res = await api.prepareUrls(candidates);
      const addedNow: string[] = [];
      setStagedUrls((prev) => {
        const next = [...prev];
        res.to_scrape.forEach((u: string) => {
          if (!next.includes(u)) { next.push(u); addedNow.push(u); }
        });
        setQueueStats(calcQueueStats(next));
        return next;
      });
      setPrepSummary({
        added: addedNow,
        alreadyProcessed: res.already_processed || [],
        duplicatesInPayload: res.duplicates_in_payload || [],
        normalizedMap: res.normalized_map || {},
      });
    } catch (err: any) {
      setPrepError(err.message || "Could not prepare URLs.");
    } finally {
      setIsPreparing(false);
    }
  };

  const handleManualStage = async () => {
    // For a single URL, run the listing-page preview first so the user can
    // select individual grants before they hit the scrape queue.
    if (detectedManualUrls.length === 1) {
      setIsPreparing(true);
      setPrepError(null);
      try {
        const preview = await api.previewScrapeUrl(detectedManualUrls[0]);
        if (preview.type === "listing" && preview.items.length > 0) {
          setListingPreview({ sourceUrl: detectedManualUrls[0], items: preview.items });
          return;
        }
      } catch {
        // Preview failed — fall through to normal staging
      } finally {
        setIsPreparing(false);
      }
    }
    prepareAndStage(detectedManualUrls);
  };

  const handleCsvUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      await prepareAndStage(extractUrls(text));
    } catch (err: any) {
      setPrepError(err.message || "Could not read CSV file.");
    } finally {
      event.target.value = "";
    }
  };

  const removeFromQueue = (url: string) => {
    setStagedUrls((prev) => { const next = prev.filter((u) => u !== url); setQueueStats(calcQueueStats(next)); return next; });
  };

  const clearQueue = () => {
    setStagedUrls([]);
    setQueueStats({ uniqueDomains: 0, totalQueued: 0 });
    setPrepSummary(null);
    setPrepError(null);
  };

  const refreshSheetConnection = async () => {
    setIsRefreshingSheet(true);
    setSheetRefreshMessage(null);
    setSheetRefreshError(null);
    try {
      const res = await api.refreshResults();
      setSheetRefreshMessage(`Sheet refreshed (${res.total_results || 0} rows).`);
      writeCache(RESULTS_FORCE_REFRESH_KEY, { jobId: "manual-refresh", completedAt: Date.now() });
    } catch (err: any) {
      setSheetRefreshError(err.message || "Failed to refresh the sheet connection.");
    } finally {
      setIsRefreshingSheet(false);
    }
  };

  const startScrape = async () => {
    if (stagedUrls.length === 0) return;
    setIsScraping(true);
    setJobError(null);
    try {
      const payload = await api.scrapeBatch(stagedUrls);
      const status = await api.jobStatus(payload.job_id);
      setJob(status);
      setStagedUrls([]);
      setPrepSummary({ added: payload.to_scrape || [], alreadyProcessed: payload.already_processed || [], duplicatesInPayload: payload.duplicates_in_payload || [], normalizedMap: {} });
      setQueueStats({ uniqueDomains: 0, totalQueued: 0 });
    } catch (err: any) {
      setJobError(err.message || "Failed to start scrape job.");
    } finally {
      setIsScraping(false);
    }
  };

  const clearCompletedJob = () => {
    setJob(null);
    setJobError(null);
    setIsCancelling(false);
    lastCompletedJobId.current = null;
    clearCache(RESULTS_FORCE_REFRESH_KEY);
  };

  const handleCancel = async () => {
    if (!job || job.done) return;
    setIsCancelling(true);
    try {
      await api.cancelJob(job.job_id);
    } catch {
      // Job may have already finished — polling will reflect done state
    }
  };

  const requeueFailed = () => {
    if (!job || job.errors.length === 0) return;
    prepareAndStage(job.errors.map((e) => e.url));
  };

  return (
    <div className="space-y-6">
      {/* Control bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Scrape controls</p>
          <p className="mt-0.5 text-sm text-slate-600">Paste URLs or upload a CSV, queue them, then scrape.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={refreshSheetConnection} disabled={isRefreshingSheet} className="gap-1.5">
            <RefreshCw size={13} className={cn(isRefreshingSheet && "animate-spin")} />
            {isRefreshingSheet ? "Refreshing…" : "Refresh results"}
          </Button>
          <Button variant="outline" size="sm" onClick={resetAll} className="gap-1.5">
            <RotateCcw size={13} />
            Reset all
          </Button>
        </div>
      </div>
      {sheetRefreshMessage && (
        <p className="flex items-center gap-1.5 text-xs text-slate-500">
          <CheckCircle size={12} className="text-emerald-500" /> {sheetRefreshMessage}
        </p>
      )}
      {sheetRefreshError && <p className="text-xs text-red-600">{sheetRefreshError}</p>}

      {/* Input cards */}
      <div className="grid gap-5 lg:grid-cols-2">
        {/* Manual entry */}
        <div className="card-base overflow-hidden">
          <div className="h-0.5 bg-gradient-to-r from-brand via-brand-dark to-transparent" />
          <div className="px-5 py-4">
            <div className="flex items-center gap-2 pb-3">
              <Link2 size={15} className="text-brand" />
              <p className="font-semibold text-slate-900">Paste fund URLs</p>
            </div>
            <p className="mb-3 text-xs text-slate-500">
              Enter as many URLs as you like — we normalize and de-duplicate before scraping.
            </p>
            <textarea
              value={manualInput}
              onChange={(e) => setManualInput(e.target.value)}
              placeholder={"https://example.org/grant-1\nhttps://example.org/grant-2"}
              className="min-h-[160px] w-full"
            />
            <div className="mt-3 flex items-center justify-between text-sm">
              <span className="text-slate-500">{detectedManualUrls.length} URL{detectedManualUrls.length !== 1 ? "s" : ""} detected</span>
              <Button variant="outline" size="sm" onClick={handleManualStage} disabled={detectedManualUrls.length === 0 || isPreparing} className="gap-1.5">
                <Play size={12} />
                {isPreparing ? "Staging…" : "Add to queue"}
              </Button>
            </div>
          </div>
        </div>

        {/* CSV upload */}
        <div className="card-base overflow-hidden">
          <div className="h-0.5 bg-gradient-to-r from-slate-400 to-transparent" />
          <div className="px-5 py-4">
            <div className="flex items-center gap-2 pb-3">
              <FileText size={15} className="text-slate-500" />
              <p className="font-semibold text-slate-900">Upload a CSV</p>
            </div>
            <p className="mb-4 text-xs text-slate-500">
              We scan the file for http(s) URLs, skip ones already in results, and stage the rest.
            </p>
            <label
              htmlFor="csv-upload"
              className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center transition hover:border-brand/40 hover:bg-brand-50/30"
            >
              <Upload size={20} className="text-slate-400" />
              <span className="text-sm font-medium text-slate-600">Click to choose CSV</span>
              <span className="text-xs text-slate-400">Any column containing URLs will be picked up</span>
              <input id="csv-upload" type="file" accept=".csv" className="sr-only" onChange={handleCsvUpload} />
            </label>
          </div>
        </div>
      </div>

      {/* Listing expand panel — shown when a single URL resolves to a listing page */}
      {listingPreview && (
        <ListingExpandPanel
          sourceUrl={listingPreview.sourceUrl}
          items={listingPreview.items}
          onConfirm={(selectedUrls) => {
            setListingPreview(null);
            setManualInput("");
            prepareAndStage(selectedUrls);
          }}
          onDismiss={() => setListingPreview(null)}
        />
      )}

      {/* Queue */}
      <div className="card-base overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
          <div>
            <p className="font-semibold text-slate-900">Scrape queue</p>
            <p className="text-xs text-slate-500">URLs must pass pre-check — duplicates and already-scraped entries are removed.</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="stat-pill">{stagedUrls.length} queued</span>
            {queueStats.uniqueDomains > 0 && (
              <span className="stat-pill">{queueStats.uniqueDomains} domains</span>
            )}
          </div>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* Pre-check summary */}
          {prepSummary && (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <p className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-400">Pre-check summary</p>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: "Added", value: prepSummary.added.length, color: "text-emerald-700" },
                  { label: "Already scraped", value: prepSummary.alreadyProcessed.length, color: "text-slate-600" },
                  { label: "Duplicates removed", value: prepSummary.duplicatesInPayload.length, color: "text-slate-600" },
                  { label: "Unique domains", value: queueStats.uniqueDomains, color: "text-slate-700" },
                ].map(({ label, value, color }) => (
                  <div key={label} className="rounded-lg bg-white border border-slate-100 p-3">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
                    <p className={cn("mt-1 text-2xl font-bold", color)}>{value}</p>
                  </div>
                ))}
              </div>
              {(prepSummary.alreadyProcessed.length > 0 || prepSummary.duplicatesInPayload.length > 0) && (
                <p className="mt-3 text-xs text-slate-500">
                  Already-processed URLs are skipped. Use the <strong>Stale Funds</strong> tab to rescrape them.
                </p>
              )}
            </div>
          )}

          {prepError && <p className="text-sm text-red-600">{prepError}</p>}

          {/* URL list */}
          <div className={cn(
            "rounded-xl border-2 border-dashed p-3 transition",
            stagedUrls.length === 0 ? "border-slate-200 bg-slate-50" : "border-slate-200 bg-white"
          )}>
            {stagedUrls.length === 0 ? (
              <p className="py-4 text-center text-sm text-slate-400">
                Nothing queued yet. Paste URLs or upload a CSV above.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {stagedUrls.map((url, idx) => (
                  <li key={url} className="flex items-center justify-between gap-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-slate-800">{url}</p>
                      <p className="text-xs text-slate-400">#{idx + 1} · {safeDomain(url)}</p>
                    </div>
                    <button type="button" onClick={() => removeFromQueue(url)} className="shrink-0 rounded-md p-1 text-slate-400 hover:bg-red-50 hover:text-red-500">
                      <X size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Actions */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <Button variant="ghost" size="sm" disabled={stagedUrls.length === 0 || isScraping} onClick={clearQueue} className="gap-1.5 text-slate-500">
              <Trash2 size={13} />
              Clear queue
            </Button>
            <Button onClick={startScrape} disabled={stagedUrls.length === 0 || isScraping} className="gap-2 bg-brand text-white hover:bg-brand-dark">
              <Play size={14} />
              {isScraping ? "Starting…" : `Scrape ${stagedUrls.length} fund${stagedUrls.length !== 1 ? "s" : ""}`}
            </Button>
          </div>

          {jobError && <p className="text-sm text-red-600">{jobError}</p>}

          {/* Job monitor */}
          {job && (
            <div className="card-section mt-2 space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  {job.done ? (
                    <CheckCircle size={16} className="text-emerald-500" />
                  ) : (
                    <RefreshCw size={16} className="animate-spin text-brand" />
                  )}
                  <div>
                    <p className="text-sm font-semibold text-slate-800">
                      {job.done ? "Completed" : "Processing"}
                    </p>
                    <p className="text-xs text-slate-500">
                      Job {job.job_id.slice(0, 8)} · {job.completed_urls ?? job.results.length}/{job.total_urls ?? "?"} done
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1.5 text-xs text-slate-500">
                    <Clock size={12} />
                    {formatSeconds(job.total_elapsed_seconds || 0)}
                  </div>
                  {!job.done && (
                    <Button variant="outline" size="sm" onClick={handleCancel} disabled={isCancelling} className="gap-1.5 border-red-200 text-red-600 hover:bg-red-50">
                      <StopCircle size={12} />
                      {isCancelling ? "Stopping…" : "Stop"}
                    </Button>
                  )}
                  {job.done && (
                    <Button variant="outline" size="sm" onClick={clearCompletedJob} className="gap-1.5">
                      <X size={12} />
                      Dismiss
                    </Button>
                  )}
                </div>
              </div>

              <div>
                <Progress value={Math.max(0, Math.min(100, Number(job.progress_percent) || 0))} />
                <p className="mt-1 text-right text-xs text-slate-500">{Math.max(0, Math.min(100, Number(job.progress_percent) || 0))}%</p>
              </div>

              {job.current_url && (
                <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Currently scraping</p>
                  <p className="mt-0.5 truncate text-sm font-medium text-slate-800">{job.current_url}</p>
                  <p className="text-xs text-slate-400">{formatSeconds(job.current_elapsed_seconds || 0)} elapsed</p>
                </div>
              )}

              {job.errors.length > 0 && (
                <details className="rounded-lg border border-red-200 bg-red-50">
                  <summary className="flex cursor-pointer items-center justify-between px-3 py-2">
                    <span className="text-xs font-semibold text-red-700">
                      {job.errors.length} error{job.errors.length !== 1 ? "s" : ""}
                    </span>
                    {job.done && (
                      <Button variant="ghost" size="sm" onClick={(e) => { e.preventDefault(); requeueFailed(); }} className="h-6 gap-1 px-2 text-[11px] text-red-600 hover:bg-red-100">
                        <RotateCcw size={11} />
                        Re-queue failed
                      </Button>
                    )}
                  </summary>
                  <ul className="space-y-1 px-3 pb-3 pt-1">
                    {job.errors.map((err) => (
                      <li key={err.url} className="text-xs text-red-600">
                        <span className="font-medium">{err.url}:</span> {err.message}
                      </li>
                    ))}
                  </ul>
                </details>
              )}

              {job.results.length > 0 && (
                <div className="space-y-2">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Latest results</p>
                  <ul className="space-y-1.5">
                    {job.results.slice(-5).reverse().map((res) => (
                      <li key={`${res.fund_url}-${res.fund_name}`} className="flex items-center justify-between gap-3 rounded-lg border border-slate-100 bg-white px-3 py-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-slate-800">{res.fund_name || res.fund_url}</p>
                          <p className="truncate text-xs text-slate-400">{res.fund_url}</p>
                        </div>
                        <Badge variant={eligibilityVariantMap[res.eligibility] ?? "muted"} className="shrink-0">
                          {res.eligibility || "Pending"}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {job.url_timings && job.url_timings.length > 0 && (
                <details className="rounded-lg border border-slate-200">
                  <summary className="cursor-pointer px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    Per-fund timing
                  </summary>
                  <ul className="space-y-1.5 px-3 pb-3 pt-1">
                    {job.url_timings.slice(-5).reverse().map((t) => (
                      <li key={`${t.url}-${t.finished_at ?? t.started_at}`} className="flex items-center justify-between gap-3 rounded-lg bg-white border border-slate-100 px-3 py-2">
                        <div className="min-w-0">
                          <p className="truncate text-xs font-medium text-slate-700">{t.url}</p>
                          {t.error && <p className="text-xs text-red-500">{t.error}</p>}
                        </div>
                        <span className="stat-pill shrink-0">{formatSeconds(t.duration_seconds || 0)}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function safeDomain(url: string): string {
  try { return new URL(url).hostname || "unknown"; } catch { return "unknown"; }
}

function isPdfRead(value: any): boolean {
  if (value === true) return true;
  if (typeof value === "number") return value > 0;
  if (typeof value === "string") return ["true", "yes", "1", "y"].includes(value.trim().toLowerCase());
  return false;
}

function calcQueueStats(urls: string[]): QueueStats {
  const domains = new Set<string>();
  urls.forEach((u) => { const d = safeDomain(u); if (d !== "unknown") domains.add(d); });
  return { uniqueDomains: domains.size, totalQueued: urls.length };
}

function formatSeconds(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  return [hours > 0 ? `${hours}h` : null, minutes > 0 ? `${minutes}m` : null, `${seconds}s`]
    .filter(Boolean).join(" ");
}
