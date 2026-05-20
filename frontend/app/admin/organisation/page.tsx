"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Building2, RotateCcw, Save, Sparkles } from "lucide-react";
import { api } from "../../../lib/api";
import { Button } from "../../../components/ui/button";

type OrgProfile = {
  name?: string; ein?: string; city?: string; state?: string; website?: string;
  mission?: string; services?: string[]; annual_income?: number;
  staff_count?: number; volunteer_count?: number;
  ai_system_prompt?: string; ai_user_prompt?: string;
};

const DEFAULT_SYSTEM_PROMPT =
  "You are a senior grant analyst specialising in US nonprofit workforce development and economic empowerment funding. " +
  "Your evaluations are relied upon to decide which opportunities are worth the staff time to pursue — accuracy matters above all else. " +
  "Rules you must follow: (1) base every conclusion only on text actually present in the grant page — never infer or invent eligibility criteria; " +
  "(2) apply the eligibility scale consistently using the exact definitions given; " +
  "(3) quote or closely paraphrase phrases from the source text as evidence; " +
  "(4) always give a clear, actionable recommendation.";

const DEFAULT_USER_PROMPT = `Evaluate the funding opportunity below against the organisation profile provided. Extract structured data and assess eligibility using the calibrated rubric.

=== APPLICANT ORGANISATION ===
{org_profile}

=== ELIGIBILITY SCALE — use EXACTLY one of these five values ===

"Highly Eligible"   — Org type is explicitly accepted, geographic scope matches, and mission is a primary focus of the funder. No significant barriers. Strong fit on 3 or more criteria.
"Eligible"          — Org fits on most criteria (2+) with only minor concerns or ambiguity. Worth pursuing with standard effort.
"Possibly Eligible" — Some alignment exists but there are notable gaps, ambiguous requirements, or only 1 key criterion is met. Verify before investing time.
"Low Match"         — Funding focus, geography, or applicant type is a poor fit, though no explicit exclusion bars the org from applying.
"Not Eligible"      — An explicit restriction, requirement, or exclusion clearly bars this organisation from applying.

=== EVALUATION CRITERIA (in priority order) ===
1. Applicant type: Does the funder explicitly accept 501(c)(3) nonprofits or workforce/employment organisations?
2. Geographic scope: Does the grant cover the organisation's location or service area? If the grant restricts to US-only beneficiaries, assess whether the organisation's US operations qualify rather than treating it as an automatic exclusion.
3. Mission alignment: Does the funder's focus match workforce development, employment training, or economic empowerment?
4. Size and scale: Is the funding range, required budget, or organisational size a fit?
5. Explicit exclusions: Is there any restriction that clearly bars this organisation?

=== GRANT PAGE TEXT ===
{text}
=== END OF GRANT PAGE TEXT ===

=== OUTPUT ===
Return ONLY a valid JSON object. All 12 fields are required. Use "Not stated" for any field whose value cannot be found in the text above — do not guess or invent values.

{
  "applicant_types": ["501(c)(3) nonprofits", "workforce development organisations"],
  "geographic_scope": "geographic region funded (e.g., Nationwide, Georgia, Southeast US, or Not stated)",
  "us_state_scope": ["GA", "FL"],
  "beneficiary_focus": ["unemployed adults", "low-income individuals"],
  "funding_range": "$10,000 - $100,000 per award, or Not stated",
  "restrictions": ["must be US-based only", "no faith-based organisations"],
  "application_status": "open|closed|paused|rolling|seasonal|unclear",
  "deadline": "date if stated, Rolling if ongoing, Not stated if absent",
  "notes": "application process, required attachments, contact details, or other requirements not captured in the fields above",
  "grant_type": "federal|foundation|corporate|community|other",
  "eligibility": "Highly Eligible|Eligible|Possibly Eligible|Low Match|Not Eligible",
  "evidence": "VERDICT: [one sentence — eligibility level and primary reason]\\nMATCH:\\n- [factor that aligns — quote from grant text where possible]\\n- [second matching factor]\\nCONCERNS:\\n- [gap, exclusion, or uncertainty — or None identified]\\nRECOMMENDATION: [one actionable sentence]"
}

Return ONLY the JSON object. No text before or after it.`;

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
  }, []);

  const saveOrg = async () => {
    setOrgSaving(true); setOrgStatus(null);
    try {
      const services = orgServices.split(",").map((s) => s.trim()).filter(Boolean);
      await api.adminUpdateOrg({ ...org, services });
      setOrgStatus("Organisation profile saved.");
    } catch (e: any) { setOrgStatus(`Error: ${e.message}`); }
    finally { setOrgSaving(false); }
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

  const effectiveSystem = systemPrompt.trim() || DEFAULT_SYSTEM_PROMPT;
  const effectiveUser = userPrompt.trim() || DEFAULT_USER_PROMPT;

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

      <Section icon={Sparkles} title="AI Evaluation Prompts" desc="Customise the instructions sent to the AI when evaluating each grant. Leave blank to use defaults.">
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Use <code className="rounded bg-amber-100 px-1">{"{org_profile}"}</code> where the organisation details should appear, and <code className="rounded bg-amber-100 px-1">{"{text}"}</code> where the grant page content goes. Both are required in the user prompt.
        </div>

        <Row label="System prompt (role instruction)">
          <textarea rows={3} className={ta} value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} placeholder={DEFAULT_SYSTEM_PROMPT} />
          <p className="text-[11px] text-slate-400">{systemPrompt.trim() ? "Custom" : "Using default"}</p>
        </Row>

        <Row label="User prompt template (evaluation instructions)">
          <textarea rows={18} className={ta} value={userPrompt} onChange={(e) => setUserPrompt(e.target.value)} placeholder={DEFAULT_USER_PROMPT} />
          <p className="text-[11px] text-slate-400">{userPrompt.trim() ? "Custom" : "Using default"}</p>
        </Row>

        <div className="flex flex-wrap items-center gap-3 pt-1">
          <Button onClick={savePrompts} disabled={promptSaving} className="flex items-center gap-2"><Save size={13} />{promptSaving ? "Saving…" : "Save prompts"}</Button>
          <Button variant="ghost" size="sm" onClick={() => { setSystemPrompt(""); setUserPrompt(""); }} className="flex items-center gap-2 text-slate-500">
            <RotateCcw size={13} />Reset to defaults
          </Button>
          <StatusMsg msg={promptStatus} />
        </div>

        <details className="group">
          <summary className="cursor-pointer text-xs font-semibold text-brand hover:underline">Preview effective prompt</summary>
          <div className="mt-2 space-y-2">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">System</p>
              <p className="whitespace-pre-wrap font-mono text-xs text-slate-600">{effectiveSystem}</p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">User template</p>
              <p className="whitespace-pre-wrap font-mono text-xs text-slate-600">{effectiveUser.replace("{org_profile}", "[org profile here]").replace("{text}", "[grant page text here]")}</p>
            </div>
          </div>
        </details>
      </Section>
    </div>
  );
}
