"use client";

import type { DashboardStats } from "../../lib/api";

type Props = {
  stats: DashboardStats;
};

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="card-base p-5">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">{label}</p>
      <p className={`mt-2 text-3xl font-bold ${accent ?? "text-slate-900"}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

export function StatsGrid({ stats }: Props) {
  const eligible =
    (stats.funds.by_eligibility["Highly Eligible"] ?? 0) +
    (stats.funds.by_eligibility["Eligible"] ?? 0) +
    (stats.funds.by_eligibility["Possibly Eligible"] ?? 0);

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <StatCard
        label="Total funds"
        value={stats.funds.total}
        sub="in database"
      />
      <StatCard
        label="Strong matches"
        value={eligible}
        sub="Eligible or higher"
        accent="text-emerald-600"
      />
      <StatCard
        label="Added this week"
        value={stats.funds.added_last_7d}
        sub="last 7 days"
        accent={stats.funds.added_last_7d > 0 ? "text-brand" : undefined}
      />
      <StatCard
        label="Discovery runs"
        value={stats.discovery.total_runs}
        sub={
          stats.discovery.total_urls_found > 0
            ? `${stats.discovery.total_urls_found} URLs found total`
            : "no runs yet"
        }
      />
    </div>
  );
}
