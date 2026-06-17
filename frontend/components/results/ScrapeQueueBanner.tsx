"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "../../lib/api";

interface ActiveJob {
  job_id: string;
  total_urls: number;
  completed_urls: number;
  progress_percent: number;
  current_url: string | null;
  done: boolean;
}

export function ScrapeQueueBanner() {
  const [jobs, setJobs] = useState<ActiveJob[]>([]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      if (cancelled) return;
      try {
        const { jobs: active } = await api.activeJobs();
        if (!cancelled) setJobs((active as ActiveJob[]).filter((j) => !j.done));
      } catch {}
      if (!cancelled) timer = setTimeout(poll, 5000);
    };
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  if (jobs.length === 0) return null;

  const totalUrls = jobs.reduce((s, j) => s + j.total_urls, 0);
  const completedUrls = jobs.reduce((s, j) => s + j.completed_urls, 0);
  const pct = totalUrls > 0 ? Math.round((completedUrls / totalUrls) * 100) : 0;
  const currentUrl = jobs[0]?.current_url;

  return (
    <div className="flex items-center gap-3 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-xs">
      <Loader2 size={13} className="shrink-0 animate-spin text-indigo-500" />
      <div className="min-w-0 flex-1">
        <span className="font-semibold text-indigo-800">
          {jobs.length} scrape job{jobs.length !== 1 ? "s" : ""} in progress
        </span>
        <span className="ml-2 text-indigo-600">
          {completedUrls}&thinsp;/&thinsp;{totalUrls} URLs analysed ({pct}%)
        </span>
        {currentUrl && (
          <span className="ml-2 truncate text-indigo-400">
            · currently: {currentUrl}
          </span>
        )}
      </div>
      <div className="shrink-0">
        <div className="h-1.5 w-32 overflow-hidden rounded-full bg-indigo-200">
          <div
            className="h-full rounded-full bg-indigo-500 transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    </div>
  );
}
