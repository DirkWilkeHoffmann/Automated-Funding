"use client";

import { AlertCircle, CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import type { APIKeyStatus, DiscoveryHealth } from "../../lib/api";

const KEY_LABELS: Record<string, string> = {
  openai: "OpenAI",
  brave_search: "Brave Search",
  sam_gov: "SAM.gov",
  candid: "Candid",
};

const KEY_IMPACT: Record<string, string> = {
  openai: "LLM extraction and result scoring will be skipped — every result will be flagged Low Match.",
  brave_search: "Web-search fallback to DuckDuckGo will return fewer, lower-quality results.",
  sam_gov: "SAM.gov contract-opportunities source will be skipped if enabled.",
  candid: "Candid Essentials funder search will be skipped if enabled.",
};

const REQUIRED_KEYS = new Set(["openai"]);  // missing → red; others → amber

export function APIKeyWarningBanner({ health }: { health: DiscoveryHealth | null }) {
  if (!health) return null;

  const issues = health.keys.filter((k) => k.status !== "ok");
  if (issues.length === 0) return null;

  return (
    <div className="space-y-2">
      {issues.map((k) => {
        const required = REQUIRED_KEYS.has(k.name);
        const isInvalid = k.status === "invalid";
        const tone =
          (required && (k.status === "missing" || isInvalid)) || isInvalid
            ? "red"
            : "amber";
        const styles =
          tone === "red"
            ? "border-red-200 bg-red-50 text-red-800"
            : "border-amber-200 bg-amber-50 text-amber-800";
        const Icon = tone === "red" ? XCircle : AlertCircle;
        const verb =
          k.status === "missing"
            ? "is not configured"
            : k.status === "invalid"
              ? "is invalid"
              : "status unknown";

        return (
          <div
            key={k.name}
            className={`flex items-start gap-2 rounded-lg border px-4 py-3 text-sm ${styles}`}
          >
            <Icon size={15} className="mt-0.5 shrink-0" />
            <div className="flex-1">
              <div>
                <span className="font-semibold">{KEY_LABELS[k.name] || k.name}</span>{" "}
                key {verb}
                {k.detail ? <span className="ml-1 opacity-75">({k.detail})</span> : null}
                {". "}
                <span className="opacity-90">{KEY_IMPACT[k.name]}</span>{" "}
                <Link href="/admin" className="font-semibold underline">
                  Set in Admin → API Tokens →
                </Link>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function APIKeyStatusPill({ status }: { status: APIKeyStatus }) {
  const map: Record<APIKeyStatus, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
    ok: { label: "OK", cls: "bg-emerald-50 text-emerald-700 border-emerald-200", Icon: CheckCircle2 },
    missing: { label: "Missing", cls: "bg-amber-50 text-amber-700 border-amber-200", Icon: AlertCircle },
    invalid: { label: "Invalid", cls: "bg-red-50 text-red-700 border-red-200", Icon: XCircle },
    unknown: { label: "Unknown", cls: "bg-slate-50 text-slate-600 border-slate-200", Icon: AlertCircle },
  };
  const { label, cls, Icon } = map[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${cls}`}>
      <Icon size={11} />
      {label}
    </span>
  );
}
