"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Building2, Filter, RotateCcw, Save, Sparkles, Target, Wand2 } from "lucide-react";
import { api } from "../../../lib/api";
import { Button } from "../../../components/ui/button";

const SELECTABLE_APPLICANT_TYPES = [
  "501c3", "nonprofit", "fiscal_sponsor", "government", "tribal",
  "school", "higher_education", "faith_based", "for_profit", "individual",
  // International legal forms
  "npo", "charity", "ngo",
];

// Phase 5: Grants.gov "Category of Funding Activity" codes (mirror of
// utils/discovery/cfda_categories.py).
const CFDA_CATEGORIES: { code: string; label: string }[] = [
  { code: "ACA",  label: "Affordable Care Act" },
  { code: "AG",   label: "Agriculture" },
  { code: "AR",   label: "Arts (cultural affairs, dance, design, theatre)" },
  { code: "BC",   label: "Business and Commerce" },
  { code: "CD",   label: "Community Development" },
  { code: "CP",   label: "Consumer Protection" },
  { code: "DPR",  label: "Disaster Prevention and Relief" },
  { code: "ED",   label: "Education" },
  { code: "ELT",  label: "Employment, Labor, and Training" },
  { code: "EN",   label: "Energy" },
  { code: "ENV",  label: "Environment" },
  { code: "FN",   label: "Food and Nutrition" },
  { code: "HL",   label: "Health" },
  { code: "HO",   label: "Housing" },
  { code: "HU",   label: "Humanities" },
  { code: "IIJ",  label: "Infrastructure Investment and Jobs Act" },
  { code: "IS",   label: "Information and Statistics" },
  { code: "ISS",  label: "Income Security and Social Services" },
  { code: "LJL",  label: "Law, Justice and Legal Services" },
  { code: "NR",   label: "Natural Resources" },
  { code: "O",    label: "Opportunity Zone Benefits" },
  { code: "RA",   label: "Recovery Act" },
  { code: "RD",   label: "Regional Development" },
  { code: "ST",   label: "Science and Technology / R&D" },
  { code: "T",    label: "Transportation" },
];

// Phase 5: Grants.gov EligibleApplicants codes the org self-identifies as.
// Excludes catch-alls (00/11/25/99) — they're never useful as a filter.
const ELIGIBLE_APPLICANT_CODES: { code: string; label: string }[] = [
  { code: "01", label: "County governments" },
  { code: "02", label: "City or township governments" },
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
  { code: "22", label: "For-profit organizations (not small business)" },
  { code: "23", label: "Small businesses" },
];

const NTEE_PREFIXES = [
  "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
  "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
];

const US_STATES = [
  "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
  "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
  "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
  "VA","WA","WV","WI","WY",
];

type OrgProfile = {
  name?: string; ein?: string; city?: string; state?: string; website?: string;
  mission?: string; services?: string[]; annual_income?: number;
  staff_count?: number; volunteer_count?: number;
  ai_system_prompt?: string; ai_user_prompt?: string;
  ntee_codes?: string[];
  service_states?: string[];
  applicant_types?: string[];
  accepts_unsolicited?: boolean;
  can_cost_share?: boolean;
  min_grant_size?: number | null;
  max_grant_size?: number | null;
  // Phase 5 — RFP topic filter
  cfda_categories?: string[];
  eligible_applicant_codes?: string[];
  category_suggestion_notes?: string;
  // Phase 9 — structured profile
  org_type_description?: string;
  service_area_description?: string;
  beneficiaries?: string[];
  programs?: string[];
  income_sources?: string[];
  currency?: string;
  founded_year?: number | null;
  target_outcomes?: string[];
  partner_orgs?: string[];
  accreditations?: string[];
  // Phase 10 — geography rework
  country?: string;
  service_countries?: string[];
  service_regions?: Record<string, string[]>;
};

// The actual defaults live in the backend (utils/constants/llm.py). We fetch
// them via /admin/org/default-prompts on mount so this section never goes
// stale relative to the live prompts. Fallback strings below are only used
// before the fetch resolves.
const DEFAULT_SYSTEM_PROMPT_FALLBACK = "(loading default from backend…)";
const DEFAULT_USER_PROMPT_FALLBACK = "(loading default from backend…)";

