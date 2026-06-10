"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Archive, Download, RotateCcw, Star, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import { clearCache, readCache, writeCache } from "../../lib/storage";
import { Button } from "../ui/button";
import type { GroupBy, SortMode } from "./ResultsFilters";
import { ResultsHeader } from "./ResultsHeader";
import { ResultsToolbar } from "./ResultsToolbar";
import { ResultsFilters } from "./ResultsFilters";
import { ResultsTable, getRowKey } from "./ResultsTable";
import { ScrapeQueueBanner } from "./ScrapeQueueBanner";

type ResultRecord = Record<string, any>;

interface ResultsCacheData {
  data: ResultRecord[];
  eligibilityFilter: string[];
  sortMode: SortMode;
  search: string;
  onlyFutureDeadlines: boolean;
  minFunding: string;
  showEvidence: boolean;
  pinnedRowKey: string | null;
  groupBy: GroupBy;
  sourceFilter: string;
}

const RESULTS_CACHE_KEY = "results_cache_v4";
const RESULTS_FORCE_REFRESH_KEY = "results_force_refresh_v1";
const STARRED_KEY = "results_starred_v1";
const ARCHIVED_KEY = "results_archived_v1";
// Persists new-row keys with their first-seen timestamp. Expires after 24h.
const NEW_KEYS_STORAGE = "results_new_keys_v2";

const eligibilityFilterOptions = [
  "Highly Eligible",
  "Eligible",
  "Possibly Eligible",
  "Low Match",
  "Not Eligible",
];

// Phase 1: default to strict — only surface results the engine stands behind.
// Operators can lift this via the "Show all candidates" toggle.
const STRICT_ELIGIBILITY_DEFAULT = ["Highly Eligible", "Eligible"];

const detailFields = [
  { accessor: "applicant_types", label: "Applicant types" },
  { accessor: "geographic_scope", label: "Geographic scope" },
  { accessor: "beneficiary_focus", label: "Beneficiary focus" },
  { accessor: "funding_range", label: "Funding range" },
  { accessor: "restrictions", label: "Restrictions" },
  { accessor: "application_status", label: "Application status" },
  { accessor: "deadline", label: "Deadline" },
  { accessor: "notes", label: "Notes" },
  { accessor: "eligibility", label: "Eligibility" },
  { accessor: "eligibility_reason", label: "Eligibility reason" },
  { accessor: "evidence", label: "Evidence" },
  { accessor: "pages_scraped", label: "Pages scraped" },
  { accessor: "visited_urls_count", label: "Visited URLs" },
  {
    accessor: "pdf_read",
    label: "PDF read",
    formatter: (row: ResultRecord) => (isPdfRead(row.pdf_read) ? "Yes" : "No"),
  },
  { accessor: "pdf_pages", label: "PDF pages" },
  { accessor: "pdf_url", label: "PDF URL" },
  {
    accessor: "extraction_timestamp",
    label: "Scraped date",
    formatter: (row: ResultRecord) => formatTimestamp(row.extraction_timestamp),
  },
  { accessor: "error", label: "Error" },
  { accessor: "source_folder", label: "Source folder" },
  { accessor: "Processed", label: "Processed" },
  { accessor: "discovery_source", label: "Discovery source" },
];

const exportColumns = [
  { accessor: "fund_url", label: "fund_url" },
  { accessor: "fund_name", label: "fund_name" },
  { accessor: "applicant_types", label: "applicant_types" },
  { accessor: "geographic_scope", label: "geographic_scope" },
  { accessor: "beneficiary_focus", label: "beneficiary_focus" },
  { accessor: "funding_range", label: "funding_range" },
  { accessor: "restrictions", label: "restrictions" },
  { accessor: "application_status", label: "application_status" },
  { accessor: "deadline", label: "deadline" },
  { accessor: "notes", label: "notes" },
  { accessor: "eligibility", label: "eligibility" },
  { accessor: "evidence", label: "evidence" },
  { accessor: "pages_scraped", label: "pages_scraped" },
  { accessor: "visited_urls_count", label: "visited_urls_count" },
  { accessor: "pdf_read", label: "pdf_read" },
  { accessor: "pdf_url", label: "pdf_url" },
  { accessor: "pdf_pages", label: "pdf_pages" },
  { accessor: "pdf_text", label: "pdf_text" },
  { accessor: "extraction_timestamp", label: "extraction_timestamp" },
  { accessor: "error", label: "error" },
  { accessor: "source_folder", label: "source_folder" },
  { accessor: "Processed", label: "Processed" },
];

