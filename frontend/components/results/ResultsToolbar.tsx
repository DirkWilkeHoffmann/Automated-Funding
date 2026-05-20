"use client";

import { Download, RefreshCw, X } from "lucide-react";
import { Button } from "../ui/button";
import { cn } from "../../lib/utils";

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
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-6 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          disabled={refreshing}
          className="gap-1.5"
        >
          <RefreshCw size={13} className={cn(refreshing && "animate-spin")} />
          {refreshing ? "Refreshing…" : "Refresh"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onClearFilters}
          disabled={!filtersActive}
          className="gap-1.5"
        >
          <X size={13} />
          Clear filters
        </Button>
        <Button variant="outline" size="sm" onClick={onDownload} className="gap-1.5">
          <Download size={13} />
          Export CSV
        </Button>
      </div>
      {totalCount > 0 && (
        <p className="text-sm text-slate-500">
          {filtersActive ? (
            <>
              <span className="font-medium text-slate-700">{visibleCount}</span>
              {" of "}
              <span className="font-medium text-slate-700">{totalCount}</span>
              {" results"}
            </>
          ) : (
            <>
              <span className="font-medium text-slate-700">{totalCount}</span>
              {" results"}
            </>
          )}
        </p>
      )}
    </div>
  );
}
