"use client";

import { Badge } from "../ui/badge";
import { Button } from "../ui/button";

/**
 * ResultsToolbar: Top toolbar with export, refresh, and filter controls
 */
interface ResultsToolbarProps {
  visibleCount: number;
  totalCount: number;
  filtersActive: boolean;
  refreshing: boolean;
  onRefresh: () => void;
  onClearFilters: () => void;
  onDownload: () => void;
}

export function ResultsToolbar({
  visibleCount,
  totalCount,
  filtersActive,
  refreshing,
  onRefresh,
  onClearFilters,
  onDownload,
}: ResultsToolbarProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <span className="text-base font-semibold">Funding results</span>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          disabled={refreshing}
        >
          {refreshing ? "Refreshing..." : "Refresh"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onClearFilters}
          disabled={!filtersActive}
        >
          Clear filters
        </Button>
        <Button variant="outline" size="sm" onClick={onDownload}>
          Download CSV
        </Button>
        {totalCount > 0 && (
          <Badge variant="outline">
            {filtersActive ? `${visibleCount} of ${totalCount} shown` : `${visibleCount} shown`}
          </Badge>
        )}
      </div>
    </div>
  );
}
