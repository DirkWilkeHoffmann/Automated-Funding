"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Archive, Download, Star, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import { clearCache, readCache, writeCache } from "../../lib/storage";
import { Button } from "../ui/button";
import type { GroupBy, SortMode } from "./ResultsFilters";
import { ResultsHeader } from "./ResultsHeader";
import { ResultsToolbar } from "./ResultsToolbar";
import { ResultsFilters } from "./ResultsFilters";
import { ResultsTable, getRowKey } from "./ResultsTable";

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

const RESULTS_CACHE_KEY = "results_cache_v3";
const RESULTS_FORCE_REFRESH_KEY = "results_force_refresh_v1";
const STARRED_KEY = "results_starred_v1";
const ARCHIVED_KEY = "results_archived_v1";

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
  const [checkedUrls, setCheckedUrls] = useState<Set<string>>(new Set());
  const [starredUrls, setStarredUrls] = useState<Set<string>>(new Set());
  const [archivedUrls, setArchivedUrls] = useState<Set<string>>(new Set());
  const [showArchived, setShowArchived] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const seenUrls = useRef<Set<string>>(new Set());
  const searchRef = useRef<HTMLInputElement>(null);

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
    setEligibilityFilter(eligibilityFilterOptions);
    setSortMode("recent");
    setSearch("");
    setOnlyFutureDeadlines(false);
    setMinFunding("");
    setSourceFilter("all");
  }, []);

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
            // Fade out "new" badges after 35 seconds
            setTimeout(() => {
              setNewResultKeys((prev) => {
                const next = new Set(prev);
                addedKeys.forEach((k) => next.delete(k));
                return next;
              });
            }, 35_000);
          }
        }

        setHasCachedData(Boolean(newRows.length));
        setEligibilityFilter((prev) => (prev.length === 0 ? eligibilityFilterOptions : prev));
        setError(null);
        setLastRefreshedAt(new Date());
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
      setData(cached.data || []);
      setEligibilityFilter(
        cached.eligibilityFilter?.length > 0 ? cached.eligibilityFilter : eligibilityFilterOptions
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
      setEligibilityFilter(eligibilityFilterOptions);
    }
    const flag = readCache<{ jobId?: string }>(RESULTS_FORCE_REFRESH_KEY)?.value;
    if (flag) setShouldForceRefresh(true);
    setHydratedCache(true);

    api.discoveryConfig().then((c: any) => setAutoDiscoveryEnabled(c?.enabled ?? false)).catch(() => {});

    try {
      const starred = JSON.parse(localStorage.getItem(STARRED_KEY) || "[]");
      setStarredUrls(new Set(Array.isArray(starred) ? starred : []));
    } catch {}
    try {
      const archived = JSON.parse(localStorage.getItem(ARCHIVED_KEY) || "[]");
      setArchivedUrls(new Set(Array.isArray(archived) ? archived : []));
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

  const toggleCheck = useCallback((url: string) => {
    setCheckedUrls((prev) => {
      const next = new Set(prev);
      next.has(url) ? next.delete(url) : next.add(url);
      return next;
    });
  }, []);

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
      />

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
        />
      </div>
    </div>
  );
}