function isPdfRead(value: any): boolean {
  if (value === true) return true;
  if (typeof value === "number") return value > 0;
  if (typeof value === "string") {
    return ["true", "yes", "1", "y"].includes(value.trim().toLowerCase());
  }
  return false;
}

function formatTimestamp(value: any): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function parseDateValue(val: any): number | null {
  if (!val) return null;
  const t = new Date(val).getTime();
  return Number.isNaN(t) ? null : t;
}

function getSortTimestamp(row: ResultRecord): number {
  return parseDateValue(row.extraction_timestamp) ?? parseDateValue(row.deadline) ?? 0;
}

function getEligibilityRank(value: string): number {
  const idx = eligibilityFilterOptions.indexOf(value);
  return idx === -1 ? eligibilityFilterOptions.length : idx;
}

function parseCurrencyInput(value: string): number | null {
  if (!value) return null;
  const cleaned = value.replace(/,/g, "").trim().toLowerCase();
  const match = cleaned.match(/^(\d+(?:\.\d+)?)(\s*[km])?/);
  if (!match) return null;
  let amount = Number.parseFloat(match[1]);
  const suffix = match[2]?.trim();
  if (suffix === "k") amount *= 1000;
  if (suffix === "m") amount *= 1_000_000;
  return Number.isNaN(amount) ? null : amount;
}

function parseFundingRangeMax(value: any): number | null {
  if (!value) return null;
  const text = String(value).toLowerCase();
  const amounts: number[] = [];
  text.replace(/(\d+(?:\.\d+)?)(\s*[km])?/g, (_, num, unit) => {
    let amount = Number.parseFloat(num);
    const suffix = (unit ?? "").trim();
    if (suffix === "k") amount *= 1000;
    if (suffix === "m") amount *= 1_000_000;
    if (Number.isFinite(amount)) amounts.push(amount);
    return "";
  });
  const maxAmount = amounts.length > 0 ? Math.max(...amounts) : null;
  return maxAmount !== null && Number.isFinite(maxAmount) ? maxAmount : null;
}

function isFutureDeadline(value: any, now: number): boolean {
  if (!value) return false;
  const text = String(value).toLowerCase();
  if (text.includes("rolling") || text.includes("ongoing") || text.includes("open")) return true;
  const t = parseDateValue(value);
  return t !== null && t >= now;
}

function matchesGlobalSearch(row: ResultRecord, query: string): boolean {
  if (!query) return true;
  return Object.values(row).some((val) => String(val || "").toLowerCase().includes(query));
}

