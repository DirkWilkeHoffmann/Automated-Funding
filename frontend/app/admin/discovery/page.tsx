"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Save, Sparkles, Target } from "lucide-react";
import { api, type TargetingSuggestion, type TargetingStatus } from "../../../lib/api";
import { Button } from "../../../components/ui/button";

// ── Constants ─────────────────────────────────────────────────────────────────

const NTEE_PREFIXES = [
  { code: "A", label: "Arts & Culture" },
  { code: "B", label: "Education" },
  { code: "C", label: "Environment" },
  { code: "D", label: "Animal-Related" },
  { code: "E", label: "Health Care" },
  { code: "F", label: "Mental Health" },
  { code: "G", label: "Disease & Disorders" },
  { code: "H", label: "Medical Research" },
  { code: "I", label: "Crime & Legal" },
  { code: "J", label: "Employment" },
  { code: "K", label: "Food & Agriculture" },
  { code: "L", label: "Housing" },
  { code: "M", label: "Public Safety" },
  { code: "N", label: "Recreation & Sports" },
  { code: "O", label: "Youth Development" },
  { code: "P", label: "Human Services" },
  { code: "Q", label: "International" },
  { code: "R", label: "Civil Rights" },
  { code: "S", label: "Community Improvement" },
  { code: "T", label: "Philanthropy / Foundations" },
  { code: "U", label: "Science & Technology" },
  { code: "V", label: "Social Science" },
  { code: "W", label: "Public / Societal Benefit" },
  { code: "X", label: "Religion" },
  { code: "Y", label: "Mutual Benefit" },
  { code: "Z", label: "Unknown" },
];

const CFDA_CATEGORIES: { code: string; label: string }[] = [
  { code: "ACA", label: "Affordable Care Act" },
  { code: "AG",  label: "Agriculture" },
  { code: "AR",  label: "Arts" },
  { code: "BC",  label: "Business & Commerce" },
  { code: "CD",  label: "Community Development" },
  { code: "CP",  label: "Consumer Protection" },
  { code: "DPR", label: "Disaster Prevention & Relief" },
  { code: "ED",  label: "Education" },
  { code: "ELT", label: "Employment, Labor & Training" },
  { code: "EN",  label: "Energy" },
  { code: "ENV", label: "Environment" },
  { code: "FN",  label: "Food & Nutrition" },
  { code: "HL",  label: "Health" },
  { code: "HO",  label: "Housing" },
  { code: "HU",  label: "Humanities" },
  { code: "IIJ", label: "Infrastructure Investment & Jobs Act" },
  { code: "IS",  label: "Information & Statistics" },
  { code: "ISS", label: "Income Security & Social Services" },
  { code: "LJL", label: "Law, Justice & Legal Services" },
  { code: "NR",  label: "Natural Resources" },
  { code: "RD",  label: "Regional Development" },
  { code: "ST",  label: "Science & Technology / R&D" },
  { code: "T",   label: "Transportation" },
];

