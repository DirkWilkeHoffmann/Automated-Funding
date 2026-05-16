"use client";

import type { ReactNode } from "react";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { api } from "../../lib/api";
import { clearCache, readCache, writeCache } from "../../lib/storage";
import { ResultsHeader } from "./ResultsHeader";
import { ResultsToolbar } from "./ResultsToolbar";
import { ResultsFilters } from "./ResultsFilters";
import { ResultsTable } from "./ResultsTable";

type ResultRecord = Record<string, any>;
type SortMode = "recent" | "alphabetical" | "eligibility";

interface ResultsCacheData {
  data: ResultRecord[];
  eligibilityFilter: string[];
  sortMode: SortMode;
  search: string;
  onlyFutureDeadlines: boolean;
  minFunding: string;
  showEvidence: boolean;
  pinnedRowKey: string | null;
}

const RESULTS_CACHE_KEY = "results_cache_v1";
const RESULTS_FORCE_REFRESH_KEY = "results_force_refresh_v1";

const eligibilityFilterOptions = [
  "Highly Eligible",
  "Eligible",
  "Possibly Eligible",
  "Low Match",
  "Not Eligible",
];

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
  { accessor: "visited_urls_count", label: "Visited URLs count" },
  {
    accessor: "pdf_read",
    label: "PDF read",
    formatter: (row: Record<string, any>) => (isPdfRead(row.pdf_read) ? "Yes" : "No"),
  },
  { accessor: "pdf_pages", label: "PDF pages" },
  { accessor: "pdf_url", label: "PDF URL" },
  {
    accessor: "extraction_timestamp",
    label: "Scraped date",
    formatter: (row: Record<string, any>) => formatTimestamp(row.extraction_timestamp),
  },
  { accessor: "error", label: "Error" },
  { accessor: "source_folder", label: "Source folder" },
  { accessor: "Processed", label: "Processed" },
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
    const normalized = value.trim().toLowerCase();
    return ["true", "yes", "1", "y"].includes(normalized);
  }
  return false;
}

function formatTimestamp(value: any): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function parseDateValue(val: any): number | null {
  if (!val) return null;
  const date = new Date(val);
  const time = date.getTime();
  return Number.isNaN(time) ? null : time;
}

function getSortTimestamp(row: ResultRecord): number {
  const extractionTime = parseDateValue(row.extraction_timestamp);
  if (extractionTime !== null) return extractionTime;
  const deadlineTime = parseDateValue(row.deadline);
  return deadlineTime !== null ? deadlineTime : 0;
}

function getEligibilityRank(value: string): number {
  const idx = eligibilityFilterOptions.indexOf(value);
  return idx === -1 ? eligibilityFilterOptions.length : idx;
}

function parseCurrencyInput(value: string): number | null {
  if (!value) return null;
  const cleaned = value.replace(/,/g, "").trim().toLowerCase();
  const match = cleaned.match(/(\d+(?:\.\d+)?)(\s*[km])?/);
  if (!match) return null;
  let amount = Number.parseFloat(match[1]);
  const suffix = match[2]?.trim();
  if (suffix === "k") amount *= 1000;
  if (suffix === "m") amount *= 1000000;
  return Number.isNaN(amount) ? null : amount;
}

function parseFundingRangeMax(value: any): number | null {
  if (!value) return null;
  const text = String(value).toLowerCase();
  const regex = /(\d+(?:\.\d+)?)(\s*[km])?/g;
  const amounts: number[] = [];
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    let amount = Number.parseFloat(match[1]);
    const suffix = match[2]?.trim();
    if (suffix === "k") amount *= 1000;
    if (suffix === "m") amount *= 1000000;
    if (Number.isFinite(amount)) amounts.push(amount);
  }
  if (amounts.length === 0) return null;
  const maxAmount = Math.max(...amounts);
  return Number.isFinite(maxAmount) ? maxAmount : null;
}

function isFutureDeadline(value: any, now: number): boolean {
  if (!value) return false;
  const text = String(value).toLowerCase();
  if (text.includes("rolling") || text.includes("ongoing") || text.includes("open")) {
    return true;
  }
  const timestamp = parseDateValue(value);
  return timestamp !== null && timestamp >= now;
}

