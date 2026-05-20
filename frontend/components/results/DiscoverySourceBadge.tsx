const SOURCE_MAP: Record<string, { label: string; className: string }> = {
  propublica: {
    label: "ProPublica",
    className: "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
  },
  grants_gov: {
    label: "Grants.gov",
    className: "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200",
  },
  sam_gov: {
    label: "SAM.gov",
    className: "bg-violet-50 text-violet-700 ring-1 ring-violet-200",
  },
  manual: {
    label: "Manual",
    className: "bg-slate-100 text-slate-600 ring-1 ring-slate-200",
  },
};

interface DiscoverySourceBadgeProps {
  source?: string | null;
}

export function DiscoverySourceBadge({ source }: DiscoverySourceBadgeProps) {
  if (!source) return null;
  const config = SOURCE_MAP[source];
  if (!config) return null;

  return (
    <span
      className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-semibold leading-none ${config.className}`}
    >
      {config.label}
    </span>
  );
}
