"use client";

import type { ReactNode } from "react";
import { Fragment } from "react";
import { ChevronDown, ChevronRight, Inbox, Pin, PinOff, RotateCcw, SearchX } from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Skeleton } from "../ui/skeleton";
import { cn } from "../../lib/utils";
import { eligibilityVariantMap } from "../../lib/eligibility";
import type { GroupBy } from "./ResultsFilters";
import { DiscoverySourceBadge } from "./DiscoverySourceBadge";

type ResultRecord = Record<string, any>;

interface ResultsTableProps {
  results: ResultRecord[];
  selectedRowKey: string | null;
  expandedRows: Set<string>;
  pinnedRowKey: string | null;
  searchQuery: string;
  groupBy: GroupBy;
  newResultKeys: Set<string>;
  onRowSelect: (rowKey: string) => void;
  onToggleExpand: (rowKey: string) => void;
  onTogglePin: (rowKey: string) => void;
  detailFields: Array<{
    accessor: string;
    label: string;
    formatter?: (row: ResultRecord) => string;
  }>;
  showEvidence: boolean;
  loading?: boolean;
  error?: string | null;
  onClearFilters?: () => void;
  hasAnyData?: boolean;
  checkedUrls?: Set<string>;
  starredUrls?: Set<string>;
  allChecked?: boolean;
  onToggleCheck?: (url: string, shiftKey?: boolean) => void;
  onToggleCheckAll?: () => void;
  onRescrape?: (url: string) => void;
}


function highlightText(value: any, query: string): ReactNode {
  const text = normalizeText(value);
  if (!text) return <span className="text-slate-400">—</span>;
  const trimmedQuery = query.trim();
  if (!trimmedQuery) return text;
  const queryLower = trimmedQuery.toLowerCase();
  const regex = new RegExp(`(${escapeRegExp(trimmedQuery)})`, "ig");
  return text.split(regex).map((part, idx) =>
    part.toLowerCase() === queryLower ? (
      <mark key={`${part}-${idx}`} className="rounded bg-amber-100 px-0.5 text-inherit">
        {part}
      </mark>
    ) : (
      part
    )
  );
}

function normalizeText(val: any): string {
  if (val === null || val === undefined) return "";
  if (Array.isArray(val)) return val.join(", ");
  return String(val);
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function getDeadlineClass(deadline: string | null | undefined): string {
  if (!deadline) return "text-slate-300";
  const t = new Date(deadline).getTime();
  if (isNaN(t)) return "text-slate-700";
  const daysUntil = (t - Date.now()) / (1000 * 60 * 60 * 24);
  if (daysUntil < 0) return "text-red-400 line-through";
  if (daysUntil < 14) return "text-red-600 font-bold";
  if (daysUntil < 60) return "text-amber-600 font-semibold";
  return "text-emerald-600 font-semibold";
}

function formatValue(val: any): string {
  if (val === null || val === undefined || val === "") return "";
  return Array.isArray(val) ? val.join(", ") : String(val);
}

function TagList({ value, query, max = 3 }: { value: any; query: string; max?: number }) {
  if (!value) return <span className="text-slate-300">—</span>;
  const tags = String(value).split(";").map((t) => t.trim()).filter(Boolean);
  if (tags.length === 0) return <span className="text-slate-300">—</span>;
  const visible = tags.slice(0, max);
  const overflow = tags.length - max;
  return (
    <div className="flex flex-wrap gap-1">
      {visible.map((tag, i) => (
        <span
          key={`${tag}-${i}`}
          className="inline-flex items-center rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600"
        >
          {highlightText(tag, query)}
        </span>
      ))}
      {overflow > 0 && (
        <span className="inline-flex items-center rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-400">
          +{overflow}
        </span>
      )}
    </div>
  );
}

const STATUS_STYLES: Record<string, string> = {
  open:     "border-emerald-200 bg-emerald-50 text-emerald-700",
  rolling:  "border-teal-200 bg-teal-50 text-teal-700",
  closed:   "border-red-200 bg-red-50 text-red-600",
  paused:   "border-amber-200 bg-amber-50 text-amber-700",
  seasonal: "border-purple-200 bg-purple-50 text-purple-700",
  unclear:  "border-slate-200 bg-slate-50 text-slate-500",
};

function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = (status || "unclear").toLowerCase();
  const cls = STATUS_STYLES[s] ?? STATUS_STYLES.unclear;
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide", cls)}>
      {s}
    </span>
  );
}

