// Custom hook for sorting logic.

import { useMemo } from "react";

type ResultRecord = Record<string, any>;
export type SortMode = "recent" | "alphabetical" | "eligibility";

export const SORT_OPTIONS: { value: SortMode; label: string }[] = [
  { value: "recent", label: "Most recent" },
  { value: "alphabetical", label: "Alphabetical (A-Z)" },
  { value: "eligibility", label: "Eligibility (best first)" },
];

export const ELIGIBILITY_TONE: Record<string, "accent" | "muted" | "outline"> = {
  "Highly Eligible": "accent",
  Eligible: "accent",
  "Possibly Eligible": "muted",
  "Low Match": "outline",
  "Not Eligible": "outline",
};

export function useSorting(data: ResultRecord[], sortMode: SortMode) {
  const sortedData = useMemo(() => {
    const copy = [...data];

    switch (sortMode) {
      case "recent":
        return copy.sort((a, b) => {
          const aTime = new Date(a.extraction_timestamp || 0).getTime();
          const bTime = new Date(b.extraction_timestamp || 0).getTime();
          return bTime - aTime;
        });

      case "alphabetical":
        return copy.sort((a, b) => (a.fund_name || "").localeCompare(b.fund_name || ""));

      case "eligibility": {
        const eligibilityOrder = [
          "Highly Eligible",
          "Eligible",
          "Possibly Eligible",
          "Low Match",
          "Not Eligible",
        ];
        return copy.sort((a, b) => {
          const aIndex = eligibilityOrder.indexOf(a.eligibility || "");
          const bIndex = eligibilityOrder.indexOf(b.eligibility || "");
          return (aIndex === -1 ? 999 : aIndex) - (bIndex === -1 ? 999 : bIndex);
        });
      }

      default:
        return copy;
    }
  }, [data, sortMode]);

  return { sortedData };
}
