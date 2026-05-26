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
  web_search: {
    label: "Web search",
    className: "bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200",
  },
  federal_register: {
    label: "Fed. Register",
    className: "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
  },
  state_portals: {
    label: "State portals",
    className: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  },
  usaspending: {
    label: "USAspending",
    className: "bg-teal-50 text-teal-700 ring-1 ring-teal-200",
  },
  candid: {
    label: "Candid",
    className: "bg-pink-50 text-pink-700 ring-1 ring-pink-200",
  },
  philanthropy_digest: {
    label: "PND",
    className: "bg-stone-50 text-stone-600 ring-1 ring-stone-200",
  },
  irs_bmf: {
    label: "IRS BMF",
    className: "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
  },
  grants_gov_db: {
    label: "Grants.gov DB",
    className: "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200",
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