export function getRowKey(row: ResultRecord, idx: number): string {
  return (
    row.fund_url || row.fund_name || row.source_folder || row.extraction_timestamp || `row-${idx}`
  );
}

function getDateBucket(val: any): string {
  if (!val) return "Unknown date";
  const d = new Date(val);
  if (isNaN(d.getTime())) return "Unknown date";
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays <= 7) return "This week";
  if (diffDays <= 30) return "This month";
  return "Older";
}

function groupResults(
  results: ResultRecord[],
  groupBy: GroupBy
): { label: string; rows: ResultRecord[] }[] {
  if (groupBy === "none") return [{ label: "", rows: results }];

  const groups = new Map<string, ResultRecord[]>();

  if (groupBy === "eligibility") {
    const order = ["Highly Eligible", "Eligible", "Possibly Eligible", "Low Match", "Not Eligible"];
    results.forEach((row) => {
      const key = row.eligibility || "Unknown";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(row);
    });
    const ordered: { label: string; rows: ResultRecord[] }[] = [];
    order.forEach((key) => {
      if (groups.has(key)) ordered.push({ label: key, rows: groups.get(key)! });
    });
    if (groups.has("Unknown")) ordered.push({ label: "Unknown", rows: groups.get("Unknown")! });
    return ordered;
  }

  if (groupBy === "scrape-date") {
    const bucketOrder = ["Today", "Yesterday", "This week", "This month", "Older", "Unknown date"];
    results.forEach((row) => {
      const key = getDateBucket(row.extraction_timestamp);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(row);
    });
    return bucketOrder.filter((k) => groups.has(k)).map((k) => ({ label: k, rows: groups.get(k)! }));
  }

  return [{ label: "", rows: results }];
}

// Phase 10 — per-dimension eligibility rubric rendered as a grid.
// Reads `match_rubric` JSONB from the fund row. Veto dimensions are flagged
// with a small badge so the operator can see at a glance which categories
// can hard-fail the rating.
const RUBRIC_DIMENSION_ORDER: { key: string; label: string; veto: boolean }[] = [
  { key: "geography",          label: "Geography",          veto: true },
  { key: "applicant_type",     label: "Applicant type",     veto: true },
  { key: "topic_focus",        label: "Topic / focus",      veto: true },
  { key: "beneficiary",        label: "Beneficiary",        veto: true },
  { key: "org_history",        label: "Org history / age",  veto: true },
  { key: "grant_size",         label: "Grant size",         veto: false },
  { key: "cost_share",         label: "Cost-share",         veto: true },
  { key: "explicit_exclusion", label: "Explicit exclusion", veto: true },
];

