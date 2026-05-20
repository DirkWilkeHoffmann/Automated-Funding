"use client";

import Link from "next/link";
import { ExternalLink, Info } from "lucide-react";
import { API_BASE_URL } from "../../lib/api";
import { useAuth } from "../../lib/auth";

export default function SettingsPage() {
  const { user } = useAuth();

  return (
    <div className="page-content space-y-6">
      <header>
        <p className="text-xs font-medium uppercase tracking-widest text-slate-400">Settings</p>
        <h1 className="mt-0.5 text-2xl font-bold text-slate-900">Configuration</h1>
      </header>

      {/* API connection */}
      <div className="card-base divide-y divide-slate-100 overflow-hidden">
        <div className="px-5 py-4">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">API connection</p>
        </div>
        <div className="space-y-3 px-5 py-4">
          <div className="space-y-1.5">
            <label htmlFor="api-base" className="text-xs font-semibold text-slate-600">
              API base URL
            </label>
            <input
              id="api-base"
              value={API_BASE_URL}
              disabled
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500 shadow-sm"
            />
          </div>
          <p className="flex items-center gap-1.5 text-xs text-slate-500">
            <Info size={12} className="shrink-0" />
            Set with <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-slate-700">NEXT_PUBLIC_API_BASE_URL</code> in your environment.
          </p>
        </div>
      </div>

      {/* Account */}
      <div className="card-base divide-y divide-slate-100 overflow-hidden">
        <div className="px-5 py-4">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Account</p>
        </div>
        <div className="space-y-3 px-5 py-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-600">Signed in as</label>
            <input
              value={user?.email ?? "—"}
              disabled
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500 shadow-sm"
            />
          </div>
        </div>
        <div className="px-5 py-4">
          <p className="flex items-center gap-1.5 text-sm text-slate-600">
            OpenAI key, user roles, and org profile are managed in the{" "}
            <Link
              href="/admin"
              className="inline-flex items-center gap-1 text-brand hover:underline"
            >
              Admin panel
              <ExternalLink size={12} />
            </Link>{" "}
            (superusers only).
          </p>
        </div>
      </div>
    </div>
  );
}
