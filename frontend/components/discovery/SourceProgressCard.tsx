import { AlertCircle, CheckCircle2, Loader2, Minus, XCircle } from "lucide-react";
import type { SourceProgress } from "../../lib/api";
import { DiscoverySourceBadge } from "../results/DiscoverySourceBadge";

const STATUS_ICON = {
  pending: <Minus size={12} className="text-slate-300" />,
  running: <Loader2 size={12} className="animate-spin text-brand" />,
  completed: <CheckCircle2 size={12} className="text-emerald-500" />,
  failed: <XCircle size={12} className="text-red-500" />,
  cancelled: <AlertCircle size={12} className="text-amber-500" />,
} as const;

export function SourceProgressCard({ source }: { source: SourceProgress }) {
  const icon = STATUS_ICON[source.status as keyof typeof STATUS_ICON] ?? null;
  const dimmed = source.status === "pending";
  const hasNew = (source.urls_new ?? 0) > 0;

  return (
    <div
      className={`group relative rounded-lg border px-3 py-2.5 transition-all ${
        dimmed ? "opacity-60" : ""
      } ${
        hasNew
          ? "border-orange-300 bg-white shadow-[0_0_0_3px_rgba(251,146,60,0.18)]"
          : "border-slate-200 bg-white"
      }`}
    >
      {hasNew && (
        <div className="pointer-events-none invisible absolute -top-9 left-1/2 z-20 -translate-x-1/2 whitespace-nowrap rounded-md bg-slate-800 px-2.5 py-1 text-[11px] font-medium text-white opacity-0 shadow-md transition-all group-hover:visible group-hover:opacity-100">
          {source.urls_found} found · {source.urls_new} new
          <div className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-slate-800" />
        </div>
      )}
      <div className="flex items-center gap-2">
        {icon}
        <DiscoverySourceBadge source={source.name} />
        <span className="ml-auto text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          {source.status}
        </span>
      </div>
      <div className="mt-2 flex items-baseline gap-3">
        <div>
          <p className="text-lg font-bold text-slate-900">{source.urls_found}</p>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">URLs</p>
        </div>
        {source.urls_new > 0 && (
          <div>
            <p className="text-lg font-bold text-brand">{source.urls_new}</p>
            <p className="text-[10px] uppercase tracking-wider text-slate-400">new</p>
          </div>
        )}
        {source.documents_found > 0 && (
          <div>
            <p className="text-lg font-bold text-emerald-600">{source.documents_found}</p>
            <p className="text-[10px] uppercase tracking-wider text-slate-400">docs</p>
          </div>
        )}
      </div>
      {(source.current_action || source.error) && (
        <p
          className={`mt-1.5 truncate text-[11px] ${
            source.error ? "text-red-500" : "text-slate-500"
          }`}
          title={source.error || source.current_action || ""}
        >
          {source.error || source.current_action}
        </p>
      )}
    </div>
  );
}
