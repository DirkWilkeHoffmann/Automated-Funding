"use client";

import type { ReactNode } from "react";
import { Fragment } from "react";
import { ChevronDown, ChevronRight, Inbox, Pin, PinOff, SearchX } from "lucide-react";
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
  onToggleCheck?: (url: string) => void;
  onToggleCheckAll?: () => void;
}


const DETAIL_SECTIONS: Record<string, string[]> = {
  "Funding Details": ["funding_range", "application_status", "deadline", "restrictions", "notes"],
  Eligibility: ["eligibility", "eligibility_reason", "evidence"],
  "Scope & Audience": ["applicant_types", "geographic_scope", "beneficiary_focus"],
  "Source & Technical": [
    "pages_scraped",
    "visited_urls_count",
    "pdf_read",
    "pdf_pages",
    "pdf_url",
    "extraction_timestamp",
    "error",
    "source_folder",
    "Processed",
  ],
};

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

function formatValue(val: any): string {
  if (val === null || val === undefined || val === "") return "";
  return Array.isArray(val) ? val.join(", ") : String(val);
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

              // Group fields into sections for expanded view
              const fieldsBySection: Record<string, typeof detailFields> = {};
              const ungrouped: typeof detailFields = [];
              detailFields.forEach((field) => {
                let found = false;
                for (const [sectionName, accessors] of Object.entries(DETAIL_SECTIONS)) {
                  if (accessors.includes(field.accessor)) {
                    if (!fieldsBySection[sectionName]) fieldsBySection[sectionName] = [];
                    fieldsBySection[sectionName].push(field);
                    found = true;
                    break;
                  }
                }
                if (!found) ungrouped.push(field);
              });

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
                      isSelected && !isPinned && "bg-slate-50/80",
                      isPinned && "bg-brand-50/30 ring-1 ring-inset ring-brand/20",
                      isChecked && "bg-brand/5"
                    )}
                    onClick={() => onRowSelect(rowKey)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") onRowSelect(rowKey);
                    }}
                  >
                    {/* Checkbox */}
                    <div className="flex items-start pt-1" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => onToggleCheck?.(rowUrl)}
                        className="h-3.5 w-3.5 rounded border-slate-300 accent-brand"
                        aria-label="Select row"
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
                    <div className="min-w-0 space-y-0.5 pr-4 text-xs text-slate-600">
                      {row.applicant_types && (
                        <p className="truncate">
                          <span className="font-medium text-slate-700">Applicants:</span>{" "}
                          {highlightText(formatValue(row.applicant_types), searchQuery)}
                        </p>
                      )}
                      {row.beneficiary_focus && (
                        <p className="truncate">
                          <span className="font-medium text-slate-700">Focus:</span>{" "}
                          {highlightText(formatValue(row.beneficiary_focus), searchQuery)}
                        </p>
                      )}
                      {row.geographic_scope && (
                        <p className="truncate">
                          <span className="font-medium text-slate-700">Scope:</span>{" "}
                          {highlightText(formatValue(row.geographic_scope), searchQuery)}
                        </p>
                      )}
                    </div>

                    {/* Status & deadline */}
                    <div className="min-w-0 space-y-1">
                      <Badge variant="muted" className="w-fit">
                        {highlightText(row.application_status || "Not stated", searchQuery)}
                      </Badge>
                      {row.deadline && (
                        <p className="truncate text-xs text-slate-500">
                          {highlightText(row.deadline, searchQuery)}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Expanded detail view */}
                  {isExpanded && (
                    <div className={cn(
                      "px-4 pb-5 pt-2",
                      isPinned ? "bg-brand-50/20" : "bg-slate-50/40"
                    )}>
                      <div className="rounded-xl border border-slate-200 bg-white shadow-card overflow-hidden">
                        {/* Expanded header */}
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

                        {/* Sections */}
                        <div className="grid gap-0 divide-y divide-slate-100 p-4 md:grid-cols-2 md:gap-4 md:divide-y-0 md:divide-x">
                          {Object.entries(DETAIL_SECTIONS).map(([sectionName]) => {
                            const sectionFields = fieldsBySection[sectionName];
                            if (!sectionFields || sectionFields.length === 0) return null;
                            return (
                              <div key={sectionName} className="py-3 first:pt-0 last:pb-0 md:py-0 md:pr-4 md:last:pl-4 md:last:pr-0">
                                <p className="mb-2.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                                  {sectionName}
                                </p>
                                <dl className="space-y-2">
                                  {sectionFields.map((field) => {
                                    const rawVal = field.formatter
                                      ? field.formatter(row)
                                      : formatValue(row[field.accessor]);
                                    const isEmpty = !rawVal || rawVal === "-";
                                    return (
                                      <div key={field.accessor}>
                                        <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                                          {field.label}
                                        </dt>
                                        <dd className={cn(
                                          "mt-0.5 whitespace-pre-wrap break-words text-xs",
                                          isEmpty ? "text-slate-300" : "text-slate-800"
                                        )}>
                                          {isEmpty
                                            ? "—"
                                            : highlightText(rawVal, searchQuery)}
                                        </dd>
                                      </div>
                                    );
                                  })}
                                </dl>
                              </div>
                            );
                          })}
                          {ungrouped.length > 0 && (
                            <div className="py-3 md:py-0">
                              <p className="mb-2.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                                Other
                              </p>
                              <dl className="space-y-2">
                                {ungrouped.map((field) => {
                                  const rawVal = field.formatter
                                    ? field.formatter(row)
                                    : formatValue(row[field.accessor]);
                                  return (
                                    <div key={field.accessor}>
                                      <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                                        {field.label}
                                      </dt>
                                      <dd className="mt-0.5 whitespace-pre-wrap break-words text-xs text-slate-800">
                                        {highlightText(rawVal || "—", searchQuery)}
                                      </dd>
                                    </div>
                                  );
                                })}
                              </dl>
                            </div>
                          )}
                        </div>

                        {/* PDF text */}
                        {row.pdf_text && (
                          <div className="border-t border-slate-100 px-4 pb-4 pt-3">
                            <details className="group">
                              <summary className="flex cursor-pointer list-none items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400 hover:text-slate-600">
                                <ChevronRight
                                  size={12}
                                  className="transition-transform group-open:rotate-90"
                                />
                                PDF text
                              </summary>
                              <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
                                {highlightText(String(row.pdf_text), searchQuery)}
                              </pre>
                            </details>
                          </div>
                        )}

                        {!showEvidence && (
                          <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-400">
                            Evidence hidden — press <kbd className="rounded bg-slate-100 px-1 py-0.5 font-mono text-slate-600">E</kbd> to show it
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
