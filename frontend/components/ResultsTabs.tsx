"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, RefreshCcw } from "lucide-react";

const tabs = [
  { href: "/results", label: "All Results", icon: BarChart3 },
  { href: "/results/expired-scraped", label: "Stale Funds", icon: RefreshCcw },
];

export default function ResultsTabs() {
  const pathname = usePathname();

  return (
    <div className="flex items-center gap-1 border-b border-slate-200 bg-white px-6">
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`flex items-center gap-2 border-b-2 px-3 py-3.5 text-sm font-medium transition-colors ${
              active
                ? "border-brand text-slate-900"
                : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700"
            }`}
          >
            <Icon size={15} />
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
