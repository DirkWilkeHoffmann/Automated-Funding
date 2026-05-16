"use client";

import { Checkbox } from "../ui/checkbox";
import { Input } from "../ui/input";
import { Label } from "../ui/label";

/**
 * ResultsFilters: Sidebar filters for eligibility, search, funding range, and deadline
 */
interface ResultsFiltersProps {
  eligibilityFilter: string[];
  onEligibilityChange: (selected: string[]) => void;
  sortMode: "recent" | "alphabetical" | "eligibility";
  onSortChange: (mode: "recent" | "alphabetical" | "eligibility") => void;
  search: string;
  onSearchChange: (value: string) => void;
  onlyFutureDeadlines: boolean;
  onFutureDeadlinesChange: (value: boolean) => void;
  minFunding: string;
  onMinFundingChange: (value: string) => void;
}

const eligibilityFilterOptions = [
  "Highly Eligible",
  "Eligible",
  "Possibly Eligible",
  "Low Match",
  "Not Eligible",
];

const sortOptions: { value: "recent" | "alphabetical" | "eligibility"; label: string }[] = [
  { value: "recent", label: "Most recent" },
  { value: "alphabetical", label: "Alphabetical (A-Z)" },
  { value: "eligibility", label: "Eligibility (best first)" },
];

export function ResultsFilters({
  eligibilityFilter,
  onEligibilityChange,
  sortMode,
  onSortChange,
  search,
  onSearchChange,
  onlyFutureDeadlines,
  onFutureDeadlinesChange,
  minFunding,
  onMinFundingChange,
}: ResultsFiltersProps) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <p className="text-xs uppercase tracking-wide text-neutral-600">Eligibility</p>
        <div className="flex flex-wrap gap-2">
          {eligibilityFilterOptions.map((opt) => {
            const active = eligibilityFilter.includes(opt);
            return (
              <label
                key={opt}
                className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wide transition ${
                  active
                    ? "border-neutral-900 bg-neutral-900 text-white"
                    : "border-neutral-200 bg-white text-neutral-700 hover:border-neutral-900"
                }`}
              >
                <Checkbox
                  checked={active}
                  onChange={(e) => {
                    const newFilter = e.target.checked
                      ? [...eligibilityFilter, opt]
                      : eligibilityFilter.filter((v) => v !== opt);
                    onEligibilityChange(newFilter);
                  }}
                />
                {opt}
              </label>
            );
          })}
        </div>
      </div>

      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div className="w-full max-w-xs space-y-1">
          <Label
            htmlFor="result-sort"
            className="text-xs uppercase tracking-wide text-neutral-600"
          >
            Sort by
          </Label>
          <select
            id="result-sort"
            value={sortMode}
            onChange={(e) => onSortChange(e.target.value as typeof sortMode)}
            className="h-10 w-full rounded-md border border-neutral-300 bg-white px-3 text-sm shadow-sm outline-none transition focus:border-neutral-900 focus:ring-2 focus:ring-neutral-900/10"
          >
            {sortOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <div className="w-full max-w-sm space-y-1">
          <Label
            htmlFor="result-search"
            className="text-xs uppercase tracking-wide text-neutral-600"
          >
            Search
          </Label>
          <Input
            id="result-search"
            placeholder="Search all columns..."
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
          />
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <label className="flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700">
          <Checkbox
            checked={onlyFutureDeadlines}
            onChange={(e) => onFutureDeadlinesChange(e.target.checked)}
          />
          Future deadlines only
        </label>
        <div className="space-y-1">
          <Label
            htmlFor="min-funding"
            className="text-xs uppercase tracking-wide text-neutral-600"
          >
            Min funding
          </Label>
          <Input
            id="min-funding"
            placeholder="e.g. 50000 or 50k"
            value={minFunding}
            onChange={(e) => onMinFundingChange(e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}