const inp = "w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 focus:border-brand/50 focus:outline-none focus:ring-2 focus:ring-brand/10";
const ta = `${inp} resize-y font-mono leading-relaxed`;

function Section({ icon: Icon, title, desc, children }: { icon: any; title: string; desc: string; children: React.ReactNode }) {
  return (
    <div className="card-base overflow-hidden">
      <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand/10 text-brand"><Icon size={15} /></div>
        <div>
          <p className="text-sm font-semibold text-slate-800">{title}</p>
          <p className="text-xs text-slate-500">{desc}</p>
        </div>
      </div>
      <div className="space-y-4 p-5">{children}</div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-semibold text-slate-600">{label}</label>
      {children}
    </div>
  );
}

function StatusMsg({ msg }: { msg: string | null }) {
  if (!msg) return null;
  const isErr = msg.startsWith("Error");
  return <p className={`text-xs ${isErr ? "text-red-600" : "text-emerald-600"}`}>{msg}</p>;
}

/** Multi-tag input for arrays of short strings (beneficiaries, programs, etc.) */
function TagListInput({
  label,
  hint,
  values,
  onChange,
  placeholder,
}: {
  label: string;
  hint?: string;
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");
  const items = Array.isArray(values) ? values : [];
  const add = () => {
    const v = draft.trim();
    if (!v) return;
    if (items.includes(v)) {
      setDraft("");
      return;
    }
    onChange([...items, v]);
    setDraft("");
  };
  const remove = (v: string) => onChange(items.filter((x) => x !== v));
  return (
    <div className="space-y-1">
      <label className="text-xs font-semibold text-slate-600">
        {label} <span className="font-normal text-slate-400">({items.length})</span>
      </label>
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
      <div className="flex flex-wrap gap-1.5">
        {items.map((v) => (
          <span
            key={v}
            className="flex items-center gap-1 rounded-full bg-brand/10 px-2.5 py-0.5 text-xs font-medium text-brand"
          >
            {v}
            <button
              type="button"
              onClick={() => remove(v)}
              aria-label={`Remove ${v}`}
              className="text-brand/70 hover:text-red-600"
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
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder || "Type and press Enter"}
          className={`${inp} flex-1`}
        />
        <Button type="button" variant="outline" size="sm" onClick={add} disabled={!draft.trim()}>
          Add
        </Button>
      </div>
    </div>
  );
}

export default function OrganisationPage() {
  const [loadError, setLoadError] = useState<string | null>(null);
  const [org, setOrg] = useState<OrgProfile>({});
  const [orgServices, setOrgServices] = useState("");
  const [orgSaving, setOrgSaving] = useState(false);
  const [orgStatus, setOrgStatus] = useState<string | null>(null);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [userPrompt, setUserPrompt] = useState("");
  const [promptSaving, setPromptSaving] = useState(false);
  const [promptStatus, setPromptStatus] = useState<string | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [suggestStatus, setSuggestStatus] = useState<string | null>(null);
  const [suggestingProfile, setSuggestingProfile] = useState(false);
  const [suggestProfileStatus, setSuggestProfileStatus] = useState<string | null>(null);
  const [defaultSystemPrompt, setDefaultSystemPrompt] = useState(DEFAULT_SYSTEM_PROMPT_FALLBACK);
  const [defaultUserPrompt, setDefaultUserPrompt] = useState(DEFAULT_USER_PROMPT_FALLBACK);
  const [livePreview, setLivePreview] = useState<string>("(loading live org profile from backend…)");
  const [previewLoading, setPreviewLoading] = useState(false);

  useEffect(() => {
    api.adminOrg()
      .then((o: OrgProfile) => {
        const profile = o || {};
        setOrg(profile);
        setOrgServices(Array.isArray(profile.services) ? profile.services.join(", ") : (profile.services as any) || "");
        setSystemPrompt(profile.ai_system_prompt || "");
        setUserPrompt(profile.ai_user_prompt || "");
      })
      .catch((e: any) => setLoadError(e.message || "Failed to load organisation data"));

    // Fetch live defaults from backend so the "Using default" text in this
    // section always matches what the backend will actually send to the LLM.
    api.adminDefaultPrompts()
      .then((d) => {
        if (d?.system) setDefaultSystemPrompt(d.system);
        if (d?.user) setDefaultUserPrompt(d.user);
      })
      .catch(() => {
        // Non-fatal: section will show the fallback placeholder.
      });

    refreshLivePreview();
  }, []);

  // Re-fetch the live org profile text. Used on mount and after saving so
  // the preview reflects whatever was just saved.
  const refreshLivePreview = async () => {
    setPreviewLoading(true);
    try {
      const r = await api.adminOrgProfileText();
      setLivePreview(r.org_profile_text || "(empty profile)");
    } catch (e: any) {
      setLivePreview(`(could not load: ${e.message})`);
    } finally {
      setPreviewLoading(false);
    }
  };

  const saveOrg = async () => {
    setOrgSaving(true); setOrgStatus(null);
    try {
      const services = orgServices.split(",").map((s) => s.trim()).filter(Boolean);
      await api.adminUpdateOrg({ ...org, services });
      setOrgStatus("Organisation profile saved.");
      // Phase 10 — re-fetch the live preview so the operator can verify
      // the saved values flow through to the LLM-injected profile text.
      refreshLivePreview();
    } catch (e: any) { setOrgStatus(`Error: ${e.message}`); }
    finally { setOrgSaving(false); }
  };

  const suggestProfile = async () => {
    setSuggestingProfile(true);
    setSuggestProfileStatus(null);
    try {
      const out = await api.adminSuggestProfile();
      setOrg((o) => ({
        ...o,
        org_type_description: out.org_type_description || "",
        service_area_description: out.service_area_description || "",
        beneficiaries: out.beneficiaries || [],
        programs: out.programs || [],
        income_sources: out.income_sources || [],
        currency: out.currency || "USD",
        founded_year: out.founded_year,
        target_outcomes: out.target_outcomes || [],
        partner_orgs: out.partner_orgs || [],
        accreditations: out.accreditations || [],
      }));
      setSuggestProfileStatus(
        out.notes
          ? `AI profile applied — ${out.notes} (review and save)`
          : "AI profile applied — review and save."
      );
    } catch (e: any) {
      setSuggestProfileStatus(`Error: ${e.message}`);
    } finally {
      setSuggestingProfile(false);
    }
  };

  const suggestCategories = async () => {
    setSuggesting(true);
    setSuggestStatus(null);
    try {
      const out = await api.adminSuggestCategories();
      setOrg((o) => ({
        ...o,
        cfda_categories: out.cfda_categories || [],
        eligible_applicant_codes: out.eligible_applicant_codes || [],
        category_suggestion_notes: out.notes || "",
      }));
      setSuggestStatus(
        out.notes
          ? `AI suggestion applied — ${out.notes} (review and save)`
          : "AI suggestion applied — review and save."
      );
    } catch (e: any) {
      setSuggestStatus(`Error: ${e.message}`);
    } finally {
      setSuggesting(false);
    }
  };

  const savePrompts = async () => {
    setPromptSaving(true); setPromptStatus(null);
    try {
      await api.adminUpdateOrg({ ...org, ai_system_prompt: systemPrompt || null, ai_user_prompt: userPrompt || null });
      setOrg((o) => ({ ...o, ai_system_prompt: systemPrompt || undefined, ai_user_prompt: userPrompt || undefined }));
      setPromptStatus("AI prompts saved. Next scrape will use updated prompts.");
    } catch (e: any) { setPromptStatus(`Error: ${e.message}`); }
    finally { setPromptSaving(false); }
  };

  if (loadError) return (
    <div className="page-content">
      <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        <AlertCircle size={14} />{loadError}
      </div>
    </div>
  );

  const effectiveSystem = systemPrompt.trim() || defaultSystemPrompt;
  const effectiveUser = userPrompt.trim() || defaultUserPrompt;

  return (
    <div className="page-content space-y-6">
      <header>
        <p className="text-xs font-medium uppercase tracking-widest text-slate-400">Admin · Organisation</p>
        <h1 className="mt-0.5 text-2xl font-bold text-slate-900">Organisation & AI</h1>
        <p className="mt-1 text-sm text-slate-500">Your organisation profile and AI evaluation instructions.</p>
      </header>

      <Section icon={Building2} title="Organisation Profile" desc="Injected into every AI grant evaluation as context about your organisation.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Row label="Organisation name"><input className={inp} value={org.name || ""} onChange={(e) => setOrg({ ...org, name: e.target.value })} placeholder="Work4ALiving" /></Row>
          <Row label="EIN"><input className={inp} value={org.ein || ""} onChange={(e) => setOrg({ ...org, ein: e.target.value })} placeholder="12-3456789" /></Row>
          <Row label="City"><input className={inp} value={org.city || ""} onChange={(e) => setOrg({ ...org, city: e.target.value })} /></Row>
          <Row label="State"><input className={inp} value={org.state || ""} onChange={(e) => setOrg({ ...org, state: e.target.value })} placeholder="GA" /></Row>
          <Row label="Website"><input className={inp} value={org.website || ""} onChange={(e) => setOrg({ ...org, website: e.target.value })} placeholder="https://…" /></Row>
          <Row label="Annual income ($)"><input type="number" className={inp} value={org.annual_income ?? ""} onChange={(e) => setOrg({ ...org, annual_income: e.target.value ? Number(e.target.value) : undefined })} /></Row>
          <Row label="Staff count"><input type="number" className={inp} value={org.staff_count ?? ""} onChange={(e) => setOrg({ ...org, staff_count: e.target.value ? Number(e.target.value) : undefined })} /></Row>
          <Row label="Volunteer count"><input type="number" className={inp} value={org.volunteer_count ?? ""} onChange={(e) => setOrg({ ...org, volunteer_count: e.target.value ? Number(e.target.value) : undefined })} /></Row>
          <div className="sm:col-span-2">
            <Row label="Mission statement"><textarea rows={2} className={ta} value={org.mission || ""} onChange={(e) => setOrg({ ...org, mission: e.target.value })} placeholder="We provide employment support services to…" /></Row>
          </div>
          <div className="sm:col-span-2">
            <Row label="Services (comma-separated)"><input className={inp} value={orgServices} onChange={(e) => setOrgServices(e.target.value)} placeholder="job training, career counseling, placement services" /></Row>
          </div>
        </div>
        <div className="flex items-center gap-3 pt-1">
          <Button onClick={saveOrg} disabled={orgSaving} className="flex items-center gap-2"><Save size={13} />{orgSaving ? "Saving…" : "Save profile"}</Button>
          <StatusMsg msg={orgStatus} />
        </div>
      </Section>

      <Section icon={Building2} title="Detailed organisation profile" desc="Structured fields injected into every AI grant evaluation. Richer profile = sharper eligibility matching against funder criteria.">
        <div className="rounded-lg border border-brand/20 bg-brand/5 px-3 py-2 text-xs text-slate-700">
          <strong className="text-brand">Tip:</strong> click <strong>AI suggest profile</strong> to auto-fill all fields from your mission &amp; services, then edit before saving.
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={suggestProfile}
            disabled={suggestingProfile}
            variant="outline"
            className="flex items-center gap-2"
          >
            <Wand2 size={13} />
            {suggestingProfile ? "Asking GPT-4o-mini…" : "AI suggest profile from mission"}
          </Button>
          <StatusMsg msg={suggestProfileStatus} />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Row label="Org type description (one line)">
              <input
                className={inp}
                value={org.org_type_description || ""}
                onChange={(e) => setOrg({ ...org, org_type_description: e.target.value })}
                placeholder="e.g. Registered US 501(c)(3) nonprofit providing workforce development training in the US and internationally"
              />
            </Row>
          </div>
          <div className="sm:col-span-2">
            <Row label="Service area (detailed)">
              <input
                className={inp}
                value={org.service_area_description || ""}
                onChange={(e) => setOrg({ ...org, service_area_description: e.target.value })}
                placeholder="e.g. Jasper, GA + W4AL Training Centers in 12 countries"
              />
            </Row>
          </div>
          <Row label="Founded year">
            <input
              type="number"
              className={inp}
              value={org.founded_year ?? ""}
              onChange={(e) => setOrg({ ...org, founded_year: e.target.value ? Number(e.target.value) : null })}
              placeholder="e.g. 2007"
              min={1800}
              max={2100}
            />
          </Row>
          <Row label="Currency">
            <input
              className={inp}
              value={org.currency || "USD"}
              onChange={(e) => setOrg({ ...org, currency: e.target.value.toUpperCase().slice(0, 3) })}
              placeholder="USD"
              maxLength={3}
            />
          </Row>
        </div>

        {/* Phase 10 — Geography (HQ country + service countries + per-country regions) */}
        <div className="space-y-3 rounded-lg border border-brand/20 bg-brand/5 p-4">
          <div>
            <p className="text-sm font-semibold text-brand">Geography (Phase 10)</p>
            <p className="text-xs text-slate-600">
              The fund's geographic scope is matched against your HQ country + the full list of countries+regions you operate in.
              Any geographic mismatch is a VETO — it overrides every other match dimension. Use FULL country names (e.g. "United States", "South Africa") — they're passed verbatim to the LLM.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Row label="HQ country (full name)">
              <input
                className={inp}
                value={org.country || ""}
                onChange={(e) => setOrg({ ...org, country: e.target.value })}
                placeholder="e.g. United States"
              />
            </Row>
            <div className="hidden sm:block" />
          </div>
          <TagListInput
            label="Countries the org operates in (service_countries)"
            hint="Full country names. Include the HQ country here too. Add ALL countries — funds in any of these become geographically eligible."
            values={org.service_countries || []}
            onChange={(v) => setOrg({ ...org, service_countries: v })}
            placeholder="e.g. United States, South Africa, Kenya"
          />
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600">
              Sub-regions per country (service_regions, optional)
            </label>
            <p className="text-xs text-slate-500">
              Optional — if you want region-level precision per country, add regions below.
              <strong> Leaving regions empty for a country means country-level overlap is enough to match.</strong>
              {" "}For example: leave South Africa regions empty if you'll consider any South African fund, or add specific provinces if you only work in some.
            </p>
            {(org.service_countries || []).map((countryName) => {
              const regions = org.service_regions?.[countryName] || [];
              return (
                <div key={countryName} className="rounded border border-slate-200 bg-white p-2">
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">{countryName} regions ({regions.length})</p>
                  <TagListInput
                    label=""
                    values={regions}
                    onChange={(v) => setOrg({
                      ...org,
                      service_regions: { ...(org.service_regions || {}), [countryName]: v },
                    })}
                    placeholder={countryName.toLowerCase().includes("united states") ? "e.g. Georgia, Florida" : "e.g. Eastern Cape, Western Cape"}
                  />
                </div>
              );
            })}
            {(org.service_countries || []).length === 0 && (
              <p className="text-[11px] italic text-slate-400">
                Add a country above to specify its sub-regions.
              </p>
            )}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <TagListInput
            label="Beneficiaries served"
            hint="Target groups your programs serve."
            values={org.beneficiaries || []}
            onChange={(v) => setOrg({ ...org, beneficiaries: v })}
            placeholder="e.g. unemployed adults"
          />
          <TagListInput
            label="Programs offered"
            hint="Distinct named programs (more structured than the services list above)."
            values={org.programs || []}
            onChange={(v) => setOrg({ ...org, programs: v })}
            placeholder="e.g. W4AL Training Centers"
          />
          <TagListInput
            label="Target outcomes"
            hint="Measurable outcomes your org aims for."
            values={org.target_outcomes || []}
            onChange={(v) => setOrg({ ...org, target_outcomes: v })}
            placeholder="e.g. 70% job placement within 6 months"
          />
          <TagListInput
            label="Income sources"
            hint="Where your funding comes from."
            values={org.income_sources || []}
            onChange={(v) => setOrg({ ...org, income_sources: v })}
            placeholder="e.g. foundation grants"
          />
          <TagListInput
            label="Partner organisations"
            hint="Major partners, employers, or co-funders."
            values={org.partner_orgs || []}
            onChange={(v) => setOrg({ ...org, partner_orgs: v })}
            placeholder="e.g. Local Workforce Board"
          />
          <TagListInput
            label="Accreditations / certifications"
            hint="Formal accreditations or registrations."
            values={org.accreditations || []}
            onChange={(v) => setOrg({ ...org, accreditations: v })}
            placeholder="e.g. 501(c)(3), GuideStar Gold"
          />
        </div>

        <div className="flex items-center gap-3 pt-1">
          <Button onClick={saveOrg} disabled={orgSaving} className="flex items-center gap-2"><Save size={13} />{orgSaving ? "Saving…" : "Save detailed profile"}</Button>
          <StatusMsg msg={orgStatus} />
        </div>
      </Section>

      <Section icon={Filter} title="Discovery Filters" desc="Narrow the pre-filter pool used by Auto-Discovery. Leave empty to apply no filter for that dimension.">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600">NTEE code prefixes</label>
            <p className="text-xs text-slate-500">Only consider funders whose NTEE code starts with one of these prefixes.</p>
            <div className="flex flex-wrap gap-1.5">
              {NTEE_PREFIXES.map((p) => {
                const active = org.ntee_codes?.includes(p) ?? false;
                return (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setOrg((o) => ({
                      ...o,
                      ntee_codes: active
                        ? (o.ntee_codes || []).filter((x) => x !== p)
                        : [...(o.ntee_codes || []), p],
                    }))}
                    className={`rounded px-2 py-0.5 text-xs font-semibold transition ${active ? "bg-brand text-white" : "border border-slate-200 text-slate-500 hover:bg-slate-50"}`}
                  >
                    {p}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600">Service states</label>
            <p className="text-xs text-slate-500">Only consider funders that serve at least one of these states.</p>
            <div className="flex flex-wrap gap-1.5">
              {org.service_states?.map((s) => (
                <span key={s} className="flex items-center gap-1 rounded-full bg-brand/10 px-2.5 py-0.5 text-xs font-semibold text-brand">
                  {s}
                  <button type="button" onClick={() => setOrg((o) => ({ ...o, service_states: (o.service_states || []).filter((x) => x !== s) }))} aria-label={`Remove ${s}`} className="hover:text-red-600">×</button>
                </span>
              ))}
            </div>
            <select
              className={`${inp} w-36`}
              value=""
              onChange={(e) => {
                const s = e.target.value;
                if (s && !org.service_states?.includes(s)) setOrg((o) => ({ ...o, service_states: [...(o.service_states || []), s] }));
              }}
            >
              <option value="">Add state…</option>
              {US_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          <div className="sm:col-span-2 space-y-2">
            <label className="text-xs font-semibold text-slate-600">Applicant types</label>
            <p className="text-xs text-slate-500">Only consider opportunities open to at least one of these applicant categories.</p>
            <div className="flex flex-wrap gap-2">
              {SELECTABLE_APPLICANT_TYPES.map((t) => {
                const active = org.applicant_types?.includes(t) ?? false;
                return (
                  <label key={t} className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-700">
                    <input
                      type="checkbox"
                      checked={active}
                      onChange={() => setOrg((o) => ({
                        ...o,
                        applicant_types: active
                          ? (o.applicant_types || []).filter((x) => x !== t)
                          : [...(o.applicant_types || []), t],
                      }))}
                      className="h-3.5 w-3.5 rounded border-slate-300 accent-brand"
                    />
                    {t.replace(/_/g, " ")}
                  </label>
                );
              })}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600">Accepts unsolicited proposals</label>
            <button
              type="button"
              onClick={() => setOrg((o) => ({ ...o, accepts_unsolicited: !(o.accepts_unsolicited ?? true) }))}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${(org.accepts_unsolicited ?? true) ? "bg-brand" : "bg-slate-200"}`}
            >
              <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${(org.accepts_unsolicited ?? true) ? "translate-x-6" : "translate-x-1"}`} />
            </button>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600">Can cost-share / match</label>
            <button
              type="button"
              onClick={() => setOrg((o) => ({ ...o, can_cost_share: !(o.can_cost_share ?? true) }))}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${(org.can_cost_share ?? true) ? "bg-brand" : "bg-slate-200"}`}
            >
              <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${(org.can_cost_share ?? true) ? "translate-x-6" : "translate-x-1"}`} />
            </button>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-600">Min grant size ($)</label>
            <input type="number" min={0} className={inp} value={org.min_grant_size ?? ""} onChange={(e) => setOrg((o) => ({ ...o, min_grant_size: e.target.value ? Number(e.target.value) : null }))} placeholder="e.g. 10000" />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-600">Max grant size ($)</label>
            <input type="number" min={0} className={inp} value={org.max_grant_size ?? ""} onChange={(e) => setOrg((o) => ({ ...o, max_grant_size: e.target.value ? Number(e.target.value) : null }))} placeholder="e.g. 500000" />
          </div>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <Button onClick={saveOrg} disabled={orgSaving} className="flex items-center gap-2"><Save size={13} />{orgSaving ? "Saving…" : "Save filters"}</Button>
          <StatusMsg msg={orgStatus} />
        </div>
      </Section>

      <Section icon={Target} title="Topic Filter (Phase 5)" desc="Federal grant categories and applicant-type codes used to gate Grants.gov opportunities BEFORE LLM extraction. Cuts out off-topic noise like defense research RFPs.">
        <div className="rounded-lg border border-brand/20 bg-brand/5 px-3 py-2 text-xs text-slate-700">
          <strong className="text-brand">How to use:</strong> click <strong>AI suggest</strong>
          to auto-fill from your mission &amp; services, then review/edit before saving.
          Leaving both lists empty disables this gate (all grants pass).
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={suggestCategories}
            disabled={suggesting}
            variant="outline"
            className="flex items-center gap-2"
          >
            <Wand2 size={13} />
            {suggesting ? "Asking GPT-4o-mini…" : "AI suggest from mission"}
          </Button>
          <StatusMsg msg={suggestStatus} />
        </div>

        {org.category_suggestion_notes && (
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <strong className="text-slate-700">AI rationale:</strong> {org.category_suggestion_notes}
          </div>
        )}

        <div className="space-y-2">
          <label className="text-xs font-semibold text-slate-600">CFDA categories ({org.cfda_categories?.length || 0} selected)</label>
          <p className="text-xs text-slate-500">Grants.gov "Category of Funding Activity" codes the org applies for. Only opportunities tagged with one of these will be considered.</p>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {CFDA_CATEGORIES.map(({ code, label }) => {
              const active = org.cfda_categories?.includes(code) ?? false;
              return (
                <label key={code} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-0.5 text-xs text-slate-700 hover:bg-slate-50">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() =>
                      setOrg((o) => ({
                        ...o,
                        cfda_categories: active
                          ? (o.cfda_categories || []).filter((x) => x !== code)
                          : [...(o.cfda_categories || []), code],
                      }))
                    }
                    className="h-3.5 w-3.5 rounded border-slate-300 accent-brand"
                  />
                  <span className="font-mono font-semibold text-slate-500">{code}</span>
                  <span className="text-slate-700">{label}</span>
                </label>
              );
            })}
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-xs font-semibold text-slate-600">Eligible-applicant codes ({org.eligible_applicant_codes?.length || 0} selected)</label>
          <p className="text-xs text-slate-500">What KIND of organisation you are. Grants whose <code className="rounded bg-slate-100 px-1">EligibleApplicants</code> codes don't intersect this list (and aren't catch-alls 00/11/25/99) will be dropped.</p>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {ELIGIBLE_APPLICANT_CODES.map(({ code, label }) => {
              const active = org.eligible_applicant_codes?.includes(code) ?? false;
              return (
                <label key={code} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-0.5 text-xs text-slate-700 hover:bg-slate-50">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() =>
                      setOrg((o) => ({
                        ...o,
                        eligible_applicant_codes: active
                          ? (o.eligible_applicant_codes || []).filter((x) => x !== code)
                          : [...(o.eligible_applicant_codes || []), code],
                      }))
                    }
                    className="h-3.5 w-3.5 rounded border-slate-300 accent-brand"
                  />
                  <span className="font-mono font-semibold text-slate-500">{code}</span>
                  <span className="text-slate-700">{label}</span>
                </label>
              );
            })}
          </div>
        </div>

        <div className="flex items-center gap-3 pt-1">
          <Button onClick={saveOrg} disabled={orgSaving} className="flex items-center gap-2"><Save size={13} />{orgSaving ? "Saving…" : "Save topic filter"}</Button>
          <StatusMsg msg={orgStatus} />
        </div>
      </Section>

      <Section icon={Sparkles} title="AI Evaluation Prompts" desc="Customise the instructions sent to the AI when evaluating each grant. Leave blank to use defaults.">
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Use <code className="rounded bg-amber-100 px-1">{"{org_profile}"}</code> where the organisation details should appear, and <code className="rounded bg-amber-100 px-1">{"{text}"}</code> where the grant page content goes. Both are required in the user prompt.
        </div>

        <Row label="System prompt (role instruction)">
          <textarea rows={3} className={ta} value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} placeholder={defaultSystemPrompt} />
          <p className="text-[11px] text-slate-400">{systemPrompt.trim() ? "Custom" : "Using default (live from backend)"}</p>
        </Row>

        <Row label="User prompt template (evaluation instructions)">
          <textarea rows={18} className={ta} value={userPrompt} onChange={(e) => setUserPrompt(e.target.value)} placeholder={defaultUserPrompt} />
          <p className="text-[11px] text-slate-400">{userPrompt.trim() ? "Custom" : "Using default (live from backend)"}</p>
        </Row>

        <div className="flex flex-wrap items-center gap-3 pt-1">
          <Button onClick={savePrompts} disabled={promptSaving} className="flex items-center gap-2"><Save size={13} />{promptSaving ? "Saving…" : "Save prompts"}</Button>
          <Button variant="ghost" size="sm" onClick={() => { setSystemPrompt(""); setUserPrompt(""); }} className="flex items-center gap-2 text-slate-500">
            <RotateCcw size={13} />Reset to defaults
          </Button>
          <StatusMsg msg={promptStatus} />
        </div>

        <details className="group" open>
          <summary className="cursor-pointer text-xs font-semibold text-brand hover:underline">
            Preview effective prompt (the live message that gets sent to the LLM)
          </summary>
          <div className="mt-2 flex items-center justify-between">
            <p className="text-[11px] text-slate-500">
              {previewLoading ? "Refreshing…" : "This is the live message — refresh after editing fields above."}
            </p>
            <Button type="button" variant="ghost" size="sm" onClick={refreshLivePreview} disabled={previewLoading} className="h-6 gap-1 px-2 text-[11px]">
              <RotateCcw size={11} /> Refresh preview
            </Button>
          </div>
          <div className="mt-2 space-y-2">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">System prompt (sent first)</p>
              <p className="whitespace-pre-wrap font-mono text-xs text-slate-600">{effectiveSystem}</p>
            </div>
            <div className="rounded-lg border border-emerald-200 bg-emerald-50/40 p-3">
              <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-emerald-700">Org profile (LIVE — substituted for {"{org_profile}"})</p>
              <p className="whitespace-pre-wrap font-mono text-xs text-slate-700">{livePreview}</p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">User prompt template (org profile + grant text get substituted)</p>
              <p className="whitespace-pre-wrap font-mono text-xs text-slate-600">{
                effectiveUser
                  .replace("{org_profile}", "[↑ see Org profile box above ↑]")
                  .replace("{text}", "[grant page text here at scrape time]")
              }</p>
            </div>
          </div>
        </details>
      </Section>
    </div>
  );
}
