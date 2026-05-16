// Custom hook for filter management and logic.

import { useCallback, useMemo } from "react";

type ResultRecord = Record<string, any>;

export const ELIGIBILITY_FILTER_OPTIONS = [
  "Highly Eligible",
  "Eligible",
  "Possibly Eligible",
  "Low Match",
  "Not Eligible",
];

export function useFilters(
  data: ResultRecord[],
  eligibilityFilter: string[],
  search: string,
  minFunding: string,
  onlyFutureDeadlines: boolean
) {
  // Check if any filters are active
  const filtersActive = useMemo(() => {
    const eligibilityActive =
      eligibilityFilter.length > 0 &&
      eligibilityFilter.length !== ELIGIBILITY_FILTER_OPTIONS.length;
    if (search.trim() || minFunding.trim()) return true;
    if (onlyFutureDeadlines) return true;
    if (eligibilityActive) return true;
    return false;
  }, [search, minFunding, onlyFutureDeadlines, eligibilityFilter]);

  // Filter data based on criteria
  const filteredData = useMemo(() => {
    let filtered = data;

    // Filter by eligibility
    if (eligibilityFilter.length > 0) {
      filtered = filtered.filter((row) => eligibilityFilter.includes(row.eligibility || ""));
    }

    // Filter by search term
    if (search.trim()) {
      const searchLower = search.toLowerCase();
      filtered = filtered.filter((row) => {
        const fundName = (row.fund_name || "").toLowerCase();
        const fundUrl = (row.fund_url || "").toLowerCase();
        const notes = (row.notes || "").toLowerCase();
        return (
          fundName.includes(searchLower) ||
          fundUrl.includes(searchLower) ||
          notes.includes(searchLower)
        );
      });
    }

    // Filter by minimum funding
    if (minFunding.trim()) {
      const minAmount = parseFloat(minFunding);
      if (!isNaN(minAmount)) {
        filtered = filtered.filter((row) => {
          const fundingRange = row.funding_range || "";
          const numbers = fundingRange.match(/\d+/g);
          if (numbers && numbers.length > 0) {
            return parseInt(numbers[numbers.length - 1]) >= minAmount;
          }
          return true;
        });
      }
    }

    // Filter by future deadlines
    if (onlyFutureDeadlines) {
      const now = new Date();
      filtered = filtered.filter((row) => {
        const deadline = row.deadline;
        if (!deadline) return false;
        try {
          const deadlineDate = new Date(deadline);
          return deadlineDate > now;
        } catch {
          return false;
        }
      });
    }

    return filtered;
  }, [data, eligibilityFilter, search, minFunding, onlyFutureDeadlines]);

  return {
    filteredData,
    filtersActive,
  };
}
