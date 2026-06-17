"use client";

import { useEffect, useState } from "react";
import { Filter } from "lucide-react";
import { api, type PreFilterFunnelStage, type PreFilterPreview } from "../../lib/api";

export function PreFilterSummary() {
  const [preview, setPreview] = useState<PreFilterPreview | null>(null);

  useEffect(() => {
    api.prefilterPreview().then(setPreview).catch(() => {});
  }, []);

  if (!preview) return null;

  return (
    <div className="card-base overflow-hidden">
      <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-4">
        <Filter size={13} className="text-slate-400" />
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">
            Pre-filter preview
          </p>
          <p className="mt-0.5 text-xs text-slate-500">
            Candidate pool your org profile would pass through before a discovery run starts.
          </p>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-6 p-5 sm:grid-cols-2">
        {[preview.funders, preview.opportunities].map((funnel) => {
          const max = funnel.stages[0]?.count || 1;
          return (
            <div key={funnel.name}>
              <p className="mb-3 text-xs font-semibold text-slate-600">{funnel.name}</p>
              <div className="space-y-2">
                {funnel.stages.map((stage: PreFilterFunnelStage, i: number) => (
                  <div key={i}>
                    <div className="mb-0.5 flex justify-between text-[11px]">
                      <span className="text-slate-600">{stage.label}</span>
                      <span className="font-semibold text-slate-800">
                        {stage.count.toLocaleString()}
                      </span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full rounded-full bg-brand/60 transition-all"
                        style={{ width: `${Math.max(2, Math.round((stage.count / max) * 100))}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
