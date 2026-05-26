"use client";

import type { DashboardStats } from "../../lib/api";

const BUCKETS = [
  { key: "Highly Eligible", color: "bg-emerald-500", textColor: "text-emerald-700", label: "Highly Eligible" },
  { key: "Eligible", color: "bg-green-400", textColor: "text-green-700", label: "Eligible" },
  { key: "Possibly Eligible", color: "bg-yellow-400", textColor: "text-yellow-700", label: "Possibly" },
  { key: "Low Match", color: "bg-orange-400", textColor: "text-orange-700", label: "Low Match" },
  { key: "Not Eligible", color: "bg-red-400", textColor: "text-red-700", label: "Not Eligible" },
];

type Props = {
  stats: DashboardStats;
};

export function EligibilityBar({ stats }: Props) {
  const total = stats.funds.total;
  const byElig = stats.funds.by_eligibility;

  return (
    <div className="card-base p-5 space-y-3">
      <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Eligibility breakdown</p>

      {total === 0 ? (
        <p className="py-4 text-center text-sm text-slate-400">No funds analysed yet.</p>
      ) : (
        <>
          {/* Stacked bar */}
          <div className="flex h-5 w-full overflow-hidden rounded-full bg-slate-100">
            {BUCKETS.map(({ key, color }) => {
              const count = byElig[key] ?? 0;
              const pct = (count / total) * 100;
              if (pct === 0) return null;
              return (
                <div
                  key={key}
                  className={`${color} transition-all`}
                  style={{ width: `${pct}%` }}
                  title={`${key}: ${count}`}
                />
              );
            })}
          </div>

          {/* Legend */}
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {BUCKETS.map(({ key, color, textColor, label }) => {
              const count = byElig[key] ?? 0;
              if (count === 0) return null;
              return (
                <div key={key} className="flex items-center gap-1.5">
                  <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${color}`} />
                  <span className={`text-xs font-medium ${textColor}`}>{label}</span>
                  <span className="text-xs text-slate-500">{count}</span>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