const RUBRIC_VERDICT_STYLE: Record<string, { icon: string; cls: string; label: string }> = {
  match:    { icon: "✓", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200", label: "Match" },
  partial:  { icon: "⚠", cls: "bg-amber-50 text-amber-700 ring-amber-200",     label: "Partial" },
  mismatch: { icon: "✗", cls: "bg-red-50 text-red-700 ring-red-200",            label: "Mismatch" },
  unknown:  { icon: "?", cls: "bg-slate-50 text-slate-500 ring-slate-200",       label: "Unknown" },
};

function MatchRubricCard({ rubric }: { rubric: any }) {
  if (!rubric || typeof rubric !== "object") {
    return null;
  }
  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-4">
      <div className="mb-3 flex items-center gap-2">
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-indigo-50 text-sm">🎯</div>
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Eligibility Rubric</span>
        <span className="ml-auto text-[10px] text-slate-400">VETO dimensions in red can hard-fail the rating</span>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wider text-slate-400">
            <th className="pb-1 font-semibold">Dimension</th>
            <th className="pb-1 font-semibold w-24">Verdict</th>
            <th className="pb-1 font-semibold">Evidence</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {RUBRIC_DIMENSION_ORDER.map(({ key, label, veto }) => {
            const entry = (rubric[key] || {}) as { verdict?: string; evidence?: string };
            const verdict = (entry.verdict || "unknown").toLowerCase();
            const style = RUBRIC_VERDICT_STYLE[verdict] || RUBRIC_VERDICT_STYLE.unknown;
            return (
              <tr key={key} className="align-top">
                <td className="py-1.5 pr-3">
                  <span className="text-slate-700">{label}</span>
                  {veto && (
                    <span className="ml-1.5 rounded bg-red-50 px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-red-600">
                      veto
                    </span>
                  )}
                </td>
                <td className="py-1.5 pr-3">
                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ${style.cls}`}>
                    <span>{style.icon}</span>
                    <span>{style.label}</span>
                  </span>
                </td>
                <td className="py-1.5 text-slate-600">
                  {entry.evidence || <span className="italic text-slate-300">no evidence captured</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ResultsTableSkeleton() {
  return (
    <div className="divide-y divide-slate-100">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex items-start gap-4 px-4 py-4">
          <Skeleton className="mt-1 h-7 w-7 rounded-lg" />
          <div className="flex-1 space-y-2 py-0.5">
            <Skeleton className="h-4 w-3/5" />
            <Skeleton className="h-3 w-2/5" />
            <Skeleton className="h-3 w-1/3" />
          </div>
          <div className="w-[28%] space-y-2 py-0.5">
            <Skeleton className="h-3 w-4/5" />
            <Skeleton className="h-3 w-3/5" />
          </div>
          <div className="w-[18%] space-y-2 py-0.5">
            <Skeleton className="h-5 w-20 rounded-full" />
            <Skeleton className="h-3 w-24" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ResultsTable({
  results,
  selectedRowKey,
  expandedRows,
  pinnedRowKey,
  searchQuery,
  groupBy,
  newResultKeys,
  onRowSelect,
  onToggleExpand,
  onTogglePin,
  detailFields,
  showEvidence,
  loading = false,
  error = null,
  onClearFilters,
  hasAnyData = false,
  checkedUrls = new Set(),
  starredUrls = new Set(),
  allChecked = false,
  onToggleCheck,
  onToggleCheckAll,
  onRescrape,
}: ResultsTableProps) {
  if (loading) return <ResultsTableSkeleton />;

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
        <div className="rounded-full bg-red-50 p-4">
          <SearchX size={24} className="text-red-400" />
        </div>
        <p className="text-sm font-medium text-red-700">{error}</p>
      </div>
    );
  }

  if (results.length === 0) {
    if (!hasAnyData) {
      return (
        <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
          <div className="rounded-2xl bg-slate-100 p-5">
            <Inbox size={32} className="text-slate-400" />
          </div>
          <div>
            <p className="font-semibold text-slate-700">No funds scraped yet</p>
            <p className="mt-1 text-sm text-slate-500">
              Head to the Scrape &amp; Analyze page to discover funding opportunities.
            </p>
          </div>
        </div>
      );
    }
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
        <div className="rounded-2xl bg-slate-100 p-5">
          <SearchX size={32} className="text-slate-400" />
        </div>
        <div>
          <p className="font-semibold text-slate-700">No results match your filters</p>
          <p className="mt-1 text-sm text-slate-500">
            Try adjusting your eligibility filters or clearing your search.
          </p>
        </div>
        {onClearFilters && (
          <button
            type="button"
            onClick={onClearFilters}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            Clear all filters
          </button>
        )}
      </div>
    );
  }

  const grouped = groupResults(results, groupBy);

  return (
    <div className="overflow-x-auto">
      {/* Table header */}
      <div className="grid grid-cols-[32px_44px_1fr_0.6fr_0.38fr] border-b border-slate-200 bg-slate-50 px-4 py-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        <div className="flex items-center">
          <input
            type="checkbox"
            checked={allChecked}
            onChange={onToggleCheckAll}
            className="h-3.5 w-3.5 rounded border-slate-300 accent-brand"
            aria-label="Select all"
          />
        </div>
        <div />
        <div>Fund details</div>
        <div>Audience &amp; scope</div>
        <div>Status &amp; deadline</div>
      </div>

      {/* Rows */}
      <div className="divide-y divide-slate-100">
        {grouped.map(({ label, rows }) => (
          <Fragment key={label}>
            {groupBy !== "none" && label && (
              <div className="sticky top-0 z-10 flex items-center justify-between bg-slate-100/80 px-4 py-2 backdrop-blur-sm">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                    {label}
                  </span>
                  {groupBy === "eligibility" && (
                    <Badge variant={eligibilityVariantMap[label] ?? "muted"} className="py-0">
                      {label}
                    </Badge>
                  )}
                </div>
                <span className="text-xs text-slate-400">{rows.length}</span>
              </div>
            )}

            {rows.map((row, idx) => {
              const rowKey = getRowKey(row, idx);
              const isSelected = selectedRowKey === rowKey;
              const isPinned = pinnedRowKey === rowKey;
              const isExpanded = expandedRows.has(rowKey) || isPinned;
              const isNew = newResultKeys.has(rowKey);

const rowUrl = row.fund_url || "";
              const isChecked = checkedUrls.has(rowUrl);
              const isStarred = starredUrls.has(rowUrl);

              return (
                <Fragment key={`${rowKey}-${idx}`}>
                  {/* Main row */}
                  <div
                    role="button"
                    tabIndex={0}
                    className={cn(
                      "grid cursor-pointer grid-cols-[32px_44px_1fr_0.6fr_0.38fr] px-4 py-3 transition-colors",
                      "hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand/40",
                      isNew && !isExpanded && !isPinned && "bg-sky-50/70",
                      isSelected && !isPinned && !isNew && "bg-slate-50/80",
                      isPinned && "bg-brand-50/30 ring-1 ring-inset ring-brand/20",
                      isChecked && !isNew && "bg-brand/5"
                    )}
                    onClick={() => onRowSelect(rowKey)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") onRowSelect(rowKey);
                    }}
                  >
                    {/* Checkbox — shift-click selects a range */}
                    <div className="flex items-start pt-1" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => {}}
                        onClick={(e) => {
                          e.stopPropagation();
                          onToggleCheck?.(rowUrl, e.shiftKey);
                        }}
                        className="h-3.5 w-3.5 cursor-pointer rounded border-slate-300 accent-brand"
                        aria-label="Select row"
                        title="Click to select · Shift+click to select range"
                      />
                    </div>

                    {/* Expand button */}
                    <div className="flex items-start pt-0.5">
                      <button
                        type="button"
                        className={cn(
                          "flex h-7 w-7 items-center justify-center rounded-lg border transition",
                          isExpanded
                            ? "border-brand/30 bg-brand-50 text-brand"
                            : "border-slate-200 bg-white text-slate-500 hover:border-slate-300 hover:text-slate-700"
                        )}
                        aria-expanded={isExpanded}
                        onClick={(e) => {
                          e.stopPropagation();
                          onToggleExpand(rowKey);
                        }}
                      >
                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </button>
                    </div>

                    {/* Fund details */}
                    <div className="min-w-0 space-y-1 pr-4">
                      <div className="flex flex-wrap items-center gap-1.5">
                        {isStarred && (
                          <span className="text-amber-400" title="Starred">★</span>
                        )}
                        <p className="text-sm font-semibold text-slate-900 leading-snug">
                          {highlightText(row.fund_name || "Unnamed fund", searchQuery)}
                        </p>
                        <Badge variant={eligibilityVariantMap[row.eligibility] ?? "muted"}>
                          {row.eligibility || "Unknown"}
                        </Badge>
                        {isNew && (
                          <Badge variant="new" className="shrink-0">
                            New
                          </Badge>
                        )}
                        {isPinned && (
                          <Badge variant="pinned" className="shrink-0">
                            Pinned
                          </Badge>
                        )}
                        <DiscoverySourceBadge source={row.discovery_source} />
                      </div>
                      {row.fund_url ? (
                        <a
                          href={row.fund_url}
                          target="_blank"
                          rel="noreferrer"
                          className="block truncate text-xs text-brand/70 underline-offset-2 hover:text-brand hover:underline"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {highlightText(row.fund_url, searchQuery)}
                        </a>
                      ) : (
                        <p className="text-xs text-slate-400">No URL</p>
                      )}
                      {row.notes && (
                        <p className="truncate text-xs text-slate-500">
                          {highlightText(row.notes, searchQuery)}
                        </p>
                      )}
                    </div>

                    {/* Audience & scope */}
                    <div className="min-w-0 space-y-1.5 pr-4 text-xs text-slate-600">
                      {row.applicant_types && (
                        <div>
                          <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-slate-400">Applicants</span>
                          <TagList value={row.applicant_types} query={searchQuery} />
                        </div>
                      )}
                      {row.beneficiary_focus && (
                        <div>
                          <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-slate-400">Focus</span>
                          <TagList value={row.beneficiary_focus} query={searchQuery} />
                        </div>
                      )}
                      {row.geographic_scope && (
                        <p className="truncate text-[11px]">
                          <span className="font-medium text-slate-500">Scope:</span>{" "}
                          {highlightText(formatValue(row.geographic_scope), searchQuery)}
                        </p>
                      )}
                    </div>

                    {/* Status & deadline */}
                    <div className="min-w-0 space-y-1">
                      <StatusBadge status={row.application_status} />
                      {row.deadline && (
                        <p className={cn("truncate text-xs", getDeadlineClass(row.deadline))}>
                          {highlightText(row.deadline, searchQuery)}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Expanded detail view */}
                  {isExpanded && (
                    <div className={cn("px-4 pb-5 pt-2", isPinned ? "bg-brand-50/20" : "bg-slate-50/40")}>
                      <div className="rounded-xl border border-slate-200 bg-white shadow-card overflow-hidden">

                        {/* Header */}
                        <div className="flex items-start justify-between border-b border-slate-100 bg-slate-50/60 px-4 py-3">
                          <div className="min-w-0">
                            <p className="font-semibold text-slate-900">
                              {highlightText(row.fund_name || "Unnamed fund", searchQuery)}
                            </p>
                            {row.fund_url && (
                              <a
                                href={row.fund_url}
                                target="_blank"
                                rel="noreferrer"
                                className="mt-0.5 block break-all text-xs text-brand/70 hover:text-brand hover:underline"
                              >
                                {row.fund_url}
                              </a>
                            )}
                          </div>
                          <div className="ml-4 flex shrink-0 items-center gap-2">
                            <Badge variant={eligibilityVariantMap[row.eligibility] ?? "muted"}>
                              {row.eligibility || "Unknown"}
                            </Badge>
                            {onRescrape && (
                              <button
                                type="button"
                                onClick={() => onRescrape(rowUrl)}
                                className="flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700 transition hover:bg-indigo-100"
                              >
                                <RotateCcw size={11} />
                                Rescrape
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => onTogglePin(rowKey)}
                              className={cn(
                                "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition",
                                isPinned
                                  ? "border-brand/30 bg-brand-50 text-brand"
                                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                              )}
                            >
                              {isPinned ? <PinOff size={12} /> : <Pin size={12} />}
                              {isPinned ? "Unpin" : "Pin"}
                            </button>
                          </div>
                        </div>

                        {/* 4-card body */}
                        <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2">

                          {/* Funding card */}
                          <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-4">
                            <div className="mb-3 flex items-center gap-2">
                              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-blue-50 text-sm">💰</div>
                              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Funding</span>
                            </div>
                            <dl className="space-y-2.5">
                              <div>
                                <dt className="text-[10px] text-slate-400">Amount</dt>
                                <dd className={cn("mt-0.5 text-sm font-semibold",
                                  row.funding_range && row.funding_range !== "Not stated" ? "text-emerald-600" : "text-slate-300")}>
                                  {highlightText(row.funding_range || "Not stated", searchQuery)}
                                </dd>
                              </div>
                              <div>
                                <dt className="text-[10px] text-slate-400">Deadline</dt>
                                <dd className={cn("mt-0.5 text-sm", getDeadlineClass(row.deadline))}>
                                  {highlightText(row.deadline || "—", searchQuery)}
                                </dd>
                              </div>
                              <div>
                                <dt className="text-[10px] text-slate-400">Status</dt>
                                <dd className="mt-0.5">
                                  <Badge variant="muted">{row.application_status || "Unknown"}</Badge>
                                </dd>
                              </div>
                              <div>
                                <dt className="text-[10px] text-slate-400">Grant type</dt>
                                <dd className="mt-0.5 text-xs capitalize text-slate-700">
                                  {highlightText(row.grant_type || "—", searchQuery)}
                                </dd>
                              </div>
                            </dl>
                          </div>

                          {/* Eligibility card */}
                          <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-4">
                            <div className="mb-3 flex items-center gap-2">
                              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-green-50 text-sm">✓</div>
                              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Eligibility</span>
                            </div>
                            <dl className="space-y-2.5">
                              <div>
                                <dt className="text-[10px] text-slate-400">Verdict</dt>
                                <dd className="mt-0.5">
                                  <Badge variant={eligibilityVariantMap[row.eligibility] ?? "muted"}>
                                    {row.eligibility || "Unknown"}
                                  </Badge>
                                </dd>
                              </div>
                              <div>
                                <dt className="text-[10px] text-slate-400">Applicant types</dt>
                                <dd className="mt-1 flex flex-wrap gap-1">
                                  {row.applicant_types
                                    ? String(row.applicant_types).split(";").map((t: string, i: number) => (
                                        <span key={`${t.trim()}-${i}`} className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                                          {highlightText(t.trim(), searchQuery)}
                                        </span>
                                      ))
                                    : <span className="text-xs text-slate-300">—</span>}
                                </dd>
                              </div>
                              <div>
                                <dt className="text-[10px] text-slate-400">Restrictions</dt>
                                <dd className="mt-0.5 text-xs leading-relaxed text-slate-700">
                                  {highlightText(row.restrictions || "—", searchQuery)}
                                </dd>
                              </div>
                            </dl>
                          </div>

                          {/* Audience & Scope card */}
                          <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-4">
                            <div className="mb-3 flex items-center gap-2">
                              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-purple-50 text-sm">👥</div>
                              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Audience &amp; Scope</span>
                            </div>
                            <dl className="space-y-2.5">
                              <div>
                                <dt className="text-[10px] text-slate-400">Beneficiaries</dt>
                                <dd className="mt-0.5 text-xs leading-relaxed text-slate-700">
                                  {highlightText(row.beneficiary_focus || "—", searchQuery)}
                                </dd>
                              </div>
                              <div>
                                <dt className="text-[10px] text-slate-400">Geography</dt>
                                <dd className="mt-0.5 text-xs text-slate-700">
                                  {highlightText(row.geographic_scope || "—", searchQuery)}
                                </dd>
                              </div>
                              <div>
                                <dt className="text-[10px] text-slate-400">Notes</dt>
                                <dd className="mt-0.5 text-xs leading-relaxed text-slate-700">
                                  {highlightText(row.notes || "—", searchQuery)}
                                </dd>
                              </div>
                            </dl>
                          </div>

                          {/* Eligibility rubric — per-dimension scoring (Phase 10) */}
                          <MatchRubricCard rubric={row.match_rubric} />

                          {/* Evidence card */}
                          <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-4">
                            <div className="mb-3 flex items-center gap-2">
                              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-orange-50 text-sm">📋</div>
                              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Evidence</span>
                            </div>
                            {row.evidence
                              ? <div className="rounded-lg border border-slate-100 bg-white p-3 text-xs leading-relaxed text-slate-600 whitespace-pre-wrap break-words">
                                  {highlightText(row.evidence, searchQuery)}
                                </div>
                              : <p className="text-xs text-slate-300">No evidence recorded</p>
                            }
                          </div>

                        </div>

                        {/* Technical details — collapsed by default */}
                        <div className="border-t border-slate-100">
                          <details className="group">
                            <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400 hover:text-slate-600">
                              <ChevronRight size={11} className="transition-transform group-open:rotate-90" aria-hidden="true" />
                              Technical details
                              <span className="ml-1 font-normal normal-case tracking-normal text-slate-300">
                                pages scraped · PDF · timestamps
                              </span>
                            </summary>
                            <div className="flex flex-wrap gap-6 px-4 pb-4 pt-1">
                              {(
                                [
                                  { label: "Pages scraped", value: row.pages_scraped },
                                  { label: "Visited URLs", value: row.visited_urls_count },
                                  { label: "PDF read", value: row.pdf_read ? "Yes" : "No" },
                                  { label: "PDF pages", value: row.pdf_pages },
                                  ...(row.pdf_url ? [{ label: "PDF URL", value: row.pdf_url }] : []),
                                  { label: "Scraped date", value: row.extraction_timestamp ? new Date(row.extraction_timestamp).toLocaleString() : "" },
                                  ...(row.discovery_source ? [{ label: "Discovery source", value: row.discovery_source }] : []),
                                  ...(row.error ? [{ label: "Error", value: row.error }] : []),
                                ] as { label: string; value: unknown }[]
                              )
                                .filter((f) => f.value !== null && f.value !== undefined && f.value !== "")
                                .map((f) => (
                                  <div key={f.label} className="flex flex-col gap-0.5">
                                    <span className="text-[9px] font-semibold uppercase tracking-wider text-slate-400">{f.label}</span>
                                    <span className="text-[11px] text-slate-600">{String(f.value)}</span>
                                  </div>
                                ))}
                            </div>
                          </details>
                        </div>

                        {/* PDF text */}
                        {row.pdf_text && (
                          <div className="border-t border-slate-100 px-4 pb-4 pt-3">
                            <details className="group">
                              <summary className="flex cursor-pointer list-none items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400 hover:text-slate-600">
                                <ChevronRight size={12} className="transition-transform group-open:rotate-90" aria-hidden="true" />
                                PDF text
                              </summary>
                              <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
                                {highlightText(String(row.pdf_text), searchQuery)}
                              </pre>
                            </details>
                          </div>
                        )}

                      </div>
                    </div>
                  )}
                </Fragment>
              );
            })}
          </Fragment>
        ))}
      </div>
    </div>
  );
}
