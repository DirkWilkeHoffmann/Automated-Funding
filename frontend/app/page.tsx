"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BarChart3, Play, Radar, Zap } from "lucide-react";
import { api, type DashboardStats } from "../lib/api";
import { Button } from "../components/ui/button";
import { StatsGrid } from "../components/dashboard/StatsGrid";
import { EligibilityBar } from "../components/dashboard/EligibilityBar";
import { DiscoveryRunCard } from "../components/dashboard/DiscoveryRunCard";
import { OrgHealthCard } from "../components/dashboard/OrgHealthCard";

function SkeletonCard({ className = "" }: { className?: string }) {
  return <div className={`card-base animate-pulse bg-slate-50 ${className}`} />;
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .stats()
      .then(setStats)
      .catch((e: any) => setError(e.message || "Failed to load stats"))
      .finally(() => setLoading(false));
  }, []);

  const today = new Date().toLocaleDateString("en-GB", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <div className="page-content space-y-6">
      <header className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-widest text-slate-400">Overview</p>
          <h1 className="mt-0.5 text-2xl font-bold text-slate-900">Dashboard</h1>
          <p className="mt-1 text-sm text-slate-500">{today}</p>
        </div>
      </header>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Stats grid */}
      {loading ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <SkeletonCard key={i} className="h-28" />)}
        </div>
      ) : stats ? (
        <StatsGrid stats={stats} />
      ) : null}

      {/* Two-column: eligibility bar + discovery run */}
      {loading ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <SkeletonCard className="h-36" />
          <SkeletonCard className="h-36" />
        </div>
      ) : stats ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <EligibilityBar stats={stats} />
          <DiscoveryRunCard stats={stats} />
        </div>
      ) : null}

      {/* Org health */}
      {loading ? (
        <SkeletonCard className="h-40" />
      ) : stats ? (
        <OrgHealthCard stats={stats} />
      ) : null}

      {/* Quick actions */}
      <div className="card-base p-5">
        <p className="mb-3 text-[10px] font-bold uppercase tracking-wider text-slate-400">Quick actions</p>
        <div className="flex flex-wrap gap-3">
          <Button asChild variant="outline" className="gap-2">
            <Link href="/scrape">
              <Zap size={14} /> Scrape URLs
            </Link>
          </Button>
          <Button asChild variant="outline" className="gap-2">
            <Link href="/discovery">
              <Radar size={14} /> Run discovery
            </Link>
          </Button>
          <Button asChild variant="outline" className="gap-2">
            <Link href="/results">
              <BarChart3 size={14} /> View results
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
