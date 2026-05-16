// Custom hook for results page data management.

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { clearCache, readCache, writeCache } from "../lib/storage";

type ResultRecord = Record<string, any>;

export type ResultsCache = {
  data: ResultRecord[];
  eligibilityFilter: string[];
  sortMode: "recent" | "alphabetical" | "eligibility";
  search: string;
  onlyFutureDeadlines: boolean;
  minFunding: string;
  showEvidence: boolean;
  pinnedRowKey: string | null;
};

const RESULTS_CACHE_KEY = "results_cache_v1";
const RESULTS_FORCE_REFRESH_KEY = "results_force_refresh_v1";

export function useResults() {
  const [data, setData] = useState<ResultRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [hasCachedData, setHasCachedData] = useState(false);

  const fetchLatest = useCallback(
    async (opts?: { showLoading?: boolean; forceRefresh?: boolean }) => {
      const showLoading = opts?.showLoading ?? false;
      const forceRefresh = opts?.forceRefresh ?? false;
      setRefreshing(true);
      if (showLoading) setLoading(true);
      try {
        const res = await api.results({ forceRefresh });
        setData(res.results || []);
        setHasCachedData(Boolean(res.results && res.results.length));
        setError(null);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
        setRefreshing(false);
        clearCache(RESULTS_FORCE_REFRESH_KEY);
      }
    },
    []
  );

  const saveToCache = useCallback((cache: Partial<ResultsCache>) => {
    const existing = readCache<ResultsCache>(RESULTS_CACHE_KEY)?.value || {};
    const updated = { ...existing, ...cache };
    writeCache(RESULTS_CACHE_KEY, updated);
  }, []);

  const clearResultsCache = useCallback(() => {
    clearCache(RESULTS_CACHE_KEY);
    setData([]);
    setError(null);
  }, []);

  return {
    data,
    setData,
    loading,
    setLoading,
    error,
    setError,
    refreshing,
    hasCachedData,
    fetchLatest,
    saveToCache,
    clearResultsCache,
    CACHE_KEY: RESULTS_CACHE_KEY,
    FORCE_REFRESH_KEY: RESULTS_FORCE_REFRESH_KEY,
  };
}