function escapeCsvValue(value: string): string {
  const escaped = value.replace(/"/g, '""');
  return /[",\n]/.test(escaped) ? `"${escaped}"` : escaped;
}

function buildCsv(rows: ResultRecord[], columns: { accessor: string; label: string }[]): string {
  const header = columns.map((col) => escapeCsvValue(col.label)).join(",");
  const lines = rows.map((row) =>
    columns
      .map((col) => {
        const val = row[col.accessor];
        const str =
          val === null || val === undefined ? "" : Array.isArray(val) ? val.join(", ") : String(val);
        return escapeCsvValue(str);
      })
      .join(",")
  );
  return [header, ...lines].join("\r\n");
}

function isTextInput(target: EventTarget | null): boolean {
  if (!target) return false;
  const el = target as HTMLElement;
  return el.isContentEditable || Boolean(el.closest("input, textarea, select, button, a"));
}

export function ResultsLayout() {
  const [data, setData] = useState<ResultRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [eligibilityFilter, setEligibilityFilter] = useState<string[]>([]);
  const [sortMode, setSortMode] = useState<SortMode>("recent");
  const [groupBy, setGroupBy] = useState<GroupBy>("none");
  const [search, setSearch] = useState("");
  const [onlyFutureDeadlines, setOnlyFutureDeadlines] = useState(false);
  const [minFunding, setMinFunding] = useState("");
  const [showEvidence, setShowEvidence] = useState(true);
  const [selectedRowKey, setSelectedRowKey] = useState<string | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [pinnedRowKey, setPinnedRowKey] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [hydratedCache, setHydratedCache] = useState(false);
  const [hasCachedData, setHasCachedData] = useState(false);
  const [shouldForceRefresh, setShouldForceRefresh] = useState(false);
  const [newResultKeys, setNewResultKeys] = useState<Set<string>>(new Set());
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);
  const [sourceFilter, setSourceFilter] = useState("all");
  const [autoDiscoveryEnabled, setAutoDiscoveryEnabled] = useState(false);
  const [stats, setStats] = useState<{
    surfaced: number;
    candidates: number;
    hedge: number;
    excluded: number;
  } | null>(null);
  const [checkedUrls, setCheckedUrls] = useState<Set<string>>(new Set());
  const [starredUrls, setStarredUrls] = useState<Set<string>>(new Set());
  const [archivedUrls, setArchivedUrls] = useState<Set<string>>(new Set());
  const [showArchived, setShowArchived] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [rescrapeUrls, setRescrapeUrls] = useState<string[]>([]);
  const [rescraping, setRescraping] = useState(false);
  const seenUrls = useRef<Set<string>>(new Set());
  const searchRef = useRef<HTMLInputElement>(null);
  const lastCheckedUrlRef = useRef<string | null>(null);

  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (eligibilityFilter.length > 0 && eligibilityFilter.length < eligibilityFilterOptions.length)
      count++;
    if (search.trim()) count++;
    if (onlyFutureDeadlines) count++;
    if (minFunding.trim()) count++;
    if (sourceFilter !== "all") count++;
    return count;
  }, [eligibilityFilter, search, onlyFutureDeadlines, minFunding, sourceFilter]);

  const filtersActive = activeFilterCount > 0;

  const resetFilters = useCallback(() => {
    setEligibilityFilter([]);  // empty = show all tiers
    setSortMode("recent");
    setSearch("");
    setOnlyFutureDeadlines(false);
    setMinFunding("");
    setSourceFilter("all");
  }, []);

  const showAllCandidates = useCallback(() => {
    setEligibilityFilter(eligibilityFilterOptions);
  }, []);

  const refreshStats = useCallback(() => {
    api
      .stats()
      .then((s) => {
        const buckets = s?.funds?.by_eligibility || {};
        setStats({
          surfaced: (buckets["Highly Eligible"] || 0) + (buckets["Eligible"] || 0),
          candidates: s?.funds?.total || 0,
          hedge: buckets["Possibly Eligible"] || 0,
          excluded: (buckets["Low Match"] || 0) + (buckets["Not Eligible"] || 0),
        });
      })
      .catch(() => {});
  }, []);

  const isStrictView = useMemo(
    () =>
      eligibilityFilter.length === STRICT_ELIGIBILITY_DEFAULT.length &&
      STRICT_ELIGIBILITY_DEFAULT.every((t) => eligibilityFilter.includes(t)),
    [eligibilityFilter]
  );

  const fetchLatest = useCallback(
    async (opts?: { showLoading?: boolean; forceRefresh?: boolean }) => {
      const showLoading = opts?.showLoading ?? false;
      const forceRefresh = opts?.forceRefresh ?? false;
      setRefreshing(true);
      if (showLoading) setLoading(true);
      try {
        const res = await api.results({ forceRefresh });
        const newRows: ResultRecord[] = res.results || [];

        if (seenUrls.current.size === 0) {
          // First load — populate seen set, no new markers
          newRows.forEach((row, idx) => seenUrls.current.add(getRowKey(row, idx)));
          setData(newRows);
          setNewResultKeys(new Set());
        } else {
          // Incremental — diff against seen set
          const addedKeys = new Set<string>();
          newRows.forEach((row, idx) => {
            const key = getRowKey(row, idx);
            if (!seenUrls.current.has(key)) {
              addedKeys.add(key);
              seenUrls.current.add(key);
            }
          });
          setData(newRows);
          if (addedKeys.size > 0) {
            setNewResultKeys((prev) => {
              const next = new Set(prev);
              addedKeys.forEach((k) => next.add(k));
              return next;
            });
            // Persist new keys with timestamp — expire after 24h or when opened
            try {
              const stored: Record<string, number> = JSON.parse(
                localStorage.getItem(NEW_KEYS_STORAGE) || "{}"
              );
              const now = Date.now();
              addedKeys.forEach((k) => { stored[k] = now; });
              localStorage.setItem(NEW_KEYS_STORAGE, JSON.stringify(stored));
            } catch {}
          }
        }

        setHasCachedData(Boolean(newRows.length));
        setEligibilityFilter((prev) =>
          prev.length === 0 ? STRICT_ELIGIBILITY_DEFAULT : prev
        );
        setError(null);
        setLastRefreshedAt(new Date());
        refreshStats();
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
        setRefreshing(false);
        clearCache(RESULTS_FORCE_REFRESH_KEY);
        setShouldForceRefresh(false);
      }
    },
    [refreshStats]
  );

  // Hydrate from cache
  useEffect(() => {
    const cached = readCache<ResultsCacheData>(RESULTS_CACHE_KEY)?.value;
    if (cached) {
      setData(cached.data || []);
      setEligibilityFilter(
        cached.eligibilityFilter?.length > 0 ? cached.eligibilityFilter : STRICT_ELIGIBILITY_DEFAULT
      );
      setSortMode(cached.sortMode || "recent");
      setGroupBy(cached.groupBy || "none");
      setSearch(cached.search || "");
      setOnlyFutureDeadlines(Boolean(cached.onlyFutureDeadlines));
      setMinFunding(cached.minFunding || "");
      setShowEvidence(cached.showEvidence ?? true);
      setPinnedRowKey(cached.pinnedRowKey || null);
      setSourceFilter(cached.sourceFilter || "all");
      setHasCachedData(Boolean(cached.data?.length));
      setLoading(false);
      // Seed seenUrls so next refresh can detect newly added items
      (cached.data || []).forEach((row, idx) => seenUrls.current.add(getRowKey(row, idx)));
    } else {
      setEligibilityFilter(STRICT_ELIGIBILITY_DEFAULT);
    }
    const flag = readCache<{ jobId?: string }>(RESULTS_FORCE_REFRESH_KEY)?.value;
    if (flag) setShouldForceRefresh(true);
    setHydratedCache(true);

    api.discoveryConfig().then((c: any) => setAutoDiscoveryEnabled(c?.enabled ?? false)).catch(() => {});
    refreshStats();

    try {
      const starred = JSON.parse(localStorage.getItem(STARRED_KEY) || "[]");
      setStarredUrls(new Set(Array.isArray(starred) ? starred : []));
    } catch {}
    try {
      const archived = JSON.parse(localStorage.getItem(ARCHIVED_KEY) || "[]");
      setArchivedUrls(new Set(Array.isArray(archived) ? archived : []));
    } catch {}
    // Load persisted "new" keys — keep only those < 24h old
    try {
      const storedNew: Record<string, number> = JSON.parse(
        localStorage.getItem(NEW_KEYS_STORAGE) || "{}"
      );
      const cutoff = Date.now() - 24 * 60 * 60 * 1000;
      const valid = Object.entries(storedNew).filter(([, ts]) => ts > cutoff);
      if (valid.length > 0) setNewResultKeys(new Set(valid.map(([k]) => k)));
      if (valid.length !== Object.keys(storedNew).length) {
        localStorage.setItem(NEW_KEYS_STORAGE, JSON.stringify(Object.fromEntries(valid)));
      }
    } catch {}
  }, []);

  useEffect(() => {
    if (!hydratedCache || shouldForceRefresh) return;
    fetchLatest({ showLoading: !hasCachedData });
  }, [hydratedCache, hasCachedData, shouldForceRefresh, fetchLatest]);

  useEffect(() => {
    if (!hydratedCache || !shouldForceRefresh) return;
    fetchLatest({ showLoading: true, forceRefresh: true });
  }, [hydratedCache, shouldForceRefresh, fetchLatest]);

  // Persist to cache
  useEffect(() => {
    if (!hydratedCache) return;
    writeCache(RESULTS_CACHE_KEY, {
      data,
      eligibilityFilter,
      sortMode,
      groupBy,
      search,
      onlyFutureDeadlines,
      minFunding,
      showEvidence,
      pinnedRowKey,
      sourceFilter,
    } satisfies ResultsCacheData);
  }, [
    data,
    eligibilityFilter,
    sortMode,
    groupBy,
    search,
    onlyFutureDeadlines,
    minFunding,
    showEvidence,
    pinnedRowKey,
    sourceFilter,
    hydratedCache,
  ]);

  const visibleResults = useMemo(() => {
    const query = search.trim().toLowerCase();
    const minFundingValue = parseCurrencyInput(minFunding);
    const now = Date.now();

    const filtered = data.filter((row) => {
      const url = row.fund_url || "";
      if (!showArchived && archivedUrls.has(url)) return false;
      if (eligibilityFilter.length > 0 && !eligibilityFilter.includes(row.eligibility || ""))
        return false;
      if (query && !matchesGlobalSearch(row, query)) return false;
      if (onlyFutureDeadlines && !isFutureDeadline(row.deadline, now)) return false;
      if (minFundingValue !== null) {
        const maxFunding = parseFundingRangeMax(row.funding_range);
        if (maxFunding === null || maxFunding < minFundingValue) return false;
      }
      if (sourceFilter !== "all" && row.discovery_source !== sourceFilter) return false;
      return true;
    });

    return [...filtered].sort((a, b) => {
      if (sortMode === "alphabetical") {
        return (a.fund_name || a.fund_url || "").localeCompare(
          b.fund_name || b.fund_url || "",
          undefined,
          { sensitivity: "base" }
        );
      }
      if (sortMode === "eligibility") {
        return getEligibilityRank(a.eligibility) - getEligibilityRank(b.eligibility);
      }
      return getSortTimestamp(b) - getSortTimestamp(a);
    });
  }, [data, eligibilityFilter, search, sortMode, onlyFutureDeadlines, minFunding, sourceFilter, archivedUrls, showArchived]);

  const detailFieldList = useMemo(
    () => (showEvidence ? detailFields : detailFields.filter((f) => f.accessor !== "evidence")),
    [showEvidence]
  );

  const selectedIndex = useMemo(() => {
    if (!selectedRowKey || visibleResults.length === 0) return 0;
    const idx = visibleResults.findIndex((row, i) => getRowKey(row, i) === selectedRowKey);
    return idx === -1 ? 0 : idx;
  }, [visibleResults, selectedRowKey]);

  useEffect(() => {
    if (visibleResults.length === 0) {
      setSelectedRowKey(null);
      return;
    }
    const idx = visibleResults.findIndex((row, i) => getRowKey(row, i) === selectedRowKey);
    if (idx === -1) setSelectedRowKey(getRowKey(visibleResults[0], 0));
  }, [visibleResults, selectedRowKey]);

  useEffect(() => {
    if (!pinnedRowKey) return;
    const exists = data.some((row, i) => getRowKey(row, i) === pinnedRowKey);
    if (!exists) setPinnedRowKey(null);
  }, [data, pinnedRowKey]);

  const toggleExpandedRow = useCallback(
    (rowKey: string) => {
      if (pinnedRowKey === rowKey) {
        setPinnedRowKey(null);
        return;
      }
      setExpandedRows((prev) => {
        const next = new Set(prev);
        next.has(rowKey) ? next.delete(rowKey) : next.add(rowKey);
        return next;
      });
      // Opening a row dismisses its "new" highlight
      setNewResultKeys((prev) => {
        if (!prev.has(rowKey)) return prev;
        const next = new Set(prev);
        next.delete(rowKey);
        try {
          const stored: Record<string, number> = JSON.parse(
            localStorage.getItem(NEW_KEYS_STORAGE) || "{}"
          );
          delete stored[rowKey];
          localStorage.setItem(NEW_KEYS_STORAGE, JSON.stringify(stored));
        } catch {}
        return next;
      });
    },
    [pinnedRowKey]
  );

  const togglePinnedRow = useCallback(
    (rowKey: string) => {
      setPinnedRowKey((prev) => (prev === rowKey ? null : rowKey));
      setExpandedRows((prev) => {
        const next = new Set(prev);
        pinnedRowKey === rowKey ? next.delete(rowKey) : next.add(rowKey);
        return next;
      });
      setSelectedRowKey(rowKey);
    },
    [pinnedRowKey]
  );

  const allChecked =
    visibleResults.length > 0 && visibleResults.every((row) => checkedUrls.has(row.fund_url || ""));

  const toggleCheck = useCallback(
    (url: string, shiftKey?: boolean) => {
      setCheckedUrls((prev) => {
        const next = new Set(prev);
        if (shiftKey && lastCheckedUrlRef.current && lastCheckedUrlRef.current !== url) {
          const lastIdx = visibleResults.findIndex((r) => r.fund_url === lastCheckedUrlRef.current);
          const currIdx = visibleResults.findIndex((r) => r.fund_url === url);
          if (lastIdx !== -1 && currIdx !== -1) {
            const from = Math.min(lastIdx, currIdx);
            const to = Math.max(lastIdx, currIdx);
            const shouldCheck = !prev.has(url);
            for (let i = from; i <= to; i++) {
              const rowUrl = visibleResults[i]?.fund_url || "";
              if (rowUrl) shouldCheck ? next.add(rowUrl) : next.delete(rowUrl);
            }
          } else {
            next.has(url) ? next.delete(url) : next.add(url);
          }
        } else {
          next.has(url) ? next.delete(url) : next.add(url);
        }
        lastCheckedUrlRef.current = url;
        return next;
      });
    },
    [visibleResults]
  );

  const toggleCheckAll = useCallback(() => {
    if (allChecked) {
      setCheckedUrls(new Set());
    } else {
      setCheckedUrls(new Set(visibleResults.map((row) => row.fund_url || "").filter(Boolean)));
    }
  }, [allChecked, visibleResults]);

  const handleStarSelected = useCallback(() => {
    setStarredUrls((prev) => {
      const next = new Set(prev);
      const allStarred = Array.from(checkedUrls).every((u) => prev.has(u));
      checkedUrls.forEach((u) => (allStarred ? next.delete(u) : next.add(u)));
      try { localStorage.setItem(STARRED_KEY, JSON.stringify(Array.from(next))); } catch {}
      return next;
    });
    setCheckedUrls(new Set());
  }, [checkedUrls]);

  const handleArchiveSelected = useCallback(() => {
    setArchivedUrls((prev) => {
      const next = new Set(prev);
      checkedUrls.forEach((u) => next.add(u));
      try { localStorage.setItem(ARCHIVED_KEY, JSON.stringify(Array.from(next))); } catch {}
      return next;
    });
    setCheckedUrls(new Set());
  }, [checkedUrls]);

  const handleDownloadSelected = useCallback(() => {
    const rows = visibleResults.filter((row) => checkedUrls.has(row.fund_url || ""));
    if (rows.length === 0) return;
    const csv = buildCsv(rows, exportColumns);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `funding-selected-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [checkedUrls, visibleResults]);

  const handleDeleteSelected = useCallback(async () => {
    if (checkedUrls.size === 0 || deleting) return;
    setDeleting(true);
    const urls = Array.from(checkedUrls);
    try {
      await api.deleteResults(urls);
      setData((prev) => prev.filter((row) => !urls.includes(row.fund_url || "")));
      setCheckedUrls(new Set());
    } catch (err: any) {
      setError(err.message || "Delete failed");
    } finally {
      setDeleting(false);
    }
  }, [checkedUrls, deleting]);

  const handleRescrapeSelected = useCallback(() => {
    if (checkedUrls.size === 0) return;
    setRescrapeUrls(Array.from(checkedUrls));
  }, [checkedUrls]);

  const handleRescrapeSingle = useCallback((url: string) => {
    setRescrapeUrls([url]);
  }, []);

  const handleRescrapeConfirm = useCallback(async () => {
    if (rescraping || rescrapeUrls.length === 0) return;
    setRescraping(true);
    const urls = rescrapeUrls;
    try {
      await api.deleteResults(urls);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Delete failed");
      setRescraping(false);
      return;
    }
    // Delete succeeded — update local state immediately
    setData((prev) => prev.filter((row) => !urls.includes(row.fund_url || "")));
    setCheckedUrls(new Set());
    setRescrapeUrls([]);
    try {
      await api.scrapeBatch([], urls, { rescrapeScope: "any" });
    } catch {
      setError("Deleted but scrape failed to queue — use the Scrape page to re-add these URLs manually.");
    } finally {
      setRescraping(false);
    }
  }, [rescraping, rescrapeUrls]);

  const handleDownload = useCallback(() => {
    if (visibleResults.length === 0) return;
    const csv = buildCsv(visibleResults, exportColumns);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `funding-results-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [visibleResults]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (isTextInput(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        const next = Math.min(selectedIndex + 1, visibleResults.length - 1);
        if (visibleResults[next]) setSelectedRowKey(getRowKey(visibleResults[next], next));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        const next = Math.max(selectedIndex - 1, 0);
        if (visibleResults[next]) setSelectedRowKey(getRowKey(visibleResults[next], next));
      } else if (event.key === "Enter") {
        event.preventDefault();
        const row = visibleResults[selectedIndex];
        if (row) togglePinnedRow(getRowKey(row, selectedIndex));
      } else if (event.key === "f" || event.key === "F") {
        event.preventDefault();
        searchRef.current?.focus();
      } else if (event.key === "e" || event.key === "E") {
        event.preventDefault();
        setShowEvidence((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectedIndex, togglePinnedRow, visibleResults]);

  return (
    <div className="page-content space-y-4">
      <ResultsHeader
        total={data.length}
        visible={visibleResults.length}
        newCount={newResultKeys.size}
        lastRefreshedAt={lastRefreshedAt}
        autoDiscoveryEnabled={autoDiscoveryEnabled}
        stats={stats}
        isStrictView={isStrictView}
        onShowAllCandidates={showAllCandidates}
      />

      <ScrapeQueueBanner />

      <div className="card-base overflow-hidden">
        <ResultsToolbar
          visibleCount={visibleResults.length}
          totalCount={data.length}
          filtersActive={filtersActive}
          refreshing={refreshing}
          onRefresh={() => fetchLatest({ showLoading: false, forceRefresh: true })}
          onClearFilters={resetFilters}
          onDownload={handleDownload}
        />

        {/* Selection action toolbar */}
        {checkedUrls.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-brand/5 px-4 py-2.5">
            <span className="text-xs font-semibold text-slate-700">{checkedUrls.size} selected</span>
            <div className="ml-auto flex items-center gap-1.5">
              <Button variant="ghost" size="sm" onClick={handleStarSelected} className="h-7 gap-1.5 px-2 text-xs text-amber-600 hover:bg-amber-50">
                <Star size={12} />Star
              </Button>
              <Button variant="ghost" size="sm" onClick={handleArchiveSelected} className="h-7 gap-1.5 px-2 text-xs text-slate-600 hover:bg-slate-100">
                <Archive size={12} />Archive
              </Button>
              <Button variant="ghost" size="sm" onClick={handleDownloadSelected} className="h-7 gap-1.5 px-2 text-xs text-slate-600 hover:bg-slate-100">
                <Download size={12} />Download
              </Button>
              <Button variant="ghost" size="sm" onClick={handleDeleteSelected} disabled={deleting} className="h-7 gap-1.5 px-2 text-xs text-red-600 hover:bg-red-50">
                <Trash2 size={12} />{deleting ? "Deleting…" : "Delete"}
              </Button>
              <Button variant="ghost" size="sm" onClick={handleRescrapeSelected} disabled={rescraping} className="h-7 gap-1.5 px-2 text-xs font-semibold text-indigo-600 hover:bg-indigo-50">
                <RotateCcw size={12} />Rescrape
              </Button>
            </div>
          </div>
        )}

        {/* Rescrape confirmation banner */}
        {rescrapeUrls.length > 0 && (
          <div className="flex flex-wrap items-center gap-3 border-b border-slate-800 bg-slate-900 px-4 py-3">
            <RotateCcw size={14} className="shrink-0 text-indigo-400" />
            <p className="flex-1 text-xs text-slate-200">
              <span className="font-semibold text-white">
                Delete {rescrapeUrls.length} result{rescrapeUrls.length > 1 ? "s" : ""} and queue a fresh scrape?
              </span>{" "}
              Current data is removed and these URLs are re-analysed from scratch. This cannot be undone.
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setRescrapeUrls([])}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-700"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRescrapeConfirm}
                disabled={rescraping}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-60"
              >
                {rescraping ? "Rescraping…" : "Confirm & Rescrape"}
              </button>
            </div>
          </div>
        )}

        {/* Show archived toggle */}
        {archivedUrls.size > 0 && (
          <div className="flex items-center justify-end border-b border-slate-100 px-4 py-1.5">
            <button type="button" onClick={() => setShowArchived((v) => !v)} className="text-[11px] text-slate-400 hover:text-slate-600">
              {showArchived ? "Hide archived" : `Show ${archivedUrls.size} archived`}
            </button>
          </div>
        )}
        <ResultsFilters
          eligibilityFilter={eligibilityFilter}
          onEligibilityChange={setEligibilityFilter}
          sortMode={sortMode}
          onSortChange={setSortMode}
          groupBy={groupBy}
          onGroupByChange={setGroupBy}
          search={search}
          onSearchChange={setSearch}
          onlyFutureDeadlines={onlyFutureDeadlines}
          onFutureDeadlinesChange={setOnlyFutureDeadlines}
          minFunding={minFunding}
          onMinFundingChange={setMinFunding}
          sourceFilter={sourceFilter}
          onSourceFilterChange={setSourceFilter}
          activeFilterCount={activeFilterCount}
          onClearAll={resetFilters}
        />
        <ResultsTable
          results={visibleResults}
          selectedRowKey={selectedRowKey}
          expandedRows={expandedRows}
          pinnedRowKey={pinnedRowKey}
          searchQuery={search.trim()}
          groupBy={groupBy}
          newResultKeys={newResultKeys}
          onRowSelect={setSelectedRowKey}
          onToggleExpand={toggleExpandedRow}
          onTogglePin={togglePinnedRow}
          detailFields={detailFieldList}
          showEvidence={showEvidence}
          loading={loading}
          error={error}
          onClearFilters={resetFilters}
          hasAnyData={data.length > 0}
          checkedUrls={checkedUrls}
          starredUrls={starredUrls}
          allChecked={allChecked}
          onToggleCheck={toggleCheck}
          onToggleCheckAll={toggleCheckAll}
          onRescrape={handleRescrapeSingle}
        />
      </div>
    </div>
  );
}