const APPLICANT_CODES: { code: string; label: string }[] = [
  { code: "01", label: "County governments" },
  { code: "02", label: "City / township governments" },
  { code: "04", label: "Special district governments" },
  { code: "05", label: "Independent school districts" },
  { code: "06", label: "Public / state-controlled higher education" },
  { code: "07", label: "Federally recognized tribal governments" },
  { code: "08", label: "Public housing authorities" },
  { code: "10", label: "Other Native American tribal organizations" },
  { code: "12", label: "Nonprofits with 501(c)(3) status" },
  { code: "13", label: "Nonprofits without 501(c)(3) status" },
  { code: "20", label: "Private institutions of higher education" },
  { code: "21", label: "Individuals" },
  { code: "22", label: "For-profit organizations" },
  { code: "23", label: "Small businesses" },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

const inp =
  "w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 focus:border-brand/50 focus:outline-none focus:ring-2 focus:ring-brand/10";

function StatusMsg({ msg }: { msg: string | null }) {
  if (!msg) return null;
  const isErr = msg.startsWith("Error");
  return (
    <p className={`text-xs ${isErr ? "text-red-600" : "text-emerald-600"}`}>{msg}</p>
  );
}

function ChipSet({
  items,
  active,
  onToggle,
  hint,
}: {
  items: { code: string; label: string }[];
  active: string[];
  onToggle: (code: string) => void;
  hint?: string;
}) {
  return (
    <div className="space-y-2">
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
      <div className="flex flex-wrap gap-1.5">
        {items.map(({ code, label }) => {
          const on = active.includes(code);
          return (
            <button
              key={code}
              type="button"
              onClick={() => onToggle(code)}
              title={label}
              className={`rounded-full px-2.5 py-0.5 text-xs font-semibold transition ${
                on
                  ? "bg-brand text-white"
                  : "border border-slate-200 text-slate-500 hover:bg-slate-50"
              }`}
            >
              {code}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function KeywordChips({
  values,
  onChange,
}: {
  values: string[];
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (!v || values.includes(v)) { setDraft(""); return; }
    onChange([...values, v]);
    setDraft("");
  };
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {values.map((v) => (
          <span
            key={v}
            className="flex items-center gap-1 rounded-full bg-brand/10 px-2.5 py-0.5 text-xs font-medium text-brand"
          >
            {v}
            <button
              type="button"
              onClick={() => onChange(values.filter((x) => x !== v))}
              aria-label={`Remove ${v}`}
              className="text-brand/60 hover:text-red-600"
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder="Type a keyword and press Enter"
          className={`${inp} flex-1`}
        />
        <Button type="button" variant="outline" size="sm" onClick={add} disabled={!draft.trim()}>
          Add
        </Button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

type DraftTargeting = {
  ntee_prefixes: string[];
  cfda_categories: string[];
  cause_keywords: string[];
  applicant_codes: string[];
};

export default function DiscoveryTargetingPage() {
  const [status, setStatus] = useState<TargetingStatus | null>(null);
  const [draft, setDraft] = useState<DraftTargeting>({
    ntee_prefixes: [],
    cfda_categories: [],
    cause_keywords: [],
    applicant_codes: [],
  });
  const [mission, setMission] = useState("");
  const [deriving, setDeriving] = useState(false);
  const [deriveStatus, setDeriveStatus] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<TargetingSuggestion | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  useEffect(() => {
    api.discoveryTargetingGet()
      .then((s) => {
        setStatus(s);
        setDraft({
          ntee_prefixes: s.ntee_prefixes,
          cfda_categories: s.cfda_categories,
          cause_keywords: s.cause_keywords,
          applicant_codes: s.applicant_codes,
        });
      })
      .catch((e: any) => setLoadErr(e.message || "Failed to load targeting profile"));
  }, []);

  const derive = async () => {
    if (!mission.trim()) { setDeriveStatus("Error: paste a mission statement first."); return; }
    setDeriving(true);
    setDeriveStatus(null);
    setSuggestion(null);
    try {
      const s = await api.discoveryTargetingDerive({ mission });
      setSuggestion(s);
      setDraft({
        ntee_prefixes: s.ntee_prefixes,
        cfda_categories: s.cfda_categories,
        cause_keywords: s.cause_keywords,
        applicant_codes: s.applicant_codes,
      });
      setDeriveStatus(
        s.notes
          ? `AI suggestion applied — ${s.notes} (review chips below, then Save)`
          : "AI suggestion applied — review chips below, then Save."
      );
    } catch (e: any) {
      setDeriveStatus(`Error: ${e.message}`);
    } finally {
      setDeriving(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setSaveStatus(null);
    try {
      const updated = await api.discoveryTargetingConfirm(draft);
      setStatus(updated);
      setSaveStatus(
        updated.client_embedding_set
          ? "Targeting confirmed and client embedding computed."
          : "Targeting confirmed (embedding not set — check OpenAI key)."
      );
    } catch (e: any) {
      setSaveStatus(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const toggle = (key: keyof DraftTargeting) => (code: string) =>
    setDraft((d) => ({
      ...d,
      [key]: d[key].includes(code) ? d[key].filter((x) => x !== code) : [...d[key], code],
    }));

  if (loadErr) {
    return (
      <div className="page-content">
        <p className="text-sm text-red-600">{loadErr}</p>
      </div>
    );
  }

  return (
    <div className="page-content space-y-6">
      <header>
        <p className="text-xs font-medium uppercase tracking-widest text-slate-400">
          Admin · Discovery · Targeting
        </p>
        <h1 className="mt-0.5 text-2xl font-bold text-slate-900">
          Client Targeting Profile
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Define your organisation&apos;s mission-driven targeting signals. Auto Discovery
          uses these to rank funder candidates by match quality before scraping.
        </p>
      </header>

      {/* Status banner */}
      {status && (
        <div
          className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm ${
            status.targeting_confirmed
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-amber-200 bg-amber-50 text-amber-700"
          }`}
        >
          {status.targeting_confirmed ? (
            <CheckCircle2 size={14} />
          ) : (
            <Target size={14} />
          )}
          {status.targeting_confirmed ? (
            <>
              Targeting confirmed
              {status.targeting_updated_at &&
                ` · last updated ${new Date(status.targeting_updated_at).toLocaleDateString()}`}
              {status.client_embedding_set && " · client embedding ready"}
            </>
          ) : (
            "Targeting not yet confirmed — paste your mission and click AI Suggest, then Save."
          )}
        </div>
      )}

      {/* Step 1 — derive from mission */}
      <div className="card-base overflow-hidden">
        <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand/10 text-brand">
            <Sparkles size={15} />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-800">Step 1 — AI Suggest from Mission</p>
            <p className="text-xs text-slate-500">
              Paste your mission statement and let GPT-4o suggest the right targeting signals.
            </p>
          </div>
        </div>
        <div className="space-y-4 p-5">
          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-600">Mission statement</label>
            <textarea
              rows={3}
              className={`${inp} resize-y`}
              value={mission}
              onChange={(e) => setMission(e.target.value)}
              placeholder="We provide employment support services to adults with barriers to work…"
            />
          </div>
          <div className="flex items-center gap-3">
            <Button
              onClick={derive}
              disabled={deriving || !mission.trim()}
              variant="outline"
              className="flex items-center gap-2"
            >
              {deriving ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
              {deriving ? "Asking GPT-4o…" : "AI Suggest targeting"}
            </Button>
            <StatusMsg msg={deriveStatus} />
          </div>
          {suggestion?.notes && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <strong className="text-slate-700">AI rationale:</strong> {suggestion.notes}
            </div>
          )}
        </div>
      </div>

      {/* Step 2 — review & edit */}
      <div className="card-base overflow-hidden">
        <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand/10 text-brand">
            <Target size={15} />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-800">Step 2 — Review & Edit Signals</p>
            <p className="text-xs text-slate-500">
              Toggle chips to refine. NTEE prefixes and cause keywords drive funder vector search;
              CFDA categories gate federal opportunities; applicant codes gate Grants.gov eligibility.
            </p>
          </div>
        </div>
        <div className="space-y-6 p-5">

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600">
              NTEE code prefixes ({draft.ntee_prefixes.length} selected)
            </label>
            <ChipSet
              items={NTEE_PREFIXES}
              active={draft.ntee_prefixes}
              onToggle={toggle("ntee_prefixes")}
              hint="Funder mission categories. Select 2–5 that best describe which types of foundations fund your work."
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600">
              CFDA categories ({draft.cfda_categories.length} selected)
            </label>
            <ChipSet
              items={CFDA_CATEGORIES}
              active={draft.cfda_categories}
              onToggle={toggle("cfda_categories")}
              hint="Grants.gov funding categories. Federal opportunities must match at least one to reach the scrape queue."
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600">
              Cause keywords ({draft.cause_keywords.length})
            </label>
            <p className="text-xs text-slate-500">
              Free-text terms used in the funder embedding search. Add specific program areas,
              beneficiary groups, or issue areas.
            </p>
            <KeywordChips
              values={draft.cause_keywords}
              onChange={(v) => setDraft((d) => ({ ...d, cause_keywords: v }))}
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600">
              Grants.gov applicant codes ({draft.applicant_codes.length} selected)
            </label>
            <ChipSet
              items={APPLICANT_CODES}
              active={draft.applicant_codes}
              onToggle={toggle("applicant_codes")}
              hint="What kind of organisation you are. Opportunities that only accept other entity types are dropped."
            />
          </div>
        </div>
      </div>

      {/* Save */}
      <div className="flex items-center gap-3">
        <Button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-2"
        >
          {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
          {saving ? "Saving & embedding…" : "Confirm targeting"}
        </Button>
        <StatusMsg msg={saveStatus} />
      </div>
    </div>
  );
}
