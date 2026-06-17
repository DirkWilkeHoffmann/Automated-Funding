"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Key } from "lucide-react";
import { api } from "../../../lib/api";
import { Button } from "../../../components/ui/button";

type TokenRecord = { name: string; masked: string; updated_at: string | null };

const inp = "w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 focus:border-brand/50 focus:outline-none focus:ring-2 focus:ring-brand/10";

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

function StatusMsg({ msg }: { msg: string | null }) {
  if (!msg) return null;
  const isErr = msg.startsWith("Error");
  return <p className={`text-xs ${isErr ? "text-red-600" : "text-emerald-600"}`}>{msg}</p>;
}

function TokenCard({ token, label, description, placeholder, onSave }: {
  token: TokenRecord | undefined;
  label: string;
  description: string;
  placeholder: string;
  onSave: (key: string) => Promise<void>;
}) {
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const save = async () => {
    if (!value.trim()) return;
    setSaving(true); setStatus(null);
    try {
      await onSave(value.trim());
      setStatus("Key saved.");
      setValue("");
    } catch (e: any) { setStatus(`Error: ${e.message}`); }
    finally { setSaving(false); }
  };

  return (
    <div className="rounded-lg border border-slate-200 p-4 space-y-3">
      <div>
        <p className="text-sm font-semibold text-slate-800">{label}</p>
        <p className="text-xs text-slate-500">{description}</p>
      </div>
      {token ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm">
          <span className="text-slate-500 font-mono">{token.masked}</span>
          {token.updated_at && (
            <span className="ml-3 text-xs text-slate-400">Updated {new Date(token.updated_at).toLocaleString()}</span>
          )}
        </div>
      ) : (
        <p className="text-xs text-slate-400 italic">No key set — using server environment variable if available.</p>
      )}
      <div className="flex gap-2">
        <input type="password" placeholder={placeholder} value={value} onChange={(e) => setValue(e.target.value)}
          autoComplete="off" className={`${inp} max-w-sm font-mono`} />
        <Button onClick={save} disabled={saving || !value.trim()}>{saving ? "Saving…" : token ? "Rotate" : "Set key"}</Button>
      </div>
      <StatusMsg msg={status} />
    </div>
  );
}

export default function KeysPage() {
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tokens, setTokens] = useState<TokenRecord[]>([]);

  useEffect(() => {
    api.adminTokens()
      .then((t: TokenRecord[]) => setTokens(t))
      .catch((e: any) => setLoadError(e.message || "Failed to load API keys"));
  }, []);

  const reload = () => api.adminTokens().then((t: TokenRecord[]) => setTokens(t));

  if (loadError) return (
    <div className="page-content">
      <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        <AlertCircle size={14} />{loadError}
      </div>
    </div>
  );

  const openaiToken = tokens.find((t) => t.name === "openai");
  const samToken = tokens.find((t) => t.name === "sam_gov");
  const braveToken = tokens.find((t) => t.name === "brave_search");
  const candidToken = tokens.find((t) => t.name === "candid");

  return (
    <div className="page-content space-y-6">
      <header>
        <p className="text-xs font-medium uppercase tracking-widest text-slate-400">Admin · API Keys</p>
        <h1 className="mt-0.5 text-2xl font-bold text-slate-900">API Keys</h1>
        <p className="mt-1 text-sm text-slate-500">Stored securely in Supabase. Never exposed to the browser.</p>
      </header>

      <Section icon={Key} title="Service Credentials" desc="Keys used by the backend to call third-party APIs.">
        <TokenCard
          token={openaiToken}
          label="OpenAI"
          description="Used for all AI grant evaluations (gpt-4o-mini / gpt-4.1)."
          placeholder="sk-…"
          onSave={async (key) => { await api.adminSetOpenAIKey(key); await reload(); }}
        />
        <TokenCard
          token={samToken}
          label="SAM.gov"
          description="Optional. Required to include US federal contract opportunities in Auto-Discovery."
          placeholder="SAM.gov API key…"
          onSave={async (key) => { await api.adminSetSamGovKey(key); await reload(); }}
        />
        <TokenCard
          token={braveToken}
          label="Brave Search"
          description="(Deprecated — web search source was cut in Phase 4.) Key still accepted for historical compatibility but no longer used."
          placeholder="BSA…"
          onSave={async (key) => { await api.adminSetBraveKey(key); await reload(); }}
        />
        <TokenCard
          token={candidToken}
          label="Candid Essentials"
          description="Paid. Optional. Unlocks the Candid grantmaker search source (foundation directory with NTEE filters). Toggle the 'candid' source on in Admin → Discovery once set."
          placeholder="Candid API key…"
          onSave={async (key) => { await api.adminSetCandidKey(key); await reload(); }}
        />
      </Section>
    </div>
  );
}
