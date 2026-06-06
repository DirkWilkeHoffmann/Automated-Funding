"use client";

interface ResultsStats {
  surfaced: number;
  candidates: number;
  hedge: number;
  excluded: number;
}

interface ResultsHeaderProps {
  total?: number;
  visible?: number;
  newCount?: number;
  lastRefreshedAt?: Date | null;
  autoDiscoveryEnabled?: boolean;
  stats?: ResultsStats | null;
  isStrictView?: boolean;
  onShowAllCandidates?: () => void;
}

export function ResultsHeader({
  total,
  visible,
  newCount,
  lastRefreshedAt,
  autoDiscoveryEnabled,
  stats,
  isStrictView,
  onShowAllCandidates,
}: ResultsHeaderProps) {
  const hasStats = typeof total === "number" && total > 0;
  const hasFunnel = stats && stats.candidates > 0;

  return (
    <header className="flex flex-col gap-3 px-6 pt-6 pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-xs font-medium uppercase tracking-widest text-slate-400">Results</p>
          <h1 className="mt-0.5 text-2xl font-bold text-slate-900">Funding results</h1>
        </div>

        {hasStats && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="stat-pill">
              <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
              {total} total
            </span>
            {typeof visible === "number" && visible !== total && (
              <span className="stat-pill">
                <span className="h-1.5 w-1.5 rounded-full bg-brand" />
                {visible} visible
              </span>
            )}
            {newCount != null && newCount > 0 && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-50 px-2.5 py-0.5 text-xs font-semibold text-accent">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-accent" />
                </span>
                {newCount} new
              </span>
            )}
            {lastRefreshedAt && (
              <span className="text-xs text-slate-400">
                Updated {lastRefreshedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
            {autoDiscoveryEnabled && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
                </span>
                Auto-discovery active
              </span>
            )}
          </div>
        )}
      </div>

      {hasFunnel && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg border border-slate-200 bg-gradient-to-r from-emerald-50/60 via-white to-slate-50 px-4 py-2.5 text-xs">
          <div className="flex items-baseline gap-1.5">
            <span className="text-base font-bold text-emerald-700">{stats!.surfaced}</span>
            <span className="text-slate-600">surfaced</span>
          </div>
          <span className="text-slate-300">/</span>
          <div className="flex items-baseline gap-1.5">
            <span className="font-semibold text-slate-700">{stats!.candidates}</span>
            <span className="text-slate-500">candidates evaluated</span>
          </div>
          {stats!.hedge > 0 && (
            <>
              <span className="text-slate-300">·</span>
              <span className="text-slate-500">
                <span className="font-medium text-slate-600">{stats!.hedge}</span> hedge (hidden)
              </span>
            </>
          )}
          {stats!.excluded > 0 && (
            <>
              <span className="text-slate-300">·</span>
              <span className="text-slate-500">
                <span className="font-medium text-slate-600">{stats!.excluded}</span> excluded
              </span>
            </>
          )}
          {isStrictView && (stats!.hedge > 0 || stats!.excluded > 0) && onShowAllCandidates && (
            <button
              type="button"
              onClick={onShowAllCandidates}
              className="ml-auto rounded-md border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 shadow-sm hover:border-slate-300 hover:bg-slate-50"
            >
              Show all candidates
            </button>
          )}
        </div>
      )}
    </header>
  );
}
