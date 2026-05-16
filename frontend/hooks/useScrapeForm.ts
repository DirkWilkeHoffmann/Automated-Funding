// Custom hook for scrape form state and job management.

import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { clearCache, readCache, writeCache } from "../lib/storage";

export type JobStatus = {
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

export type PrepSummary = {
  added: string[];
  alreadyProcessed: string[];
  duplicatesInPayload: string[];
  normalizedMap: Record<string, string>;
};

export type QueueStats = {
  uniqueDomains: number;
  totalQueued: number;
};

export type ScrapeCache = {
  manualInput: string;
  stagedUrls: string[];
  prepSummary: PrepSummary | null;
  queueStats: QueueStats;
  job: JobStatus | null;
};

const SCRAPE_CACHE_KEY = "scrape_form_cache_v1";
const RESULTS_FORCE_REFRESH_KEY = "results_force_refresh_v1";

export function useScrapeForm() {
  const [manualInput, setManualInput] = useState("");
  const [stagedUrls, setStagedUrls] = useState<string[]>([]);
  const [prepSummary, setPrepSummary] = useState<PrepSummary | null>(null);
  const [prepError, setPrepError] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const [isScraping, setIsScraping] = useState(false);
  const [queueStats, setQueueStats] = useState<QueueStats>({
    uniqueDomains: 0,
    totalQueued: 0,
  });
  const lastCompletedJobId = useRef<string | null>(null);

  const resetAll = () => {
    setManualInput("");
    setStagedUrls([]);
    setPrepSummary(null);
    setPrepError(null);
    setJobError(null);
    setJob(null);
    setQueueStats({ uniqueDomains: 0, totalQueued: 0 });
    lastCompletedJobId.current = null;
    clearCache(SCRAPE_CACHE_KEY);
    clearCache(RESULTS_FORCE_REFRESH_KEY);
  };

  const saveToCache = (cache: Partial<ScrapeCache>) => {
    const existing = readCache<ScrapeCache>(SCRAPE_CACHE_KEY)?.value || {};
    const updated = { ...existing, ...cache };
    writeCache(SCRAPE_CACHE_KEY, updated);
  };

  const loadFromCache = () => {
    const cached = readCache<ScrapeCache>(SCRAPE_CACHE_KEY)?.value;
    if (cached) {
      setManualInput(cached.manualInput || "");
      setStagedUrls(cached.stagedUrls || []);
      setPrepSummary(cached.prepSummary || null);
      setJob(cached.job || null);
      setQueueStats(cached.queueStats || { uniqueDomains: 0, totalQueued: 0 });
    }
  };

  return {
    manualInput,
    setManualInput,
    stagedUrls,
    setStagedUrls,
    prepSummary,
    setPrepSummary,
    prepError,
    setPrepError,
    jobError,
    setJobError,
    job,
    setJob,
    isPreparing,
    setIsPreparing,
    isScraping,
    setIsScraping,
    queueStats,
    setQueueStats,
    lastCompletedJobId,
    resetAll,
    saveToCache,
    loadFromCache,
    CACHE_KEY: SCRAPE_CACHE_KEY,
    FORCE_REFRESH_KEY: RESULTS_FORCE_REFRESH_KEY,
  };
}
