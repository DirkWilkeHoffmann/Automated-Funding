"use client";

import Link from "next/link";
import { AlertCircle, ArrowRight, CheckCircle2 } from "lucide-react";
import type { DashboardStats } from "../../lib/api";

type Props = {
  stats: DashboardStats;
};

const FIELD_LABELS: Record<string, string> = {
  name: "Organisation name",
  state: "Home state",
  mission: "Mission statement",
  ein: "EIN (tax ID)",
};

const ALL_FIELDS = ["name", "state", "mission", "ein"];

export function OrgHealthCard({ stats }: Props) {
  const { name, profile_complete, missing_fields } = stats.org;
  const present = ALL_FIELDS.filter((f) => !missing_fields.includes(f));

  return (
    <div className="card-base p-5 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Organisation profile</p>
        <Link href="/admin/organisation" className="flex items-center gap-1 text-xs font-medium text-brand hover:underline">
          Edit <ArrowRight size={11} />
        </Link>
      </div>

      {name && (
        <p className="text-sm font-semibold text-slate-800">{name}</p>
      )}

      <div className="space-y-1.5">
        {ALL_FIELDS.map((field) => {
          const ok = !missing_fields.includes(field);
          return (
            <div key={field} className="flex items-center gap-2">
              {ok ? (
                <CheckCircle2 size={13} className="shrink-0 text-emerald-500" />
              ) : (
                <AlertCircle size={13} className="shrink-0 text-amber-500" />
              )}
              <span className={`text-xs ${ok ? "text-slate-600" : "text-amber-700"}`}>
                {FIELD_LABELS[field] ?? field}
                {!ok && " — missing"}
              </span>
            </div>
          );
        })}
      </div>

      {!profile_complete && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          Incomplete profile reduces eligibility scoring accuracy.{" "}
          <Link href="/admin/organisation" className="font-semibold underline hover:text-amber-900">
            Complete profile →
          </Link>
        </div>
      )}
    </div>
  );
}
