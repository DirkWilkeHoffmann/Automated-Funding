"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { Checkbox } from "../ui/checkbox";
import { Label } from "../ui/label";
import { cn } from "../../lib/utils";

export type GroupBy = "none" | "eligibility" | "scrape-date";
export type SortMode = "recent" | "alphabetical" | "eligibility";

const eligibilityOptions = [
  { value: "Highly Eligible", color: "emerald" },
  { value: "Eligible", color: "teal" },
  { value: "Possibly Eligible", color: "amber" },
  { value: "Low Match", color: "orange" },
  { value: "Not Eligible", color: "red" },
] as const;

const sortOptions: { value: SortMode; label: string }[] = [
  { value: "recent", label: "Most recent" },
  { value: "alphabetical", label: "Alphabetical (A–Z)" },
  { value: "eligibility", label: "Best match first" },
];

const groupByOptions: { value: GroupBy; label: string }[] = [
  { value: "none", label: "No grouping" },
  { value: "eligibility", label: "Group by eligibility" },
  { value: "scrape-date", label: "Group by scrape date" },
];

const activeColorMap: Record<string, string> = {
  emerald: "border-emerald-300 bg-emerald-50 text-emerald-800",
  teal: "border-teal-300 bg-teal-50 text-teal-800",
  amber: "border-amber-300 bg-amber-50 text-amber-800",
  orange: "border-orange-300 bg-orange-50 text-orange-800",
  red: "border-red-300 bg-red-50 text-red-700",
};

const sourceOptions = [
  { value: "all", label: "All sources" },
  { value: "grants_gov", label: "Grants.gov" },
  { value: "propublica", label: "ProPublica" },
  { value: "sam_gov", label: "SAM.gov" },
  { value: "manual", label: "Manual" },
];

interface ResultsFiltersProps {
  eligibilityFilter: string[];
  onEligibilityChange: (selected: string[]) => void;
  sortMode: SortMode;
  onSortChange: (mode: SortMode) => void;
  groupBy: GroupBy;
  onGroupByChange: (value: GroupBy) => void;
  search: string;
  onSearchChange: (value: string) => void;
  onlyFutureDeadlines: boolean;
  onFutureDeadlinesChange: (value: boolean) => void;
  minFunding: string;
  onMinFundingChange: (value: string) => void;
  sourceFilter: string;
  onSourceFilterChange: (value: string) => void;
  activeFilterCount: number;
  onClearAll: () => void;
}

export function ResultsFilters({
  eligibilityFilter,
  onEligibilityChange,
  sortMode,
  onSortChange,
  groupBy,
  onGroupByChange,
  search,
  onSearchChange,
  onlyFutureDeadlines,
  onFutureDeadlinesChange,
  minFunding,
  onMinFundingChange,
  sourceFilter,
  onSourceFilterChange,
  activeFilterCount,
  onClearAll,
}: ResultsFiltersProps) {
  const [localSearch, setLocalSearch] = useState(search);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLocalSearch(search);
  }, [search]);

  useEffect(() => () => { if (debounceRef.current) clearTimeout(debounceRef.current); }, []);

  const handleSearchChange = useCallback(
    (value: string) => {
      setLocalSearch(value);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => onSearchChange(value), 300);
    },
    [onSearchChange]
  );

  const handleClearSearch = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setLocalSearch("");
    onSearchChange("");
  }, [onSearchChange]);

  return (
    <div className="space-y-4 border-b border-slate-100 px-6 py-4">
      {/* Eligibility filter chips */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Eligibility
        </span>
        {eligibilityOptions.map(({ value, color }) => {
          const active = eligibilityFilter.includes(value);
          return (
            <label
              key={value}
              className={cn(
                "flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-all",
                active
                  ? activeColorMap[color]
                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50"
              )}
            >
              <Checkbox
                checked={active}
                onChange={(e) => {
                  const newFilter = e.target.checked
                    ? [...eligibilityFilter, value]
                    : eligibilityFilter.filter((v) => v !== value);
                  onEligibilityChange(newFilter);
                }}
                className="sr-only"
              />
              {value}
            </label>
          );
        })}
        {activeFilterCount > 0 && (
          <button
            type="button"
            onClick={onClearAll}
            className="flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200"
          >
            <X size={11} />
            Clear {activeFilterCount} filter{activeFilterCount !== 1 ? "s" : ""}
          </button>
        )}
      </div>

      {/* Second row: sort, group-by, search, deadline, min funding */}
      <div className="flex flex-wrap items-end gap-3">
        {/* Sort */}
        <div className="space-y-1">
          <Label htmlFor="result-sort" className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Sort
          </Label>
          <select
            id="result-sort"
            value={sortMode}
            onChange={(e) => onSortChange(e.target.value as SortMode)}
            className="h-8 rounded-lg border border-slate-200 bg-white pl-3 pr-7 text-xs text-slate-900 shadow-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20"
          >
            {sortOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Group by */}
        <div className="space-y-1">
          <Label htmlFor="result-groupby" className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Group
          </Label>
          <select
            id="result-groupby"
            value={groupBy}
            onChange={(e) => onGroupByChange(e.target.value as GroupBy)}
            className="h-8 rounded-lg border border-slate-200 bg-white pl-3 pr-7 text-xs text-slate-900 shadow-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20"
          >
            {groupByOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Source */}
        <div className="space-y-1">
          <Label htmlFor="result-source" className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Source
          </Label>
          <select
            id="result-source"
            value={sourceFilter}
            onChange={(e) => onSourceFilterChange(e.target.value)}
            className="h-8 rounded-lg border border-slate-200 bg-white pl-3 pr-7 text-xs text-slate-900 shadow-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20"
          >
            {sourceOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Search */}
        <div className="min-w-[200px] flex-1 space-y-1">
          <Label htmlFor="result-search" className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Search
          </Label>
          <div className="relative">
            <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              id="result-search"
              type="text"
              placeholder="Search all fields…"
              value={localSearch}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="h-8 w-full rounded-lg border border-slate-200 bg-white pl-7 pr-8 text-xs text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20"
            />
            {localSearch && (
              <button
                type="button"
                onClick={handleClearSearch}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                aria-label="Clear search"
              >
                <X size={13} />
              </button>
            )}
          </div>
        </div>

        {/* Future deadlines */}
        <label className="flex h-8 cursor-pointer items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 hover:bg-slate-50">
          <Checkbox
            checked={onlyFutureDeadlines}
            onChange={(e) => onFutureDeadlinesChange(e.target.checked)}
          />
          Future deadlines only
        </label>

        {/* Min funding */}
        <div className="space-y-1">
          <Label htmlFor="min-funding" className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Min funding
          </Label>
          <input
            id="min-funding"
            type="text"
            placeholder="e.g. 50k"
            value={minFunding}
            onChange={(e) => onMinFundingChange(e.target.value)}
            className="h-8 w-28 rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20"
          />
        </div>
      </div>
    </div>
  );
}
