"use client";

interface ResultsHeaderProps {
  total?: number;
  visible?: number;
  newCount?: number;
  lastRefreshedAt?: Date | null;
  autoDiscoveryEnabled?: boolean;
}

export function ResultsHeader({
  total,
  visible,
  newCount,
  lastRefreshedAt,
  autoDiscoveryEnabled,
}: ResultsHeaderProps) {
  const hasStats = typeof total === "number" && total > 0;

  return (
    <header className="flex flex-col gap-1 px-6 pt-6 pb-0">
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
    </header>
  );
}
