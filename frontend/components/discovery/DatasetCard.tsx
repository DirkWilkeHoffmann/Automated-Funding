"use client";

import { Download, RefreshCw } from "lucide-react";
import { Button } from "../ui/button";

const cronInput =
  "rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 font-mono text-sm text-slate-700 focus:border-brand/50 focus:outline-none focus:ring-2 focus:ring-brand/10";

type DatasetCardProps = {
  icon: React.ReactNode;
  title: string;
  description: string;
  badge?: string;
  total: number | null;
  totalLabel?: string;
  secondaryCount?: number | null;
  secondaryLabel?: string;
  lastImportedAt: string | null;
  isRefreshing: boolean;
  onRefresh: () => void;
  refreshLabel?: string;
  refreshingLabel?: string;
  cron?: string;
  onCronChange?: (cron: string) => void;
  children?: React.ReactNode;
};

export function DatasetCard({
  icon,
  title,
  description,
  badge,
  total,
  totalLabel = "Total",
  secondaryCount,
  secondaryLabel,
  lastImportedAt,
  isRefreshing,
  onRefresh,
  refreshLabel = "Refresh",
  refreshingLabel = "Importing…",
  cron,
  onCronChange,
  children,
}: DatasetCardProps) {
  const hasExtra = !!(children || onCronChange);
  return (
    <div className="card-base overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
            {icon}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <p className="text-sm font-semibold text-slate-800">{title}</p>
              {badge && (
                <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-700">
                  {badge}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500">{description}</p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          disabled={isRefreshing}
          className="flex items-center gap-1.5"
        >
          {isRefreshing ? (
            <RefreshCw size={12} className="animate-spin" />
          ) : (
            <Download size={12} />
          )}
          {isRefreshing ? refreshingLabel : refreshLabel}
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-4 p-5 sm:grid-cols-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            {totalLabel}
          </p>
          <p className="mt-0.5 text-lg font-bold text-slate-900">
            {total != null ? total.toLocaleString() : "—"}
          </p>
        </div>
        {secondaryLabel != null && (
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              {secondaryLabel}
            </p>
            <p className="mt-0.5 text-lg font-bold text-brand">
              {secondaryCount != null ? secondaryCount.toLocaleString() : "—"}
            </p>
          </div>
        )}
        <div className={secondaryLabel ? "col-span-2" : "col-span-3"}>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Last imported
          </p>
          <p className="mt-0.5 text-xs text-slate-600">
            {lastImportedAt
              ? new Date(lastImportedAt).toLocaleString()
              : "Never — click Refresh to import"}
          </p>
        </div>
      </div>

      {hasExtra && (
        <div className="space-y-4 border-t border-slate-100 px-5 pb-5 pt-4">
          {children}
          {onCronChange && cron !== undefined && (
            <div className="space-y-1">
              <p className="text-xs font-semibold text-slate-600">Import schedule (cron)</p>
              <input
                type="text"
                value={cron}
                onChange={(e) => onCronChange(e.target.value)}
                className={`w-52 ${cronInput}`}
                placeholder="0 3 * * 0"
              />
              <p className="text-[11px] text-slate-400">
                5-part cron: minute hour day month weekday
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
