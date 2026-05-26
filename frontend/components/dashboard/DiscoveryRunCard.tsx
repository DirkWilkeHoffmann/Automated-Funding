"use client";

import Link from "next/link";
import { ArrowRight, Radar } from "lucide-react";
import type { DashboardStats } from "../../lib/api";

type Props = {
  stats: DashboardStats;
};

const STATUS_STYLE: Record<string, string> = {
  completed: "bg-emerald-50 text-emerald-700",
  running: "bg-brand/10 text-brand",
  running_docs: "bg-brand/10 text-brand",
  failed: "bg-red-50 text-red-700",
  cancelled: "bg-amber-50 text-amber-700",
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function DiscoveryRunCard({ stats }: Props) {
  const run = stats.discovery.last_run;

  return (
    <div className="card-base p-5 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Last discovery run</p>
        <Link href="/discovery" className="flex items-center gap-1 text-xs font-medium text-brand hover:underline">
          View all <ArrowRight size={11} />
        </Link>
      </div>

      {!run ? (
        <div className="flex flex-col items-center gap-2 py-6 text-center">
          <Radar size={28} className="text-slate-200" />
          <p className="text-sm text-slate-400">No runs yet.</p>
          <Link href="/discovery" className="text-xs text-brand hover:underline">
            Run discovery →
          </Link>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${STATUS_STYLE[run.status] ?? "bg-slate-100 text-slate-600"}`}>
              {run.status}
            </span>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${run.trigger === "manual" ? "bg-indigo-50 text-indigo-700" : "bg-slate-100 text-slate-600"}`}>
              {run.trigger}
            </span>
            <span className="text-xs text-slate-400">{formatDate(run.started_at)}</span>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg bg-slate-50 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">URLs found</p>
              <p className="mt-0.5 text-xl font-bold text-slate-800">{run.urls_discovered}</p>
            </div>
            <div className="rounded-lg bg-slate-50 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">New to scrape</p>
              <p className={`mt-0.5 text-xl font-bold ${run.urls_new > 0 ? "text-brand" : "text-slate-400"}`}>
                {run.urls_new}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