function matchesGlobalSearch(row: ResultRecord, query: string): boolean {
  if (!query) return true;
  return Object.values(row).some((val) => String(val || "").toLowerCase().includes(query));
}

function escapeCsvValue(value: string): string {
  const escaped = value.replace(/"/g, '""');
  return /[",\n]/.test(escaped) ? `"${escaped}"` : escaped;
}

function formatCsvValue(value: any): string {
  if (value === null || value === undefined) return "";
  return Array.isArray(value) ? value.join(", ") : String(value);
}

function buildCsv(rows: ResultRecord[], columns: { accessor: string; label: string }[]): string {
  const header = columns.map((col) => escapeCsvValue(col.label)).join(",");
  const lines = rows.map((row) =>
    columns.map((col) => escapeCsvValue(formatCsvValue(row[col.accessor]))).join(",")
  );
  return [header, ...lines].join("\r\n");
}

function downloadCsv(csv: string, filename: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function isTextInput(target: EventTarget | null): boolean {
  if (!target) return false;
  const element = target as HTMLElement;
  if (element.isContentEditable) return true;
  return Boolean(element.closest("input, textarea, select, button, a"));
}

function getRowKey(row: ResultRecord, idx: number): string {
  return (
    row.fund_url || row.fund_name || row.source_folder || row.extraction_timestamp || `row-${idx}`
  );
}

/**
 * ResultsLayout: Main layout component managing all results state and data flow
 */
export function ResultsLayout() {
  const [data, setData] = useState<ResultRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [eligibilityFilter, setEligibilityFilter] = useState<string[]>([]);
  const [sortMode, setSortMode] = useState<SortMode>("recent");
  const [search, setSearch] = useState("");
  const [onlyFutureDeadlines, setOnlyFutureDeadlines] = useState(false);
  const [minFunding, setMinFunding] = useState("");
  const [showEvidence, setShowEvidence] = useState(true);
  const [selectedRowKey, setSelectedRowKey] = useState<string | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(() => new Set());
  const [pinnedRowKey, setPinnedRowKey] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [hydratedCache, setHydratedCache] = useState(false);
  const [hasCachedData, setHasCachedData] = useState(false);
  const [shouldForceRefresh, setShouldForceRefresh] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const filtersActive = useMemo(() => {
    const eligibilityActive =
      eligibilityFilter.length > 0 && eligibilityFilter.length !== eligibilityFilterOptions.length;
    if (search.trim() || minFunding.trim()) return true;
    if (onlyFutureDeadlines) return true;
    if (eligibilityActive) return true;
    return false;
  }, [search, minFunding, onlyFutureDeadlines, eligibilityFilter]);

  const resetFilters = useCallback(() => {
    setEligibilityFilter(eligibilityFilterOptions);
    setSortMode("recent");
    setSearch("");
    setOnlyFutureDeadlines(false);
    setMinFunding("");
  }, []);

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
        setEligibilityFilter((prev) => (prev.length === 0 ? eligibilityFilterOptions : prev));
        setError(null);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
        setRefreshing(false);
        clearCache(RESULTS_FORCE_REFRESH_KEY);
        setShouldForceRefresh(false);
      }
    },
    []
  );

  // Hydrate from cache
  useEffect(() => {
    const cached = readCache<ResultsCacheData>(RESULTS_CACHE_KEY)?.value;
    if (cached) {
      const legacyPinned = (cached as { pinnedResult?: ResultRecord | null }).pinnedResult;
      setData(cached.data || []);
      setEligibilityFilter(
        cached.eligibilityFilter && cached.eligibilityFilter.length > 0
          ? cached.eligibilityFilter
          : eligibilityFilterOptions
      );
      setSortMode(cached.sortMode || "recent");
      setSearch(cached.search || "");
      setOnlyFutureDeadlines(Boolean(cached.onlyFutureDeadlines));
      setMinFunding(cached.minFunding || "");
      setShowEvidence(cached.showEvidence ?? true);
      setPinnedRowKey(cached.pinnedRowKey || legacyPinned?.fund_url || null);
      setHasCachedData(Boolean(cached.data && cached.data.length));
      setLoading(false);
    } else {
      setEligibilityFilter(eligibilityFilterOptions);
    }
    const refreshFlag = readCache<{ jobId?: string; completedAt?: number }>(
      RESULTS_FORCE_REFRESH_KEY
    )?.value;
    if (refreshFlag) setShouldForceRefresh(true);
    setHydratedCache(true);
  }, []);

  // Fetch latest if needed
  useEffect(() => {
    if (!hydratedCache || shouldForceRefresh) return;
    fetchLatest({ showLoading: !hasCachedData });
  }, [hydratedCache, hasCachedData, shouldForceRefresh, fetchLatest]);

  // Force refresh if flag is set
  useEffect(() => {
    if (!hydratedCache || !shouldForceRefresh) return;
    fetchLatest({ showLoading: true, forceRefresh: true });
  }, [hydratedCache, shouldForceRefresh, fetchLatest]);

  // Persist to cache
  useEffect(() => {
    if (!hydratedCache) return;
    const payload: ResultsCacheData = {
      data,
      eligibilityFilter,
      sortMode,
      search,
      onlyFutureDeadlines,
      minFunding,
      showEvidence,
      pinnedRowKey,
    };
    writeCache(RESULTS_CACHE_KEY, payload);
  }, [
    data,
    eligibilityFilter,
    sortMode,
    search,
    onlyFutureDeadlines,
    minFunding,
    showEvidence,
    pinnedRowKey,
    hydratedCache,
  ]);

  // Compute visible results
  const visibleResults = useMemo(() => {
    const query = search.trim().toLowerCase();
    const minFundingValue = parseCurrencyInput(minFunding);
    const now = Date.now();

    const filtered = data.filter((row) => {
      const elig = row.eligibility || "";
      const inFilter = eligibilityFilter.length === 0 || eligibilityFilter.includes(elig);
      if (!inFilter) return false;

      if (query && !matchesGlobalSearch(row, query)) return false;

      if (onlyFutureDeadlines && !isFutureDeadline(row.deadline, now)) return false;

      if (minFundingValue !== null) {
        const maxFunding = parseFundingRangeMax(row.funding_range);
        if (maxFunding === null || maxFunding < minFundingValue) return false;
      }

      return true;
    });

    const sorted = [...filtered].sort((a, b) => {
      if (sortMode === "alphabetical") {
        const aVal = (a.fund_name || a.fund_url || "").toString();
        const bVal = (b.fund_name || b.fund_url || "").toString();
        return aVal.localeCompare(bVal, undefined, { sensitivity: "base" });
      }

      if (sortMode === "eligibility") {
        return getEligibilityRank(a.eligibility) - getEligibilityRank(b.eligibility);
      }

      return getSortTimestamp(b) - getSortTimestamp(a);
    });

    return sorted;
  }, [data, eligibilityFilter, search, sortMode, onlyFutureDeadlines, minFunding]);

  const detailFieldList = useMemo(
    () =>
      showEvidence ? detailFields : detailFields.filter((field) => field.accessor !== "evidence"),
    [showEvidence]
  );

  const selectedIndex = useMemo(() => {
    if (visibleResults.length === 0) return -1;
    if (!selectedRowKey) return 0;
    const idx = visibleResults.findIndex((row, index) => getRowKey(row, index) === selectedRowKey);
    return idx === -1 ? 0 : idx;
  }, [visibleResults, selectedRowKey]);

  // Sync selected row
  useEffect(() => {
    if (visibleResults.length === 0) {
      if (selectedRowKey !== null) setSelectedRowKey(null);
      return;
    }
    const idx = visibleResults.findIndex((row, index) => getRowKey(row, index) === selectedRowKey);
    if (idx === -1) {
      setSelectedRowKey(getRowKey(visibleResults[0], 0));
    }
  }, [visibleResults, selectedRowKey]);

  // Sync pinned row
  useEffect(() => {
    if (!pinnedRowKey) return;
    const exists = data.some((row, index) => getRowKey(row, index) === pinnedRowKey);
    if (!exists) setPinnedRowKey(null);
  }, [data, pinnedRowKey]);

  const toggleExpandedRow = useCallback(
    (rowKey: string) => {
      setExpandedRows((prev) => {
        const next = new Set(prev);
        if (pinnedRowKey === rowKey) {
          next.delete(rowKey);
          return next;
        }
        if (next.has(rowKey)) {
          next.delete(rowKey);
        } else {
          next.add(rowKey);
        }
        return next;
      });
      if (pinnedRowKey === rowKey) {
        setPinnedRowKey(null);
      }
    },
    [pinnedRowKey]
  );

  const togglePinnedRow = useCallback(
    (rowKey: string) => {
      setPinnedRowKey((prev) => (prev === rowKey ? null : rowKey));
      setExpandedRows((prev) => {
        const next = new Set(prev);
        if (pinnedRowKey === rowKey) {
          next.delete(rowKey);
        } else {
          next.add(rowKey);
        }
        return next;
      });
      setSelectedRowKey(rowKey);
    },
    [pinnedRowKey]
  );

  const handleDownload = useCallback(() => {
    if (visibleResults.length === 0) return;
    const csv = buildCsv(visibleResults, exportColumns);
    downloadCsv(csv, `funding-results-${new Date().toISOString().slice(0, 10)}.csv`);
  }, [visibleResults]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (isTextInput(event.target)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (visibleResults.length === 0) return;
        const nextIndex = Math.min(selectedIndex + 1, visibleResults.length - 1);
        setSelectedRowKey(getRowKey(visibleResults[nextIndex], nextIndex));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        if (visibleResults.length === 0) return;
        const nextIndex = Math.max(selectedIndex - 1, 0);
        setSelectedRowKey(getRowKey(visibleResults[nextIndex], nextIndex));
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        if (selectedIndex === -1) return;
        const row = visibleResults[selectedIndex];
        if (!row) return;
        togglePinnedRow(getRowKey(row, selectedIndex));
        return;
      }
      if (event.key === "f" || event.key === "F") {
        event.preventDefault();
        searchRef.current?.focus();
        return;
      }
      if (event.key === "e" || event.key === "E") {
        event.preventDefault();
        setShowEvidence((prev) => !prev);
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectedIndex, togglePinnedRow, visibleResults]);

  return (
    <div className="space-y-6">
      <ResultsHeader />

      <Card className="overflow-hidden">
        <div className="h-1 bg-gradient-to-r from-neutral-900 via-orange-500 to-neutral-900" />
        <CardHeader className="pb-4">
          <CardTitle>
            <ResultsToolbar
              visibleCount={visibleResults.length}
              totalCount={data.length}
              filtersActive={filtersActive}
              refreshing={refreshing}
              onRefresh={() => fetchLatest({ showLoading: true, forceRefresh: true })}
              onClearFilters={resetFilters}
              onDownload={handleDownload}
            />
          </CardTitle>
          {refreshing && <p className="text-xs text-neutral-500 mt-3">Refreshing latest data...</p>}
        </CardHeader>
        <CardContent className="space-y-5">
          <ResultsFilters
            eligibilityFilter={eligibilityFilter}
            onEligibilityChange={setEligibilityFilter}
            sortMode={sortMode}
            onSortChange={setSortMode}
            search={search}
            onSearchChange={setSearch}
            onlyFutureDeadlines={onlyFutureDeadlines}
            onFutureDeadlinesChange={setOnlyFutureDeadlines}
            minFunding={minFunding}
            onMinFundingChange={setMinFunding}
          />

          <ResultsTable
            results={visibleResults}
            selectedRowKey={selectedRowKey}
            expandedRows={expandedRows}
            pinnedRowKey={pinnedRowKey}
            searchQuery={search.trim()}
            onRowSelect={setSelectedRowKey}
            onToggleExpand={toggleExpandedRow}
            onTogglePin={togglePinnedRow}
            detailFields={detailFieldList}
            showEvidence={showEvidence}
            loading={loading}
            error={error}
          />
        </CardContent>
      </Card>
    </div>
  );
}
