"use client";

import { useState, useEffect } from "react";
import { API_BASE_URL, getApiBaseUrl, setApiOverride, clearApiOverride } from "../../lib/api";

const GIT_BRANCH = process.env.NEXT_PUBLIC_GIT_BRANCH ?? "(not set)";
const GIT_SHA = process.env.NEXT_PUBLIC_GIT_SHA ?? "(not set)";

type HealthStatus = "idle" | "loading" | "ok" | "error";

export default function TestPage() {
  const [activeUrl, setActiveUrl] = useState(API_BASE_URL);
  const [overrideInput, setOverrideInput] = useState("");
  const [hasOverride, setHasOverride] = useState(false);
  const [healthStatus, setHealthStatus] = useState<HealthStatus>("idle");
  const [healthBody, setHealthBody] = useState<string | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem("dev_api_override");
    setHasOverride(!!stored);
    setActiveUrl(getApiBaseUrl());
    if (stored) setOverrideInput(stored);
  }, []);

  function applyOverride() {
    const url = overrideInput.trim();
    if (!url) return;
    setApiOverride(url);
    setActiveUrl(url.replace(/\/$/, ""));
    setHasOverride(true);
    setHealthStatus("idle");
    setHealthBody(null);
  }

  function removeOverride() {
    clearApiOverride();
    setOverrideInput("");
    setHasOverride(false);
    setActiveUrl(API_BASE_URL);
    setHealthStatus("idle");
    setHealthBody(null);
  }

  async function runHealthCheck() {
    setHealthStatus("loading");
    setHealthBody(null);
    const url = getApiBaseUrl();
    const extraHeaders = url.includes("ngrok") ? { "ngrok-skip-browser-warning": "true" } : {};
    try {
      const res = await fetch(`${url}/health`, { cache: "no-store", headers: extraHeaders });
      const text = await res.text();
      setHealthStatus(res.ok ? "ok" : "error");
      setHealthBody(text);
    } catch (err) {
      setHealthStatus("error");
      setHealthBody(err instanceof Error ? err.message : String(err));
    }
  }

  const statusColor = {
    idle: "text-slate-400",
    loading: "text-yellow-500",
    ok: "text-emerald-600",
    error: "text-red-600",
  }[healthStatus];

  const statusLabel = {
    idle: "—",
    loading: "Checking…",
    ok: "OK",
    error: "Failed",
  }[healthStatus];

  return (
    <div className="mx-auto max-w-2xl px-6 py-10 space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-slate-800">Test &amp; Environment</h1>
        <p className="text-sm text-slate-500 mt-1">
          Dev tool — use this page to verify deployments and point the app at a different backend.
        </p>
      </div>

      {/* Deployment info */}
      <section className="rounded-xl border border-slate-200 bg-white shadow-card divide-y divide-slate-100">
        <div className="px-5 py-3">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-400">Deployment</span>
        </div>
        <Row label="Branch" value={GIT_BRANCH} mono />
        <Row label="Commit" value={GIT_SHA} mono />
        <Row label="Build-time API URL" value={API_BASE_URL} mono />
        <Row
          label="Active API URL"
          value={activeUrl}
          mono
          badge={hasOverride ? { text: "override", color: "bg-amber-100 text-amber-700" } : undefined}
        />
      </section>

      {/* API URL override */}
      <section className="rounded-xl border border-slate-200 bg-white shadow-card space-y-4 p-5">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">API URL override</h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Stored in localStorage. Persists across page reloads. Use an ngrok URL to point this
            deployment at your local backend.
          </p>
        </div>
        <div className="flex gap-2">
          <input
            type="url"
            className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm font-mono text-slate-700 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-brand/40"
            placeholder="https://xxxx.ngrok-free.app"
            value={overrideInput}
            onChange={(e) => setOverrideInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && applyOverride()}
          />
          <button
            onClick={applyOverride}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark transition-colors"
          >
            Apply
          </button>
          {hasOverride && (
            <button
              onClick={removeOverride}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 transition-colors"
            >
              Clear
            </button>
          )}
        </div>
      </section>

      {/* Health check */}
      <section className="rounded-xl border border-slate-200 bg-white shadow-card p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">Health check</h2>
            <p className="text-xs text-slate-400 mt-0.5">Hits GET /health on the active API URL.</p>
          </div>
          <div className="flex items-center gap-3">
            <span className={`text-sm font-medium ${statusColor}`}>{statusLabel}</span>
            <button
              onClick={runHealthCheck}
              disabled={healthStatus === "loading"}
              className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50 transition-colors"
            >
              {healthStatus === "loading" ? "Checking…" : "Check"}
            </button>
          </div>
        </div>
        {healthBody && (
          <pre className="rounded-lg bg-slate-50 border border-slate-100 px-4 py-3 text-xs font-mono text-slate-600 whitespace-pre-wrap break-all">
            {healthBody}
          </pre>
        )}
      </section>
    </div>
  );
}

function Row({
  label,
  value,
  mono,
  badge,
}: {
  label: string;
  value: string;
  mono?: boolean;
  badge?: { text: string; color: string };
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 py-3">
      <span className="text-sm text-slate-500 shrink-0 w-36">{label}</span>
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={`text-sm text-slate-800 break-all ${mono ? "font-mono" : ""}`}
        >
          {value}
        </span>
        {badge && (
          <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${badge.color}`}>
            {badge.text}
          </span>
        )}
      </div>
    </div>
  );
}
